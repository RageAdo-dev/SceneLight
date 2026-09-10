from __future__ import annotations

import gc
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import scenelight.cuda_backend as cuda_backend
from scenelight.builder import _transport_maps
from scenelight.cuda_backend import (
    _cpu_component_geometry,
    _detect_components_for_layout,
    _detect_components_for_placements,
    _write_shared_prepared_scene,
    allocate_shared_prepared_buffer,
    materialize_shared_prepared_scene,
)
from scenelight.engine import (
    EPSILON,
    DetectedLight,
    Placement,
    _detect_source_components,
    _linear_quantile,
    _placement_region,
    _prepare_creative_color_fields,
    _pseudo_surface,
    _sample_environment_probes,
    _srgb_to_linear,
    _weighted_rgb,
    analyze_scene,
    prepare_scene,
)
from scenelight.form_maps import _SRGB_U8_TO_LINEAR, _normal_lambert_matrix, _normal_response_lut


def test_fast_linear_quantile_is_bit_exact_to_numpy() -> None:
    generator = np.random.default_rng(1947)
    sizes = (*range(1, 48), 100, 101, 1024)
    quantiles = (0.16, 0.50, 0.90, (0.50, 0.90), (0.54, 0.60, 0.92))

    for dtype in (np.float32, np.float64):
        for size in sizes:
            values = generator.random(size).astype(dtype)
            for requested in quantiles:
                expected = np.quantile(values, requested, method="linear")
                actual = _linear_quantile(values, requested)
                assert np.array_equal(actual, expected)


def test_form_map_uint8_linear_lookup_is_bit_exact() -> None:
    values = np.arange(256, dtype=np.uint8)
    expected = _srgb_to_linear(values.astype(np.float32) / 255.0)

    assert np.array_equal(_SRGB_U8_TO_LINEAR[values], expected)


def test_pseudo_surface_reuses_linear_pixels_bit_exactly() -> None:
    rgba = np.asarray(_varied_scene().convert("RGBA"), dtype=np.uint8)
    srgb = rgba[..., :3].astype(np.float32) / 255.0
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    linear = _srgb_to_linear(srgb)

    expected = _pseudo_surface(alpha, srgb, 0.72)
    actual = _pseudo_surface(alpha, srgb, 0.72, linear_srgb=linear)

    assert all(np.array_equal(left, right) for left, right in zip(expected, actual, strict=True))


def test_cached_normal_response_geometry_is_bit_exact() -> None:
    rgba = np.asarray(_varied_scene().convert("RGBA"), dtype=np.uint8).astype(np.float32) / 255.0
    srgb, alpha = rgba[..., :3], rgba[..., 3]
    _height, nx, ny, nz = _pseudo_surface(alpha, srgb, 0.72)
    visibility = np.linspace(0.38, 1.0, alpha.size, dtype=np.float32).reshape(alpha.shape)

    expected, expected_mean = _reference_normal_response(nx, ny, nz, alpha, visibility)
    actual, actual_mean = _normal_response_lut(nx, ny, nz, alpha, visibility)

    assert np.array_equal(
        np.round(np.clip(actual, 0.0, 1.0) * 255.0).astype(np.uint8),
        np.round(np.clip(expected, 0.0, 1.0) * 255.0).astype(np.uint8),
    )
    assert actual_mean == expected_mean
    _normal_lambert_matrix.cache_clear()


def _reference_normal_response(nx, ny, nz, alpha, visibility):
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
    x_centers = (x_edges[:-1] + x_edges[1:]) * 0.5
    y_centers = (y_edges[:-1] + y_edges[1:]) * 0.5
    normal_x, normal_y = np.meshgrid(x_centers, y_centers, indexing="ij")
    normal_z = np.sqrt(np.maximum(1.0 - normal_x * normal_x - normal_y * normal_y, 0.0))
    length = np.sqrt(normal_x * normal_x + normal_y * normal_y + normal_z * normal_z) + 1e-8
    normal_x /= length
    normal_y /= length
    normal_z /= length
    response = np.zeros((64, 64, 3), dtype=np.float32)
    coordinates = np.linspace(-1.0, 1.0, 64, dtype=np.float32)
    for row, light_y in enumerate(coordinates):
        for column, light_x in enumerate(coordinates):
            light_z = float(np.sqrt(max(1.0 - light_x * light_x - light_y * light_y, 0.0)))
            direction_length = (
                float(np.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)) + 1e-8
            )
            lx, ly, lz = (
                light_x / direction_length,
                light_y / direction_length,
                light_z / direction_length,
            )
            lambert = np.maximum(normal_x * lx + normal_y * ly + normal_z * lz, 0.0)
            response[row, column, 0] = float(np.sum(lambert * histogram) / total)
            response[row, column, 1] = float(np.sum(lambert * visibility_histogram) / total)
    mean = float(np.sum(weights * visibility) / total)
    response[..., 2] = mean
    return response, mean


