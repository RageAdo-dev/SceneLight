import json
from pathlib import Path

import pytest

from scenelight.calibration import Calibration, CalibrationProfile, profile_path
from scenelight.cli import _effective_config
from scenelight.configuration import resolve_project_settings
from scenelight.preview.settings_export import SettingsChangedError, prepare_settings_write
from scenelight.project import _load_config


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    for name in ("LOCALAPPDATA", "APPDATA", "SCENELIGHT_MANAGED_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / name))


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_project_export_replaces_stale_profile_defaults_for_preview_and_install(tmp_path):
    config = tmp_path / "scenelight.json"
    associated = profile_path(tmp_path)
    write(
        config,
        {
            "strength": 1,
            "character_tags": ["hero"],
            "scene_calibration": {"night": {"exposure_bias": -0.5}},
            "sprite_rules": {"hero": {"strength": 0.6}},
        },
    )
    write(
        associated,
        {
            "strength": 0.3,
            "calibration": {"exposure_bias": -0.2},
            "excluded_character_tags": ["sticker"],
            "auto_include_new_characters": False,
        },
    )
    original = config.read_bytes(), associated.read_bytes()
    selected = CalibrationProfile(Calibration(exposure_bias=0.4), strength=0.8)
    plan = prepare_settings_write(config, selected, associated_profile=associated)
    assert (config.read_bytes(), associated.read_bytes()) == original
    assert len(plan.related) == 1
    plan.write()
    effective = resolve_project_settings(tmp_path)
    assert effective.values == _load_config(tmp_path, _effective_config(tmp_path, None))
    assert effective.values["strength"] == 0.8
    assert effective.values["calibration"]["exposure_bias"] == 0.4
    assert effective.values["character_tags"] == ["hero"]
    assert effective.values["excluded_character_tags"] == ["sticker"]
    assert effective.values["auto_include_new_characters"] is False
    assert effective.values["sprite_rules"] == {"hero": {"strength": 0.6}}
    assert effective.values["scene_calibration"] == {"night": {"exposure_bias": -0.5}}
    preview_profile = CalibrationProfile.from_payload(effective.values)
    assert preview_profile.strength == selected.strength
    assert preview_profile.calibration == selected.calibration
    assert preview_profile.for_scene("night").exposure_bias == -0.5


def test_config_layers_preserve_nested_overrides_and_explicit_file_wins(tmp_path):
    project = tmp_path / "project"
    config, associated, explicit = (
        project / "scenelight.json",
        profile_path(project),
        tmp_path / "portable.json",
    )
    write(
        config,
        {
            "calibration": {"exposure_bias": -0.2, "glow_strength": 2},
            "scene_calibration": {"room": {"exposure_bias": -0.4}},
        },
    )
    write(
        associated,
        {
            "calibration": {"glow_strength": 3},
            "scene_calibration": {"room": {"color_adaptation": 0.5}},
        },
    )
    write(explicit, {"calibration": {"glow_strength": 4}})
    resolved = resolve_project_settings(project, explicit)
    assert resolved.sources == (config, associated, explicit)
    assert resolved.values["calibration"] == {"exposure_bias": -0.2, "glow_strength": 4}
    assert resolved.values["scene_calibration"] == {
        "room": {"exposure_bias": -0.4, "color_adaptation": 0.5}
    }
    assert _load_config(project, explicit) == resolved.values


def test_failed_project_export_restores_saved_profile(tmp_path, monkeypatch):
    from scenelight.preview import settings_export

    config, associated = tmp_path / "scenelight.json", profile_path(tmp_path)
    write(config, {"strength": 1})
    write(associated, {"strength": 0.3, "excluded_character_tags": ["sticker"]})
    before = config.read_bytes(), associated.read_bytes()
    plan = prepare_settings_write(
        config, CalibrationProfile(strength=0.8), associated_profile=associated
    )
    replace = settings_export.os.replace

    def fail_primary(source, destination):
        if Path(destination) == config:
            raise PermissionError("project is read-only")
        replace(source, destination)

    monkeypatch.setattr(settings_export.os, "replace", fail_primary)
    with pytest.raises(PermissionError, match="read-only"):
        plan.write()
    assert (config.read_bytes(), associated.read_bytes()) == before


def test_profile_edited_after_export_review_prevents_both_writes(tmp_path):
    config, associated = tmp_path / "scenelight.json", profile_path(tmp_path)
    write(config, {"strength": 1})
    write(associated, {"strength": 0.3})
    before = config.read_bytes()
    plan = prepare_settings_write(
        config, CalibrationProfile(strength=0.8), associated_profile=associated
    )
    write(associated, {"strength": 0.6})
    with pytest.raises(SettingsChangedError):
        plan.write()
    assert config.read_bytes() == before
    assert json.loads(associated.read_bytes())["strength"] == 0.6


def test_preview_loads_root_config_without_a_saved_profile(tmp_path):
    from PySide6.QtWidgets import QApplication

    from scenelight.preview.ui import MainWindow

    (tmp_path / "game").mkdir()
    write(tmp_path / "scenelight.json", {"strength": 0.8, "calibration": {"exposure_bias": 0.4}})
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    try:
        assert window._calibration_profile.strength == 0.8
        assert window._calibration.exposure_bias == 0.4
        assert "scenelight.json" in window._settings_export.sources.text()
    finally:
        window.close()
        app.processEvents()
