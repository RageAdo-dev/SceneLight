"""Build palette-independent SceneLight fields for any Ren'Py project.

Only derived light fields and sprite-form textures are written. Source art is
read from the user's local project and is never copied into the SDK or a
release archive.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from colorsys import rgb_to_hsv
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from .effects import compile_effect_packs
from .engine import (
    BROAD_DIFFUSE_MAX_STOPS,
    REFERENCE_ART_MID,
    DetectedLight,
    EnvironmentProbe,
    Placement,
    _detect_source_components,
    _display_chromaticity,
    _environment_probe_specs,
    _incident_mid,
    _linear_to_srgb,
    _luminance,
    _placement_region,
    _prepare_creative_color_fields,
    _smoothstep_scalar,
    _srgb_to_linear,
    _weighted_rgb,
    analyze_scene,
    diffuse_scene_chroma_guard,
    diffuse_scene_exposure_guard,
    prepare_scene,
    scene_target_mid,
)
from .form_maps import FORM_MAP_VERSION, build_sprite_form_maps
from .hashing import sha256_file
from .project import ProjectDiscovery, SpriteSpec

TILE_SIZE = (160, 90)
ATLAS_COLUMNS = 4
CHROMA_RANGE = 2.4
TRANSPORT_GRID_SIZE = (16, 9)
TRANSPORT_PLANES = 26
TRANSPORT_SUBJECT_Y_MAX = 0.84
TRANSPORT_CHARACTER_HEIGHT = 0.92
TRANSPORT_LIGHT_BASE = 3
TRANSPORT_PROBE_BASE = 15
TRANSPORT_PROBE_SCALAR_BASE = 23
TRANSPORT_CACHE_VERSION = "14-spatial-radiance-basis"
RUNTIME_MANIFEST_VERSION = 8
FORM_CHECKPOINT_INTERVAL = 16
MIB = 1024**2
GIB = 1024**3


def _atlas_layout(
    scene_count: int, grid_size: tuple[int, int], limit: int = 4096
) -> tuple[int, int]:
    """Fit both atlases inside the supported Ren'Py texture limit before allocating."""
    row_height = max(TILE_SIZE[1], grid_size[1])
    block_width = max(TILE_SIZE[0], grid_size[0] * TRANSPORT_PLANES)
    max_rows = limit // row_height
    max_columns = limit // block_width
    if max_rows < 1 or max_columns < 1:
        raise ValueError("SceneLight analysis grid exceeds the supported texture size")
    columns = max(min(ATLAS_COLUMNS, max_columns), math.ceil((scene_count + 1) / max_rows))
    if columns > max_columns:
        raise ValueError(
            f"SceneLight needs {scene_count + 1} light-field tiles; this analysis grid supports "
            f"at most {max_rows * max_columns} in {limit}px textures. "
            "Reduce the video inventory or grid size. No installed runtime was replaced."
        )
    return columns, math.ceil((scene_count + 1) / columns)


# Each worker retains a 128 MiB Lambert matrix plus image-sized working arrays.
# Source dimensions increase the scheduling estimate for large sprites; fewer
# concurrent workers preserve full-resolution output on smaller-memory hosts.
FORM_WORKER_MEMORY_BYTES = 256 * MIB
FORM_PIXEL_MEMORY_BYTES = 192
FORM_PARENT_MEMORY_RESERVE_BYTES = 512 * MIB
FORM_UNKNOWN_MEMORY_WORKERS = 2


@dataclass(frozen=True, slots=True)
class BuildResult:
    output_root: Path
    scene_count: int
    sprite_count: int
    manifest_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class _TransportGeometry:
    """Exact image-independent weights shared by every scene of one shape."""

    coordinates: tuple[tuple[int, int], ...]
    placements: tuple[Placement, ...]
    local_weights: tuple[np.ndarray, ...]
    local_weight_totals: tuple[float, ...]
    probe_specs: tuple[tuple[tuple[float, float, int], ...], ...]
    probe_weights: tuple[np.ndarray, ...]
    probe_weight_totals: tuple[float, ...]


_TRANSPORT_GEOMETRY_LOCK = Lock()


def _linear_chroma(display_color: tuple[float, float, float]) -> np.ndarray:
    linear = _srgb_to_linear(np.asarray(display_color, dtype=np.float32))
    return np.clip(linear / (float(_luminance(linear)) + 1e-6), 0.45, CHROMA_RANGE)


def _disabled_creative_light() -> DetectedLight:
    return DetectedLight(
        x=0.5,
        y=0.2,
        color=(0.7353569, 0.7353569, 0.7353569),
        intensity=0.0,
        radius=1.0,
        confidence=0.0,
        emission_score=0.0,
        creative_only=True,
    )


def _creative_hue_family(light: DetectedLight) -> int:
    hue = rgb_to_hsv(*light.color)[0]
    return int(math.floor(hue * 3.0 + 0.5)) % 3


def _single_creative_source_is_separate(
    physical: list[DetectedLight],
    candidate: DetectedLight,
) -> bool:
    """Accept one colored source only when it is distinct from a neutral key.

    A neutral key plus one red/blue/green practical is already a genuinely
    multicolored environment; requiring two *colored* hue families discards
    exactly the local light that should paint one side of the character.  The
    conservative evidence below is scene-only and keeps a weak colorful prop
    from replacing ordinary multi-light transport.
    """

    if not physical:
        return False
    primary = physical[0]
    primary_chroma = _linear_chroma(primary.color)
    candidate_chroma = _linear_chroma(candidate.color)
    primary_neutral_distance = float(np.linalg.norm(primary_chroma - 1.0))
    chroma_distance = float(np.linalg.norm(primary_chroma - candidate_chroma))
    spatial_distance = float(np.hypot(primary.x - candidate.x, primary.y - candidate.y))
    return (
        primary_neutral_distance < 0.40
        and chroma_distance > 0.45
        and spatial_distance > 0.10
        and candidate.intensity > 0.72
        and candidate.confidence > 0.72
    )


def _select_transport_lights(
    analysis,
    *,
    creative_layout: bool | None = None,
) -> tuple[DetectedLight, ...]:
    """Keep the physical aggregate plus hue families needed for spatial light.

    The first physical light is the analyzer's energy-balanced aggregate, so it
    remains the complete ordinary-lighting input. When two or more distinct
    hue families exist, reserve the remaining three shader slots for them
    instead of allowing connected-component lights to crowd them out. One
    strong colored family is also retained when it is spatially separated from
    a neutral physical key. Creative sources stay disabled in the physical sum;
    the shader activates them only after measuring matching conservative
    evidence.
    """

    physical = list(analysis.lights[:4])
    creative = list(analysis.creative_lights)
    if creative_layout is False:
        return tuple(physical)
    if not creative:
        if creative_layout is True:
            return tuple(physical[:1] + [_disabled_creative_light() for _ in range(3)])
        return tuple(physical)

    # Sum the hue sectors in each stable slot. Picking a winning sector made
    # a light jump between similarly colored regions as their scores crossed.
    grouped: dict[int, list[DetectedLight]] = {}
    for light in creative:
        if light.intensity > 0.0:
            grouped.setdefault(_creative_hue_family(light), []).append(light)
    energies = {
        family: sum(light.intensity**2 for light in group) for family, group in grouped.items()
    }
    maximum_energy = max(energies.values(), default=1.0)
    families: dict[int, DetectedLight] = {}
    for family, group in grouped.items():
        weights = np.asarray([light.intensity**2 for light in group], dtype=np.float32)
        weights /= energies[family]
        geometry = weights @ np.asarray(
            [(light.x, light.y, light.radius, light.confidence) for light in group],
            dtype=np.float32,
        )
        color = weights @ _srgb_to_linear(
            np.asarray([light.color for light in group], dtype=np.float32)
        )
        families[family] = DetectedLight(
            x=float(geometry[0]),
            y=float(geometry[1]),
            radius=float(geometry[2]),
            color=_display_chromaticity(color),
            confidence=float(geometry[3]),
            intensity=min(math.sqrt(energies[family] / maximum_energy), 1.0),
            emission_score=1.0,
            creative_only=True,
        )
    if not families:
        if creative_layout is True:
            return tuple(physical[:1] + [_disabled_creative_light() for _ in range(3)])
        return tuple(physical)
    if len(families) == 1 and creative_layout is None:
        candidate = next(iter(families.values()))
        if not _single_creative_source_is_separate(physical, candidate):
            return tuple(physical)
    hue_slots = [families.get(index, _disabled_creative_light()) for index in range(3)]
    return tuple(physical[:1] + hue_slots)