def _varied_scene() -> Image.Image:
    height, width = 180, 320
    yy, xx = np.mgrid[0:height, 0:width]
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    rgb[..., 0] = np.clip(18 + xx * 0.42 + yy * 0.08, 0, 255)
    rgb[..., 1] = np.clip(26 + xx * 0.17 + yy * 0.21, 0, 255)
    rgb[..., 2] = np.clip(44 + xx * 0.09 + yy * 0.36, 0, 255)
    cv2.circle(rgb, (42, 32), 11, (255, 188, 92), -1, lineType=cv2.LINE_AA)
    cv2.circle(rgb, (247, 63), 7, (146, 205, 255), -1, lineType=cv2.LINE_AA)
    cv2.rectangle(rgb, (112, 112), (206, 151), (232, 228, 214), -1)
    return Image.fromarray(rgb, "RGB")


def test_prepared_scene_reuses_global_work_without_changing_analysis() -> None:
    background = _varied_scene()
    placements = (
        Placement(0.0, 0.44, 0.92),
        Placement(0.5, 0.86, 0.92),
        Placement(1.0, 1.28, 0.92),
    )
    prepared = prepare_scene(background, (0.92,))

    for placement in placements:
        direct = analyze_scene(background, placement)
        reused = analyze_scene(background, placement, prepared=prepared)
        assert direct.to_dict() == reused.to_dict()


def test_cropped_component_path_preserves_every_transport_byte(tmp_path: Path) -> None:
    background_path = tmp_path / "varied_scene.png"
    _varied_scene().save(background_path)

    _name, reference = _transport_maps(
        "reference",
        str(background_path),
        (3, 2),
        point_workers=1,
        crop_components=False,
    )
    _name, optimized = _transport_maps(
        "optimized",
        str(background_path),
        (3, 2),
        point_workers=2,
        crop_components=True,
    )

    assert np.array_equal(reference, optimized)


def test_fused_weighted_rgb_preserves_approved_reduction_bits() -> None:
    generator = np.random.default_rng(1947)
    rgb = generator.random((47, 83, 3), dtype=np.float32)
    weights = generator.random((47, 83), dtype=np.float32)
    expected = np.sum(rgb * weights[..., None], axis=(0, 1)) / (float(np.sum(weights)) + EPSILON)

    actual = _weighted_rgb(rgb, weights)
    reused_total = _weighted_rgb(rgb, weights, float(np.sum(weights)))

    assert np.array_equal(actual, expected)
    assert np.array_equal(reused_total, expected)


def test_exact_geometry_inputs_preserve_analysis() -> None:
    background = _varied_scene()
    placement = Placement(0.63, 0.94, 0.92)
    prepared = prepare_scene(background, (placement.height,))
    _y_slice, _x_slice, weights = _placement_region(
        prepared.luma.shape,
        placement,
        (prepared.yy, prepared.xx),
    )
    probes = _sample_environment_probes(
        prepared.linear,
        placement.center_x,
        placement.baseline_y - placement.height * 0.48,
        placement,
        (prepared.yy, prepared.xx),
    )

    direct = analyze_scene(background, placement, prepared=prepared)
    reused = analyze_scene(
        background,
        placement,
        prepared=prepared,
        local_weights=weights,
        local_weight_total=float(np.sum(weights)),
        environment_probes=probes,
    )

    assert direct.to_dict() == reused.to_dict()


