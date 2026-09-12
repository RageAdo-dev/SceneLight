"""Universal sprite form data shared by the CPU reference and GPU runtime.

The expensive, scene-independent reconstruction is performed once per source
sprite.  Lighting remains dynamic: the runtime shader combines these maps with
the current scene emitters, probes, and final transformed screen position on
every frame.  No character identity or hand-authored material profile enters
the reconstruction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from .engine import (
    RelightSettings,
    _luminance,
    _material_light_response,
    _pseudo_surface,
    _surface_ambient_occlusion,
)

FORM_MAP_VERSION = 5
FORM_ANALYSIS_MAX_DIMENSION = 512
HEIGHT_MIN = -0.25
HEIGHT_MAX = 1.25
NOISE_RANGE = 4.0
RESPONSE_SIZE = 64


def _srgb_u8_table() -> np.ndarray:
    values = np.arange(256, dtype=np.float32) / 255.0
    base = (values + np.float32(0.055)) / np.float32(1.055)
    # AVX-512's float32 power can differ by one ULP from the approved table.
    # Evaluate only this 256-entry table in double precision, retaining the
    # original float32 base/exponent and rounding back once. Per-pixel lookup
    # and the live analyzer keep their existing fast paths.
    high = np.power(base.astype(np.float64), float(np.float32(2.4))).astype(np.float32)
    result = np.where(values <= 0.04045, values / 12.92, high)
    result.flags.writeable = False
    return result


_SRGB_U8_TO_LINEAR = _srgb_u8_table()


@dataclass(frozen=True, slots=True)
class SpriteFormMaps:
    normal_noise: Image.Image
    height_ao_edge: Image.Image
    response: Image.Image
    metadata: dict[str, object]


def _encode_unit(values: np.ndarray) -> np.ndarray:
    return np.round(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)


def _rgba_texture(rgb: np.ndarray) -> Image.Image:
    alpha = np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)
    return Image.fromarray(np.concatenate((rgb, alpha), axis=2), "RGBA")


@lru_cache(maxsize=8)
def _encoded_noise(shape: tuple[int, int], seed: int) -> np.ndarray:
    """Return the exact deterministic grain field once per worker and size."""

    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, shape).astype(np.float32)
    noise -= cv2.GaussianBlur(noise, (0, 0), sigmaX=0.42)
    encoded = _encode_unit(noise / (2.0 * NOISE_RANGE) + 0.5)
    encoded.flags.writeable = False
    return encoded


def _normal_response_lut(
    nx: np.ndarray,
    ny: np.ndarray,
    nz: np.ndarray,
    alpha: np.ndarray,
    form_visibility: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Build a compact integral of the sprite's normal distribution.

    A fragment shader cannot reduce all visible pixels to reproduce the CPU
    renderer's energy normalization.  The lookup stores the alpha-weighted
    mean Lambert response (R) and the same response weighted by local material
    visibility (G) for every possible upper-hemisphere light direction.  It is
    universal derived data, and lets differently shaped sprites conserve the
    same energy without per-character exposure constants.
    """

    visible = alpha > 0.01
    weights = (alpha * visible).astype(np.float64)
    total_weight = float(np.sum(weights))
    if total_weight <= 1e-8:
        raise ValueError("The sprite has no visible pixels")

    # Compress the normal distribution before evaluating the directional LUT.
    # This turns a 960x960 by 64x64 reduction into a small deterministic matrix
    # multiply while preserving the CPU surface statistics.
    bin_count = 64
    histogram, x_edges, y_edges = np.histogram2d(
        nx[visible],
        ny[visible],
        bins=bin_count,
        range=((-1.0, 1.0), (-1.0, 1.0)),
        weights=weights[visible],
    )
    visibility_histogram, _x_edges, _y_edges = np.histogram2d(
        nx[visible],
        ny[visible],
        bins=bin_count,
        range=((-1.0, 1.0), (-1.0, 1.0)),
        weights=(weights * form_visibility)[visible],
    )
    del x_edges, y_edges
    lambert_matrix = _normal_lambert_matrix()

    response = np.zeros((RESPONSE_SIZE * RESPONSE_SIZE, 3), dtype=np.float32)
    response[:, 0] = lambert_matrix @ histogram.reshape(-1) / total_weight
    response[:, 1] = lambert_matrix @ visibility_histogram.reshape(-1) / total_weight

    mean_form_visibility = float(np.sum(weights * form_visibility) / total_weight)
    response[..., 2] = mean_form_visibility
    return response.reshape(RESPONSE_SIZE, RESPONSE_SIZE, 3), mean_form_visibility


