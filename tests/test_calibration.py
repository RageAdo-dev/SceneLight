from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenelight.calibration import (
    CALIBRATION_VERSION,
    Calibration,
    CalibrationProfile,
    lighting_mode_preset,
    load_profile,
    merge_profile_into_config,
    save_profile,
)


def test_default_uniforms_reproduce_validated_constants() -> None:
    blocks = Calibration().uniform_blocks()
    assert blocks[0] == (0.88, 0.0, 1.0, 0.78)
    assert blocks[1] == (0.72, 0.58, 1.2, 0.82)
    assert blocks[2] == (0.58, 0.34, 0.48, 0.32)
    assert blocks[3] == (0.24, 0.64, 0.42, 0.52)
    assert blocks[4] == (0.62, 0.0, 1.0, 0.25)
    assert blocks[8] == (0.25, 0.50, 1.0, 0.0)


def test_individual_light_colors_is_bounded_and_uses_spare_uniform_slot() -> None:
    assert Calibration(individual_light_colors=3.0).uniform_blocks()[4] == (
        0.62,
        2.0,
        1.0,
        0.25,
    )


def test_adaptive_light_colors_is_bounded_and_uses_spare_uniform_slot() -> None:
    assert Calibration(adaptive_light_colors=3.0).uniform_blocks()[4] == (
        0.62,
        0.0,
        2.0,
        0.25,
    )


def test_public_lighting_mode_presets_keep_physical_default_and_cinematic_hybrid() -> None:
    physical_strength, physical = lighting_mode_preset("physical")
    cinematic_strength, cinematic = lighting_mode_preset("cinematic")
    separate_strength, separate = lighting_mode_preset("separate")

    assert physical_strength == 1.0
    assert physical == Calibration()
    assert cinematic_strength == 0.72
    assert cinematic.exposure_bias == -0.22
    assert cinematic.color_adaptation == 0.92
    assert cinematic.individual_light_colors == 1.0
    assert separate_strength == 1.0
    assert separate.individual_light_colors == 1.0
    with pytest.raises(ValueError, match="physical, cinematic, or separate"):
        lighting_mode_preset("unknown")


def test_profile_round_trip_and_scene_inheritance(tmp_path: Path) -> None:
    global_value = Calibration(exposure_bias=-0.25)
    scene_value = Calibration.from_mapping({"rim_strength": 0.9}, base=global_value)
    profile = CalibrationProfile(global_value, {"night street": scene_value}, strength=0.72)
    path = tmp_path / "profile.json"
    save_profile(path, profile)
    loaded = load_profile(path)
    assert loaded.calibration.exposure_bias == -0.25
    assert loaded.for_scene("night street").exposure_bias == -0.25
    assert loaded.for_scene("night street").rim_strength == 0.9
    assert loaded.for_scene("unknown") == loaded.calibration
    assert loaded.strength == 0.72


def test_exact_sprite_strength_and_partial_tint_survive_profile_round_trip():
    profile = CalibrationProfile(Calibration(glow_color_mix=0.35), strength=1.85)
    loaded = CalibrationProfile.from_payload(profile.to_payload())
    assert loaded.strength == 1.85
    assert loaded.calibration.glow_color_mix == 0.35


def test_profile_rejects_unknown_or_non_numeric_settings() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        Calibration.from_mapping({"character_brightness": 1.0})
    with pytest.raises(ValueError, match="number"):
        Calibration.from_mapping({"rim_strength": "high"})


def test_export_preserves_asset_discovery_config(tmp_path: Path) -> None:
    path = tmp_path / "scenelight.json"
    path.write_text(json.dumps({"character_tags": ["hero"]}), encoding="utf-8")
    merge_profile_into_config(
        path, CalibrationProfile(Calibration(exposure_bias=0.2), strength=0.72)
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["character_tags"] == ["hero"]
    assert payload["calibration_version"] == CALIBRATION_VERSION
    assert payload["calibration"]["exposure_bias"] == 0.2
    assert payload["strength"] == 0.72


def test_legacy_profile_without_strength_keeps_approved_physical_default(tmp_path: Path) -> None:
    path = tmp_path / "legacy-profile.json"
    path.write_text(
        '{"calibration_version":1,"calibration":{"exposure_bias":-0.1}}',
        encoding="utf-8",
    )

    assert load_profile(path).strength == 1.0
