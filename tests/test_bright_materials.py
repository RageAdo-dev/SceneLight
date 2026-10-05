from dataclasses import replace

import numpy as np
from PIL import Image

from scenelight.engine import (
    Placement,
    RelightSettings,
    _display_referred_exposure,
    analyze_scene,
    relight_sprite,
)


def test_scene_gain_preserves_darkness_and_has_a_smooth_bounded_positive_response():
    dark = np.linspace(0.0001, 1, 100)
    np.testing.assert_array_equal(_display_referred_exposure(dark), dark)
    gains = _display_referred_exposure(np.linspace(1, 10, 100))
    assert np.all(np.diff(gains) > 0)
    assert gains.max() < 1.25
    # No exposure jump or slope discontinuity when a moving scene crosses unity.
    assert abs((_display_referred_exposure(1.00001) - 1) / 0.00001 - 1) < 0.001


def test_cpu_neutral_scene_does_not_bleach_color_and_protects_existing_highlights():
    pixels = np.full((128, 128, 4), 255, np.uint8)
    pixels[:64, :, :3] = (180, 30, 45)
    pixels[64:96, :, :3] = (235, 235, 235)
    sprite = Image.fromarray(pixels)
    analysis = analyze_scene(Image.new("RGB", (256, 144), (210, 210, 210)), Placement())
    settings = RelightSettings(
        auto_strength=0,
        ambient_strength=0.7,
        color_adaptation=0,
        contrast_match=0,
        saturation_match=0,
        key_strength=0,
        multi_light_strength=0,
        ambient_occlusion=0,
        ray_shadow_strength=0,
        probe_strength=0,
        bounce_strength=0,
        specular_strength=0,
        rim_strength=0,
        wrap_strength=0,
        grain_match=0,
    )
    protected = np.array(relight_sprite(sprite, analysis, settings))
    plain = np.array(relight_sprite(sprite, analysis, replace(settings, highlight_rolloff=0)))
    np.testing.assert_allclose(protected, plain, atol=1)
    normal = np.array(relight_sprite(sprite, analysis, replace(settings, auto_strength=0.88)))
    matching = np.array(
        relight_sprite(sprite, analysis, replace(settings, auto_strength=0.88, saturation_match=2))
    )
    np.testing.assert_array_equal(normal, matching)
