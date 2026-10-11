"""Finalization reports stages and completed file counts through commit or rollback."""

import json
import queue
import shutil
import threading
import types

import pytest

from scenelight import cli, developer, diagnostics
from scenelight import progress as module
from scenelight import setup_gui as ui
from scenelight.progress import ProgressStage, copytree_with_progress


def test_heartbeat_reports_waiting_without_inventing_completion(monkeypatch):
    lines = []
    heartbeat = threading.Event()

    def record(line, **_kwargs):
        lines.append(line)
        if len(lines) >= 2:
            heartbeat.set()

    monkeypatch.setattr(module, "print", record, raising=False)
    with ProgressStage("form-workers", interval=0.02, item="Waiting for workers"):
        assert heartbeat.wait(1), "No liveness update while an operation was blocked"
        assert all("0/0:" in line for line in lines)
    assert lines[-1].endswith(": Complete")
    assert "0/0:" in lines[-1]
    assert all("100%" not in line for line in lines)


def test_failed_phase_never_emits_a_successful_completion(monkeypatch):
    lines = []
    monkeypatch.setattr(module, "print", lambda line, **_kwargs: lines.append(line), raising=False)
    with pytest.raises(OSError, match="disk full"):
        with ProgressStage("runtime-copy", total=2) as stage:
            stage.advance()
            raise OSError("disk full")
    assert "1/2:" in lines[-1] and "Stopped: OSError: disk full" in lines[-1]
    assert not any(line.endswith(": Complete") for line in lines)