def _separation_evidence(lights: tuple[DetectedLight, ...]) -> float:
    """Continuous evidence for the optional colored-light hypothesis."""
    if not lights:
        return 0.0
    primary, *families = lights
    primary_chroma = _linear_chroma(primary.color)
    evidence = 0.0
    for i, light in enumerate(families):
        if light.intensity <= 0.0 or light.confidence <= 0.0:
            continue
        chroma = _linear_chroma(light.color)
        single = (
            (
                (1.0 - _smoothstep_scalar(float(np.linalg.norm(primary_chroma - 1.0)), 0.22, 0.40))
                * _smoothstep_scalar(float(np.linalg.norm(primary_chroma - chroma)), 0.45, 0.80)
                * _smoothstep_scalar(
                    math.hypot(primary.x - light.x, primary.y - light.y), 0.10, 0.24
                )
                * _smoothstep_scalar(light.intensity, 0.72, 0.90)
                * _smoothstep_scalar(light.confidence, 0.72, 0.90)
            )
            if primary.confidence > 0.0 and primary.intensity > 0.0
            else 0.0
        )
        evidence = max(evidence, single)
        for other in families[i + 1 :]:
            pair = (
                _smoothstep_scalar(
                    float(np.linalg.norm(chroma - _linear_chroma(other.color))), 0.55, 0.95
                )
                * _smoothstep_scalar(math.hypot(light.x - other.x, light.y - other.y), 0.04, 0.24)
                * _smoothstep_scalar(min(light.intensity, other.intensity), 0.0, 0.85)
                * _smoothstep_scalar(min(light.confidence, other.confidence), 0.0, 0.82)
            )
            evidence = max(evidence, pair)
    return evidence


def _camera_metadata(analysis) -> dict[str, object]:
    """Scene-only camera/material response used by the real-time shader."""

    selected_lights = _select_transport_lights(analysis)
    transport_lights = [(light, 0.0 if light.creative_only else 1.0) for light in selected_lights]
    light_transport_layout = (
        "physical-rgb-families-v1"
        if any(light.creative_only for light in selected_lights)
        else "physical-components-v1"
    )

    return {
        "shadow_chroma": [
            round(float(value), 6) for value in _linear_chroma(analysis.shadow_color)
        ],
        "local_contrast": round(float(analysis.local_contrast), 6),
        "local_saturation": round(float(analysis.local_saturation), 6),
        "light_confidence": round(float(analysis.light_confidence), 6),
        "source_size": round(float(analysis.source_size), 6),
        "grain": round(float(analysis.grain), 6),
        "sharpness": round(float(analysis.sharpness), 6),
        "local_luminance": round(float(analysis.local_luminance), 6),
        "broad_diffuse_chroma_guard": round(float(diffuse_scene_chroma_guard(analysis)), 6),
        "light_transport_layout": light_transport_layout,
        "light_transport": [
            {
                "position_radius_intensity": [
                    round(float(light.x), 6),
                    round(float(light.y), 6),
                    round(float(light.radius), 6),
                    round(float(light.intensity * default_enabled), 6),
                ],
                "chroma_confidence": [
                    *[round(float(value), 6) for value in _linear_chroma(light.color)],
                    round(float(light.confidence), 6),
                ],
                "emission_enabled": [
                    round(
                        float(light.emission_score if default_enabled > 0.5 else light.intensity),
                        6,
                    ),
                    default_enabled,
                ],
            }
            for light, default_enabled in transport_lights
        ],
        "probe_transport": [
            {
                "direction_luminance_enabled": [
                    round(float(probe.direction_x), 6),
                    round(float(probe.direction_y), 6),
                    round(float(probe.luminance), 6),
                    1.0,
                ],
                "chroma": [round(float(value), 6) for value in _linear_chroma(probe.color)],
            }
            for probe in analysis.environment_probes[:8]
        ],
    }


def _encode_unit(values: np.ndarray) -> np.ndarray:
    return np.round(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)


def _wrap_map(path: Path) -> np.ndarray:
    """Return the CPU renderer's low-frequency local background response.

    The desktop path blurs the scene patch in linear light before mixing it
    into silhouette and semitransparent pixels.  This scene-only equivalent is
    generated once, encoded back to sRGB for precision, and sampled by final
    screen position in the GPU shader.
    """

    source = Image.open(path).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    linear = _srgb_to_linear(np.asarray(source, dtype=np.float32) / 255.0)
    # 18 px at 720p matches the reference 960 px sprite canvas at the default
    # 0.92 scene height. The operation remains scene-only and universal.
    blurred = cv2.GaussianBlur(linear, (0, 0), sigmaX=18.0, sigmaY=18.0)
    reduced = cv2.resize(blurred, TILE_SIZE, interpolation=cv2.INTER_AREA)
    return _encode_unit(_linear_to_srgb(np.maximum(reduced, 0.0)))


@lru_cache(maxsize=1)
def _cached_transport_geometry(
    analysis_shape: tuple[int, int],
    grid_size: tuple[int, int],
) -> _TransportGeometry:
    """Build exact placement/probe weights once for all same-shaped scenes."""

    height, width = analysis_shape
    grid_width, grid_height = grid_size
    yy, xx = np.mgrid[0:height, 0:width]
    coordinates = tuple((row, column) for row in range(grid_height) for column in range(grid_width))

    placements: list[Placement] = []
    all_probe_specs: list[tuple[tuple[float, float, tuple[float, float, float, float]], ...]] = []
    for row, column in coordinates:
        subject_y = TRANSPORT_SUBJECT_Y_MAX * row / max(grid_height - 1, 1)
        baseline_y = subject_y + TRANSPORT_CHARACTER_HEIGHT * 0.48
        placement = Placement(
            column / max(grid_width - 1, 1),
            baseline_y,
            TRANSPORT_CHARACTER_HEIGHT,
        ).clamped()
        placements.append(placement)
        subject_x = float(np.clip(placement.center_x, 0.0, 1.0))
        exact_subject_y = float(np.clip(placement.baseline_y - placement.height * 0.48, 0.0, 1.0))
        all_probe_specs.append(
            _environment_probe_specs(
                analysis_shape,
                subject_x,
                exact_subject_y,
                placement,
            )
        )

    geometry_workers = max(1, min(12, os.cpu_count() or 1))

    def placement_weights(placement: Placement) -> np.ndarray:
        return _placement_region(
            analysis_shape,
            placement,
            (yy, xx),
        )[2]

    with ThreadPoolExecutor(max_workers=geometry_workers) as executor:
        local_weights = tuple(executor.map(placement_weights, placements))

    unique_probe_keys = tuple(
        dict.fromkeys(
            key
            for placement_specs in all_probe_specs
            for _direction_x, _direction_y, key in placement_specs
        )
    )
    probe_key_indices = {key: index for index, key in enumerate(unique_probe_keys)}
    probe_y = yy[:, :1]
    probe_x = xx[:1, :]

    def gaussian_weights(key: tuple[float, float, float, float]) -> np.ndarray:
        target_x, target_y, sigma_x, sigma_y = key
        # This is intentionally the same single float64 exp followed by the
        # same float32 cast used by the reference analyzer. It is cached, not
        # approximated or made separable.
        return np.exp(
            -0.5 * (((probe_x - target_x) / sigma_x) ** 2 + ((probe_y - target_y) / sigma_y) ** 2)
        ).astype(np.float32)

    with ThreadPoolExecutor(max_workers=geometry_workers) as executor:
        probe_weights = tuple(executor.map(gaussian_weights, unique_probe_keys))

    indexed_probe_specs = tuple(
        tuple(
            (direction_x, direction_y, probe_key_indices[key])
            for direction_x, direction_y, key in placement_specs
        )
        for placement_specs in all_probe_specs
    )
    return _TransportGeometry(
        coordinates=coordinates,
        placements=tuple(placements),
        local_weights=local_weights,
        local_weight_totals=tuple(float(np.sum(weights)) for weights in local_weights),
        probe_specs=indexed_probe_specs,
        probe_weights=probe_weights,
        probe_weight_totals=tuple(float(np.sum(weights)) for weights in probe_weights),
    )