def test_sparse_component_layout_is_exactly_equal_to_dense_annuli() -> None:
    background = _varied_scene()
    prepared = prepare_scene(background, (0.92,))
    placements = (
        Placement(0.0, 0.44, 0.92).clamped(),
        Placement(0.5, 0.86, 0.92).clamped(),
        Placement(1.0, 1.28, 0.92).clamped(),
    )
    dense_weights = tuple(
        _placement_region(
            prepared.luma.shape,
            placement,
            (prepared.yy, prepared.xx),
        )[2]
        for placement in placements
    )

    dense = _detect_components_for_placements(
        prepared,
        dense_weights,
        crop_components=True,
    )
    sparse = _detect_components_for_layout(
        prepared,
        placements,
        crop_components=True,
    )

    assert sparse == dense


def test_clamped_transport_rows_are_classified_once(monkeypatch) -> None:
    prepared = prepare_scene(_varied_scene(), (0.92,))
    placements = _cpu_component_geometry(prepared.luma.shape, (16, 9), 1.10, 0.92)
    calls = 0

    def classify(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return ()

    cuda_backend.initialize_component_worker(1)
    monkeypatch.setattr(cuda_backend, "_detect_source_components", classify)
    detected = _detect_components_for_layout(prepared, placements, crop_components=True)

    assert len(detected) == 16 * 9
    assert calls == 16 * 7


def test_scene_fixed_transport_classifies_emitters_once(monkeypatch) -> None:
    prepared = prepare_scene(_varied_scene(), (0.92,))
    placements = _cpu_component_geometry(prepared.luma.shape, (16, 9), 1.10, 0.92)
    calls = 0
    sentinel = (DetectedLight(0.2, 0.1, (1.0, 0.8, 0.6), 1.0, 0.1, 0.9),)

    def classify(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return sentinel

    cuda_backend.initialize_component_worker(1)
    monkeypatch.setattr(cuda_backend, "_detect_source_components", classify)
    detected = _detect_components_for_layout(
        prepared,
        placements,
        crop_components=True,
        scene_fixed=True,
    )

    assert len(detected) == 16 * 9
    assert calls == 1
    assert all(lights is sentinel for lights in detected)


def test_prepared_creative_hue_fields_preserve_detected_lights() -> None:
    prepared = prepare_scene(_varied_scene(), (0.92,))
    placement = Placement(0.63, 0.94, 0.92)
    _y_slice, _x_slice, local_weights = _placement_region(
        prepared.luma.shape,
        placement,
        (prepared.yy, prepared.xx),
    )
    source_weights = prepared.base_source_weights * (0.58 + 0.42 * local_weights)
    arguments = {
        "luma": prepared.luma,
        "texture_residual": prepared.texture_residual,
        "coordinate_grid": (prepared.yy, prepared.xx),
        "ring_kernel": prepared.ring_kernel,
        "crop_components": True,
    }

    expected = _detect_source_components(prepared.linear, source_weights, **arguments)
    actual = _detect_source_components(
        prepared.linear,
        source_weights,
        creative_fields=_prepare_creative_color_fields(prepared.linear),
        **arguments,
    )

    assert actual == expected


def test_shared_prepared_scene_preserves_every_cuda_input() -> None:
    prepared = prepare_scene(_varied_scene(), (0.92,))
    allocation = allocate_shared_prepared_buffer(prepared.luma.shape, 0.92)
    rebuilt = None
    try:
        info = _write_shared_prepared_scene(prepared, allocation.spec)
        rebuilt = materialize_shared_prepared_scene(info, allocation)
        assert np.array_equal(rebuilt.linear, prepared.linear)
        assert np.array_equal(rebuilt.clipped_luma, prepared.clipped_luma)
        assert np.array_equal(rebuilt.saturation, prepared.saturation)
        assert np.array_equal(
            rebuilt.base_source_weights,
            prepared.base_source_weights,
        )
        for expected, actual in zip(
            prepared.gradient_fields[0.92],
            rebuilt.gradient_fields[0.92],
            strict=True,
        ):
            assert np.array_equal(actual, expected)
        assert rebuilt.global_mean == prepared.global_mean
        assert rebuilt.global_contrast == prepared.global_contrast
        assert rebuilt.separation == prepared.separation
        assert rebuilt.grain == prepared.grain
        assert rebuilt.sharpness == prepared.sharpness
    finally:
        del rebuilt
        gc.collect()
        allocation.close()