def test_copy_progress_retains_contents_metadata_and_ignore_rules(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(48):
        (source / f"map-{index}.bin").write_bytes(bytes([index]) * 100)
    (source / "ignored.tmp").write_text("temporary checkpoint")
    ignored_dir = source / "old.tmp"
    ignored_dir.mkdir()
    (ignored_dir / "hidden.bin").write_bytes(b"do not copy")
    lines = []
    copied = [0]
    real_copy = shutil.copy2

    def copying(src, dst):
        result = real_copy(src, dst)
        copied[0] += 1
        return result

    def record(line, **_kwargs):
        lines.append(line)
        update = ui.parse_progress(line)
        assert update.current <= copied[0], "Progress advanced before data was copied"

    monkeypatch.setattr(module.shutil, "copy2", copying)
    monkeypatch.setattr(module, "print", record, raising=False)
    target = tmp_path / "target"
    copytree_with_progress(source, target, "cache-save", ignore=shutil.ignore_patterns("*.tmp"))
    assert copied[0] == 48
    assert "48/48:" in lines[-1]
    assert len(lines) < 12, "Fast small files should not flood logs"
    assert sorted(p.name for p in target.iterdir()) == sorted(f"map-{i}.bin" for i in range(48))
    for dest in target.iterdir():
        original = source / dest.name
        assert dest.read_bytes() == original.read_bytes()
        assert dest.stat().st_mtime_ns == original.stat().st_mtime_ns


def test_copy_error_preserves_prior_cache_and_is_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = tmp_path / "project"
    managed = tmp_path / "working"
    cache = managed / ".scenelight_cache"
    cache.mkdir(parents=True)
    (cache / "new.bin").write_text("new data")
    destination = cli.analysis_cache_root(project)
    destination.mkdir(parents=True)
    (destination / "old.bin").write_text("last good cache")

    def fail(*_args, **_kwargs):
        raise OSError("output unavailable")

    lines = []
    monkeypatch.setattr(module.shutil, "copy2", fail)
    monkeypatch.setattr(module, "print", lambda line, **_kwargs: lines.append(line), raising=False)
    with pytest.raises(shutil.Error):
        cli._preserve_analysis_cache(project, managed)
    assert (destination / "old.bin").read_text() == "last good cache"
    assert not (destination / "new.bin").exists()
    assert any("Stopped" in line for line in lines)
    assert not any(line.endswith(": Complete") for line in lines)


def test_stage_parser_does_not_present_unknown_work_as_100_percent():
    for phase in module.STAGE_LABELS:
        update = ui.parse_progress(f"SceneLight stage {phase} 0/0: Waiting on files")
        assert update and update.total == 0
        text = ui.format_progress_status(update, elapsed_seconds=125, completed_since_start=0)
        assert "elapsed 2m 05s" in text and "Waiting on files" in text
        assert "%" not in text and "left" not in text
    assert ui.parse_progress("SceneLight stage bogus 0/0: unregistered") is None
    assert ui.parse_progress("SceneLight stage cache-save 4/2: invalid") is None


def test_ui_leaves_map_100_percent_and_updates_elapsed_without_new_console_lines(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ui.time, "monotonic", lambda: now[0])
    events = queue.Queue()
    bar = types.SimpleNamespace(state={}, starts=0)
    bar.stop = lambda: None
    bar.configure = lambda **kwargs: bar.state.update(kwargs)

    def start(_interval):
        bar.starts += 1

    bar.start = start
    label = types.SimpleNamespace(value="old map stage")
    label.set = lambda value: setattr(label, "value", value)
    state = types.SimpleNamespace(
        _events=events,
        _active_operation="embed",
        _progress_phase="form",
        _progress_current=14501,
        _progress_total=14501,
        _progress_started_at=80.0,
        _progress_origin=0,
        _progress_indeterminate=False,
        _latest_progress=None,
        _last_elapsed_refresh=0.0,
        progress=bar,
        operation_var=label,
        _append_log=lambda *_args, **_kw: None,
        after=lambda *_args: None,
    )
    state._drain_events = types.MethodType(ui.SceneLightSetup._drain_events, state)
    state._refresh_elapsed_progress = types.MethodType(
        ui.SceneLightSetup._refresh_elapsed_progress, state
    )
    events.put(("log", "SceneLight stage form-workers 0/0: Waiting for workers"))
    ui.SceneLightSetup._drain_events(state)
    assert bar.state["mode"] == "indeterminate" and bar.starts == 1
    assert "Finishing sprite-map workers" in label.value and "100%" not in label.value
    now[0] += 9
    ui.SceneLightSetup._drain_events(state)
    assert "elapsed 9s" in label.value
    events.put(("log", "SceneLight stage cache-save 0/0: Counting files"))
    ui.SceneLightSetup._drain_events(state)
    now[0] += 3
    events.put(("log", "SceneLight stage cache-save 0/40000: map.png"))
    ui.SceneLightSetup._drain_events(state)
    assert bar.state["mode"] == "determinate" and bar.state["maximum"] == 40000
    assert "Saving reusable analysis files" in label.value
    assert "elapsed 3s" in label.value, "Discovering the total must not reset the stage clock"
    events.put(("log", "SceneLight stage cache-save 17000/40000: map-17000.png"))
    ui.SceneLightSetup._drain_events(state)
    assert "17,000 of 40,000" in label.value and "map-17000.png" in label.value
    before = label.value
    state._active_operation = None
    now[0] += 20
    ui.SceneLightSetup._drain_events(state)
    assert label.value == before


def test_activity_retains_each_finalization_phase_even_when_fast(tmp_path):
    session = diagnostics.Session("setup", root=tmp_path)
    session.output("form 14501/14501: last sprite")
    for phase in (
        "form-index",
        "cache-save",
        "runtime-copy",
        "runtime-hashes",
        "workspace-cleanup",
    ):
        session.output(f"SceneLight stage {phase} 0/40: starting")
    rows = diagnostics.read_events(session.path)
    assert len([row for row in rows if "SceneLight stage" in row["message"]]) == 5


def test_existing_installation_is_not_labeled_ready_during_update(tmp_path):
    class Widget:
        value = ""

        def set(self, value):
            self.value = value

        def configure(self, **_kwargs):
            pass

        def grid(self):
            pass

        def grid_remove(self):
            pass

    inspection = types.SimpleNamespace(
        preferred_release_relation=None,
        direct_install_needs_attention=False,
        managed_install_needs_attention=False,
        unmanaged_namespace_present=False,
        error=None,
        direct_install_ready=True,
        managed_install_present=False,
        managed_launcher=None,
        direct_refresh_required=False,
        refresh_required=False,
        direct_launch_ready=True,
        managed_install_ready=False,
    )
    app = types.SimpleNamespace(
        _selection=lambda: ui.ProjectSelection(tmp_path, True, "66 scripts"),
        _project_inspection=inspection,
        _dependency_state=types.SimpleNamespace(ready=True),
        _character_review_pending_for=None,
        _project_checking=False,
        _running=True,
        _active_operation="refresh",
        _attached=True,
        _scan_ok=True,
        developer_mode=True,
        step_labels=[],
    )
    for name in (
        "project_name_var",
        "project_path_var",
        "status_var",
        "project_status",
        "installation_var",
        "installation_status",
        "project_browse",
        "state_row",
        "primary_button",
        "install_choice_frame",
        "workflow_title_var",
        "workflow_subtitle_var",
    ):
        setattr(app, name, Widget())
    for name in (
        "mode_button",
        "sdk_entry",
        "sdk_browse",
        "cuda_check",
        "inspector_check",
        "verify_button",
        "review_button",
        "characters_button",
        "preview_button",
        "open_button",
        "remove_button",
        "unembed_button",
        "embed_button",
        "manage_button",
        "components_button",
        "advanced_components_button",
    ):
        setattr(app, name, None)
    ui.SceneLightSetup._refresh_project_state(app)
    assert "update is still running" in app.installation_var.value
    assert "ready" not in app.installation_var.value
    assert app.workflow_title_var.value == "Updating SceneLight"
    app._running = False
    app._active_operation = None
    ui.SceneLightSetup._refresh_project_state(app)
    assert "installed and ready" in app.installation_var.value


def test_developer_copy_and_verification_report_real_file_totals(tmp_path, capsys):
    from test_developer import _projects

    project, managed = _projects(tmp_path)
    maps = managed / "game/scenelight_runtime/sprite_form"
    maps.mkdir()
    for index in range(200):
        (maps / f"map-{index}.bin").write_bytes(bytes([index]) * 16)
    original = (project / "game/script.rpy").read_bytes()
    result = developer.embed_from_managed(project, managed)
    lines = capsys.readouterr().out.splitlines()
    stages = [ui.parse_progress(line) for line in lines if line.startswith("SceneLight stage")]
    assert {row.phase for row in stages} >= {
        "stage-runtime-copy",
        "stage-runtime-hashes",
        "stage-source-index",
        "stage-install-record",
    }
    verified = [row for row in stages if row.phase == "stage-runtime-hashes"][-1]
    assert verified.current == verified.total == result["owned_file_count"]
    manifest = json.loads((project / developer.MANIFEST_NAME).read_text())
    assert len(manifest["files"]) == result["owned_file_count"]
    assert (project / "game/script.rpy").read_bytes() == original
    assert developer.developer_status(project).clean


@pytest.mark.parametrize(
    "position, reset, follow",
    [((0.8, 1.0), False, True), ((0.1, 0.3), False, False), ((0.1, 0.3), True, True)],
)
def test_activity_refresh_follows_live_end_but_preserves_older_reading(position, reset, follow):
    from scenelight.diagnostics_ui import _replace_activity_text

    calls = []
    text = types.SimpleNamespace(
        yview=lambda: position,
        configure=lambda **kw: calls.append(("configure", kw)),
        delete=lambda *args: calls.append(("delete", args)),
        insert=lambda *args: calls.append(("insert", args)),
        see=lambda value: calls.append(("see", value)),
        yview_moveto=lambda value: calls.append(("move", value)),
    )
    _replace_activity_text(text, "new verification progress", reset=reset)
    assert calls[-1] == (("see", "end") if follow else ("move", position[0]))
    assert ("insert", ("end", "new verification progress")) in calls
