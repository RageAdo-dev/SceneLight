"""Compare exact and precomputed Lambert response-LUT implementations."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from scenelight.engine import RelightSettings, _pseudo_surface, _srgb_to_linear
from scenelight.form_maps import _encode_unit, _normal_response_lut


def matrix_response(nx, ny, nz, alpha, visibility):
    visible = alpha > 0.01
    weights = (alpha * visible).astype(np.float64)
    total = float(np.sum(weights))
    histogram, x_edges, y_edges = np.histogram2d(
        nx[visible],
        ny[visible],
        bins=64,
        range=((-1.0, 1.0), (-1.0, 1.0)),
        weights=weights[visible],
    )
    visibility_histogram, _, _ = np.histogram2d(
        nx[visible],
        ny[visible],
        bins=64,
        range=((-1.0, 1.0), (-1.0, 1.0)),
        weights=(weights * visibility)[visible],
    )
    xc = (x_edges[:-1] + x_edges[1:]) * 0.5
    yc = (y_edges[:-1] + y_edges[1:]) * 0.5
    normal_x, normal_y = np.meshgrid(xc, yc, indexing="ij")
    normal_z = np.sqrt(np.maximum(1.0 - normal_x * normal_x - normal_y * normal_y, 0.0))
    length = np.sqrt(normal_x * normal_x + normal_y * normal_y + normal_z * normal_z) + 1e-8
    normals = np.stack((normal_x / length, normal_y / length, normal_z / length), axis=-1).reshape(
        -1, 3
    )
    coordinates = np.linspace(-1.0, 1.0, 64, dtype=np.float32)
    directions = []
    for light_y in coordinates:
        for light_x in coordinates:
            light_z = float(np.sqrt(max(1.0 - light_x * light_x - light_y * light_y, 0.0)))
            direction_length = (
                float(np.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)) + 1e-8
            )
            directions.append(
                (light_x / direction_length, light_y / direction_length, light_z / direction_length)
            )
    lambert = np.maximum(np.asarray(directions, dtype=np.float64) @ normals.T, 0.0)
    response = np.zeros((4096, 3), dtype=np.float32)
    response[:, 0] = lambert @ histogram.reshape(-1) / total
    response[:, 1] = lambert @ visibility_histogram.reshape(-1) / total
    mean_visibility = float(np.sum(weights * visibility) / total)
    response[:, 2] = mean_visibility
    return response.reshape(64, 64, 3), mean_visibility


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--form", default="monika 1")
    args = parser.parse_args()
    project = args.project.resolve()
    capture = json.loads((project / ".scenelight_cache/capture_result.json").read_text())
    rgba = (
        np.asarray(
            Image.open(project / capture["sprites"][args.form]).convert("RGBA"), dtype=np.uint8
        ).astype(np.float32)
        / 255.0
    )
    srgb, alpha = rgba[..., :3], rgba[..., 3]
    _, nx, ny, nz = _pseudo_surface(alpha, srgb, RelightSettings().surface_depth)
    linear_luma = (
        _srgb_to_linear(srgb)[..., 0] * 0.2126
        + _srgb_to_linear(srgb)[..., 1] * 0.7152
        + _srgb_to_linear(srgb)[..., 2] * 0.0722
    )
    visibility = 0.38 + 0.62 * np.clip((linear_luma - 0.012) / (0.115 - 0.012), 0.0, 1.0) ** 2 * (
        3.0 - 2.0 * np.clip((linear_luma - 0.012) / (0.115 - 0.012), 0.0, 1.0)
    )
    started = time.perf_counter()
    reference, _ = _normal_response_lut(nx, ny, nz, alpha, visibility)
    reference_seconds = time.perf_counter() - started
    started = time.perf_counter()
    candidate, _ = matrix_response(nx, ny, nz, alpha, visibility)
    candidate_seconds = time.perf_counter() - started
    old, new = _encode_unit(reference), _encode_unit(candidate)
    difference = np.abs(old.astype(np.int16) - new.astype(np.int16))
    print(f"reference_seconds={reference_seconds:.4f}")
    print(f"matrix_seconds={candidate_seconds:.4f}")
    print(f"encoded_equal={np.array_equal(old, new)}")
    print(f"max_difference={int(difference.max())}")
    print(f"changed_channels={int(np.count_nonzero(difference))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
