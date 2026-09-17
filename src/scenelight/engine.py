"""Deterministic screen-space light transport for transparent 2D sprites.

This is intentionally not advertised as physical 3D ray tracing: a flat PNG
contains no hidden geometry.  The engine instead reconstructs a soft height
field, estimates multiple scene lights and an eight-direction environment,
then evaluates diffuse/specular response, ray-marched self-shadow, ambient
occlusion, ground bounce, edge spill, contact shadow, and camera matching in
linear RGB.  Every estimate is recomputed in scene coordinates when the
character moves.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from math import atan2, degrees
from typing import Any

import cv2
import numpy as np
from PIL import Image

# Small/medium 2D images are faster and more predictable without OpenCV
# spawning a large native worker pool for every preview slider movement.
cv2.setNumThreads(1)


EPSILON = 1e-6

# All input sprites are treated as display-referred artwork made under the same
# neutral reference illumination.  Exposure therefore belongs to the scene,
# not to the subject's palette: a white shirt must not make its wearer darker,
# and black fur must not make an animal brighter.  This neutral-art midpoint is
# fixed from the renderer's neutral reference artwork, then applied unchanged
# to every sprite. No filename or character identity is allowed to alter scene
# exposure.
REFERENCE_ART_MID = 0.221169

# Broad daylight and overcast photos can have a high robust midpoint without
# containing a compact source that should make the subject glow.  In that
# specific high-key/low-contrast regime, a restrained scene-referred shoulder
# keeps pale anime materials from reading as self-emissive.  The gate depends
# only on measured scene radiometry; sprite palette, filename, and identity are
# intentionally absent.
BROAD_DIFFUSE_MAX_STOPS = 0.42

# A bright, broad, low-confidence source is normally camera-white-balanced in
# the photograph itself. Multiplying the same cyan/green ambient chroma into a
# pale, nearly neutral painted material a second time can erase its authored
# reflectance (most visibly on faces and white fabric). This is a maximum
# chroma-only restoration; it never changes exposure or generated form.
BROAD_DIFFUSE_CHROMA_PRESERVATION = 0.78

# The palette meter remains useful for diagnostics and audit stratification,
# but it must never drive radiometric exposure.  Its wide variation across
# intentionally black, white, and saturated materials is precisely why a
# content-dependent exposure anchor is physically invalid here.
REFERENCE_MATERIAL_CALIBRATION = 0.611


@dataclass(slots=True)
class Placement:
    """Sprite placement in normalized background coordinates."""

    center_x: float = 0.5
    baseline_y: float = 0.98
    height: float = 0.88

    def clamped(self) -> "Placement":
        return Placement(
            center_x=float(np.clip(self.center_x, -0.25, 1.25)),
            baseline_y=float(np.clip(self.baseline_y, 0.1, 1.25)),
            height=float(np.clip(self.height, 0.05, 1.5)),
        )


@dataclass(slots=True)
class RelightSettings:
    """Creative controls layered on top of automatic scene matching."""

    auto_strength: float = 0.88
    exposure_bias: float = 0.0
    ambient_strength: float = 1.0
    color_adaptation: float = 0.78
    contrast_match: float = 0.72
    saturation_match: float = 0.58
    highlight_rolloff: float = 1.2
    key_strength: float = 0.82
    multi_light_strength: float = 0.82
    surface_depth: float = 0.72
    ray_shadow_strength: float = 0.58
    ray_steps: int = 14
    ambient_occlusion: float = 0.34
    probe_strength: float = 0.48
    bounce_strength: float = 0.32
    specular_strength: float = 0.24
    rim_strength: float = 0.64
    wrap_strength: float = 0.42
    shadow_strength: float = 0.62
    shadow_softness: float = 0.62
    grain_match: float = 0.52
    warmth_bias: float = 0.0
    manual_light_x: float | None = None
    manual_light_y: float | None = None

    def normalized(self) -> "RelightSettings":
        values = asdict(self)
        for key in (
            "auto_strength",
            "ambient_strength",
            "color_adaptation",
            "contrast_match",
            "saturation_match",
            "highlight_rolloff",
            "key_strength",
            "multi_light_strength",
            "surface_depth",
            "ray_shadow_strength",
            "ambient_occlusion",
            "probe_strength",
            "bounce_strength",
            "specular_strength",
            "rim_strength",
            "wrap_strength",
            "shadow_strength",
            "shadow_softness",
            "grain_match",
        ):
            values[key] = float(np.clip(values[key], 0.0, 2.0))
        values["exposure_bias"] = float(np.clip(values["exposure_bias"], -4.0, 4.0))
        values["warmth_bias"] = float(np.clip(values["warmth_bias"], -1.0, 1.0))
        values["ray_steps"] = int(np.clip(round(values["ray_steps"]), 4, 32))
        return RelightSettings(**values)


@dataclass(slots=True, frozen=True)
class DetectedLight:
    """One screen-space emitter inferred from a bright scene region."""

    x: float
    y: float
    color: tuple[float, float, float]
    intensity: float
    radius: float
    confidence: float
    emission_score: float = 1.0
    creative_only: bool = False


@dataclass(slots=True, frozen=True)
class EnvironmentProbe:
    """Directional irradiance sample around the character position."""

    direction_x: float
    direction_y: float
    color: tuple[float, float, float]
    luminance: float


@dataclass(slots=True)
class SceneAnalysis:
    ambient_color: tuple[float, float, float]
    light_color: tuple[float, float, float]
    shadow_color: tuple[float, float, float]
    local_luminance: float
    adaptation_luminance: float
    global_luminance: float
    global_contrast: float
    local_contrast: float
    local_saturation: float
    light_x: float
    light_y: float
    subject_x: float
    subject_y: float
    light_confidence: float
    source_size: float
    grain: float
    sharpness: float
    low_key: bool
    lights: tuple[DetectedLight, ...]
    environment_probes: tuple[EnvironmentProbe, ...]
    creative_lights: tuple[DetectedLight, ...] = ()

    @property
    def light_direction_name(self) -> str:
        dx = self.light_x - self.subject_x
        dy = self.light_y - self.subject_y
        horizontal = "left" if dx < -0.08 else "right" if dx > 0.08 else "center"
        vertical = "upper" if dy < -0.08 else "lower" if dy > 0.08 else "level"
        return f"{vertical} {horizontal}"

    @property
    def light_angle_degrees(self) -> float:
        return degrees(atan2(self.subject_y - self.light_y, self.light_x - self.subject_x))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["light_direction"] = self.light_direction_name
        result["light_angle_degrees"] = self.light_angle_degrees
        return result


@dataclass(slots=True)
class PreparedScene:
    """Immutable-by-convention scene data shared by position samples.

    A transport atlas evaluates the same background at many character
    positions.  Resizing, transfer conversion, robust global statistics,
    saliency, texture, and camera measurements do not depend on that
    position.  Keeping them here avoids recomputing identical arrays for all
    144 transport samples while leaving every spatial meter and emitter
    decision position-dependent.
    """

    srgb: np.ndarray
    linear: np.ndarray
    luma: np.ndarray
    clipped_luma: np.ndarray
    saturation: np.ndarray
    base_source_weights: np.ndarray
    texture_residual: np.ndarray
    yy: np.ndarray
    xx: np.ndarray
    normalized_y: np.ndarray
    ring_kernel: np.ndarray
    global_mean: float
    global_contrast: float
    separation: float
    grain: float
    sharpness: float
    gradient_fields: dict[float, tuple[np.ndarray, np.ndarray]]
    creative_fields: tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]] | None = None


@dataclass(slots=True, frozen=True)
class ScenePlacementMeasurements:
    """Pre-reduced scene meters for one transport-grid placement.

    A CUDA backend can evaluate all placements as a batch and pass only these
    scalar/vector results back to the shared decision logic. The regular CPU
    analyzer leaves this unset and follows its original reduction path.
    """

    ambient_linear: tuple[float, float, float]
    local_mean: float
    adaptation_luminance: float
    local_variance: float
    local_saturation: float
    source_total: float
    upper_light_linear: tuple[float, float, float]
    gradient_x: float
    gradient_y: float


def _pil_rgba(image: Image.Image) -> Image.Image:
    return image.convert("RGBA") if image.mode != "RGBA" else image.copy()


def _pil_rgb(image: Image.Image) -> Image.Image:
    return image.convert("RGB") if image.mode != "RGB" else image.copy()


def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.maximum(np.asarray(rgb, dtype=np.float32), 0.0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def _luminance(linear_rgb: np.ndarray) -> np.ndarray:
    return linear_rgb[..., 0] * 0.2126 + linear_rgb[..., 1] * 0.7152 + linear_rgb[..., 2] * 0.0722


def _clamp_scalar(value: float, lower: float, upper: float) -> float:
    """Clamp a known-finite scalar without dispatching through NumPy."""

    return min(max(float(value), lower), upper)


def _smoothstep_scalar(value: float, lower: float, upper: float) -> float:
    value = _clamp_scalar((value - lower) / (upper - lower), 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _directional_support(
    light: DetectedLight, subject_y: float, adaptation: float, physical_count: int
) -> float:
    """Blend uncertain sources with diffuse light without discarding their geometry."""
    lower = _smoothstep_scalar(light.y, subject_y - 0.06, subject_y + 0.02)
    daylight = _smoothstep_scalar(adaptation, 0.12, 0.20)
    reflection = _smoothstep_scalar(light.radius, 0.06, 0.11)
    if physical_count >= 2:
        reflection = max(reflection, 1.0 - _smoothstep_scalar(light.emission_score, 0.54, 0.70))
    # Reflected light still has a direction. Emission controls its point-source
    # falloff, not whether its measured position and color exist at all.
    return 1.0 - lower * daylight * reflection


def _linear_quantile(
    values: np.ndarray,
    quantiles: float | tuple[float, ...],
    *,
    overwrite_input: bool = False,
) -> Any:
    """Return NumPy's linear quantile without its repeated public API setup.

    Source-component classification calls this thousands of times per scene.
    The input is already a finite one-dimensional luminance selection and the
    requested quantiles are fixed constants, so public validation and generic
    axis reduction are pure overhead. This is the same partition, indexing,
    and two-sided interpolation used by ``np.quantile(method="linear")``.
    Scalar quantiles inherit a floating input's dtype, preserving the reference
    float32 threshold decisions bit for bit.
    """

    array = np.asarray(values).reshape(-1)
    if not overwrite_input:
        array = array.copy()
    if isinstance(quantiles, (int, float)):
        requested = (
            np.asarray(quantiles, dtype=array.dtype)[()] if array.dtype.kind == "f" else quantiles
        )
        virtual_index = (array.size - 1) * requested
        previous_index = int(np.floor(virtual_index))
        next_index = previous_index + 1
        if virtual_index >= array.size - 1:
            previous_index = next_index = -1
        elif virtual_index < 0:
            previous_index = next_index = 0
        array.partition((previous_index, next_index))
        previous = array[previous_index]
        following = array[next_index]
        gamma = np.asarray(
            virtual_index - previous_index,
            dtype=np.asarray(virtual_index).dtype,
        )[()]
        difference = np.subtract(following, previous)
        result = np.asarray(np.add(previous, difference * gamma))
        np.subtract(
            following,
            difference * (1 - gamma),
            out=result,
            where=gamma >= 0.5,
            casting="unsafe",
            dtype=type(result.dtype),
        )
        return result[()]

    requested = np.asanyarray(quantiles)
    virtual_indexes = np.asanyarray((array.size - 1) * requested)
    previous_indexes = np.asanyarray(np.floor(virtual_indexes))
    next_indexes = np.asanyarray(previous_indexes + 1)

    indexes_above_bounds = virtual_indexes >= array.size - 1
    if indexes_above_bounds.any():
        previous_indexes[indexes_above_bounds] = -1
        next_indexes[indexes_above_bounds] = -1
    indexes_below_bounds = virtual_indexes < 0
    if indexes_below_bounds.any():
        previous_indexes[indexes_below_bounds] = 0
        next_indexes[indexes_below_bounds] = 0

    previous_indexes = previous_indexes.astype(np.intp)
    next_indexes = next_indexes.astype(np.intp)
    array.partition(tuple(np.concatenate((previous_indexes, next_indexes)).tolist()))
    previous = array[previous_indexes]
    following = array[next_indexes]
    gamma = np.asanyarray(
        virtual_indexes - previous_indexes,
        dtype=virtual_indexes.dtype,
    )
    difference = np.subtract(following, previous)
    result = np.asanyarray(np.add(previous, difference * gamma))
    np.subtract(
        following,
        difference * (1 - gamma),
        out=result,
        where=gamma >= 0.5,
        casting="unsafe",
        dtype=type(result.dtype),
    )
    return result[()] if result.ndim == 0 else result


def _resize_for_analysis(image: Image.Image, maximum: int = 640) -> np.ndarray:
    rgb = np.asarray(_pil_rgb(image), dtype=np.float32) / 255.0
    h, w = rgb.shape[:2]
    scale = min(1.0, maximum / max(h, w))
    if scale < 1.0:
        rgb = cv2.resize(
            rgb, (max(2, round(w * scale)), max(2, round(h * scale))), interpolation=cv2.INTER_AREA
        )
    return rgb


def _weighted_rgb(
    rgb: np.ndarray,
    weights: np.ndarray,
    total: float | None = None,
) -> np.ndarray:
    total = float(np.sum(weights)) if total is None else total
    # ``einsum`` keeps NumPy's original C-order float32 accumulation but fuses
    # the multiply/reduce, avoiding a full HxWx3 temporary for every meter and
    # irradiance probe. The resulting floats are bit-identical to the former
    # expression on the supported NumPy builds.
    return np.einsum("ijk,ij->k", rgb, weights, optimize=False) / (total + EPSILON)


def _saturation(rgb: np.ndarray) -> np.ndarray:
    maximum = np.max(rgb, axis=-1)
    minimum = np.min(rgb, axis=-1)
    return (maximum - minimum) / (maximum + EPSILON)


def _placement_region(
    shape: tuple[int, int],
    placement: Placement,
    coordinate_grid: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[slice, slice, np.ndarray]:
    h, w = shape
    p = placement.clamped()
    char_h = max(4, int(h * p.height))
    char_w = max(4, int(char_h * 0.54))
    cx = int(p.center_x * w)
    bottom = int(p.baseline_y * h)
    x0, x1 = max(0, cx - char_w // 2), min(w, cx + char_w // 2)
    y0, y1 = max(0, bottom - char_h), min(h, bottom)
    if coordinate_grid is None:
        yy, xx = np.mgrid[0:h, 0:w]
    else:
        yy, xx = coordinate_grid
    radius_x = max(char_w * 0.86, 1)
    radius_y = max(char_h * 0.66, 1)
    center_y = bottom - char_h * 0.48
    distance = ((xx - cx) / radius_x) ** 2 + ((yy - center_y) / radius_y) ** 2
    annulus = np.exp(-np.maximum(distance - 0.5, 0.0) * 1.8)
    annulus *= np.where(distance < 0.28, 0.18, 1.0)
    return slice(y0, y1), slice(x0, x1), annulus.astype(np.float32)


def _display_chromaticity(linear_color: np.ndarray) -> tuple[float, float, float]:
    luma = float(_luminance(linear_color))
    chroma = np.clip(linear_color / (luma + EPSILON), 0.45, 2.4)
    display = np.clip(_linear_to_srgb(chroma * 0.5), 0.0, 1.0)
    return tuple(float(channel) for channel in display)


def _detect_creative_color_sources(
    linear: np.ndarray,
    source_weights: np.ndarray,
    coordinate_grid: tuple[np.ndarray, np.ndarray],
    prepared_fields: tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]] | None = None,
) -> tuple[DetectedLight, ...]:
    """Recover colored emitters that touch in the ordinary saliency mask.

    The physically balanced detector groups touching bright pixels spatially.
    That is desirable for the default renderer, but a wall of adjacent colored
    lamps becomes one broad, average-colored source. Creative mode needs the
    individual hue families as optional inputs, so split only sufficiently
    saturated saliency into fixed hue sectors. These sources are stored in
    disabled transport slots. The shader admits them only when multiple strong
    colors are also spatially distinct, so ordinary scenes keep their physical
    aggregate while real multi-emitter scenes retain their actual directions.
    """

    positive = source_weights[source_weights > EPSILON]
    if positive.size == 0:
        return ()

    if prepared_fields is None:
        prepared_fields = _prepare_creative_color_fields(linear)
    saturation, saturated, sector_memberships = prepared_fields
    colored = saturated
    if not np.any(colored):
        return ()

    yy, xx = coordinate_grid
    # Hue energy must fade with radiance. The physical saliency mask is useful
    # for finding compact lights, but drops a dimming colored lamp abruptly.
    chroma_weight = _luminance(linear) * (0.30 + 0.70 * saturation) * colored
    total_energy = float(np.sum(chroma_weight)) + EPSILON
    candidates: list[tuple[float, int, DetectedLight]] = []
    h, w = source_weights.shape
    for sector, membership in enumerate(sector_memberships):
        weights = chroma_weight * membership
        energy = float(np.sum(weights))
        if energy < total_energy * 0.012:
            continue
        cx = float(np.sum(xx * weights) / (energy + EPSILON))
        cy = float(np.sum(yy * weights) / (energy + EPSILON))
        spread = float(
            np.sum((((xx - cx) / max(w, 1)) ** 2 + ((yy - cy) / max(h, 1)) ** 2) * weights)
            / (energy + EPSILON)
        )
        color = _display_chromaticity(_weighted_rgb(linear, weights, energy))
        candidates.append(
            (
                energy,
                sector,
                DetectedLight(
                    x=_clamp_scalar(cx / max(w - 1, 1), 0.0, 1.0),
                    y=_clamp_scalar(cy / max(h - 1, 1), 0.0, 1.0),
                    color=color,
                    intensity=1.0,
                    radius=_clamp_scalar(np.sqrt(max(spread, 0.0)) * 3.2, 0.055, 0.72),
                    confidence=_clamp_scalar(0.62 + energy / total_energy * 0.85, 0.0, 0.96),
                    emission_score=1.0,
                    creative_only=True,
                ),
            )
        )

    if not candidates:
        return ()

    maximum_energy = max(item[0] for item in candidates)
    selected: list[DetectedLight] = []
    for energy, _sector, candidate in sorted(candidates, key=lambda item: (-item[0], item[1])):
        selected.append(
            DetectedLight(
                x=candidate.x,
                y=candidate.y,
                color=candidate.color,
                intensity=_clamp_scalar(np.sqrt(energy / (maximum_energy + EPSILON)), 0.0, 1.0)
                * _smoothstep_scalar(energy / total_energy, 0.012, 0.06),
                radius=candidate.radius,
                confidence=candidate.confidence,
                emission_score=candidate.emission_score,
                creative_only=True,
            )
        )
    return tuple(selected)


def _prepare_creative_color_fields(
    linear: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
    """Prepare position-independent creative hue fields once per scene."""

    display = np.clip(_linear_to_srgb(linear), 0.0, 1.0).astype(np.float32, copy=False)
    hsv = cv2.cvtColor(display, cv2.COLOR_RGB2HSV)
    hue = hsv[..., 0]
    saturation = hsv[..., 1]
    saturated = saturation >= 0.24
    sector_width = 30.0
    memberships = []
    for sector in range(12):
        center = sector * sector_width + sector_width * 0.5
        # The triangular sector is exactly zero beyond 21.6 degrees. Avoid
        # twelve full-image floating-point remainder passes, while evaluating
        # the original expression (including its rounding) inside a slightly
        # wider support. The broad margin includes every wrap/boundary case.
        distance = np.abs(hue - center)
        support = (distance <= 22.0) | (distance >= 338.0)
        membership = np.zeros_like(hue)
        selected = hue[support]
        membership[support] = np.clip(
            1.0 - np.abs((selected - center + 180.0) % 360.0 - 180.0) / (sector_width * 0.72),
            0.0,
            1.0,
        )
        memberships.append(membership)
    return saturation, saturated, tuple(memberships)


def _detect_source_components(
    linear: np.ndarray,
    source_weights: np.ndarray,
    *,
    luma: np.ndarray | None = None,
    texture_residual: np.ndarray | None = None,
    coordinate_grid: tuple[np.ndarray, np.ndarray] | None = None,
    ring_kernel: np.ndarray | None = None,
    crop_components: bool = False,
    creative_fields: tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]] | None = None,
) -> tuple[DetectedLight, ...]:
    """Integrate light over four overlapping, fixed spatial basis functions.

    The weights sum to one at every pixel. Regions may merge, split or cross
    without changing the identity or count of the lighting representation.
    """
    h, w = source_weights.shape
    total = float(source_weights.sum())
    if total <= EPSILON:
        return ()
    yy, xx = np.mgrid[:h, :w] if coordinate_grid is None else coordinate_grid
    x = xx / max(w - 1, 1)
    y = yy / max(h - 1, 1)
    weights = [source_weights * wx * wy for wy in (1.0 - y, y) for wx in (1.0 - x, x)]
    energy = [float(weight.sum()) for weight in weights]
    maximum = max(energy)
    lights = []
    for weight, amount in zip(weights, energy, strict=True):
        denominator = amount + EPSILON
        cx = float(np.sum(weight * x) / denominator)
        cy = float(np.sum(weight * y) / denominator)
        variance = float(np.sum(weight * (x * x + y * y)) / denominator) - cx * cx - cy * cy
        radius = float(np.clip(np.sqrt(max(variance, 0.0)) * 3.2, 0.055, 1.0))
        color = np.sum(linear * weight[..., None], axis=(0, 1)) / denominator
        lights.append(
            DetectedLight(
                x=cx,
                y=cy,
                color=_display_chromaticity(color),
                intensity=float(np.sqrt(amount / (maximum + EPSILON))),
                radius=radius,
                confidence=0.35 + 0.60 * (1.0 - radius),
                emission_score=1.0 - _smoothstep_scalar(radius, 0.10, 0.45),
            )
        )
    return tuple(lights) + _detect_creative_color_sources(
        linear, source_weights, (yy, xx), prepared_fields=creative_fields
    )


_PROBE_DIRECTIONS = (
    (-1.0, 0.0),
    (-0.7071, -0.7071),
    (0.0, -1.0),
    (0.7071, -0.7071),
    (1.0, 0.0),
    (0.7071, 0.7071),
    (0.0, 1.0),
    (-0.7071, 0.7071),
)


def _environment_probe_specs(
    shape: tuple[int, int],
    subject_x: float,
    subject_y: float,
    placement: Placement,
) -> tuple[tuple[float, float, tuple[float, float, float, float]], ...]:
    """Return scene-independent probe directions and exact Gaussian keys."""

    h, w = shape
    radius_x = float(np.clip(placement.height * 0.42, 0.12, 0.46))
    radius_y = float(np.clip(placement.height * 0.34, 0.10, 0.38))
    sigma_x = max(w * np.clip(placement.height * 0.105, 0.035, 0.12), 2.0)
    sigma_y = max(h * np.clip(placement.height * 0.105, 0.035, 0.12), 2.0)
    return tuple(
        (
            direction_x,
            direction_y,
            (
                float(np.clip(subject_x + direction_x * radius_x, 0.0, 1.0)) * max(w - 1, 1),
                float(np.clip(subject_y + direction_y * radius_y, 0.0, 1.0)) * max(h - 1, 1),
                sigma_x,
                sigma_y,
            ),
        )
        for direction_x, direction_y in _PROBE_DIRECTIONS
    )


@lru_cache(maxsize=32)
def _probe_geometry(
    shape: tuple[int, int], target_x: float, target_y: float, sigma_x: float, sigma_y: float
) -> tuple[np.ndarray, float]:
    """Cache exact Gaussian weights, never image-dependent probe measurements."""
    h, w = shape
    probe_y = np.arange(h, dtype=np.int64)[:, None]
    probe_x = np.arange(w, dtype=np.int64)[None, :]
    weights = np.exp(
        -0.5 * (((probe_x - target_x) / sigma_x) ** 2 + ((probe_y - target_y) / sigma_y) ** 2)
    ).astype(np.float32)
    total = float(np.sum(weights))
    weights.flags.writeable = False
    return weights, total


def _sample_environment_probes(
    linear: np.ndarray,
    subject_x: float,
    subject_y: float,
    placement: Placement,
    coordinate_grid: tuple[np.ndarray, np.ndarray] | None = None,
    sample_cache: dict[tuple[float, float, float, float], tuple[tuple[float, float, float], float]]
    | None = None,
    cache_lock: Any | None = None,
) -> tuple[EnvironmentProbe, ...]:
    """Measure eight colored irradiance lobes around the current subject."""

    h, w = linear.shape[:2]
    canonical_grid = coordinate_grid is None or (
        coordinate_grid[0].dtype == np.dtype(np.int64)
        and coordinate_grid[1].dtype == np.dtype(np.int64)
        and np.array_equal(coordinate_grid[0][:, 0], np.arange(h))
        and np.array_equal(coordinate_grid[1][0], np.arange(w))
    )
    probes: list[EnvironmentProbe] = []
    for direction_x, direction_y, cache_key in _environment_probe_specs(
        (h, w), subject_x, subject_y, placement
    ):
        target_x, target_y, sigma_x, sigma_y = cache_key
        cached_sample = None
        if sample_cache is not None:
            if cache_lock is None:
                cached_sample = sample_cache.get(cache_key)
            else:
                with cache_lock:
                    cached_sample = sample_cache.get(cache_key)
        if cached_sample is None:
            if canonical_grid:
                weights, total = _probe_geometry((h, w), target_x, target_y, sigma_x, sigma_y)
            else:
                yy, xx = coordinate_grid
                weights = np.exp(
                    -0.5
                    * (
                        ((xx[:1, :] - target_x) / sigma_x) ** 2
                        + ((yy[:, :1] - target_y) / sigma_y) ** 2
                    )
                ).astype(np.float32)
                total = float(np.sum(weights))
            sample = _weighted_rgb(linear, weights, total)
            cached_sample = (
                _display_chromaticity(sample),
                float(np.clip(_luminance(sample), 0.0, 1.0)),
            )
            if sample_cache is not None:
                if cache_lock is None:
                    sample_cache.setdefault(cache_key, cached_sample)
                else:
                    with cache_lock:
                        cached_sample = sample_cache.setdefault(cache_key, cached_sample)
        color, luminance = cached_sample
        probes.append(
            EnvironmentProbe(
                direction_x=direction_x,
                direction_y=direction_y,
                color=color,
                luminance=luminance,
            )
        )
    return tuple(probes)


def _gradient_field(
    clipped_luma: np.ndarray,
    character_height: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the broad illumination gradient for one character height."""

    h, w = clipped_luma.shape
    field_sigma = max(8.0, min(h, w) * max(character_height, 0.12) * 0.16)
    light_field = cv2.GaussianBlur(clipped_luma, (0, 0), sigmaX=field_sigma)
    return (
        cv2.Sobel(light_field, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(light_field, cv2.CV_32F, 0, 1, ksize=3),
    )


def prepare_scene(
    background: Image.Image,
    gradient_heights: tuple[float, ...] = (),
) -> PreparedScene:
    """Prepare scene-wide measurements once for one or many placements."""

    srgb = _resize_for_analysis(background)
    linear = _srgb_to_linear(srgb)
    luma = _luminance(linear)
    h, w = luma.shape
    yy, xx = np.mgrid[0:h, 0:w]

    clip_hi = np.quantile(luma, 0.995)
    clipped_luma = np.minimum(luma, clip_hi)
    global_mean = float(np.mean(clipped_luma))
    global_contrast = float(np.std(clipped_luma) / (global_mean + 0.035))

    blur_radius = max(9, (min(h, w) // 18) | 1)
    local_base = cv2.GaussianBlur(clipped_luma, (0, 0), sigmaX=max(3.0, blur_radius / 3))
    residual = np.maximum(clipped_luma - local_base, 0.0)
    q86 = float(np.quantile(clipped_luma, 0.86))
    bright = np.maximum(clipped_luma - q86, 0.0)
    saliency = residual * 1.4 + bright * 0.7
    saliency = cv2.GaussianBlur(saliency, (0, 0), sigmaX=max(1.2, min(h, w) / 180))
    threshold = float(np.quantile(saliency, 0.86))
    base_source_weights = np.maximum(saliency - threshold, 0.0) ** 1.25

    q97 = float(np.quantile(clipped_luma, 0.97))
    separation = (q97 - float(np.quantile(clipped_luma, 0.55))) / (q97 + 0.04)
    texture_residual = np.abs(luma - cv2.GaussianBlur(luma, (0, 0), sigmaX=1.2))
    ring_size = max(5, (min(h, w) // 46) | 1)
    ring_kernel = np.ones((ring_size, ring_size), dtype=np.uint8)

    highpass = luma - cv2.GaussianBlur(luma, (0, 0), sigmaX=1.1)
    grain = float(np.clip(np.std(highpass) / 0.055, 0.0, 1.0))
    laplacian = cv2.Laplacian(luma, cv2.CV_32F)
    sharpness = float(np.clip(np.sqrt(np.mean(laplacian**2)) / 0.18, 0.0, 1.0))

    gradient_fields = {
        float(height): _gradient_field(clipped_luma, float(height))
        for height in dict.fromkeys(gradient_heights)
    }
    return PreparedScene(
        srgb=srgb,
        linear=linear,
        luma=luma,
        clipped_luma=clipped_luma,
        saturation=_saturation(srgb),
        base_source_weights=base_source_weights,
        texture_residual=texture_residual,
        yy=yy,
        xx=xx,
        normalized_y=yy / max(h - 1, 1),
        ring_kernel=ring_kernel,
        global_mean=global_mean,
        global_contrast=global_contrast,
        separation=separation,
        grain=grain,
        sharpness=sharpness,
        gradient_fields=gradient_fields,
    )


def analyze_scene(
    background: Image.Image,
    placement: Placement | None = None,
    *,
    prepared: PreparedScene | None = None,
    crop_components: bool = False,
    probe_cache: dict[tuple[float, float, float, float], tuple[tuple[float, float, float], float]]
    | None = None,
    probe_cache_lock: Any | None = None,
    local_weights: np.ndarray | None = None,
    local_weight_total: float | None = None,
    environment_probes: tuple[EnvironmentProbe, ...] | None = None,
    source_components: tuple[DetectedLight, ...] | None = None,
    measurements: ScenePlacementMeasurements | None = None,
    creative_fields: tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]] | None = None,
) -> SceneAnalysis:
    """Estimate environment lighting around the intended sprite position."""

    placement = (placement or Placement()).clamped()
    prepared = prepared or prepare_scene(background, (placement.height,))
    linear = prepared.linear
    luma = prepared.luma
    clipped_luma = prepared.clipped_luma
    h, w = luma.shape
    if local_weights is None:
        _, _, local_weights = _placement_region((h, w), placement, (prepared.yy, prepared.xx))
    local_weight_total = (
        float(np.sum(local_weights)) if local_weight_total is None else local_weight_total
    )
    subject_x = float(np.clip(placement.center_x, 0.0, 1.0))
    subject_y = float(np.clip(placement.baseline_y - placement.height * 0.48, 0.0, 1.0))

    # Avoid letting a single white pixel dominate; all colors are robustly clipped.
    global_mean = prepared.global_mean
    global_contrast = prepared.global_contrast
    if measurements is None:
        ambient_linear = _weighted_rgb(linear, local_weights, local_weight_total)
        local_mean = float(np.sum(clipped_luma * local_weights) / (local_weight_total + EPSILON))
        local_log_mean = float(
            np.exp(
                np.sum(np.log(clipped_luma + 0.008) * local_weights)
                / (local_weight_total + EPSILON)
            )
            - 0.008
        )
        local_variance = float(
            np.sum(((clipped_luma - local_mean) ** 2) * local_weights)
            / (local_weight_total + EPSILON)
        )
        local_saturation = float(
            np.sum(prepared.saturation * local_weights) / (local_weight_total + EPSILON)
        )
    else:
        ambient_linear = np.asarray(measurements.ambient_linear, dtype=np.float32)
        local_mean = measurements.local_mean
        local_log_mean = measurements.adaptation_luminance
        local_variance = measurements.local_variance
        local_saturation = measurements.local_saturation
    # Arithmetic luminance is easily dominated by a white object behind the
    # sprite. Camera-style log-average metering preserves position changes but
    # prevents reflective foam, snow, petals, and white walls from setting the
    # character exposure as if they emitted light.
    adaptation_luminance = max(local_log_mean, 0.0)
    local_contrast = float(np.sqrt(local_variance) / (local_mean + 0.035))

    # Bright-source saliency combines absolute brightness and locally exceptional light.
    source_weights = None
    if measurements is None or source_components is None:
        source_weights = prepared.base_source_weights * (0.58 + 0.42 * local_weights)

    # Prefer lights that can plausibly affect the character, but retain global sources.
    component_lights = source_components
    if component_lights is None:
        assert source_weights is not None
        if creative_fields is None:
            if prepared.creative_fields is None:
                prepared.creative_fields = _prepare_creative_color_fields(prepared.linear)
            creative_fields = prepared.creative_fields
        component_lights = _detect_source_components(
            linear,
            source_weights,
            luma=luma,
            texture_residual=prepared.texture_residual,
            coordinate_grid=(prepared.yy, prepared.xx),
            ring_kernel=prepared.ring_kernel,
            crop_components=crop_components,
            creative_fields=creative_fields,
        )

    physical_components = tuple(light for light in component_lights if not light.creative_only)
    creative_components = tuple(light for light in component_lights if light.creative_only)

    # A bright object below the subject in an already well-exposed scene is
    # usually reflecting daylight (flowers, snow, pale foliage, foam), not
    # emitting it.  Preserve genuinely compact practical lights and every
    # low-key source, but keep broad/repeated lower-field reflectors in the
    # environment probes.  This is a radiometric prior, not scene- or
    # character-specific tuning.
    support = {
        light: _directional_support(
            light, subject_y, adaptation_luminance, len(physical_components)
        )
        for light in physical_components
    }
    emissive_lights = physical_components
    broad_environment = not emissive_lights
    source_total = (
        float(np.sum(source_weights)) if measurements is None else measurements.source_total
    )
    separation = prepared.separation
    # Explicit emitters are meaningful in high-separation or low-key scenes.
    # Bright texture in daylight (foam, flowers, windows) belongs in the
    # environment probes instead of becoming four fake point lights.
    maximum_explicit_lights = 4
    if source_total <= EPSILON:
        light_x, light_y = 0.5, 0.2
        light_linear = np.array([1.0, 0.96, 0.9], dtype=np.float32)
        confidence = 0.0
        source_size = 1.0
    else:
        if emissive_lights:
            dominant = emissive_lights[0]
            light_x, light_y = dominant.x, dominant.y
            light_linear = _srgb_to_linear(np.asarray(dominant.color, dtype=np.float32))
            source_size = dominant.radius
        else:
            light_x = subject_x
            light_y = float(np.clip(subject_y - 0.42, 0.04, 0.42))
            if measurements is None:
                upper_hemisphere = np.clip(
                    (subject_y - prepared.normalized_y) * 2.2 + 0.35,
                    0.15,
                    1.0,
                )
                light_linear = _weighted_rgb(
                    linear,
                    local_weights * upper_hemisphere,
                )
            else:
                light_linear = np.asarray(
                    measurements.upper_light_linear,
                    dtype=np.float32,
                )
            source_size = 1.0
        concentration = 1.0 - source_size
        confidence = float(np.clip(0.68 * separation + 0.32 * concentration, 0.0, 1.0))
        if emissive_lights:
            confidence = float(np.clip(max(confidence, emissive_lights[0].confidence), 0.0, 1.0))

        # A broad illumination gradient captures light that is off-frame or too
        # large to appear as a compact highlight. It is sampled around the
        # current character position, so moving through a scene changes which
        # side of the sprite faces the brighter environment.
        gradient = prepared.gradient_fields.get(float(placement.height))
        if gradient is None:
            gradient = _gradient_field(clipped_luma, placement.height)
        gradient_x, gradient_y = gradient
        if measurements is None:
            gx = float(np.sum(gradient_x * local_weights) / (local_weight_total + EPSILON))
            gy = float(np.sum(gradient_y * local_weights) / (local_weight_total + EPSILON))
        else:
            gx = measurements.gradient_x
            gy = measurements.gradient_y
        gradient_magnitude = float(np.hypot(gx, gy))
        gradient_confidence = float(
            np.clip(gradient_magnitude / (local_mean + 0.025) * 28.0, 0.0, 1.0)
        )
        if gradient_confidence > 0.015:
            gradient_x_unit = gx / (gradient_magnitude + EPSILON)
            gradient_y_unit = gy / (gradient_magnitude + EPSILON)
            gradient_light_x = float(np.clip(subject_x + gradient_x_unit * 0.52, 0.0, 1.0))
            gradient_light_y = float(np.clip(subject_y + gradient_y_unit * 0.52, 0.0, 1.0))
            if broad_environment:
                gradient_light_y = min(gradient_light_y, subject_y - 0.12)
            gradient_blend = (0.72 if broad_environment else 0.42) * gradient_confidence
            light_x = light_x * (1.0 - gradient_blend) + gradient_light_x * gradient_blend
            light_y = light_y * (1.0 - gradient_blend) + gradient_light_y * gradient_blend
            confidence = float(np.clip(max(confidence, gradient_confidence * 0.72), 0.0, 1.0))

        # Broad, low-confidence illumination is usually sky/ceiling light. A
        # field of pale flowers or reflective ground should not become a fake
        # uplight merely because it contains many bright pixels.
        if broad_environment:
            light_y = min(light_y, subject_y - 0.12)
            confidence = min(confidence, 0.58)
        elif source_size > 0.8 and confidence < 0.32 and light_y > subject_y - 0.1:
            sky_prior = float(np.clip((0.32 - confidence) / 0.32 * 1.1, 0.0, 0.84))
            sky_y = float(np.clip(subject_y - 0.42, 0.04, 0.42))
            light_y = light_y * (1.0 - sky_prior) + sky_y * sky_prior

    primary_support = support[emissive_lights[0]] if emissive_lights else 0.0
    if emissive_lights and primary_support < 1.0 and source_total > EPSILON:
        diffuse_x = subject_x
        diffuse_y = _clamp_scalar(subject_y - 0.42, 0.04, 0.42)
        diffuse_confidence = _clamp_scalar(0.68 * separation, 0.0, 1.0)
        if measurements is None:
            upper_hemisphere = np.clip((subject_y - prepared.normalized_y) * 2.2 + 0.35, 0.15, 1.0)
            diffuse_linear = _weighted_rgb(linear, local_weights * upper_hemisphere)
        else:
            diffuse_linear = np.asarray(measurements.upper_light_linear, dtype=np.float32)
        if gradient_confidence > 0.015:
            diffuse_gradient_y = min(
                _clamp_scalar(subject_y + gradient_y_unit * 0.52, 0.0, 1.0), subject_y - 0.12
            )
            diffuse_blend = 0.72 * gradient_confidence
            diffuse_x = diffuse_x * (1.0 - diffuse_blend) + gradient_light_x * diffuse_blend
            diffuse_y = diffuse_y * (1.0 - diffuse_blend) + diffuse_gradient_y * diffuse_blend
            diffuse_confidence = max(diffuse_confidence, gradient_confidence * 0.72)
        diffuse_y = min(diffuse_y, subject_y - 0.12)
        light_x = diffuse_x * (1.0 - primary_support) + light_x * primary_support
        light_y = diffuse_y * (1.0 - primary_support) + light_y * primary_support
        light_linear = diffuse_linear * (1.0 - primary_support) + light_linear * primary_support
        source_size = 1.0 - primary_support + source_size * primary_support
        confidence = (
            min(diffuse_confidence, 0.58) * (1.0 - primary_support) + confidence * primary_support
        )

    # Normalize chromaticities without forcing bright whites into the sprite.
    ambient_luma = float(_luminance(ambient_linear))
    light_luma = float(_luminance(light_linear))
    ambient_chroma = ambient_linear / (ambient_luma + EPSILON)
    light_chroma = light_linear / (light_luma + EPSILON)
    ambient_chroma = np.clip(ambient_chroma, 0.45, 2.2)
    light_chroma = np.clip(light_chroma, 0.45, 2.4)
    shadow_chroma = np.clip(
        ambient_chroma * np.array([0.91, 0.96, 1.07], dtype=np.float32), 0.45, 2.2
    )
    ambient_display = tuple(
        float(x) for x in np.clip(_linear_to_srgb(ambient_chroma * 0.5), 0.0, 1.0)
    )
    light_display = tuple(float(x) for x in np.clip(_linear_to_srgb(light_chroma * 0.5), 0.0, 1.0))
    shadow_display = tuple(
        float(x) for x in np.clip(_linear_to_srgb(shadow_chroma * 0.5), 0.0, 1.0)
    )

    # Keep the fused dominant estimate first, followed by genuinely separate
    # connected emitters. This avoids inventing a source halfway between two
    # lamps while preserving the broad-gradient/off-frame correction above.
    lights: list[DetectedLight] = [
        DetectedLight(
            x=float(light_x),
            y=float(light_y),
            color=light_display,
            intensity=emissive_lights[0].intensity if emissive_lights else 1.0,
            radius=float(source_size),
            confidence=float(confidence),
            emission_score=0.0
            if broad_environment
            else emissive_lights[0].emission_score * primary_support,
        )
    ]
    for candidate in emissive_lights[1:maximum_explicit_lights]:
        lights.append(replace(candidate, intensity=candidate.intensity * support[candidate]))
    probes = environment_probes
    if probes is None:
        probes = _sample_environment_probes(
            linear,
            subject_x,
            subject_y,
            placement,
            (prepared.yy, prepared.xx),
            probe_cache,
            probe_cache_lock,
        )

    return SceneAnalysis(
        ambient_color=ambient_display,
        light_color=light_display,
        shadow_color=shadow_display,
        local_luminance=float(np.clip(local_mean, 0.0, 1.0)),
        adaptation_luminance=float(np.clip(adaptation_luminance, 0.0, 1.0)),
        global_luminance=global_mean,
        global_contrast=float(np.clip(global_contrast, 0.0, 2.0)),
        local_contrast=float(np.clip(local_contrast, 0.0, 2.0)),
        local_saturation=float(np.clip(local_saturation, 0.0, 1.0)),
        light_x=light_x,
        light_y=light_y,
        subject_x=subject_x,
        subject_y=subject_y,
        light_confidence=confidence,
        source_size=source_size,
        grain=prepared.grain,
        sharpness=prepared.sharpness,
        low_key=local_mean < 0.16,
        lights=tuple(lights),
        environment_probes=probes,
        creative_lights=creative_components,
    )


def sprite_content_bbox(sprite: Image.Image) -> tuple[int, int, int, int]:
    rgba = _pil_rgba(sprite)
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(
            "The sprite has no visible pixels. Use a transparent PNG with non-zero alpha."
        )
    return bbox


def _scene_box(
    background_size: tuple[int, int], sprite: Image.Image, placement: Placement
) -> tuple[int, int, int, int, tuple[int, int, int, int]]:
    bg_w, bg_h = background_size
    p = placement.clamped()
    bbox = sprite_content_bbox(sprite)
    content_w, content_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    scale = (bg_h * p.height) / max(content_h, 1)
    scaled_canvas_w = max(1, int(round(sprite.width * scale)))
    scaled_canvas_h = max(1, int(round(sprite.height * scale)))
    content_left = bbox[0] * scale
    content_bottom = bbox[3] * scale
    canvas_x = int(round(p.center_x * bg_w - (content_left + content_w * scale / 2)))
    canvas_y = int(round(p.baseline_y * bg_h - content_bottom))
    return canvas_x, canvas_y, scaled_canvas_w, scaled_canvas_h, bbox


def _environment_patch(
    background: Image.Image, sprite: Image.Image, placement: Placement
) -> np.ndarray:
    bg = np.asarray(_pil_rgb(background), dtype=np.float32) / 255.0
    x, y, scaled_w, scaled_h, _ = _scene_box(background.size, sprite, placement)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(background.width, x + scaled_w), min(background.height, y + scaled_h)
    patch = np.zeros((scaled_h, scaled_w, 3), dtype=np.float32)
    if x1 > x0 and y1 > y0:
        patch[y0 - y : y1 - y, x0 - x : x1 - x] = bg[y0:y1, x0:x1]
    patch = cv2.resize(
        patch,
        sprite.size,
        interpolation=cv2.INTER_AREA if scaled_w < sprite.width else cv2.INTER_LINEAR,
    )
    return patch


def _pseudo_surface(
    alpha: np.ndarray,
    srgb: np.ndarray,
    depth: float,
    *,
    linear_srgb: np.ndarray | None = None,
    linear_luma: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reconstruct a smooth height field and its screen-space normal map."""

    mask = (alpha > 0.035).astype(np.uint8)
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    if float(distance.max()) > EPSILON:
        distance /= float(distance.max())
    luma = (
        linear_luma
        if linear_luma is not None
        else _luminance(linear_srgb if linear_srgb is not None else _srgb_to_linear(srgb))
    )
    broad_luma = cv2.GaussianBlur(luma, (0, 0), sigmaX=max(2.0, min(alpha.shape) / 100))
    broad_luma = (broad_luma - np.mean(broad_luma[mask > 0])) if np.any(mask) else broad_luma
    # A distance field has ridges wherever two silhouette edges are equally
    # close. Smooth that broad shape separately: applying the same wide filter
    # to painted relief would erase useful hair, face and clothing detail.
    silhouette_height = cv2.GaussianBlur(
        np.sqrt(np.maximum(distance, 0.0)), (0, 0), sigmaX=max(1.2, min(alpha.shape) / 16)
    )
    # Painted shading bands and line art sit a few pixels wide. Sampled at close
    # to native scale, the artist's own boundaries become hard steps in the
    # inferred surface and read as creases across a face or a cardigan; at form
    # scale the broad painted volume still shapes the surface and those
    # boundaries stay flat. The silhouette term is untouched, so the shape of
    # the light response does not move.
    detail_height = cv2.GaussianBlur(broad_luma, (0, 0), sigmaX=max(1.2, min(alpha.shape) / 96))
    height = 0.76 * silhouette_height + 0.24 * detail_height
    # Height is dimensionless, but Sobel differences are per pixel. Express
    # slope in the same surface coordinates at every input resolution.
    strength = 5.5 * depth * (min(alpha.shape) / 256.0)
    shape_x = cv2.Sobel(silhouette_height, cv2.CV_32F, 1, 0, ksize=3) * (0.76 * strength)
    shape_y = cv2.Sobel(silhouette_height, cv2.CV_32F, 0, 1, ksize=3) * (0.76 * strength)
    detail_x = cv2.Sobel(detail_height, cv2.CV_32F, 1, 0, ksize=3) * (0.24 * strength)
    detail_y = cv2.Sobel(detail_height, cv2.CV_32F, 0, 1, ksize=3) * (0.24 * strength)
    # Painted brightness is uncertain evidence of relief. Preserve small
    # slopes, but smoothly bound strong albedo edges instead of creating a
    # cliff through a face or across two differently colored fabrics.
    detail_budget = max(0.35 * depth, EPSILON)
    detail_scale = np.sqrt(1.0 + (detail_x * detail_x + detail_y * detail_y) / detail_budget**2)
    nx = -shape_x - detail_x / detail_scale
    ny = -shape_y - detail_y / detail_scale
    nz = np.ones_like(nx) * (0.82 + 0.45 * (1.0 - depth))
    norm = np.sqrt(nx * nx + ny * ny + nz * nz) + EPSILON
    return height * mask, nx / norm, ny / norm, nz / norm


def _ray_marched_shadow(
    height: np.ndarray,
    alpha: np.ndarray,
    light_x: float,
    light_y: float,
    elevation: float,
    steps: int,
    source_radius: float = 0.0,
) -> np.ndarray:
    """Return soft self-shadow occlusion from a 2D height-field ray march.

    Each visible pixel samples reconstructed surface heights in the direction
    of the emitter. A higher intervening sample blocks the ray until its
    virtual elevation rises above that sample. The output is 0 for visible and
    1 for fully occluded.
    """

    mask = (alpha > 0.025).astype(np.float32)
    horizontal = float(np.hypot(light_x, light_y))
    if horizontal < 0.025 or not np.any(mask):
        return np.zeros_like(height, dtype=np.float32)
    direction_x, direction_y = light_x / horizontal, light_y / horizontal
    steps = int(np.clip(steps, 4, 32))
    maximum_distance = max(3.0, min(height.shape) * 0.46)
    shadow = np.zeros_like(height, dtype=np.float32)
    for index in range(1, steps + 1):
        fraction = index / steps
        distance = maximum_distance * fraction
        transform = np.float32(
            [[1.0, 0.0, -direction_x * distance], [0.0, 1.0, -direction_y * distance]]
        )
        sampled_height = cv2.warpAffine(
            height,
            transform,
            (height.shape[1], height.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        sampled_mask = cv2.warpAffine(
            mask,
            transform,
            (height.shape[1], height.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        ray_rise = fraction * (0.22 + 0.34 * float(np.clip(elevation, 0.0, 1.0)))
        blocker = np.maximum(sampled_height - height - ray_rise, 0.0) * sampled_mask
        shadow = np.maximum(shadow, blocker)
    shadow = np.clip(shadow * 4.4, 0.0, 1.0) * mask
    softness = (
        max(0.8, min(height.shape) / 420)
        + float(np.clip(source_radius, 0.0, 1.0)) * min(height.shape) / 115
    )
    return cv2.GaussianBlur(shadow, (0, 0), sigmaX=softness)


def _surface_ambient_occlusion(height: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Approximate crevice occlusion from multiscale height concavity."""

    mask = (alpha > 0.025).astype(np.float32)
    small = cv2.GaussianBlur(height, (0, 0), sigmaX=max(1.2, min(height.shape) / 180))
    broad = cv2.GaussianBlur(height, (0, 0), sigmaX=max(3.0, min(height.shape) / 65))
    concavity = np.maximum(small - height, 0.0) * 4.2 + np.maximum(broad - height, 0.0) * 2.0
    return np.clip(concavity, 0.0, 1.0) * mask


def _light_vector(
    light_x: float, light_y: float, analysis: SceneAnalysis, radius: float
) -> tuple[float, float, float]:
    dx, dy = light_x - analysis.subject_x, light_y - analysis.subject_y
    direction_norm = max(float(np.hypot(dx, dy)), 0.12)
    lx, ly = dx / direction_norm, dy / direction_norm
    lz = 0.18 + radius * 0.90
    vector_norm = float(np.sqrt(lx * lx + ly * ly + lz * lz))
    return lx / vector_norm, ly / vector_norm, lz / vector_norm


def _chromaticity_from_display(color: tuple[float, float, float]) -> np.ndarray:
    linear = _srgb_to_linear(np.asarray(color, dtype=np.float32))
    return linear / (float(_luminance(linear)) + EPSILON)


def _apply_warmth(chroma: np.ndarray, bias: float) -> np.ndarray:
    warm = np.array([1.0 + 0.32 * bias, 1.0 + 0.03 * bias, 1.0 - 0.28 * bias], dtype=np.float32)
    return np.clip(chroma * warm, 0.45, 2.5)


def _smoothstep(values: np.ndarray, lower: float, upper: float) -> np.ndarray:
    scaled = np.clip((values - lower) / max(upper - lower, EPSILON), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def diffuse_scene_exposure_guard(analysis: SceneAnalysis) -> float:
    """Return confidence that a scene needs the broad-diffuse shoulder.

    Brightness alone is insufficient: a greenhouse with a strong sun patch is
    bright, yet its high global contrast makes the existing result correct.
    The shoulder is therefore enabled only by the conjunction of a high
    whole-scene level and a very flat whole-scene field.  This global evidence
    deliberately outranks a compact-source guess: a flower cluster must not
    switch exposure as the sprite crosses it.  Local adaptation still follows
    the moving character while this classification remains stable.
    """

    bright = float(_smoothstep(analysis.global_luminance, 0.18, 0.245))
    flat = 1.0 - float(_smoothstep(analysis.global_contrast, 0.46, 0.50))
    return float(np.clip(bright * flat, 0.0, 1.0))


def diffuse_scene_chroma_guard(analysis: SceneAnalysis) -> float:
    """Detect high-key broad illumination that has already been white-balanced.

    The classifier is scene-only and continuous. It contains no character,
    palette, skin, filename, or background-name rule. Compact lamps, sunsets,
    low-light scenes, and high-confidence directional sources remain untouched.
    """

    primary_emission = analysis.lights[0].emission_score if analysis.lights else 0.0
    high_key = float(_smoothstep(analysis.local_luminance, 0.30, 0.46))
    broad = float(_smoothstep(analysis.source_size, 0.62, 0.90))
    uncertain = 1.0 - float(_smoothstep(analysis.light_confidence, 0.34, 0.60))
    diffuse = 1.0 - float(_smoothstep(primary_emission, 0.12, 0.35))
    return float(np.clip(high_key * broad * uncertain * diffuse, 0.0, 1.0))


def _incident_mid(adaptation, arithmetic):
    """Retain compact light energy in dark scenes without a constant light floor."""
    dark = np.clip((0.12 - adaptation) / 0.095, 0.0, 1.0)
    dark = dark * dark * (3.0 - 2.0 * dark)
    return np.clip(
        0.82 * (adaptation + 0.65 * np.maximum(arithmetic - adaptation, 0.0) * dark), 0.0, 0.58
    )


def scene_target_mid(analysis: SceneAnalysis) -> float:
    """Return the palette-independent target midpoint for a scene analysis."""

    nominal_target = float(_incident_mid(analysis.adaptation_luminance, analysis.local_luminance))
    nominal_exposure = float(np.clip(nominal_target / REFERENCE_ART_MID, 0.0001, 2.15))
    guard = diffuse_scene_exposure_guard(analysis)
    corrected_exposure = nominal_exposure * (2.0 ** (-BROAD_DIFFUSE_MAX_STOPS * guard))
    corrected_target = corrected_exposure * REFERENCE_ART_MID
    return float(np.clip(corrected_target, 0.0, 0.58))


def _material_light_response(linear_luma: np.ndarray) -> np.ndarray:
    """Estimate how visibly a painted material should reflect generated light.

    Near-black line art, fur, and cloth still receive scene exposure and color,
    but they should not acquire the same broad highlight, AO depth, or edge
    spill as pale skin and white fabric.  The response is continuous and local,
    so mixed sprites need no subject or filename profile.
    """

    return _smoothstep(linear_luma, 0.012, 0.115)


def _scene_coordinate_fields(
    size: tuple[int, int], scene_bounds: tuple[float, float, float, float] | None
) -> tuple[np.ndarray, np.ndarray] | None:
    """Map every sprite pixel to normalized scene coordinates when available."""

    if scene_bounds is None:
        return None
    x0, y0, width, height = scene_bounds
    sprite_w, sprite_h = size
    yy, xx = np.mgrid[0:sprite_h, 0:sprite_w]
    scene_x = x0 + xx / max(sprite_w - 1, 1) * width
    scene_y = y0 + yy / max(sprite_h - 1, 1) * height
    return scene_x.astype(np.float32), scene_y.astype(np.float32)


def _sprite_exposure_anchor(visible_luma: np.ndarray) -> tuple[float, float]:
    """Return a palette-area-invariant painted-material exposure anchor.

    A whole-sprite percentile changes when one character has more dark hair,
    a larger jacket, a different pose, or a cropped canvas. That made the same
    scene expose differently shaped and colored sprites inconsistently.
    Instead, find the strongest upper-midtone material mode in a smoothed
    luminance histogram. Brightness weighting selects a real painted midtone
    over a larger dark garment, while the 60th--92nd percentile window rejects
    tiny specular/white accents. Scaling the mode by one fixed neutral-art
    calibration preserves the renderer baseline while normalizing new art.
    """

    values = np.asarray(visible_luma, dtype=np.float32)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.35, 0.0
    values = np.clip(values, 0.0, 1.0)
    area_mid, lower, upper = (float(value) for value in np.quantile(values, (0.54, 0.60, 0.92)))
    if values.size < 32 or upper - lower < 0.004:
        material_mid = float(np.quantile(values, 0.72))
    else:
        bins = 192
        histogram, edges = np.histogram(values, bins=bins, range=(0.0, 1.0))
        smoothed = cv2.GaussianBlur(
            histogram.astype(np.float32)[:, None],
            (1, 0),
            sigmaX=0.0,
            sigmaY=1.15,
        )[:, 0]
        centers = (edges[:-1] + edges[1:]) * 0.5
        candidate = (centers >= max(lower - 1.0 / bins, 0.0)) & (
            centers <= min(upper + 1.0 / bins, 1.0)
        )
        brightness_prior = np.clip((centers + 0.02) / (upper + 0.02), 0.0, 1.2) ** 1.1
        score = smoothed * brightness_prior
        score[~candidate] = -1.0
        material_mid = float(centers[int(np.argmax(score))])

    imbalance = (material_mid + 0.012) / (area_mid + 0.012)
    if imbalance <= 1.80:
        guard = 0.0
    elif imbalance >= 2.20:
        guard = 1.0
    else:
        guard = float(np.clip((imbalance - 1.80) / 0.40, 0.0, 1.0))
        guard = guard * guard * (3.0 - 2.0 * guard)
    return float(np.clip(material_mid * REFERENCE_MATERIAL_CALIBRATION, 0.035, 0.72)), guard


def relight_sprite(
    sprite: Image.Image,
    analysis: SceneAnalysis,
    settings: RelightSettings | None = None,
    environment_patch: np.ndarray | None = None,
    seed: int = 947,
    scene_bounds: tuple[float, float, float, float] | None = None,
) -> Image.Image:
    """Relight a transparent sprite while preserving its exact alpha channel."""

    settings = (settings or RelightSettings()).normalized()
    rgba = np.asarray(_pil_rgba(sprite), dtype=np.float32) / 255.0
    srgb = rgba[..., :3]
    alpha = rgba[..., 3]
    mask = alpha > 0.01
    if not np.any(mask):
        raise ValueError("The sprite has no visible pixels.")

    linear = _srgb_to_linear(srgb)
    original_luma = _luminance(linear)
    material_response = _material_light_response(original_luma)
    # A character should usually sit slightly above the local background, not
    # be driven to the value of the brightest windows or sky behind them.
    target_mid = scene_target_mid(analysis)
    auto_exposure = np.clip(target_mid / REFERENCE_ART_MID, 0.0001, 2.15)
    exposure = (auto_exposure**settings.auto_strength) * (2.0**settings.exposure_bias)

    ambient_chroma = _apply_warmth(
        _chromaticity_from_display(analysis.ambient_color), settings.warmth_bias
    )
    light_chroma = _apply_warmth(
        _chromaticity_from_display(analysis.light_color), settings.warmth_bias
    )
    shadow_chroma = _apply_warmth(
        _chromaticity_from_display(analysis.shadow_color), settings.warmth_bias
    )
    tint = np.power(
        np.clip(ambient_chroma, 0.55, 1.9), settings.color_adaptation * settings.auto_strength
    )

    ys, xs = np.nonzero(mask)
    sprite_cx = (float(xs.min()) + float(xs.max())) * 0.5 / max(sprite.width - 1, 1)
    sprite_cy = (float(ys.min()) + float(ys.max())) * 0.5 / max(sprite.height - 1, 1)
    height, nx, ny, nz = _pseudo_surface(alpha, srgb, settings.surface_depth)
    scene_coordinates = _scene_coordinate_fields(sprite.size, scene_bounds)

    scene_lights = list(analysis.lights)
    if not scene_lights:
        scene_lights = [
            DetectedLight(
                analysis.light_x,
                analysis.light_y,
                analysis.light_color,
                1.0,
                analysis.source_size,
                analysis.light_confidence,
            )
        ]
    if settings.manual_light_x is not None or settings.manual_light_y is not None:
        primary = scene_lights[0]
        scene_lights[0] = DetectedLight(
            primary.x if settings.manual_light_x is None else settings.manual_light_x,
            primary.y if settings.manual_light_y is None else settings.manual_light_y,
            primary.color,
            primary.intensity,
            primary.radius,
            primary.confidence,
        )

    weighted_lambert = np.zeros_like(alpha, dtype=np.float32)
    source_color_field = np.zeros((*alpha.shape, 3), dtype=np.float32)
    specular_field = np.zeros((*alpha.shape, 3), dtype=np.float32)
    total_light_weight = 0.0
    broad_light_weight = 0.0
    average_lx = average_ly = 0.0
    primary_lx = primary_ly = 0.0
    primary_lx_field: float | np.ndarray | None = None
    primary_ly_field: float | np.ndarray | None = None
    primary_shadow = np.zeros_like(alpha, dtype=np.float32)
    specular_power = 22.0 + analysis.sharpness * 34.0

    for index, light in enumerate(scene_lights[:4]):
        secondary_scale = 1.0 if index == 0 else settings.multi_light_strength
        screen_distance = float(
            np.hypot(light.x - analysis.subject_x, light.y - analysis.subject_y)
        )
        effective_distance = max(screen_distance - light.radius * 0.35, 0.0)
        positional_falloff = float(np.clip(1.15 / (1.0 + 1.8 * effective_distance**2), 0.55, 1.15))
        weight = (
            light.intensity
            * secondary_scale
            * (0.32 + 0.68 * light.confidence)
            * positional_falloff
        )
        if weight <= EPSILON:
            continue
        lx, ly, lz = _light_vector(light.x, light.y, analysis, light.radius)
        lx_field: float | np.ndarray = lx
        ly_field: float | np.ndarray = ly
        lz_field: float | np.ndarray = lz
        spatial_weight: float | np.ndarray = 1.0
        emitter_blend = float(np.clip(light.emission_score, 0.0, 1.0))
        if scene_coordinates is not None and emitter_blend > 0.0:
            scene_x, scene_y = scene_coordinates
            dx_field = light.x - scene_x
            dy_field = light.y - scene_y
            screen_distance_field = np.sqrt(dx_field * dx_field + dy_field * dy_field)
            direction_norm = np.maximum(screen_distance_field, 0.12)
            pixel_lx = dx_field / direction_norm
            pixel_ly = dy_field / direction_norm
            pixel_lz = np.full_like(pixel_lx, 0.18 + light.radius * 0.90)
            vector_norm = (
                np.sqrt(pixel_lx * pixel_lx + pixel_ly * pixel_ly + pixel_lz * pixel_lz) + EPSILON
            )
            pixel_lx, pixel_ly, pixel_lz = (
                pixel_lx / vector_norm,
                pixel_ly / vector_norm,
                pixel_lz / vector_norm,
            )
            lx_field = lx * (1.0 - emitter_blend) + pixel_lx * emitter_blend
            ly_field = ly * (1.0 - emitter_blend) + pixel_ly * emitter_blend
            lz_field = lz * (1.0 - emitter_blend) + pixel_lz * emitter_blend
            blended_norm = (
                np.sqrt(lx_field * lx_field + ly_field * ly_field + lz_field * lz_field) + EPSILON
            )
            lx_field, ly_field, lz_field = (
                lx_field / blended_norm,
                ly_field / blended_norm,
                lz_field / blended_norm,
            )

            # Normalize falloff at the subject center so moving an emitter
            # changes *where* it acts without changing scene exposure.  A real
            # compact source therefore lights the nearby part of a large
            # sprite instead of multiplying the entire PNG uniformly.
            source_reach = 0.08 + light.radius * 0.90
            falloff = 1.0 / (1.0 + (screen_distance_field / source_reach) ** 2)
            center_falloff = 1.0 / (1.0 + (screen_distance / source_reach) ** 2)
            relative_falloff = np.clip(falloff / (center_falloff + EPSILON), 0.32, 1.85)
            spatial_weight = 1.0 + (relative_falloff - 1.0) * emitter_blend * 0.72
        if index == 0:
            primary_lx, primary_ly = lx, ly
            primary_lx_field, primary_ly_field = lx_field, ly_field
        lambert = np.clip(nx * lx_field + ny * ly_field + nz * lz_field, 0.0, 1.0)
        lambert = cv2.GaussianBlur(lambert, (0, 0), sigmaX=max(0.7, min(alpha.shape) / 700))
        ray_shadow = np.zeros_like(alpha, dtype=np.float32)
        if settings.ray_shadow_strength > 0 and index < 2:
            ray_shadow = _ray_marched_shadow(
                height, alpha, lx, ly, lz, settings.ray_steps, light.radius
            )
            lambert *= 1.0 - ray_shadow * settings.ray_shadow_strength
        if index == 0:
            primary_shadow = ray_shadow

        light_chroma_i = _apply_warmth(
            _chromaticity_from_display(light.color), settings.warmth_bias
        )
        light_weight_field = weight * spatial_weight
        weighted_lambert += lambert * light_weight_field
        source_color_field += (
            lambert[..., None]
            * np.asarray(light_weight_field)[..., None]
            * np.clip(light_chroma_i, 0.55, 2.2)[None, None, :]
        )

        # Blinn-Phong evaluated against the virtual camera normal (0, 0, 1).
        half_norm = float(np.sqrt(lx * lx + ly * ly + (lz + 1.0) ** 2)) + EPSILON
        hx, hy, hz = lx / half_norm, ly / half_norm, (lz + 1.0) / half_norm
        specular = np.power(np.clip(nx * hx + ny * hy + nz * hz, 0.0, 1.0), specular_power)
        specular *= 1.0 - ray_shadow * settings.ray_shadow_strength
        specular_field += (
            specular[..., None]
            * np.asarray(light_weight_field)[..., None]
            * np.clip(light_chroma_i, 0.55, 2.3)[None, None, :]
        )

        total_light_weight += weight
        broad_light_weight += weight * (1.0 - emitter_blend)
        average_lx += lx * weight
        average_ly += ly * weight

    total_light_weight = max(total_light_weight, EPSILON)
    lambert = np.clip(weighted_lambert / total_light_weight, 0.0, 1.0)
    source_color_field /= total_light_weight
    specular_field /= total_light_weight
    average_lx /= total_light_weight
    average_ly /= total_light_weight
    confidence = 0.34 + 0.66 * analysis.light_confidence
    key_amount = settings.key_strength * confidence
    # Keep the mean close to one. Directional light models form rather than
    # simply multiplying an already bright anime palette into clipping.
    diffuse = 0.22 + lambert * (0.22 + key_amount * 1.35)

    # A broad positional falloff stabilizes flat painted regions while all
    # coordinates remain relative to the moving subject in the full scene.
    yy, xx = np.mgrid[0 : sprite.height, 0 : sprite.width]
    rel_x = xx / max(sprite.width - 1, 1) - sprite_cx
    rel_y = yy / max(sprite.height - 1, 1) - sprite_cy
    directional = np.clip(0.5 + (rel_x * average_lx + rel_y * average_ly) * 0.9, 0.0, 1.0)
    broad_fraction = float(np.clip(broad_light_weight / total_light_weight, 0.0, 1.0))
    diffuse *= 1.0 + (directional - 0.5) * 0.32 * key_amount * broad_fraction

    # The painted sprite already contains its own neutral-light value.  Form
    # transport may redistribute that energy, but a complex silhouette must
    # not become globally darker merely because its reconstructed normals have
    # a different average than a human sprite.  Near-black materials also show
    # a shallower generated response than pale materials, preserving fur and
    # line detail without changing scene exposure.
    visible_weight = alpha * mask
    diffuse_mean = float(np.sum(diffuse * visible_weight) / (np.sum(visible_weight) + EPSILON))
    diffuse = diffuse / max(diffuse_mean, EPSILON)
    form_visibility = 0.38 + 0.62 * material_response
    diffuse = 1.0 + (diffuse - 1.0) * form_visibility
    diffuse_mean = float(np.sum(diffuse * visible_weight) / (np.sum(visible_weight) + EPSILON))
    diffuse = np.clip(diffuse / max(diffuse_mean, EPSILON), 0.22, 2.2)

    direct_fraction = lambert * (0.22 + key_amount * 1.35)
    direct_fraction /= 0.22 + direct_fraction
    direct_chroma = source_color_field / np.maximum(lambert[..., None], 0.001)
    direct_tint = np.power(
        np.clip(direct_chroma, 0.34, 2.85), settings.color_adaptation * settings.auto_strength
    )
    surface_tint = tint[None, None, :] * (1.0 - direct_fraction[..., None])
    surface_tint += direct_tint * direct_fraction[..., None]
    lit = linear * exposure * settings.ambient_strength * surface_tint
    lit *= diffuse[..., None]

    # Cool/colored shadows and the spatially varying mix of all source colors.
    shadow_mix = np.clip((0.78 - lambert) * 0.56 * key_amount, 0.0, 0.52)
    shadow_mix *= 0.34 + 0.66 * material_response
    shadow_mix = shadow_mix[..., None]
    lit *= (1.0 - shadow_mix) + shadow_mix * np.clip(shadow_chroma, 0.55, 1.75)[None, None, :]

    # Eight environment lobes approximate colored hemispherical irradiance.
    if settings.probe_strength > 0 and analysis.environment_probes:
        probe_rgb = np.zeros_like(lit)
        probe_weight = np.zeros_like(alpha, dtype=np.float32)
        local_reference = analysis.local_luminance + 0.025
        for probe in analysis.environment_probes:
            probe_chroma = _apply_warmth(
                _chromaticity_from_display(probe.color), settings.warmth_bias
            )
            incidence = np.clip(
                nx * probe.direction_x + ny * probe.direction_y + nz * 0.42,
                0.0,
                1.0,
            )
            relative_energy = float(np.clip((probe.luminance + 0.015) / local_reference, 0.18, 2.6))
            weight_field = incidence * (0.25 + 0.75 * relative_energy)
            probe_rgb += weight_field[..., None] * np.clip(probe_chroma, 0.55, 2.1)[None, None, :]
            probe_weight += weight_field
        probe_tint = probe_rgb / (probe_weight[..., None] + EPSILON)
        probe_tint /= _luminance(probe_tint)[..., None] + EPSILON
        probe_mix = np.clip(settings.probe_strength * 0.16 * (probe_weight / 4.0), 0.0, 0.22)[
            ..., None
        ]
        lit *= (1.0 - probe_mix) + probe_mix * np.clip(probe_tint, 0.58, 1.9)

    # Multiscale concavity darkens reconstructed creases; the ray result adds
    # extra occlusion behind the dominant blocker without baking a fake drop shadow.
    ao = _surface_ambient_occlusion(height, alpha)
    combined_occlusion = np.clip(
        ao * settings.ambient_occlusion + primary_shadow * 0.18 * settings.ray_shadow_strength,
        0.0,
        0.72,
    )
    combined_occlusion *= 0.36 + 0.64 * material_response
    lit *= 1.0 - combined_occlusion[..., None]

    # Lower probes stand in for ground/floor bounce and remain position-aware.
    ground_probes = [probe for probe in analysis.environment_probes if probe.direction_y > 0.5]
    if settings.bounce_strength > 0 and ground_probes:
        ground_linear = np.zeros(3, dtype=np.float32)
        ground_energy = 0.0
        for probe in ground_probes:
            energy = probe.luminance + 0.02
            ground_linear += _chromaticity_from_display(probe.color) * energy
            ground_energy += energy
        ground_chroma = np.clip(ground_linear / (ground_energy + EPSILON), 0.52, 2.2)
        lower_body = np.clip((rel_y + 0.3) * 1.45, 0.0, 1.0)
        downward_facing = np.clip(ny * 0.7 + (1.0 - nz) * 0.22, 0.0, 1.0)
        bounce = (0.24 * lower_body + 0.76 * downward_facing) * settings.bounce_strength * 0.16
        lit += linear * exposure * ground_chroma[None, None, :] * bounce[..., None]

    # Material-aware source reflections: broad on pale/low-saturation paint,
    # restrained on strongly colored hair and clothing.
    if settings.specular_strength > 0:
        dielectric = np.clip(0.18 + (1.0 - _saturation(srgb)) * 0.82, 0.18, 1.0)
        material = dielectric * (0.14 + 0.86 * material_response) * mask
        lit += specular_field * material[..., None] * settings.specular_strength * 0.13 * exposure

    distance = cv2.distanceTransform((alpha > 0.02).astype(np.uint8), cv2.DIST_L2, 5)
    edge_width = max(2.0, min(sprite.width, sprite.height) * 0.018)
    edge = np.clip(1.0 - distance / edge_width, 0.0, 1.0) * (alpha > 0.02)
    facing_lx = primary_lx if primary_lx_field is None else primary_lx_field
    facing_ly = primary_ly if primary_ly_field is None else primary_ly_field
    facing = np.clip(nx * facing_lx + ny * facing_ly, 0.0, 1.0)
    rim = edge * np.power(facing, 0.7) * settings.rim_strength * confidence
    rim *= 0.42 + 0.58 * (1.0 - analysis.source_size)
    # Additive edge light must respect inferred material reflectance.  Without
    # this term a near-black rough surface receives the same white edge energy
    # as pale skin, producing a sticker-like halo on fur, black dresses, and
    # other perimeter-dense silhouettes.  The smooth response leaves normal
    # DDLC midtones untouched while retaining a restrained dielectric glint on
    # genuinely dark paint.  It depends only on local linear albedo.
    rim *= 0.12 + 0.88 * material_response
    lit += rim[..., None] * np.clip(light_chroma, 0.55, 2.2)[None, None, :] * 0.52 * exposure

    # Bring actual nearby scene color into semi-transparent and silhouette pixels.
    if environment_patch is not None and settings.wrap_strength > 0:
        patch = np.asarray(environment_patch, dtype=np.float32)
        if patch.shape[:2] != alpha.shape:
            patch = cv2.resize(patch, (sprite.width, sprite.height), interpolation=cv2.INTER_LINEAR)
        patch_linear = _srgb_to_linear(np.clip(patch, 0.0, 1.0))
        patch_blur = cv2.GaussianBlur(patch_linear, (0, 0), sigmaX=max(4.0, min(alpha.shape) / 45))
        # Opaque dark paint reflects only a restrained portion of the nearby
        # background.  Semi-transparent antialias/hair pixels retain the
        # stronger optical spill that actually belongs there.
        opaque_wrap = 0.12 + 0.88 * material_response
        wrap_weight = 0.25 * alpha * opaque_wrap + (1.0 - alpha)
        wrap = edge * wrap_weight * settings.wrap_strength
        wrap = np.clip(wrap, 0.0, 0.64)[..., None]
        lit = lit * (1.0 - wrap) + patch_blur * wrap

    # Broad high-key photographs have usually already undergone camera white
    # balance. Preserve authored chroma only on bright, low-saturation painted
    # materials so a cyan sky cannot turn neutral faces or white cloth green.
    # Luminance is held constant, so exposure, shading, AO, rim, and motion all
    # remain exactly scene-driven. Dark and strongly colored materials retain
    # the full environmental transport.
    chroma_guard = diffuse_scene_chroma_guard(analysis)
    if chroma_guard > 0.0:
        source_saturation = _saturation(srgb)
        neutral_material = 1.0 - _smoothstep(source_saturation, 0.16, 0.36)
        bright_material = _smoothstep(original_luma, 0.10, 0.38)
        preservation = (
            BROAD_DIFFUSE_CHROMA_PRESERVATION
            * chroma_guard
            * neutral_material
            * bright_material
            * settings.auto_strength
        )[..., None]
        current_luma = _luminance(lit)[..., None]
        source_chroma = np.clip(
            linear / (original_luma[..., None] + EPSILON),
            0.55,
            1.80,
        )
        lit = lit * (1.0 - preservation) + current_luma * source_chroma * preservation

    # Match contrast around the relit median without crushing line work.
    lit_luma = _luminance(lit)
    lit_mid = float(np.quantile(lit_luma[alpha > 0.15], 0.52))
    desired_contrast = np.clip(0.84 + analysis.local_contrast * 0.35, 0.76, 1.24)
    contrast_power = (
        1.0 + (desired_contrast - 1.0) * settings.contrast_match * settings.auto_strength
    )
    ratio = np.power((lit_luma + 0.018) / (lit_mid + 0.018), contrast_power - 1.0)
    lit *= np.clip(ratio, 0.55, 1.7)[..., None]

    # Scene saturation adaptation in linear-light opponent distance.
    gray = _luminance(lit)[..., None]
    target_sat_scale = np.clip(0.72 + analysis.local_saturation * 1.05, 0.68, 1.3)
    sat_scale = 1.0 + (target_sat_scale - 1.0) * settings.saturation_match * settings.auto_strength
    lit = gray + (lit - gray) * sat_scale

    # A filmic shoulder keeps pale skin, white shirts, and hair shine from
    # clipping when a bright photo background drives exposure upward. It only
    # acts above middle gray, preserving line art and low-light separation.
    if settings.highlight_rolloff > 0:
        lit_luma = _luminance(lit)
        shoulder_start = 0.46
        excess = np.maximum(lit_luma - shoulder_start, 0.0)
        compressed = shoulder_start + excess / (1.0 + excess * (1.7 * settings.highlight_rolloff))
        compression_ratio = np.where(
            lit_luma > shoulder_start, compressed / (lit_luma + EPSILON), 1.0
        )
        lit *= compression_ratio[..., None]
        # Luminance rolloff alone can still clip one highly saturated channel
        # (purple hair and red bows are common DDLC examples). A hue-preserving
        # gamut shoulder scales RGB together and asymptotically approaches 1.0.
        peak = np.max(lit, axis=2)
        peak_start = 0.82
        peak_excess = np.maximum(peak - peak_start, 0.0)
        fully_compressed_peak = peak_start + peak_excess / (1.0 + peak_excess / (1.0 - peak_start))
        gamut_strength = float(np.clip(settings.highlight_rolloff / 1.2, 0.0, 1.0))
        target_peak = peak + (fully_compressed_peak - peak) * gamut_strength
        lit *= np.where(peak > peak_start, target_peak / (peak + EPSILON), 1.0)[..., None]

    # Deterministic sensor/film grain, strongest in midtones and never in alpha.
    if settings.grain_match > 0 and analysis.grain > 0.015:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, 1.0, alpha.shape).astype(np.float32)
        noise = noise - cv2.GaussianBlur(noise, (0, 0), sigmaX=0.42)
        amplitude = analysis.grain * settings.grain_match * 0.018
        grain_weight = np.clip(1.0 - np.abs(_luminance(lit) - 0.35) * 1.8, 0.24, 1.0)
        lit += noise[..., None] * amplitude * grain_weight[..., None]

    output_srgb = np.clip(_linear_to_srgb(lit), 0.0, 1.0)
    output_srgb[~mask] = srgb[~mask]
    output = np.dstack((output_srgb, alpha))
    return Image.fromarray(np.round(output * 255.0).astype(np.uint8), "RGBA")


def _contact_shadow_layer(
    background_size: tuple[int, int],
    sprite: Image.Image,
    placement: Placement,
    analysis: SceneAnalysis,
    settings: RelightSettings,
) -> Image.Image:
    bg_w, bg_h = background_size
    layer = np.zeros((bg_h, bg_w), dtype=np.float32)
    x, y, scaled_w, scaled_h, bbox = _scene_box(background_size, sprite, placement)
    scale = scaled_h / max(sprite.height, 1)
    content_left = x + bbox[0] * scale
    content_right = x + bbox[2] * scale
    content_bottom = y + bbox[3] * scale
    width = max(8, int((content_right - content_left) * 0.72))
    height = max(3, int(bg_h * (0.008 + settings.shadow_softness * 0.018)))
    light_x = analysis.light_x if settings.manual_light_x is None else settings.manual_light_x
    away_x = (placement.center_x - light_x) * bg_w * 0.055
    cx = int((content_left + content_right) * 0.5 + away_x)
    cy = int(content_bottom - height * 0.2)
    cv2.ellipse(layer, (cx, cy), (width // 2, height), 0, 0, 360, 1.0, -1)
    sigma = max(1.0, height * (0.45 + settings.shadow_softness * 1.6))
    layer = cv2.GaussianBlur(layer, (0, 0), sigmaX=sigma, sigmaY=sigma * 0.62)
    opacity = settings.shadow_strength * (0.2 + (1.0 - analysis.local_luminance) * 0.2)
    alpha = np.clip(layer * opacity, 0.0, 0.72)
    shadow_rgb = np.asarray(analysis.shadow_color, dtype=np.float32) * 0.11
    rgba = np.dstack(
        (
            np.broadcast_to(shadow_rgb, (bg_h, bg_w, 3)),
            alpha,
        )
    )
    return Image.fromarray(np.round(np.clip(rgba, 0.0, 1.0) * 255).astype(np.uint8), "RGBA")


def composite_scene(
    background: Image.Image,
    relit_sprite: Image.Image,
    placement: Placement | None = None,
    analysis: SceneAnalysis | None = None,
    settings: RelightSettings | None = None,
) -> Image.Image:
    """Place a relit sprite over a background and add a contact shadow."""

    placement = (placement or Placement()).clamped()
    settings = (settings or RelightSettings()).normalized()
    background_rgba = _pil_rgba(background)
    analysis = analysis or analyze_scene(background_rgba, placement)
    result = background_rgba.copy()
    if settings.shadow_strength > 0:
        result = Image.alpha_composite(
            result,
            _contact_shadow_layer(
                background_rgba.size, relit_sprite, placement, analysis, settings
            ),
        )
    x, y, scaled_w, scaled_h, _ = _scene_box(background_rgba.size, relit_sprite, placement)
    interpolation = (
        Image.Resampling.LANCZOS if scaled_w < relit_sprite.width else Image.Resampling.BICUBIC
    )
    scaled = relit_sprite.resize((scaled_w, scaled_h), interpolation)
    result.alpha_composite(scaled, (x, y))
    return result


def render_scene(
    background: Image.Image,
    sprite: Image.Image,
    placement: Placement | None = None,
    settings: RelightSettings | None = None,
    analysis: SceneAnalysis | None = None,
) -> tuple[Image.Image, Image.Image, SceneAnalysis]:
    """Analyze, relight, and composite in one call."""

    placement = (placement or Placement()).clamped()
    settings = (settings or RelightSettings()).normalized()
    analysis = analysis or analyze_scene(background, placement)
    patch = _environment_patch(background, sprite, placement)
    canvas_x, canvas_y, scaled_w, scaled_h, _ = _scene_box(background.size, sprite, placement)
    scene_bounds = (
        canvas_x / max(background.width, 1),
        canvas_y / max(background.height, 1),
        scaled_w / max(background.width, 1),
        scaled_h / max(background.height, 1),
    )
    relit = relight_sprite(sprite, analysis, settings, patch, scene_bounds=scene_bounds)
    composite = composite_scene(background, relit, placement, analysis, settings)
    return composite, relit, analysis