def warm_transport_geometry(
    analysis_shape: tuple[int, int] = (360, 640),
    grid_size: tuple[int, int] = TRANSPORT_GRID_SIZE,
) -> None:
    """Warm the exact, scene-independent transport geometry cache."""

    with _TRANSPORT_GEOMETRY_LOCK:
        _cached_transport_geometry(tuple(analysis_shape), tuple(grid_size))


def _analysis_shape_for_path(path: Path, maximum: int = 640) -> tuple[int, int]:
    """Return the analyzer shape without decoding the image's pixel payload."""

    with Image.open(path) as source:
        width, height = source.size
    scale = min(1.0, maximum / max(height, width))
    return (
        max(2, round(height * scale)),
        max(2, round(width * scale)),
    )


def _transport_geometry(
    analysis_shape: tuple[int, int],
    grid_size: tuple[int, int],
) -> _TransportGeometry:
    # functools.lru_cache permits duplicate concurrent misses. Keep the large
    # geometry build single-flight when a project analyzes many scenes at once.
    with _TRANSPORT_GEOMETRY_LOCK:
        return _cached_transport_geometry(tuple(analysis_shape), tuple(grid_size))


def _transport_maps(
    scene_name: str,
    path_text: str,
    grid_size: tuple[int, int] = TRANSPORT_GRID_SIZE,
    point_workers: int = 1,
    crop_components: bool = True,
    scene_fixed_components: bool = False,
) -> tuple[str, np.ndarray]:
    """Bake the position-dependent half of ``analyze_scene`` into one LUT.

    This stores no character identity or hand tuning.  Every grid point runs
    the same desktop analyzer against the background, after which the GPU
    bilinearly samples the result using the sprite's transformed center.
    """

    path = Path(path_text)
    source = Image.open(path).convert("RGB")
    source.load()
    prepared = prepare_scene(source, (TRANSPORT_CHARACTER_HEIGHT,))
    geometry = _transport_geometry(prepared.luma.shape, grid_size)
    creative_fields = _prepare_creative_color_fields(prepared.linear)
    source_components = None
    if scene_fixed_components:
        source_components = _detect_source_components(
            prepared.linear,
            prepared.base_source_weights,
            luma=prepared.luma,
            texture_residual=prepared.texture_residual,
            coordinate_grid=(prepared.yy, prepared.xx),
            ring_kernel=prepared.ring_kernel,
            crop_components=crop_components,
            creative_fields=creative_fields,
        )

    def integrate_probe(index: int) -> tuple[tuple[float, float, float], float]:
        sample = _weighted_rgb(
            prepared.linear,
            geometry.probe_weights[index],
            geometry.probe_weight_totals[index],
        )
        return (
            _display_chromaticity(sample),
            float(np.clip(_luminance(sample), 0.0, 1.0)),
        )

    integration_workers = max(1, min(12, point_workers))
    if integration_workers > 1:
        with ThreadPoolExecutor(max_workers=integration_workers) as executor:
            probe_values = tuple(executor.map(integrate_probe, range(len(geometry.probe_weights))))
    else:
        probe_values = tuple(integrate_probe(index) for index in range(len(geometry.probe_weights)))

    def sample(index: int):
        row, column = geometry.coordinates[index]
        placement = geometry.placements[index]
        probes = tuple(
            EnvironmentProbe(direction_x, direction_y, *probe_values[probe_index])
            for direction_x, direction_y, probe_index in geometry.probe_specs[index]
        )
        analysis = analyze_scene(
            source,
            placement,
            prepared=prepared,
            crop_components=crop_components,
            local_weights=geometry.local_weights[index],
            local_weight_total=geometry.local_weight_totals[index],
            environment_probes=probes,
            creative_fields=creative_fields,
            source_components=source_components,
        )
        return analysis

    analysis_workers = max(1, min(12, point_workers))
    representative_indices: list[int] = []
    representative_by_placement: dict[tuple[float, float, float], int] = {}
    sample_aliases: list[int] = []
    for index, placement in enumerate(geometry.placements):
        key = (placement.center_x, placement.baseline_y, placement.height)
        representative = representative_by_placement.get(key)
        if representative is None:
            representative = index
            representative_by_placement[key] = representative
            representative_indices.append(representative)
        sample_aliases.append(representative)
    if analysis_workers > 1:
        with ThreadPoolExecutor(max_workers=analysis_workers) as executor:
            unique_analyses = tuple(executor.map(sample, representative_indices))
    else:
        unique_analyses = tuple(sample(index) for index in representative_indices)
    analysis_by_representative = dict(zip(representative_indices, unique_analyses, strict=True))
    samples = [
        (*geometry.coordinates[index], analysis_by_representative[representative])
        for index, representative in enumerate(sample_aliases)
    ]

    return scene_name, _encode_transport_analyses(samples, grid_size)


def _encode_transport_analyses(
    samples,
    grid_size: tuple[int, int],
) -> np.ndarray:
    """Encode analyzed placements into the runtime's canonical 26-plane LUT."""

    samples = tuple(samples)
    grid_width, grid_height = grid_size
    # Share one continuous blend across the spatial grid. A majority vote
    # abruptly replaced every secondary light when an animation crossed it.
    creative_samples = tuple(
        _select_transport_lights(analysis, creative_layout=True)
        for _row, _column, analysis in samples
    )
    layout_mix = _smoothstep_scalar(
        max((_separation_evidence(lights) for lights in creative_samples), default=0.0),
        0.0,
        0.25,
    )
    # Assemble all linear transport values first, then quantize the complete
    # LUT in one vectorized operation. The earlier scalar encoder performed
    # thousands of tiny NumPy calls per scene even though every channel uses
    # the same clip/round rule.
    values = np.zeros(
        (TRANSPORT_PLANES, grid_height, grid_width, 4),
        dtype=np.float32,
    )
    values[..., 3] = 1.0
    scalar_probes: list[tuple[int, int, int, int, float]] = []
    chroma_destinations: list[tuple[int, int, int]] = []
    chroma_colors: list[tuple[float, float, float]] = []

    for light_index in range(4):
        plane = TRANSPORT_LIGHT_BASE + light_index * 3
        values[plane, ..., :3] = (0.5, 0.2, 1.0)
        values[plane + 1, ..., :3] = 1.0 / CHROMA_RANGE

    for row, column, analysis in samples:
        values[0, row, column, :3] = (
            analysis.local_contrast / 2.0,
            analysis.local_saturation,
            analysis.local_luminance,
        )
        values[2, row, column, 0] = math.sqrt(scene_target_mid(analysis) / 0.58)
        values[2, row, column, 1:3] = (layout_mix, 0.75)
        chroma_destinations.append((1, row, column))
        chroma_colors.append(analysis.ambient_color)

        transport_lights = _select_transport_lights(
            analysis,
            creative_layout=False,
        )
        for light_index, light in enumerate(transport_lights):
            plane = TRANSPORT_LIGHT_BASE + light_index * 3
            values[plane, row, column, :3] = (
                light.x,
                light.y,
                light.radius,
            )
            values[plane + 2, row, column, :3] = (
                0.0 if light.creative_only else light.intensity,
                light.confidence,
                light.intensity if light.creative_only else light.emission_score,
            )
            chroma_destinations.append((plane + 1, row, column))
            chroma_colors.append(light.color)

        for probe_index, probe in enumerate(analysis.environment_probes[:8]):
            plane = TRANSPORT_PROBE_BASE + probe_index
            chroma_destinations.append((plane, row, column))
            chroma_colors.append(probe.color)
            scalar_probes.append(
                (
                    TRANSPORT_PROBE_SCALAR_BASE + probe_index // 3,
                    row,
                    column,
                    probe_index % 3,
                    probe.luminance,
                )
            )

    if chroma_colors:
        display = np.asarray(chroma_colors, dtype=np.float32)
        linear = _srgb_to_linear(display)
        luminance = _luminance(linear)
        chroma = np.clip(
            linear / (luminance[..., None] + 1e-6),
            0.45,
            CHROMA_RANGE,
        )
        for index, (plane, row, column) in enumerate(chroma_destinations):
            values[plane, row, column, :3] = chroma[index] / CHROMA_RANGE

    if layout_mix > 0.0:
        for (row, column, _analysis), lights in zip(samples, creative_samples, strict=True):
            for light_index, light in enumerate(lights[1:], 1):
                plane = TRANSPORT_LIGHT_BASE + light_index * 3
                optional = np.asarray(
                    (
                        (light.x, light.y, light.radius),
                        _linear_chroma(light.color) / CHROMA_RANGE,
                        (0.0, light.confidence, light.intensity),
                    ),
                    dtype=np.float32,
                )
                values[plane : plane + 3, row, column, :3] *= 1.0 - layout_mix
                values[plane : plane + 3, row, column, :3] += optional * layout_mix

    # Every data plane is opaque. Ren'Py premultiplies RGBA textures, so
    # storing an independent scalar in alpha would quantize RGB chroma by that
    # scalar before sampling (particularly destructive for dim probes).
    planes = _encode_unit(values)
    for plane, row, column, channel, luminance in scalar_probes:
        planes[plane, row, column, channel] = int(np.clip(round(luminance * 255.0), 0, 255))
    return planes


