import json
from pathlib import Path

import pytest
from test_incremental_updates import installation

from scenelight import cli, updates
from scenelight.calibration import Calibration
from scenelight.developer import EMBED_ROOT, developer_status


def settings_installation(tmp_path, monkeypatch, embedded=True):
    project, root, record = installation(tmp_path, monkeypatch, embedded)
    runtime = root / EMBED_ROOT / "manifest.json"
    payload = json.loads(runtime.read_text())
    payload.update(
        character_tags=["hero", "friend"],
        excluded_character_tags=[],
        auto_include_new_characters=True,
        strength=1.0,
        calibration=Calibration().as_dict(),
        scenes={
            "room": {"calibration": Calibration().as_dict(), "tile": [1, 0]},
            "movie::1": {"calibration": Calibration().as_dict(), "tile": [2, 0]},
        },
        scene_sequences={"movie": {"frames": [[0, "movie::1"]]}},
    )
    runtime.write_text(json.dumps(payload))
    (root / EMBED_ROOT / "sprite_form_manifest.json").write_text(
        json.dumps({"sprites": {"hero idle": {}, "friend idle": {}}})
    )
    manifest = json.loads(record.read_text())
    manifest["files" if embedded else "runtime_files"] = updates.runtime_hashes(root)
    record.write_text(json.dumps(manifest))
    return project, root, record, runtime


@pytest.mark.parametrize("embedded", [True, False])
def test_new_selection_profile_and_lighting_update_without_capture_or_map_writes(
    tmp_path, monkeypatch, embedded
):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch, embedded)
    config = tmp_path / "profile.json"
    maps = list((root / EMBED_ROOT).glob("map_*.png"))
    before = [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps]
    settings = {
        "character_selection": "manual",
        "auto_include_new_characters": False,
        "character_tags": ["hero", "friend"],
        "excluded_character_tags": [],
    }
    config.write_text(json.dumps(settings))
    monkeypatch.setattr(
        cli, "_install_managed", lambda *a, **k: pytest.fail("Settings must not recapture")
    )
    command = [
        "refresh" if embedded else "install",
        "--project",
        str(project),
        "--config",
        str(config),
    ]
    assert cli._main(command) == 0
    assert json.loads(record.read_text())["last_update"]["mode"] == "settings-only"
    settings.update(
        strength=0.78,
        calibration={"glow_strength": 5},
        scene_calibration={"movie": {"exposure_bias": -0.5}},
        character_tags=["hero"],
        excluded_character_tags=["friend"],
    )
    config.write_text(json.dumps(settings))
    assert cli._main(command) == 0
    value = json.loads(runtime.read_text())
    assert value["strength"] == 0.78 and value["calibration"]["glow_strength"] == 5
    assert value["character_tags"] == ["hero"] and value["excluded_character_tags"] == ["friend"]
    assert value["scenes"]["room"]["calibration"]["glow_strength"] == 5
    assert value["scenes"]["movie::1"]["calibration"]["exposure_bias"] == -0.5
    assert value["scene_sequences"]["movie"]["frames"] == [[0, "movie::1"]]
    settings.update(character_tags=["hero", "friend"], excluded_character_tags=[])
    config.write_text(json.dumps(settings, indent=2))
    assert cli._main(command) == 0
    assert json.loads(runtime.read_text())["character_tags"] == ["friend", "hero"]
    assert [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps] == before
    assert (
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=embedded)[
            "update_mode"
        ]
        == "unchanged"
    )
    if embedded:
        assert developer_status(project).clean


def test_root_config_lighting_edits_use_settings_update_after_snapshot(tmp_path, monkeypatch):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch)
    updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=True)
    (project / "scenelight.json").write_text('{"strength":0.5}')
    result = updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=True)
    assert result["update_mode"] == "settings-only"
    assert json.loads(runtime.read_text())["strength"] == 0.5
    assert not developer_status(project).refresh_required


@pytest.mark.parametrize(
    "change", ["discovery", "new_character", "art", "unknown_previous_config", "auto_expansion"]
)
def test_uncertain_or_new_asset_inputs_still_require_analysis(tmp_path, monkeypatch, change):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch)
    config = tmp_path / "settings.json"
    settings = {"character_selection": "manual", "character_tags": ["hero"]}
    if change == "discovery":
        settings["sprites"] = {"hero other": "new.png"}
    elif change == "new_character":
        settings["character_tags"] = ["newcomer"]
    elif change == "art":
        (project / "game/new.png").write_bytes(b"new pixels")
    elif change == "unknown_previous_config":
        old = json.loads(record.read_text())
        old["config_sha256"] = "unknown older settings"
        record.write_text(json.dumps(old))
    else:
        value = json.loads(runtime.read_text())
        value["auto_include_new_characters"] = False
        runtime.write_text(json.dumps(value))
        settings["character_selection"] = "automatic"
    config.write_text(json.dumps(settings))
    before = runtime.read_bytes()
    assert updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True) is None
    assert runtime.read_bytes() == before


def test_failed_settings_commit_restores_runtime_and_ownership(tmp_path, monkeypatch):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch)
    config = tmp_path / "settings.json"
    config.write_text('{"strength":0.6}')
    originals = record.read_bytes(), runtime.read_bytes()
    replace = updates.os.replace

    def fail_commit(source, target):
        if Path(source).name == "next-record.json":
            raise OSError("commit failed")
        return replace(source, target)

    monkeypatch.setattr(updates.os, "replace", fail_commit)
    with pytest.raises(OSError, match="commit failed"):
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True)
    assert (record.read_bytes(), runtime.read_bytes()) == originals
    assert not (root / updates.JOURNAL).exists()


def test_config_edit_during_verification_is_not_silently_committed(tmp_path, monkeypatch):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch)
    config = tmp_path / "settings.json"
    config.write_text('{"strength":0.6}')
    original = runtime.read_bytes()
    verify = updates.developer_status

    def concurrent_edit(*args, **kwargs):
        result = verify(*args, **kwargs)
        config.write_text('{"strength":0.2}')
        return result

    monkeypatch.setattr(updates, "developer_status", concurrent_edit)
    with pytest.raises(RuntimeError, match="Settings changed"):
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True)
    assert runtime.read_bytes() == original


def test_automatic_selection_keeps_exclusions_but_does_not_guess_removed_opt_ins(
    tmp_path, monkeypatch
):
    project, root, record, runtime = settings_installation(tmp_path, monkeypatch)
    config = tmp_path / "settings.json"
    config.write_text('{"character_tags":["hero","friend"]}')
    assert (
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True)[
            "update_mode"
        ]
        == "settings-only"
    )
    config.write_text('{"character_tags":["hero"],"excluded_character_tags":["friend"]}')
    assert (
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True)[
            "update_mode"
        ]
        == "settings-only"
    )
    assert json.loads(runtime.read_text())["character_tags"] == ["hero"]
    config.write_text('{"character_tags":["hero","friend"]}')
    assert (
        updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True)[
            "update_mode"
        ]
        == "settings-only"
    )
    # Merely deleting an explicit effect opt-in must not leave it enabled.
    config.write_text('{"character_tags":["hero"]}')
    assert updates.try_runtime_update(project, config=config, grid=(16, 9), embedded=True) is None
