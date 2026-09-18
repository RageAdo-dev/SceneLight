"""Test colored-source acceptance through the production sprite shader."""

from dataclasses import replace

import numpy as np
import pytest
import test_gpu_lighting

renderer = test_gpu_lighting.renderer


def _light(position, color, *, radius=0.2, physical=False, emission=1.0):
    return (
        (*position, radius, float(physical)),
        (*color, 1.0),
        (emission, float(physical)),
    )


@pytest.fixture
def source_scene(renderer, monkeypatch):
    from scenelight.calibration import Calibration

    original_uniform = renderer._uniform
    overrides = {"u_sc_has_transport": 0.0, "u_sc_live_background": 0.0}

    def uniform(name, value):
        original_uniform(name, overrides.get(name, value))

    monkeypatch.setattr(renderer, "_uniform", uniform)
    renderer.set_live_analysis_enabled(True)
    renderer.set_placement(0.5, 1.0, 0.92)
    pixels = np.full((144, 256, 4), 255, np.uint8)
    pixels[..., :3] = 110
    renderer.set_background_frame(pixels)
    calibration = Calibration(
        contrast_match=0.0,
        saturation_match=0.0,
        highlight_rolloff=0.0,
        grain_match=0.0,
        ray_shadow_strength=0.0,
        ambient_occlusion=0.0,
        probe_strength=0.0,
        bounce_strength=0.0,
        specular_strength=0.0,
        rim_strength=0.0,
        wrap_strength=0.0,
        shadow_strength=0.0,
    )

    def render(lights, *, automatic=1.0, manual=0.0, rim_strength=0.0):
        # Legacy uniform inputs let this test vary source evidence without
        # relying on image-analysis thresholds. The complete production shader,
        # sprite form maps, exposure, and directional lighting still execute.
        absent = ((0.5, 0.2, 1.0, 0.0), (1.0, 1.0, 1.0, 0.0), (0.0, 0.0))
        for index, light in enumerate([*lights, *[absent] * (4 - len(lights))]):
            for suffix, value in zip(("data", "color", "extra"), light):
                overrides[f"u_sc_light{index}_{suffix}"] = value
        renderer.set_calibration(
            replace(
                calibration,
                adaptive_light_colors=automatic,
                individual_light_colors=manual,
                rim_strength=rim_strength,
            )
        )
        return renderer.render_rgba((640, 360))[65:280, 270:370, :3]

    try:
        yield render
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_placement(0.65, 1.0, 0.92)


def test_broad_colored_emitter_retains_automatic_separation(source_scene):
    green = (0.35, 1.7, 0.35)
    lights = [
        _light((0.15, 0.25), green, radius=0.85, physical=True),
        _light((0.15, 0.25), green, radius=0.85),
        _light((0.85, 0.25), (0.35, 0.45, 2.4)),
    ]
    automatic = source_scene(lights)
    manual = source_scene(lights, automatic=0.0, manual=1.0)
    aggregate = source_scene(lights, automatic=0.0)
    np.testing.assert_array_equal(automatic, manual)
    difference = np.abs(automatic.astype(float) - aggregate).mean()
    assert difference > 1.0, difference
    left = automatic[:40, 10:35].mean(axis=(0, 1))
    right = automatic[:40, 65:90].mean(axis=(0, 1))
    # The broad green emitter and compact blue lamp retain different colors
    # on opposite sides of the same painted face.
    assert left[1] / left[2] > right[1] / right[2] * 1.1, (left, right)


def test_white_lamp_does_not_validate_broad_foliage(source_scene):
    lights = [
        _light((0.15, 0.25), (1.0, 1.0, 1.0), physical=True),
        _light((0.85, 0.25), (0.35, 1.7, 0.35), radius=0.85),
    ]
    automatic = source_scene(lights)
    aggregate = source_scene(lights, automatic=0.0)
    np.testing.assert_array_equal(automatic, aggregate)


@pytest.mark.parametrize(
    ("primary_position", "primary_color", "emission"),
    [
        ((0.15, 0.25), (1.0, 1.0, 1.0), 1.0),
        ((0.65, 0.25), (0.35, 1.7, 0.35), 1.0),
        ((0.15, 0.25), (0.35, 1.7, 0.35), 0.0),
    ],
    ids=["wrong-color", "wrong-position", "non-emitting"],
)
def test_broad_family_requires_matching_emitter_evidence(
    source_scene, primary_position, primary_color, emission
):
    primary = _light(primary_position, primary_color, physical=True, emission=emission)
    compact = _light((0.85, 0.25), (0.35, 0.45, 2.4))
    without_broad_family = source_scene([primary, compact])
    with_broad_family = source_scene(
        [
            primary,
            compact,
            _light((0.15, 0.25), (0.35, 1.7, 0.35), radius=0.85),
        ]
    )
    np.testing.assert_array_equal(with_broad_family, without_broad_family)


@pytest.mark.parametrize("rim_strength", [0.0, 1.0])
def test_rejected_family_does_not_suppress_neutral_key(source_scene, rim_strength):
    lights = [
        _light((0.15, 0.25), (1.0, 1.0, 1.0), physical=True),
        _light((0.85, 0.25), (2.4, 0.4, 0.35)),
    ]
    single_lamp = source_scene(lights, rim_strength=rim_strength)
    with_foliage = source_scene(
        [
            *lights,
            _light((0.2, 0.2), (0.35, 1.7, 0.35), radius=0.85),
        ],
        rim_strength=rim_strength,
    )
    # The accepted compact lamp has engaged automatic separation. Adding a
    # rejected family must neither tint its blend nor count as a second lamp
    # and discard the neutral primary.
    aggregate = source_scene(lights, automatic=0.0, rim_strength=rim_strength)
    assert np.abs(single_lamp.astype(float) - aggregate).mean() > 1.0
    np.testing.assert_array_equal(with_foliage, single_lamp)


def test_manual_separation_keeps_unsupported_broad_colors(source_scene):
    lights = [
        _light((0.15, 0.25), (1.0, 1.0, 1.0), physical=True),
        _light((0.85, 0.25), (0.35, 1.7, 0.35), radius=0.85),
    ]
    aggregate = source_scene(lights, automatic=0.0)
    manual = source_scene(lights, automatic=0.0, manual=1.0)
    difference = np.abs(manual.astype(float) - aggregate).mean()
    assert difference > 1.0, difference
    manual_green = manual[..., 1].mean() / manual[..., (0, 2)].mean()
    aggregate_green = aggregate[..., 1].mean() / aggregate[..., (0, 2)].mean()
    assert manual_green > aggregate_green * 1.08, (manual_green, aggregate_green)


def test_additional_physical_light_is_not_rejected_as_a_broad_hue_region(source_scene):
    lights = [
        _light((0.15, 0.25), (1.0, 1.0, 1.0), physical=True),
        _light((0.85, 0.25), (2.4, 0.4, 0.35)),
        _light((0.15, 0.4), (0.35, 0.45, 2.4), radius=0.85, physical=True),
    ]
    # Older transport records can mix physical and hue-family lights. Once
    # automatic separation engages, a measured physical light retains its
    # contribution regardless of how widely it fills the image.
    automatic = source_scene(lights)
    manual = source_scene(lights, automatic=0.0, manual=1.0)
    aggregate = source_scene(lights, automatic=0.0)
    assert np.abs(automatic.astype(float) - aggregate).mean() > 1.0
    np.testing.assert_array_equal(automatic, manual)