def _transport_light_layout(transport: np.ndarray) -> str:
    """Return the semantic light-slot layout encoded by one transport LUT."""

    array = np.asarray(transport, dtype=np.uint8)
    if array.ndim == 4 and array.shape[0] == TRANSPORT_PLANES:
        planes = np.moveaxis(array, 0, 1)
    elif array.ndim == 3 and array.shape[1] % TRANSPORT_PLANES == 0:
        planes = array.reshape(
            array.shape[0],
            TRANSPORT_PLANES,
            array.shape[1] // TRANSPORT_PLANES,
            array.shape[2],
        )
    else:
        raise ValueError(f"Unexpected transport shape: {array.shape}")
    if np.all(planes[:, 2, :, 2] == 191):
        return "spatial-radiance-v3"
    if np.all(planes[:, 2, :, 2] == 255):
        return "continuous-light-slots-v2"
    for light_index in range(1, 4):
        scalar_plane = TRANSPORT_LIGHT_BASE + light_index * 3 + 2
        scalar = planes[:, scalar_plane, :, :3]
        if np.any((scalar[..., 0] <= 2) & (scalar[..., 2] > 2)):
            return "physical-rgb-families-v1"
    return "physical-components-v1"


def _transport_maps_cuda(
    scene_name: str,
    path_text: str,
    grid_size: tuple[int, int] = TRANSPORT_GRID_SIZE,
    crop_components: bool = True,
    source_components=None,
    prepared_source=None,
) -> tuple[str, np.ndarray]:
    """Bake a transport LUT with CUDA reductions and shared CPU decisions."""

    # Keep CuPy completely optional: importing the ordinary builder must never
    # load a CUDA runtime on machines that use the exact CPU fallback.
    from .cuda_backend import analyze_transport_cuda, analyze_transport_cuda_path

    analysis_kwargs = {
        "grid_size": grid_size,
        "subject_y_max": TRANSPORT_SUBJECT_Y_MAX,
        "character_height": TRANSPORT_CHARACTER_HEIGHT,
        "crop_components": crop_components,
        "source_components": source_components,
    }
    if prepared_source is None:
        result = analyze_transport_cuda_path(Path(path_text), **analysis_kwargs)
    else:
        source, prepared = prepared_source
        result = analyze_transport_cuda(
            source,
            prepared=prepared,
            **analysis_kwargs,
        )
    samples = (
        (row, column, analysis)
        for (row, column), analysis in zip(
            result.coordinates,
            result.analyses,
            strict=True,
        )
    )
    return scene_name, _encode_transport_analyses(samples, grid_size)


def _transport_maps_accelerated(
    scene_name: str,
    path_text: str,
    grid_size: tuple[int, int] = TRANSPORT_GRID_SIZE,
    *,
    component_threads: int = 6,
    require_cuda: bool = False,
    scene_fixed_components: bool = False,
) -> tuple[str, np.ndarray]:
    """Build one exact scene with overlapped CUDA geometry/classification.

    This is the low-latency path used by Studio 2. Image-independent GPU
    geometry builds while the CPU performs the exact connected-component
    decisions. The final LUT is the same production CUDA transport used by a
    full project build; machines without CUDA retain the CPU reference path.
    """

    from .cuda_backend import (
        CudaTransportGeometry,
        PreparedScene,
        cuda_available,
        cuda_transport_geometry,
        detect_transport_bundle_path,
        initialize_component_worker,
    )

    if not cuda_available():
        if require_cuda:
            raise RuntimeError("CUDA analysis was requested, but CuPy cannot access an NVIDIA GPU")
        return _transport_maps(
            scene_name,
            path_text,
            grid_size,
            scene_fixed_components=scene_fixed_components,
        )

    path = Path(path_text)
    analysis_shape = _analysis_shape_for_path(path)
    initialize_component_worker(component_threads)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            geometry_future = executor.submit(
                cuda_transport_geometry,
                analysis_shape,
                grid_size,
                TRANSPORT_SUBJECT_Y_MAX,
                TRANSPORT_CHARACTER_HEIGHT,
            )
            bundle = detect_transport_bundle_path(
                path,
                grid_size=grid_size,
                subject_y_max=TRANSPORT_SUBJECT_Y_MAX,
                character_height=TRANSPORT_CHARACTER_HEIGHT,
                crop_components=True,
                scene_fixed_components=scene_fixed_components,
            )
            geometry: CudaTransportGeometry = geometry_future.result()
        del geometry
        assert isinstance(bundle.prepared, PreparedScene)
        return _transport_maps_cuda(
            scene_name,
            path_text,
            grid_size,
            source_components=bundle.components,
            prepared_source=(Image.new("RGB", (1, 1)), bundle.prepared),
        )
    except Exception:
        if require_cuda:
            raise
        return _transport_maps(
            scene_name,
            path_text,
            grid_size,
            scene_fixed_components=scene_fixed_components,
        )


