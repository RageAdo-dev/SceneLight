from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from scenelight.builder import _camera_metadata
from scenelight.engine import (
    DetectedLight,
    Placement,
    analyze_scene,
    diffuse_scene_chroma_guard,
)


def test_reflected_light_keeps_its_direction_across_emission_classification():
    background = Image.new("RGB", (128, 72), (60, 65, 55))
    ImageDraw.Draw(background).rectangle((12, 8, 30, 25), fill=(210, 210, 205))
    light = DetectedLight(0.18, 0.2, (0.73, 0.73, 0.73), 1.0, 0.16, 0.7, 0.4)
    positions = []
    for emission in np.linspace(0.25, 0.75, 21):
        scene = analyze_scene(
            background, Placement(), source_components=(replace(light, emission_score=emission),)
        )
        positions.append((scene.light_x, scene.light_y, scene.source_size))
        assert scene.source_size == pytest.approx(light.radius)
    assert np.ptp(positions, axis=0).max() < 1e-6
    moved = analyze_scene(background, Placement(), source_components=(replace(light, x=0.82),))
    # The scene gradient remains fixed; the measured source must still move
    # the solved direction rather than being replaced by the diffuse prior.
    assert moved.light_x - positions[0][0] > 0.35


def _analysis(**overrides):
    values = {
        "local_luminance": 0.52,
        "source_size": 0.96,
        "light_confidence": 0.18,
        "lights": (SimpleNamespace(emission_score=0.02),),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_chroma_guard_selects_only_bright_broad_diffuse_scenes() -> None:
    assert diffuse_scene_chroma_guard(_analysis()) == pytest.approx(1.0)

    assert diffuse_scene_chroma_guard(_analysis(local_luminance=0.18)) == pytest.approx(0.0)
    assert diffuse_scene_chroma_guard(_analysis(source_size=0.30)) == pytest.approx(0.0)
    assert diffuse_scene_chroma_guard(_analysis(light_confidence=0.85)) == pytest.approx(0.0)
    assert diffuse_scene_chroma_guard(
        _analysis(lights=(SimpleNamespace(emission_score=0.80),))
    ) == pytest.approx(0.0)


def test_chroma_guard_is_continuous_not_a_scene_or_character_lookup() -> None:
    midpoint = diffuse_scene_chroma_guard(
        _analysis(
            local_luminance=0.38,
            source_size=0.76,
            light_confidence=0.47,
            lights=(SimpleNamespace(emission_score=0.235),),
        )
    )
    assert 0.0 < midpoint < 1.0


def _compressed_environment_tint(chroma: tuple[float, float, float]) -> tuple[float, ...]:
    span = max(chroma) - min(chroma)
    position = min(max((span - 0.55) / (1.15 - 0.55), 0.0), 1.0)
    extreme = position * position * (3.0 - 2.0 * position)
    compression = 1.0 + (0.25 - 1.0) * extreme
    return tuple(pow(pow(value, 0.78 * 0.88), compression) for value in chroma)


def test_extreme_environment_chroma_is_compressed_without_touching_neutral_scenes() -> None:
    neutral = (1.02, 0.99, 0.94)
    expected_neutral = tuple(pow(value, 0.78 * 0.88) for value in neutral)
    assert _compressed_environment_tint(neutral) == pytest.approx(expected_neutral)

    # Measured ordinary classroom transport has a chroma span around 0.40.
    # It is the protected normal path and must remain mathematically exact.
    classroom = (1.28, 0.93, 0.88)
    expected_classroom = tuple(pow(value, 0.78 * 0.88) for value in classroom)
    assert _compressed_environment_tint(classroom) == pytest.approx(expected_classroom)

    sunset = (1.70, 0.85, 0.45)
    original_sunset = tuple(pow(value, 0.78 * 0.88) for value in sunset)
    guarded_sunset = _compressed_environment_tint(sunset)
    assert (
        max(guarded_sunset) / min(guarded_sunset)
        < (max(original_sunset) / min(original_sunset)) * 0.55
    )

    normal_cool = (0.91, 0.99, 1.33)
    expected_normal_cool = tuple(pow(value, 0.78 * 0.88) for value in normal_cool)
    assert _compressed_environment_tint(normal_cool) == pytest.approx(expected_normal_cool)

    night = (0.45, 1.12, 1.51)
    original_night = tuple(pow(value, 0.78 * 0.88) for value in night)
    guarded_night = _compressed_environment_tint(night)
    assert (
        1.0 < max(guarded_night) / min(guarded_night) < (max(original_night) / min(original_night))
    )


def test_multicolor_scene_preserves_hue_families_for_creative_mode() -> None:
    scene = Image.new("RGB", (320, 180), (8, 7, 6))
    draw = ImageDraw.Draw(scene)
    draw.ellipse((20, 15, 120, 100), fill=(255, 70, 15))
    draw.ellipse((90, 10, 190, 100), fill=(20, 245, 220))
    draw.ellipse((160, 20, 270, 110), fill=(80, 255, 35))

    analysis = analyze_scene(scene)

    assert analysis.lights
    assert len(analysis.creative_lights) >= 3
    assert all(light.creative_only for light in analysis.creative_lights)
    dominant_channels = {
        max(range(3), key=lambda channel: light.color[channel])
        for light in analysis.creative_lights
    }
    assert len(dominant_channels) >= 2


def test_creative_hue_families_are_disabled_in_default_transport() -> None:
    scene = Image.new("RGB", (320, 180), (8, 7, 6))
    draw = ImageDraw.Draw(scene)
    draw.ellipse((20, 15, 120, 100), fill=(255, 70, 15))
    draw.ellipse((90, 10, 190, 100), fill=(20, 245, 220))
    draw.ellipse((160, 20, 270, 110), fill=(80, 255, 35))

    transport = _camera_metadata(analyze_scene(scene))["light_transport"]

    assert transport[0]["position_radius_intensity"][3] > 0.0
    assert transport[0]["emission_enabled"][1] == 1.0
    assert len(transport) == 4
    assert all(light["position_radius_intensity"][3] == 0.0 for light in transport[1:])
    assert all(light["emission_enabled"][1] == 0.0 for light in transport[1:])
    assert sum(light["emission_enabled"][0] > 0.0 for light in transport[1:]) >= 2


def test_transport_reserves_spatial_slots_for_three_distinct_hue_families() -> None:
    scene = Image.new("RGB", (320, 180), (8, 7, 6))
    draw = ImageDraw.Draw(scene)
    draw.ellipse((20, 15, 120, 100), fill=(255, 70, 15))
    draw.ellipse((90, 10, 190, 100), fill=(20, 245, 220))
    draw.ellipse((160, 20, 270, 110), fill=(80, 255, 35))

    transport = _camera_metadata(analyze_scene(scene))["light_transport"]

    assert len(transport) == 4
    positions = [light["position_radius_intensity"][0] for light in transport[1:]]
    assert max(positions) - min(positions) > 0.20
    assert all(light["emission_enabled"][1] == 0.0 for light in transport[1:])


def test_ordinary_scene_keeps_physical_component_layout() -> None:
    scene = Image.new("RGB", (320, 180), (128, 132, 136))

    metadata = _camera_metadata(analyze_scene(scene))

    assert metadata["light_transport_layout"] == "physical-components-v1"
    assert all(light["emission_enabled"][1] == 1.0 for light in metadata["light_transport"])
