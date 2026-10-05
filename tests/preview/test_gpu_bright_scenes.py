"""Bright scenes preserve painted colors and folds; zero strength is neutral."""

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image
from test_gpu_lighting import renderer as renderer

from scenelight.calibration import Calibration
from scenelight.engine import _srgb_to_linear
from scenelight.preview.artifacts import ArtifactCache


@pytest.fixture
def material(renderer, tmp_path):
    # Multiple known reflectances, including pre-existing white/gray folds.
    image = np.full((240, 160, 4), 255, np.uint8)
    for i, color in enumerate(((128, 128, 128), (235, 235, 235), (255, 255, 255), (180, 30, 45))):
        image[i * 60 : (i + 1) * 60, :, :3] = color
    path = tmp_path / "paint.png"
    Image.fromarray(image).save(path)
    cache = ArtifactCache(tmp_path / "cache")
    cache._cuda_available = False
    renderer.set_sprite(path, cache.form(path))
    renderer.set_placement(0.5, 1.0, 0.8)
    renderer.set_live_analysis_enabled(True)
    renderer.set_strength(1)
    try:
        yield renderer
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_compare_mode(0)
        renderer.set_strength(1)
        cache.shutdown()


def _background(view, color):
    view.set_background_frame(np.full((144, 256, 4), (*color, 255), np.uint8))


def _plain(**changes):
    return replace(
        Calibration(
            key_strength=0,
            ray_shadow_strength=0,
            ambient_occlusion=0,
            probe_strength=0,
            bounce_strength=0,
            specular_strength=0,
            rim_strength=0,
            wrap_strength=0,
            grain_match=0,
            contrast_match=0,
            color_adaptation=0,
            adaptive_light_colors=0,
        ),
        **changes,
    )


@pytest.mark.parametrize("color", [(255, 255, 255), (220, 220, 220), (110, 110, 110)])
def test_neutral_background_does_not_desaturate_colored_paint(material, color):
    _background(material, color)
    material.set_calibration(_plain(saturation_match=0))
    ungraded = material.render_rgba((640, 360))
    material.set_calibration(_plain(saturation_match=2))
    matched = material.render_rgba((640, 360))
    np.testing.assert_array_equal(matched, ungraded)


def test_highlight_protection_preserves_already_painted_folds(material):
    _background(material, (180, 180, 180))
    material.set_calibration(_plain(auto_strength=0, ambient_strength=0.7, highlight_rolloff=0))
    uncompressed = material.render_rgba((640, 360))
    material.set_calibration(_plain(auto_strength=0, ambient_strength=0.7, highlight_rolloff=1.2))
    protected = material.render_rgba((640, 360))
    # Both cloth swatches are below their painted level: they must not be
    # flattened a second time merely because they are bright materials.
    np.testing.assert_allclose(protected[165:260, 290:350], uncompressed[165:260, 290:350], atol=1)
    assert protected[235:245, 305:335, :3].mean() - protected[170:180, 305:335, :3].mean() > 10


def test_auto_brightening_is_bounded_but_manual_exposure_and_darkness_still_work(material):
    _background(material, (255, 255, 255))
    material.set_calibration(_plain(auto_strength=0, highlight_rolloff=0))
    neutral = material.render_rgba((640, 360))
    material.set_calibration(_plain(highlight_rolloff=0))
    automatic = material.render_rgba((640, 360))
    material.set_calibration(_plain(exposure_bias=1, highlight_rolloff=0))
    manual = material.render_rgba((640, 360))
    _background(material, (10, 10, 10))
    material.set_calibration(_plain(highlight_rolloff=0))
    dark = material.render_rgba((640, 360))

    def energy(frame):
        return _srgb_to_linear(frame[105:120, 300:340, :3] / 255.0).mean()

    assert 1.02 < energy(automatic) / energy(neutral) < 1.25
    assert energy(manual) > energy(automatic) * 1.8
    assert energy(dark) < energy(neutral) * 0.1


@pytest.mark.parametrize("color", [(255, 255, 255), (240, 210, 120), (15, 25, 80)])
def test_zero_strength_matches_original_even_with_custom_controls(material, color):
    _background(material, color)
    material.set_calibration(
        Calibration(
            ambient_strength=1.8,
            exposure_bias=1.2,
            grain_match=2,
            highlight_rolloff=2,
            light_color_amount=-0.7,
        )
    )
    material.set_strength(0)
    zero = material.render_rgba((640, 360))
    material.set_compare_mode(1)
    original = material.render_rgba((640, 360))
    np.testing.assert_allclose(zero, original, atol=1)
    material.set_compare_mode(0)
    material.set_calibration(Calibration(glow_strength=1.5))
    glowing = material.render_rgba((640, 360))
    assert np.abs(glowing.astype(float) - original).mean() > 1
