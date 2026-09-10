from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.core import (
    TRANSPORT_GRID_SIZE,
    TRANSPORT_PLANES,
    _scene_maps,
    _transport_maps,
)
from scenelight.preview.hardware import GIB, HardwareProfile, derive_hardware_plan


def test_form_analysis_is_content_addressed_and_cached(tmp_path: Path) -> None:
    sprite_path = tmp_path / "sprite.png"
    rgba = np.zeros((72, 64, 4), dtype=np.uint8)
    rgba[10:68, 18:48, :3] = (210, 130, 95)
    rgba[10:68, 18:48, 3] = 255
    Image.fromarray(rgba, "RGBA").save(sprite_path)

    cache = ArtifactCache(tmp_path / "cache")
    first = cache.form(sprite_path)
    second = cache.form(sprite_path)

    assert not first.cached
    assert second.cached
    assert first.root == second.root
    assert first.image("normal_noise").is_file()
    assert first.image("height_ao_edge").is_file()
    assert first.image("response").is_file()
    assert first.metadata["source_size"] == [64, 72]


def test_scene_preview_alias_never_returns_provisional_lighting(tmp_path: Path) -> None:
    background_path = tmp_path / "background.png"
    yy, xx = np.mgrid[0:90, 0:160]
    rgb = np.empty((90, 160, 3), dtype=np.uint8)
    rgb[..., 0] = 20 + xx
    rgb[..., 1] = 30 + yy
    rgb[..., 2] = 80
    Image.fromarray(rgb, "RGB").save(background_path)

    cache = ArtifactCache(tmp_path / "cache")
    preview = cache.scene_preview(background_path)
    exact = cache.scene(background_path)
    warm = cache.scene_preview(background_path)

    assert "transport_preview" not in preview.metadata
    assert "transport_preview" not in exact.metadata
    assert preview.root == exact.root
    assert exact.cached
    assert warm.cached
    assert "transport_preview" not in warm.metadata
    assert exact.image("transport").is_file()

    temporal_first = cache.temporal_scene(background_path, "animation:frame:1")
    temporal_cached = cache.temporal_scene_cached("animation:frame:1")
    temporal_warm = cache.temporal_scene(background_path, "animation:frame:1")
    assert not temporal_first.cached
    assert temporal_cached is not None
    assert temporal_cached.cached
    assert np.array_equal(temporal_cached.transport, temporal_first.transport)
    assert temporal_warm.cached
    assert temporal_first.irradiance.shape == (90, 160, 4)
    assert temporal_first.emitter.shape == (90, 160, 4)
    assert temporal_first.transport.shape[0] == 9
    assert temporal_first.metadata["probe_transport"]

    assert cache.temporal_scene_cached("animation:missing") is None


def test_cpu_hardware_pool_matches_scene_fixed_temporal_path(tmp_path: Path) -> None:
    background_path = tmp_path / "background.png"
    yy, xx = np.mgrid[0:72, 0:128]
    rgb = np.empty((72, 128, 3), dtype=np.uint8)
    rgb[..., 0] = (15 + xx * 220 // 127).astype(np.uint8)
    rgb[..., 1] = (25 + yy * 170 // 71).astype(np.uint8)
    rgb[..., 2] = np.where((xx - 96) ** 2 + (yy - 18) ** 2 < 10**2, 248, 55)
    Image.fromarray(rgb, "RGB").save(background_path)

    profile = HardwareProfile(2, 4, 4 * GIB, cuda=False)
    cache = ArtifactCache(
        tmp_path / "adaptive-cache",
        hardware_plan=derive_hardware_plan(profile),
    )
    try:
        _name, reference_planes = _transport_maps(
            "reference",
            str(background_path),
            TRANSPORT_GRID_SIZE,
            scene_fixed_components=True,
        )
        reference_transport = np.concatenate(
            [reference_planes[plane] for plane in range(TRANSPORT_PLANES)],
            axis=1,
        )
        reference_irradiance, reference_emitter, reference_metadata = _scene_maps(background_path)
        single = cache.temporal_scene(background_path, "adaptive:single")

        assert np.array_equal(single.irradiance, reference_irradiance)
        assert np.array_equal(single.emitter, reference_emitter)
        assert np.array_equal(single.transport, reference_transport)
        assert single.metadata == reference_metadata

        results = dict(
            cache.temporal_scene_batch(
                (
                    (0, background_path, "adaptive:0"),
                    (1, background_path, "adaptive:1"),
                )
            )
        )
        assert set(results) == {0, 1}
        for artifacts in results.values():
            assert np.array_equal(artifacts.irradiance, reference_irradiance)
            assert np.array_equal(artifacts.emitter, reference_emitter)
            assert np.array_equal(artifacts.transport, reference_transport)
            assert artifacts.metadata == reference_metadata
    finally:
        cache.shutdown()