@lru_cache(maxsize=1)
def _normal_lambert_matrix() -> np.ndarray:
    """Return the exact scene-independent normal/light response geometry."""

    bin_count = 64
    edges = np.linspace(-1.0, 1.0, bin_count + 1, dtype=np.float64)
    centers = (edges[:-1] + edges[1:]) * 0.5
    normal_x, normal_y = np.meshgrid(centers, centers, indexing="ij")
    normal_z = np.sqrt(np.maximum(1.0 - normal_x * normal_x - normal_y * normal_y, 0.0))
    normal_length = np.sqrt(normal_x * normal_x + normal_y * normal_y + normal_z * normal_z) + 1e-8
    normal_x = (normal_x / normal_length).reshape(-1)
    normal_y = (normal_y / normal_length).reshape(-1)
    normal_z = (normal_z / normal_length).reshape(-1)

    coordinates = np.linspace(-1.0, 1.0, RESPONSE_SIZE, dtype=np.float32)
    directions: list[tuple[float, float, float]] = []
    for light_y in coordinates:
        for light_x in coordinates:
            light_z = float(np.sqrt(max(1.0 - light_x * light_x - light_y * light_y, 0.0)))
            length = (
                float(np.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)) + 1e-8
            )
            directions.append((light_x / length, light_y / length, light_z / length))

    matrix = np.empty((len(directions), bin_count * bin_count), dtype=np.float64)
    direction_array = np.asarray(directions, dtype=np.float64)
    for start in range(0, len(directions), 64):
        block = direction_array[start : start + 64]
        matrix[start : start + len(block)] = np.maximum(
            normal_x[None, :] * block[:, 0:1]
            + normal_y[None, :] * block[:, 1:2]
            + normal_z[None, :] * block[:, 2:3],
            0.0,
        )
    matrix.flags.writeable = False
    return matrix


def build_sprite_form_maps(
    sprite: Image.Image,
    settings: RelightSettings | None = None,
    seed: int = 947,
    *,
    source_size: tuple[int, int] | None = None,
    source_sha256: str | None = None,
) -> SpriteFormMaps:
    """Derive the static half of the approved CPU lighting model."""

    settings = (settings or RelightSettings()).normalized()
    rgba = sprite if sprite.mode == "RGBA" else sprite.convert("RGBA")
    rgba_u8 = np.asarray(rgba, dtype=np.uint8)
    srgb_u8 = rgba_u8[..., :3]
    alpha = rgba_u8[..., 3].astype(np.float32) / 255.0
    visible = alpha > 0.01
    if not np.any(visible):
        raise ValueError("The sprite has no visible pixels")

    linear_srgb = _SRGB_U8_TO_LINEAR[srgb_u8]
    original_luma = _luminance(linear_srgb)
    height, nx, ny, nz = _pseudo_surface(
        alpha,
        srgb_u8,
        settings.surface_depth,
        linear_srgb=linear_srgb,
        linear_luma=original_luma,
    )
    ao = _surface_ambient_occlusion(height, alpha)
    distance = cv2.distanceTransform((alpha > 0.02).astype(np.uint8), cv2.DIST_L2, 5)
    edge_width = max(2.0, min(sprite.width, sprite.height) * 0.018)
    edge = np.clip(1.0 - distance / edge_width, 0.0, 1.0) * (alpha > 0.02)

    form_visibility = 0.38 + 0.62 * _material_light_response(original_luma)
    response, mean_form_visibility = _normal_response_lut(nx, ny, nz, alpha, form_visibility)
    ys, xs = np.nonzero(visible)
    center_x = (float(xs.min()) + float(xs.max())) * 0.5 / max(sprite.width - 1, 1)
    center_y = (float(ys.min()) + float(ys.max())) * 0.5 / max(sprite.height - 1, 1)
    contrast_mid = float(np.quantile(original_luma[alpha > 0.15], 0.52))

    # Keep all six exact v1 channels, but group smooth fields together. Storing
    # form data in alpha is unsafe because Ren'Py uses premultiplied textures.
    # v2 therefore packs normal X/Y + edge in one RGB PNG, and height/AO + the
    # exact deterministic grain byte in the other. This remains six RGB bytes
    # per texel while making the normal/edge file highly compressible.
    normal_xy = _encode_unit(np.stack((nx * 0.5 + 0.5, ny * 0.5 + 0.5), axis=2))
    normal_rgb = np.empty(alpha.shape + (3,), dtype=np.uint8)
    normal_rgb[..., :2] = normal_xy
    edge_encoded = _encode_unit(edge)
    normal_rgb[..., 2] = edge_encoded
    height_ao_rgb = _encode_unit(
        np.stack(
            (
                (height - HEIGHT_MIN) / (HEIGHT_MAX - HEIGHT_MIN),
                ao,
            ),
            axis=2,
        )
    )
    height_ao_noise = np.empty(alpha.shape + (3,), dtype=np.uint8)
    height_ao_noise[..., :2] = height_ao_rgb
    height_ao_noise[..., 2] = _encoded_noise(alpha.shape, seed)

    source_digest = source_sha256 or hashlib.sha256(rgba_u8.tobytes()).hexdigest()
    recorded_source_size = source_size or sprite.size
    metadata: dict[str, object] = {
        "version": FORM_MAP_VERSION,
        "source_size": [recorded_source_size[0], recorded_source_size[1]],
        "map_size": [sprite.width, sprite.height],
        "source_sha256": source_digest,
        "center": [round(center_x, 8), round(center_y, 8)],
        "mean_form_visibility": round(mean_form_visibility, 8),
        "contrast_mid": round(contrast_mid, 8),
        "height_range": [HEIGHT_MIN, HEIGHT_MAX],
        "noise_range": NOISE_RANGE,
        "response_size": [RESPONSE_SIZE, RESPONSE_SIZE],
        "surface_depth": settings.surface_depth,
        "seed": seed,
    }
    return SpriteFormMaps(
        normal_noise=Image.fromarray(normal_rgb, "RGB"),
        height_ao_edge=Image.fromarray(height_ao_noise, "RGB"),
        response=_rgba_texture(_encode_unit(response)),
        metadata=metadata,
    )