def _annular_meter_fields(
    linear: np.ndarray,
    clipped_luma: np.ndarray,
    character_height: float = 0.88,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate the desktop meter at every possible subject center.

    The CPU reference uses a wide annulus and deliberately downweights the
    pixels directly behind the sprite. A compact Gaussian instead mistakes a
    white wall, lamp globe, or flower cluster for local illumination. This
    convolution is the same scene-only meter evaluated once into a GPU field.
    """

    height, width = clipped_luma.shape
    character_pixels = max(4.0, height * character_height)
    character_width = max(4.0, character_pixels * 0.54)
    radius_x = max(character_width * 0.86, 1.0)
    radius_y = max(character_pixels * 0.66, 1.0)
    extent_x = min(width - 1, int(math.ceil(radius_x * 2.5)))
    extent_y = min(height - 1, int(math.ceil(radius_y * 2.5)))
    yy, xx = np.mgrid[-extent_y : extent_y + 1, -extent_x : extent_x + 1]
    distance = (xx / radius_x) ** 2 + (yy / radius_y) ** 2
    kernel = np.exp(-np.maximum(distance - 0.5, 0.0) * 1.8)
    kernel *= np.where(distance < 0.28, 0.18, 1.0)
    kernel = kernel.astype(np.float32)

    denominator = cv2.filter2D(
        np.ones_like(clipped_luma),
        -1,
        kernel,
        borderType=cv2.BORDER_CONSTANT,
    )
    log_luma = np.log(clipped_luma + 0.008)
    adaptation = (
        np.exp(
            cv2.filter2D(log_luma, -1, kernel, borderType=cv2.BORDER_CONSTANT)
            / (denominator + 1e-6)
        )
        - 0.008
    )
    ambient = np.empty_like(linear)
    for channel in range(3):
        ambient[..., channel] = cv2.filter2D(
            linear[..., channel],
            -1,
            kernel,
            borderType=cv2.BORDER_CONSTANT,
        ) / (denominator + 1e-6)
    return np.maximum(adaptation, 0.0), np.maximum(ambient, 0.0)


def _scene_maps(
    path: Path,
    *,
    source_image: Image.Image | None = None,
    prepared_scene=None,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    source = source_image or Image.open(path).convert("RGB")
    resized = source.resize(TILE_SIZE, Image.Resampling.LANCZOS)
    srgb = np.asarray(resized, dtype=np.float32) / 255.0
    linear = _srgb_to_linear(srgb)
    luma = _luminance(linear)
    clipped_luma = np.minimum(luma, np.quantile(luma, 0.995))
    adaptation_field, ambient = _annular_meter_fields(linear, clipped_luma)
    ambient_luma = _luminance(ambient)
    ambient_chroma = np.clip(ambient / (ambient_luma[..., None] + 1e-6), 0.45, CHROMA_RANGE)

    analysis = analyze_scene(
        source,
        Placement(0.5, 0.99, 0.78),
        prepared=prepared_scene,
    )
    # Local pixel value is not local illumination: a white wall, pale tree, or
    # printed highlight can be bright without emitting light. Anchor exposure
    # to the robust whole-scene adaptation and allow only a low-frequency,
    # compressed positional drift. Actual emitters still affect direction,
    # color, and key strength through the independently classified field below.
    global_target = scene_target_mid(analysis)
    nominal_target = _incident_mid(adaptation_field, ambient_luma)
    nominal_exposure = np.clip(
        nominal_target / REFERENCE_ART_MID,
        0.0001,
        2.15,
    )
    exposure_guard = diffuse_scene_exposure_guard(analysis)
    corrected_exposure = nominal_exposure * (2.0 ** (-BROAD_DIFFUSE_MAX_STOPS * exposure_guard))
    target_mid = np.clip(
        corrected_exposure * REFERENCE_ART_MID,
        0.0,
        0.58,
    )
    yy, xx = np.mgrid[0 : TILE_SIZE[1], 0 : TILE_SIZE[0]]
    nx = xx / max(TILE_SIZE[0] - 1, 1)
    ny = yy / max(TILE_SIZE[1] - 1, 1)
    field = np.zeros(TILE_SIZE[::-1], dtype=np.float32)
    weighted_color = np.zeros((*TILE_SIZE[::-1], 3), dtype=np.float32)
    for light in analysis.lights:
        radius = float(np.clip(light.radius * 0.52, 0.10, 0.72))
        distance2 = ((nx - light.x) / radius) ** 2 + ((ny - light.y) / radius) ** 2
        contribution = np.exp(-0.5 * distance2).astype(np.float32)
        contribution *= float(light.intensity * (0.42 + 0.58 * light.confidence))
        field += contribution
        weighted_color += contribution[..., None] * _linear_chroma(light.color)

    # A weak upper-hemisphere prior keeps a usable direction in flat daylight
    # while still allowing localized emitters to dominate the gradient.
    sky = (0.10 + 0.16 * (1.0 - ny)).astype(np.float32)
    field += sky
    weighted_color += sky[..., None] * _linear_chroma(analysis.light_color)
    field_max = float(np.quantile(field, 0.995)) + 1e-6
    key_strength = np.clip(field / field_max, 0.0, 1.0)
    key_chroma = np.clip(weighted_color / (field[..., None] + 1e-6), 0.45, CHROMA_RANGE)

    irradiance = np.empty((*TILE_SIZE[::-1], 4), dtype=np.uint8)
    irradiance[..., :3] = np.round(np.clip(ambient_chroma / CHROMA_RANGE, 0.0, 1.0) * 255).astype(
        np.uint8
    )
    irradiance[..., 3] = np.round(np.clip(target_mid / 0.58, 0.0, 1.0) * 255).astype(np.uint8)
    emitter = np.empty_like(irradiance)
    emitter[..., :3] = np.round(np.clip(key_chroma / CHROMA_RANGE, 0.0, 1.0) * 255).astype(np.uint8)
    emitter[..., 3] = np.round(key_strength * 255).astype(np.uint8)
    metadata = {
        # Kept diagnostic-only: no source image is copied into the runtime.
        "source_name": path.name,
        "lights": sum(
            light.intensity > 0.001 and light.confidence > 0.001
            for light in _select_transport_lights(analysis)
        ),
        "probes": len(analysis.environment_probes),
        "dominant_direction": analysis.light_direction_name,
        "adaptation_luminance": round(analysis.adaptation_luminance, 6),
        "broad_diffuse_exposure_guard": round(diffuse_scene_exposure_guard(analysis), 6),
        "target_mid": round(global_target, 6),
        **_camera_metadata(analysis),
    }
    return irradiance, emitter, metadata


def _safe_stem(key: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")[:48]
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{readable}_{digest}"


def _transport_cache_path(
    cache_root: Path,
    scene_name: str,
    source_path: Path,
    grid_size: tuple[int, int],
) -> Path:
    digest = hashlib.sha256()
    digest.update(f"scenelight-transport-{TRANSPORT_CACHE_VERSION}\0".encode("ascii"))
    digest.update(f"{grid_size[0]}x{grid_size[1]}\0".encode("ascii"))
    with source_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return cache_root / f"{_safe_stem(scene_name)}_{digest.hexdigest()[:16]}.npz"


def _form_payload(
    fallback: dict[str, str],
    entries: dict[str, object],
    skipped: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "version": FORM_MAP_VERSION,
        "algorithm": "cpu-reference-static-form-v1",
        "fallback": fallback,
        "sprites": {key: entries[key] for key in sorted(entries)},
        "skipped": sorted(skipped or [], key=lambda item: (item["sprite"], item["stage"])),
    }


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Publish a JSON checkpoint without exposing a partially-written file."""

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _available_memory_bytes() -> int | None:
    """Return currently available physical memory without an extra dependency."""

    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return max(0, int(status.ullAvailPhys))
        except (AttributeError, OSError, ValueError):
            return None
        return None

    try:
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return max(0, available_pages * page_size)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _memory_safe_form_workers(
    requested_workers: int,
    job_count: int,
    *,
    available_memory_bytes: int | None = None,
    largest_sprite_pixels: int = 0,
) -> int:
    """Cap exact form concurrency by live memory rather than CPU count alone."""

    requested = max(1, min(int(requested_workers), max(1, int(job_count))))
    available = (
        _available_memory_bytes()
        if available_memory_bytes is None
        else max(0, int(available_memory_bytes))
    )
    worker_bytes = max(
        FORM_WORKER_MEMORY_BYTES,
        128 * MIB + max(0, int(largest_sprite_pixels)) * FORM_PIXEL_MEMORY_BYTES,
    )
    if available is None:
        memory_workers = (
            1 if worker_bytes > FORM_WORKER_MEMORY_BYTES else FORM_UNKNOWN_MEMORY_WORKERS
        )
    else:
        reserve = min(4 * GIB, max(FORM_PARENT_MEMORY_RESERVE_BYTES, available // 4))
        usable = max(0, available - reserve)
        memory_workers = max(1, usable // worker_bytes)
    return max(1, min(requested, int(memory_workers)))


def _form_pixel_count(spec: SpriteSpec, sizes: dict[Path, tuple[int, int]]) -> int:
    """Read only image headers when budgeting full-resolution worker memory."""

    if spec.canvas_size is not None:
        width, height = spec.canvas_size
    else:
        source = spec.layers[0]
        size = sizes.get(source)
        if size is None:
            with Image.open(source) as image:
                size = image.size
            sizes[source] = size
        width, height = size
    return max(1, width) * max(1, height)


def _render_form_entry(
    game_root: Path,
    key: str,
    spec: SpriteSpec,
    paths: dict[str, Path],
    source_fingerprint: str,
) -> tuple[str, dict[str, object] | None]:
    sprite = spec.compose()
    if sprite.getchannel("A").getextrema()[1] / 255.0 <= 0.01:
        return key, None
    source_size = sprite.size
    source_sha256 = hashlib.sha256(sprite.tobytes()).hexdigest()
    maps = build_sprite_form_maps(
        sprite,
        source_size=source_size,
        source_sha256=source_sha256,
    )
    # Derived runtime textures are decoded losslessly either way. Fast PNG
    # compression keeps first-time attachment responsive without changing a
    # single texel; maximum compression is disproportionately CPU-expensive on
    # full-resolution sprite maps.
    maps.normal_noise.save(paths["normal_noise"], compress_level=1)
    maps.height_ao_edge.save(paths["height_ao_edge"], compress_level=1)
    maps.response.save(paths["response"], compress_level=1)
    return key, {
        **maps.metadata,
        "source_fingerprint": source_fingerprint,
        **{
            name: str(path.relative_to(game_root)).replace("\\", "/")
            for name, path in paths.items()
        },
    }


def _sprite_spec_fingerprint(
    spec: SpriteSpec,
    layer_digests: dict[Path, tuple[int, bytes]] | None = None,
    resolved_layers: dict[Path, Path] | None = None,
) -> str:
    """Hash encoded source layers without decoding a full sprite twice.

    The previous inventory pass composed every form merely to discover its
    pixel hash, then each map worker composed the same form again. Runtime
    captures are already deterministic lossless files, so an ordered digest of
    their encoded bytes is a safe cache/dedup key. The worker still records the
    established exact RGBA pixel hash in ``source_sha256``.
    """

    # v4 invalidates maps made with the CPU-dispatch-dependent sRGB table.
    # Captured source pixels and scene transport retain their own contracts.
    digest = hashlib.sha256(b"scenelight-sprite-spec-4\0")
    digest.update(json.dumps(spec.positions, separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(spec.canvas_size, separators=(",", ":")).encode("ascii"))
    digest.update(b"\1" if spec.renderer_alpha else b"\0")
    for layer in spec.layers:
        resolved = resolved_layers.get(layer) if resolved_layers is not None else None
        if resolved is None:
            resolved = layer.resolve()
            if resolved_layers is not None:
                resolved_layers[layer] = resolved
        cached = layer_digests.get(resolved) if layer_digests is not None else None
        if cached is None:
            size = resolved.stat().st_size
            layer_digest = sha256_file(resolved)
            cached = (size, layer_digest)
            if layer_digests is not None:
                layer_digests[resolved] = cached
        size, layer_digest = cached
        digest.update(b"\1")
        digest.update(size.to_bytes(8, "little", signed=False))
        digest.update(layer_digest)
    return digest.hexdigest()


def _build_form_maps(
    discovery: ProjectDiscovery,
    output_root: Path,
    worker_count: int,
) -> dict[str, object]:
    form_root = output_root / "sprite_form"
    form_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "sprite_form_manifest.json"
    previous: dict[str, object] = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    previous_entries = previous.get("sprites", {})
    if previous.get("version") != FORM_MAP_VERSION or not isinstance(previous_entries, dict):
        previous_entries = {}

    fallback_paths = {
        "normal_noise": form_root / "fallback_normal_noise.png",
        "height_ao_edge": form_root / "fallback_height_ao_edge.png",
        "response": form_root / "fallback_response.png",
    }
    Image.new("RGB", (1, 1), (128, 128, 0)).save(fallback_paths["normal_noise"])
    Image.new("RGB", (1, 1), (42, 0, 128)).save(fallback_paths["height_ao_edge"])
    Image.new("RGBA", (1, 1), (184, 184, 255, 255)).save(fallback_paths["response"])
    fallback = {
        name: str(path.relative_to(discovery.game_root)).replace("\\", "/")
        for name, path in fallback_paths.items()
    }

    entries: dict[str, object] = {}
    skipped: list[dict[str, str]] = [dict(item) for item in discovery.skipped_sprites]
    reusable_by_fingerprint: dict[str, dict[str, object]] = {}
    asset_exists: dict[str, bool] = {}
    asset_names = ("normal_noise", "height_ao_edge", "response")
    for prior in previous_entries.values():
        if not isinstance(prior, dict):
            continue
        source_fingerprint = prior.get("source_fingerprint")
        if not isinstance(source_fingerprint, str):
            continue
        prior_assets_valid = True
        for name in asset_names:
            raw_asset = prior.get(name)
            if not isinstance(raw_asset, str):
                prior_assets_valid = False
                break
            exists = asset_exists.get(raw_asset)
            if exists is None:
                exists = (discovery.game_root / raw_asset).is_file()
                asset_exists[raw_asset] = exists
            if not exists:
                prior_assets_valid = False
                break
        if prior_assets_valid:
            reusable_by_fingerprint.setdefault(source_fingerprint, prior)

    pending: list[tuple[str, SpriteSpec, dict[str, Path], str]] = []
    pending_master_by_fingerprint: dict[str, str] = {}
    aliases_by_master: dict[str, list[str]] = {}
    fingerprint_by_spec: dict[
        tuple[tuple[Path, ...], tuple[tuple[int, int], ...], tuple[int, int] | None, bool],
        str,
    ] = {}
    layer_digests: dict[Path, tuple[int, bytes]] = {}
    resolved_layers: dict[Path, Path] = {}

    def resolved_layer_path(layer: Path) -> Path:
        resolved = resolved_layers.get(layer)
        if resolved is None:
            resolved = layer.resolve()
            resolved_layers[layer] = resolved
        return resolved

    sprite_total = len(discovery.sprites)
    inventory_step = max(1, sprite_total // 100)
    cached_count = 0
    duplicate_count = 0
    if sprite_total:
        print(f"form inventory 0/{sprite_total}: checking sprite forms", flush=True)
    for index, (key, spec) in enumerate(sorted(discovery.sprites.items()), start=1):
        if index == 1 or index % inventory_step == 0 or index == sprite_total:
            print(f"form inventory {index}/{sprite_total}: {key}", flush=True)
        try:
            spec_key = (
                tuple(resolved_layer_path(layer) for layer in spec.layers),
                spec.positions,
                spec.canvas_size,
                spec.renderer_alpha,
            )
            source_fingerprint = fingerprint_by_spec.get(spec_key)
            if source_fingerprint is None:
                source_fingerprint = _sprite_spec_fingerprint(
                    spec,
                    layer_digests,
                    resolved_layers,
                )
                fingerprint_by_spec[spec_key] = source_fingerprint
        except Exception as error:  # noqa: BLE001 - third-party sprite decoders vary widely
            detail = f"{type(error).__name__}: {error}"
            skipped.append({"sprite": key, "stage": "source", "error": detail})
            print(f"form warning {index}/{sprite_total}: skipped {key} ({detail})", flush=True)
            continue
        stem = _safe_stem(key)
        paths = {
            "normal_noise": form_root / f"{stem}_normal_noise.png",
            "height_ao_edge": form_root / f"{stem}_height_ao_edge.png",
            "response": form_root / f"{stem}_response.png",
        }
        reusable = reusable_by_fingerprint.get(source_fingerprint)
        if reusable is not None:
            entries[key] = reusable
            cached_count += 1
            continue

        master = pending_master_by_fingerprint.get(source_fingerprint)
        if master is not None:
            aliases_by_master.setdefault(master, []).append(key)
            duplicate_count += 1
            continue
        pending_master_by_fingerprint[source_fingerprint] = key
        # Keep only the lightweight source specification in the queue. Each
        # worker composes its image on demand, bounding memory to the active
        # worker count even for mods with thousands of expressions.
        pending.append((key, spec, paths, source_fingerprint))

    if sprite_total:
        print(
            f"form inventory {sprite_total}/{sprite_total}: "
            f"{len(pending)} unique, {duplicate_count} duplicate, {cached_count} cached",
            flush=True,
        )

    requested_workers = max(1, min(worker_count, len(pending) or 1))
    source_sizes: dict[Path, tuple[int, int]] = {}
    largest_sprite_pixels = 0
    for _key, spec, _paths, _fingerprint in pending:
        try:
            largest_sprite_pixels = max(
                largest_sprite_pixels, _form_pixel_count(spec, source_sizes)
            )
        except (OSError, ValueError, IndexError, Image.DecompressionBombError):
            # The existing worker error path reports unreadable third-party art.
            continue
    active_workers = _memory_safe_form_workers(
        requested_workers, len(pending) or 1, largest_sprite_pixels=largest_sprite_pixels
    )
    if pending:
        memory_note = (
            f"; memory-safe from {requested_workers} requested"
            if active_workers != requested_workers
            else ""
        )
        print(
            f"form 0/{len(pending)}: preparing unique sprite surfaces "
            f"[{active_workers} workers{memory_note}]",
            flush=True,
        )

    remaining = list(pending)
    completed_total = 0
    form_progress_step = max(1, len(pending) // 100)
    while remaining:
        executor_type = ProcessPoolExecutor if active_workers > 1 else ThreadPoolExecutor
        executor = executor_type(max_workers=active_workers)
        futures = {}
        exhausted_memory = False
        try:
            for key, spec, paths, source_fingerprint in remaining:
                future = executor.submit(
                    _render_form_entry,
                    discovery.game_root,
                    key,
                    spec,
                    paths,
                    source_fingerprint,
                )
                futures[future] = key
            for future in as_completed(futures):
                key = futures[future]
                try:
                    key, entry = future.result()
                except (BrokenProcessPool, MemoryError):
                    raise
                except Exception as error:  # noqa: BLE001 - isolate malformed mod assets
                    detail = f"{type(error).__name__}: {error}"
                    skipped.append({"sprite": key, "stage": "surface-map", "error": detail})
                    aliases = aliases_by_master.get(key, ())
                    for alias in aliases:
                        skipped.append({"sprite": alias, "stage": "surface-map", "error": detail})
                    completed_total += 1
                    print(
                        f"form warning {completed_total}/{len(pending)}: skipped {key} ({detail})",
                        flush=True,
                    )
                    continue
                aliases = aliases_by_master.get(key, ())
                if entry is None:
                    # Ren'Py projects commonly register transparent
                    # placeholders for transitions, UI layers, or dynamically
                    # populated images. They have no surface to relight and
                    # must not abort analysis of the project's visible forms.
                    completed_total += 1
                    print(
                        f"form skipped {completed_total}/{len(pending)}: {key} (no visible pixels)",
                        flush=True,
                    )
                    continue
                entries[key] = entry
                for alias in aliases:
                    entries[alias] = entry
                completed_total += 1
                if (
                    completed_total == 1
                    or completed_total % form_progress_step == 0
                    or completed_total == len(pending)
                ):
                    suffix = f" (+{len(aliases)} identical forms)" if aliases else ""
                    print(f"form {completed_total}/{len(pending)}: {key}{suffix}", flush=True)
                # Checkpoint in small batches. This preserves interruption recovery
                # while avoiding an O(n²) rewrite pattern on mods with thousands of
                # expressions. Generated texture pixels and the final manifest are
                # unchanged; an interruption can redo at most one small batch.
                if completed_total % FORM_CHECKPOINT_INTERVAL == 0:
                    _write_json_atomic(manifest_path, _form_payload(fallback, entries, skipped))
        except (BrokenProcessPool, MemoryError):
            exhausted_memory = True
            for future in futures:
                future.cancel()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        if not exhausted_memory:
            break
        if active_workers <= 1:
            raise MemoryError(
                "SceneLight could not generate sprite form maps with the available memory."
            )
        remaining = [job for job in remaining if job[0] not in entries]
        active_workers = max(1, active_workers // 2)
        print(
            "form retry: the worker pool exceeded available memory; continuing "
            f"the same exact analysis with {active_workers} worker"
            f"{'s' if active_workers != 1 else ''} (quality unchanged)",
            flush=True,
        )

    payload = _form_payload(fallback, entries, skipped)
    _write_json_atomic(manifest_path, payload)
    return payload


def build_project(
    discovery: ProjectDiscovery,
    *,
    grid_size: tuple[int, int] = TRANSPORT_GRID_SIZE,
    workers: int | None = None,
    analyzer_backend: str = "auto",
) -> BuildResult:
    """Generate a complete runtime from locally discovered project art."""

    if grid_size[0] < 2 or grid_size[1] < 2:
        raise ValueError("Transport grid must be at least 2x2")
    requested_backend = analyzer_backend.lower()
    if requested_backend not in {"auto", "cuda", "cpu"}:
        raise ValueError("Analyzer backend must be auto, cuda, or cpu")
    if requested_backend == "cpu":
        resolved_backend = "cpu"
    else:
        from .cuda_backend import cuda_available

        available = cuda_available()
        if requested_backend == "cuda" and not available:
            raise RuntimeError("CUDA analysis was requested, but CuPy cannot access an NVIDIA GPU")
        resolved_backend = "cuda" if available else "cpu"
    output_root = discovery.game_root / "scenelight_runtime"
    output_root.mkdir(parents=True, exist_ok=True)
    effect_build = compile_effect_packs(discovery.game_root)
    _write_json_atomic(output_root / "effect_packs.json", effect_build.manifest)
    for warning in effect_build.warnings:
        print(f"effect pack warning: skipped {warning}", flush=True)
    scene_names = sorted(discovery.scenes)
    atlas_columns, rows = _atlas_layout(len(scene_names), grid_size)
    atlas_size = (TILE_SIZE[0] * atlas_columns, TILE_SIZE[1] * rows)
    irradiance_atlas = Image.new("RGBA", atlas_size, (106, 106, 106, 79))
    emitter_atlas = Image.new("RGBA", atlas_size, (106, 106, 106, 128))
    wrap_atlas = Image.new("RGB", atlas_size, (0, 0, 0))
    transport_block_width = grid_size[0] * TRANSPORT_PLANES
    transport_atlas = Image.new(
        "RGBA",
        (transport_block_width * atlas_columns, grid_size[1] * rows),
        (0, 0, 0, 255),
    )

    worker_count = workers or max(1, min(8, os.cpu_count() or 1, len(scene_names)))
    transport_by_scene: dict[str, np.ndarray] = {}
    cache_root = discovery.project_root / ".scenelight_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_paths = {
        name: _transport_cache_path(cache_root, name, discovery.scenes[name], grid_size)
        for name in scene_names
    }
    for name, cache_path in cache_paths.items():
        if not cache_path.is_file():
            continue
        with np.load(cache_path) as cached:
            transport = cached["transport"]
        expected = (TRANSPORT_PLANES, grid_size[1], grid_size[0], 4)
        if transport.shape == expected and transport.dtype == np.uint8:
            transport_by_scene[name] = transport
            print(f"transport cached: {name}", flush=True)

    missing_transport = [name for name in scene_names if name not in transport_by_scene]
    if missing_transport:
        print(
            f"transport 0/{len(missing_transport)}: preparing [{resolved_backend}]",
            flush=True,
        )
    names_by_shape: dict[tuple[int, int], list[str]] = {}
    for name in missing_transport:
        shape = _analysis_shape_for_path(discovery.scenes[name])
        names_by_shape.setdefault(shape, []).append(name)

    completed_transport = 0
    analysis_budget = max(1, min(12, workers or (os.cpu_count() or 1)))
    component_executor = None
    component_futures = {}
    component_buffers = {}
    ordered_missing: list[str] = []
    component_submit_index = 0
    cuda_placeholder = Image.new("RGB", (1, 1))
    if resolved_backend == "cuda" and missing_transport:
        from .cuda_backend import (
            SharedPreparedSceneInfo,
            allocate_shared_prepared_buffer,
            detect_transport_bundle_path,
            initialize_component_worker,
            materialize_shared_prepared_scene,
        )

        component_workers = max(1, min(8, worker_count, len(missing_transport)))
        component_executor = ProcessPoolExecutor(
            max_workers=component_workers,
            initializer=initialize_component_worker,
        )
        ordered_missing = [
            name for shape in sorted(names_by_shape) for name in names_by_shape[shape]
        ]
        # Each result carries exact full-resolution CUDA inputs from the worker
        # that already prepared them. Keep only a small sliding window in IPC
        # so a 700-scene mod does not accumulate gigabytes of completed arrays.
        component_window = min(len(ordered_missing), component_workers * 3)

        def submit_component_bundle(name: str):
            analysis_shape = _analysis_shape_for_path(discovery.scenes[name])
            allocation = allocate_shared_prepared_buffer(
                analysis_shape,
                TRANSPORT_CHARACTER_HEIGHT,
            )
            component_buffers[name] = allocation
            return component_executor.submit(
                detect_transport_bundle_path,
                str(discovery.scenes[name]),
                grid_size=grid_size,
                subject_y_max=TRANSPORT_SUBJECT_Y_MAX,
                character_height=TRANSPORT_CHARACTER_HEIGHT,
                crop_components=True,
                prepared_buffer=allocation.spec,
            )

        component_futures = {
            name: submit_component_bundle(name) for name in ordered_missing[:component_window]
        }
        component_submit_index = component_window
    try:
        # Process equal analysis shapes together. Both backends cache their
        # large image-independent geometry one shape at a time. CUDA pipelines
        # exact component classification across CPU processes while the parent
        # performs dense reductions on the GPU.
        for shape, shape_names in sorted(names_by_shape.items()):
            if resolved_backend == "cuda":
                assert component_executor is not None
                for name in shape_names:
                    bundle = component_futures.pop(name).result()
                    if component_submit_index < len(ordered_missing):
                        next_name = ordered_missing[component_submit_index]
                        component_submit_index += 1
                        component_futures[next_name] = submit_component_bundle(next_name)
                    allocation = component_buffers.pop(name)
                    prepared = None
                    try:
                        assert isinstance(bundle.prepared, SharedPreparedSceneInfo)
                        prepared = materialize_shared_prepared_scene(
                            bundle.prepared,
                            allocation,
                        )
                        name, transport = _transport_maps_cuda(
                            name,
                            str(discovery.scenes[name]),
                            grid_size,
                            source_components=bundle.components,
                            prepared_source=(cuda_placeholder, prepared),
                        )
                    except Exception as error:
                        if requested_backend == "cuda":
                            raise
                        print(
                            f"CUDA analyzer fallback for {name}: {error}",
                            flush=True,
                        )
                        name, transport = _transport_maps(
                            name,
                            str(discovery.scenes[name]),
                            grid_size,
                            analysis_budget,
                        )
                    finally:
                        if prepared is not None:
                            del prepared
                        allocation.close()
                    transport_by_scene[name] = transport
                    np.savez_compressed(cache_paths[name], transport=transport)
                    completed_transport += 1
                    print(
                        f"transport {completed_transport}/{len(missing_transport)}: "
                        f"{name} [{resolved_backend}]",
                        flush=True,
                    )
                continue

            warm_transport_geometry(shape, grid_size)
            scene_workers = min(2, analysis_budget, len(shape_names))
            point_workers = (
                analysis_budget if scene_workers == 1 else max(1, analysis_budget // scene_workers)
            )
            with ThreadPoolExecutor(max_workers=scene_workers) as executor:
                futures = {
                    executor.submit(
                        _transport_maps,
                        name,
                        str(discovery.scenes[name]),
                        grid_size,
                        point_workers,
                    ): name
                    for name in shape_names
                }
                for future in as_completed(futures):
                    name, transport = future.result()
                    transport_by_scene[name] = transport
                    np.savez_compressed(cache_paths[name], transport=transport)
                    completed_transport += 1
                    print(
                        f"transport {completed_transport}/{len(missing_transport)}: {name} [cpu]",
                        flush=True,
                    )
    finally:
        if component_executor is not None:
            component_executor.shutdown()
        for allocation in component_buffers.values():
            allocation.close()

    def render_scene_fields(
        scene_name: str,
    ) -> tuple[str, np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
        source_path = discovery.scenes[scene_name]
        irradiance, emitter, metadata = _scene_maps(source_path)
        return scene_name, irradiance, emitter, _wrap_map(source_path), metadata

    scene_fields: dict[
        str,
        tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]],
    ] = {}
    print(f"scene 0/{len(scene_names)}: preparing", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, min(worker_count, len(scene_names)))) as executor:
        futures = {
            executor.submit(render_scene_fields, scene_name): scene_name
            for scene_name in scene_names
        }
        for future in as_completed(futures):
            scene_name, irradiance, emitter, wrap, metadata = future.result()
            scene_fields[scene_name] = (irradiance, emitter, wrap, metadata)

    scene_manifest: dict[str, dict[str, object]] = {}
    for tile_index, scene_name in enumerate(scene_names, start=1):
        column, row = tile_index % atlas_columns, tile_index // atlas_columns
        destination = (column * TILE_SIZE[0], row * TILE_SIZE[1])
        irradiance, emitter, wrap, metadata = scene_fields[scene_name]
        irradiance_atlas.paste(Image.fromarray(irradiance, "RGBA"), destination)
        emitter_atlas.paste(Image.fromarray(emitter, "RGBA"), destination)
        wrap_atlas.paste(Image.fromarray(wrap, "RGB"), destination)
        transport_strip = np.concatenate(
            [transport_by_scene[scene_name][plane] for plane in range(TRANSPORT_PLANES)],
            axis=1,
        )
        transport_atlas.paste(
            Image.fromarray(transport_strip, "RGBA"),
            (column * transport_block_width, row * grid_size[1]),
        )
        metadata = dict(metadata)
        metadata["light_transport_layout"] = _transport_light_layout(transport_by_scene[scene_name])
        scene_manifest[scene_name] = {
            "tile": [column, row],
            "uv": [column / atlas_columns, row / rows, 1.0 / atlas_columns, 1.0 / rows],
            "transport_uv": [
                column / atlas_columns,
                row / rows,
                1.0 / (atlas_columns * TRANSPORT_PLANES),
                1.0 / rows,
            ],
            "calibration": discovery.scene_calibration.get(
                scene_name.split("::", 1)[0], discovery.calibration
            ).as_dict(),
            **metadata,
        }
        print(f"scene {tile_index}/{len(scene_names)}: {scene_name}", flush=True)

    irradiance_atlas.save(output_root / "irradiance_atlas.png", compress_level=1)
    emitter_atlas.save(output_root / "emitter_atlas.png", compress_level=1)
    wrap_atlas.save(output_root / "wrap_atlas.png", compress_level=1)
    transport_atlas.save(output_root / "transport_atlas.png", compress_level=1)
    scene_sequences: dict[str, dict[str, object]] = {}
    for scene_name, timeline in sorted(discovery.scene_sequences.items()):
        if len(timeline) < 2:
            continue
        positive_steps = [
            later[0] - earlier[0]
            for earlier, later in zip(timeline, timeline[1:], strict=False)
            if later[0] > earlier[0]
        ]
        interval_ms = min(positive_steps, default=250)
        scene_sequences[scene_name] = {
            "mode": "visible-source",
            "sample_window_ms": timeline[-1][0] + interval_ms,
            "frames": [[time_ms, frame_key] for time_ms, frame_key in timeline],
            "sources": discovery.scene_frame_sources.get(scene_name, {}),
            **discovery.scene_sequence_metadata.get(scene_name, {}),
        }

    manifest = {
        "version": RUNTIME_MANIFEST_VERSION,
        "virtual_size": [1280, 720],
        "reference_art_mid": REFERENCE_ART_MID,
        "character_tags": discovery.character_tags,
        "strength": discovery.strength,
        "calibration": discovery.calibration.as_dict(),
        "atlas": {
            "tile_size": list(TILE_SIZE),
            "columns": atlas_columns,
            "rows": rows,
            "irradiance": "scenelight_runtime/irradiance_atlas.png",
            "emitter": "scenelight_runtime/emitter_atlas.png",
            "wrap": "scenelight_runtime/wrap_atlas.png",
            "chroma_range": CHROMA_RANGE,
            "target_mid_range": 0.58,
        },
        "transport_atlas": {
            "texture": "scenelight_runtime/transport_atlas.png",
            "grid_size": list(grid_size),
            "planes": TRANSPORT_PLANES,
            "columns": atlas_columns,
            "rows": rows,
            "subject_y_max": TRANSPORT_SUBJECT_Y_MAX,
            "character_height": TRANSPORT_CHARACTER_HEIGHT,
            "chroma_range": CHROMA_RANGE,
            "target_mid_range": 0.58,
            "layout": "opaque-rgb-v1",
        },
        "scenes": scene_manifest,
        "scene_sequences": scene_sequences,
        "scene_analysis": discovery.scene_analysis,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Sprite forms are independent jobs. Start from the requested/CPU count;
    # _build_form_maps then applies a live-memory cap and exact-quality retry.
    # Concurrency changes scheduling only and never changes generated texels.
    form_worker_count = max(
        1,
        min(16, workers or (os.cpu_count() or 1), len(discovery.sprites) or 1),
    )
    forms = _build_form_maps(discovery, output_root, form_worker_count)
    report = {
        "sdk": "SceneLight",
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "transport_grid": list(grid_size),
        "analysis_backend": resolved_backend,
        "scene_count": len(scene_manifest),
        "sprite_count": len(forms["sprites"]),
        "character_tags": discovery.character_tags,
        "unsupported": discovery.unsupported,
        "skipped_sprites": forms.get("skipped", []),
        "effect_count": effect_build.effect_count,
        "effect_warnings": list(effect_build.warnings),
        "privacy": "Derived maps only. Source images were not copied.",
    }
    report_path = output_root / "install_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return BuildResult(
        output_root=output_root,
        scene_count=len(scene_manifest),
        sprite_count=len(forms["sprites"]),
        manifest_path=manifest_path,
        report_path=report_path,
    )
