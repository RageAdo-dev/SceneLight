import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration, CalibrationProfile, ColorGlowRule
from scenelight.preview.calibration_dialog import CalibrationEditor
from scenelight.preview.settings_export import (
    SettingsChangedError,
    SettingsExportPage,
    prepare_settings_write,
)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_review_is_read_only_then_writes_exact_bytes_preserving_target_rules(tmp_path):
    path = tmp_path / "scenelight.json"
    old = {
        "character_tags": ["hero"],
        "scene_calibration": {"night": {"exposure_bias": -0.5}},
        "sprite_rules": {"hero": {"strength": 0.2}},
        "strength": 1.0,
        "custom": ["keep this"],
    }
    before = json.dumps(old).encode()
    path.write_bytes(before)
    profile = CalibrationProfile(
        Calibration(glow_strength=10, glow_rules=(ColorGlowRule(name="火", strength=9),)),
        scenes={"night": Calibration(exposure_bias=1)},
        strength=0.78,
    )
    plan = prepare_settings_write(path, profile)
    assert path.read_bytes() == before
    reviewed = json.loads(plan.content)
    assert reviewed["scene_calibration"] == old["scene_calibration"]
    assert reviewed["sprite_rules"] == old["sprite_rules"]
    assert reviewed["character_tags"] == ["hero"]
    assert reviewed["custom"] == old["custom"]
    assert reviewed["strength"] == 0.78
    assert reviewed["calibration"] == profile.calibration.as_dict()
    plan.write()
    assert path.read_bytes() == plan.content
    assert not list(tmp_path.glob(".scenelight-settings-*"))


@pytest.mark.parametrize(
    "initial,external", [(None, b"{}"), (b"{}", None), (b"{}", b'{"strength":0.2}')]
)
def test_changed_added_or_removed_destination_requires_new_review(tmp_path, initial, external):
    path = tmp_path / "settings.json"
    if initial is not None:
        path.write_bytes(initial)
    plan = prepare_settings_write(path, CalibrationProfile())
    if external is None:
        path.unlink()
    else:
        path.write_bytes(external)
    with pytest.raises(SettingsChangedError, match="changed outside"):
        plan.write()
    assert (path.read_bytes() if path.exists() else None) == external


def test_failed_atomic_write_keeps_original_and_cleans_temporary(tmp_path, monkeypatch):
    from scenelight.preview import settings_export

    path = tmp_path / "settings.json"
    path.write_bytes(b"{}")
    plan = prepare_settings_write(path, CalibrationProfile())

    def fail(*args):
        raise PermissionError("Read-only destination")

    monkeypatch.setattr(settings_export.os, "replace", fail)
    with pytest.raises(PermissionError):
        plan.write()
    assert path.read_bytes() == b"{}"
    assert not list(tmp_path.glob(".scenelight-settings-*"))


def test_export_page_tracks_live_values_without_writing_until_final_click(app, tmp_path):
    path = tmp_path / "profile.json"
    profile = CalibrationProfile(strength=0.78)
    page = SettingsExportPage(profile, path, None)
    saved = []
    page.saved.connect(lambda *args: saved.append(args))
    try:
        page.show()
        app.processEvents()
        assert not path.exists()
        assert page.values.topLevelItem(0).text(1) == "0.78 (78%)"
        profile = replace(
            profile, calibration=Calibration(glow_strength=10, light_color_amount=-0.3)
        )
        page.set_profile(profile)
        reviewed = page.file_preview.toPlainText().encode()
        assert json.loads(reviewed)["calibration"]["glow_strength"] == 10
        assert not path.exists()
        page.write_button.click()
        assert path.read_bytes() == reviewed
        assert saved == [(str(path), "profile")]
        page.set_profile(replace(profile, strength=0.25))
        assert path.read_bytes() == reviewed
        page.close()
        assert path.read_bytes() == reviewed
    finally:
        page.close()


def test_export_error_requires_explicit_refresh_and_invalid_file_never_overwritten(app, tmp_path):
    path = tmp_path / "scenelight.json"
    path.write_bytes(b"{}")
    page = SettingsExportPage(CalibrationProfile(), None, path)
    try:
        page.select_mode(1)
        path.write_bytes(b'{"strength":0.1}')
        page.write_button.click()
        assert not page.write_button.isEnabled()
        assert "changed outside" in page.message.text()
        assert path.read_bytes() == b'{"strength":0.1}'
        page.refresh()
        assert page.write_button.isEnabled()
        path.write_bytes(b"broken")
        page.refresh()
        assert not page.write_button.isEnabled()
        assert not page.file_preview.toPlainText()
        page._write()
        assert path.read_bytes() == b"broken"
    finally:
        page.close()


def test_embedded_editor_preserves_untouched_precision_and_selected_glow_rule(app):
    calibration = Calibration(
        exposure_bias=0.1234567,
        glow_red=0.1234567,
        glow_color_mix=0.32123,
        glow_rules=(ColorGlowRule(name="First"), ColorGlowRule(name="Second", tolerance=0.12345)),
    )
    changes = []
    editor = CalibrationEditor(calibration, changes.append)
    try:
        assert not changes
        assert editor.calibration == calibration
        editor._controls["glow_strength"].setValue(8.5)
        assert changes[-1] == replace(calibration, glow_strength=8.5)
        editor._color_glow.rule_list.setCurrentRow(1)
        editor._color_glow.values["strength"].setValue(9.5)
        assert changes[-1].glow_rules[1].tolerance == 0.12345
        assert editor._color_glow.rule_list.currentRow() == 1
    finally:
        editor.close()


def test_hidden_export_page_defers_file_reads_and_reviews_latest_settings_on_open(
    app, tmp_path, monkeypatch
):
    from scenelight.preview import settings_export

    path = tmp_path / "profile.json"
    page = SettingsExportPage(CalibrationProfile(), path, None)
    reads = []
    read_existing = settings_export._read_existing
    monkeypatch.setattr(
        settings_export, "_read_existing", lambda path: (reads.append(path), read_existing(path))[1]
    )
    try:
        page.set_profile(CalibrationProfile(strength=0.25))
        page.set_profile(CalibrationProfile(strength=0.78))
        assert reads == []
        assert page._plan is None
        page.show()
        app.processEvents()
        assert reads
        assert json.loads(page.file_preview.toPlainText())["strength"] == 0.78
        assert not path.exists()
    finally:
        page.close()
