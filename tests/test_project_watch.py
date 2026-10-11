from types import SimpleNamespace

import pytest

from scenelight.project_watch import ProjectWatch, source_metadata
from scenelight.setup_gui import SceneLightSetup


def test_existing_player_copy_detects_changes_after_reopening(tmp_path, monkeypatch):
    import json

    from scenelight import __version__, setup_gui

    project = tmp_path / "source"
    (project / "game").mkdir(parents=True)
    (project / "game/script.rpy").write_text("label start:\n    return\n")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "copies"))
    managed = setup_gui.managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / "Game.exe").write_bytes(b"fixture launcher")
    (managed / ".scenelight_install.json").write_text(
        json.dumps({"scenelight_version": __version__, "source_state": source_metadata(project)})
    )
    assert not setup_gui.inspect_project_installation(project).refresh_required
    (project / "game/new.png").write_bytes(b"new art")
    inspection = setup_gui.inspect_project_installation(project)
    assert inspection.managed_install_ready
    assert inspection.refresh_required
    assert not inspection.release_replacement_available


def test_inspection_reports_a_source_read_failure(tmp_path, monkeypatch):
    from scenelight import setup_gui

    (tmp_path / "game").mkdir()
    (tmp_path / "game/script.rpy").write_text("label start:\n    return\n")

    def fail(root):
        raise PermissionError("file is being replaced")

    monkeypatch.setattr(setup_gui, "source_metadata", fail)
    assert "file is being replaced" in setup_gui.inspect_project_installation(tmp_path).error


def test_source_metadata_covers_edits_additions_removals_and_ignores_generated(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    source = game / "script.rpy"
    source.write_text("scene lake")
    baseline = source_metadata(tmp_path)
    for name in [
        "saves/1.save",
        "cache/compiled.json",
        "scenelight_runtime/code.rpy",
        "script.rpyc",
    ]:
        path = game / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("ignored")
    assert source_metadata(tmp_path) == baseline
    source.write_text("scene room\nshow hero")
    assert source_metadata(tmp_path) != baseline
    sprite = game / "new.png"
    sprite.write_bytes(b"new artwork")
    assert "game/new.png" in source_metadata(tmp_path)
    sprite.unlink()
    assert "game/new.png" not in source_metadata(tmp_path)
    (tmp_path / "scenelight.json").write_text("{}")
    assert "scenelight.json" in source_metadata(tmp_path)


def test_watch_debounces_and_tracks_subsequent_changes():
    watch = ProjectWatch({"a": (1, 1)})
    assert not watch.observe({"a": (2, 2)})
    assert not watch.observe({"b": (3, 3)})
    assert watch.observe({"b": (3, 3)})
    assert not watch.observe({"b": (3, 3)})
    assert not watch.observe({})
    assert watch.observe({})


@pytest.mark.parametrize(
    "running,checking,generation", [(True, False, 3), (False, True, 3), (False, False, 2)]
)
def test_watch_discards_busy_and_stale_results(running, checking, generation):
    app = SimpleNamespace(
        _watch_busy=True, _project_generation=3, _running=running, _project_checking=checking
    )
    SceneLightSetup._finish_project_sources(app, generation, {})
    assert not app._watch_busy


@pytest.mark.parametrize("developer", [False, True])
def test_stable_changes_invalidate_scan_in_both_modes(developer):
    events = []
    app = SimpleNamespace(
        developer_mode=developer,
        _project_generation=3,
        _running=False,
        _project_checking=False,
        _watch_busy=True,
        _source_watch=ProjectWatch({}),
        _scan_ok=True,
        _review_completed_for="project",
        _character_review_pending_for="project",
        _last_scan_payload={"characters": ["old"]},
        _close_character_review_window=lambda: events.append("closed"),
        preview_var=SimpleNamespace(set=lambda text: events.append(text)),
        _append_log=lambda text: events.append(text),
        _begin_project_inspection=lambda: events.append("inspect"),
    )
    SceneLightSetup._finish_project_sources(app, 3, {"new.png": (12, 34)})
    assert app._scan_ok
    SceneLightSetup._finish_project_sources(app, 3, {"new.png": (12, 34)})
    assert not app._scan_ok
    assert app._last_scan_payload == {}
    assert events[-1] == "inspect"
