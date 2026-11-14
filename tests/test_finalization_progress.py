"""Finalization reports stages and completed file counts through commit or rollback."""

import errno
import hashlib
import json
import os
import queue
import shutil
import threading
import types

import pytest

from scenelight import cli, developer, diagnostics
from scenelight import progress as module
from scenelight import setup_gui as ui
from scenelight.progress import ProgressStage, copytree_with_progress


def test_cache_copy_is_independent_and_preserves_timestamps(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "copy"
    (source / "empty").mkdir(parents=True)
    sprite = source / "pose-雪.png"
    sprite.write_bytes(b"old")
    os.utime(sprite, ns=(1730000000000000000, 1730000000000000000))
    module.copy_cache_tree(source, target, "form-cache")
    copied = target / sprite.name
    assert copied.stat().st_mtime_ns == sprite.stat().st_mtime_ns
    assert copied.read_bytes() == b"old"
    assert (target / "empty").is_dir()
    copied.write_bytes(b"new")
    assert sprite.read_bytes() == b"old"


def test_seeded_hashes_follow_replaced_added_and_deleted_maps(tmp_path):
    from scenelight.updates import runtime_hashes

    source = tmp_path / "source"
    root = tmp_path / "build"
    maps = root / "game/scenelight_runtime/sprite_form"
    maps.parent.mkdir(parents=True)
    source.mkdir()
    for name in ("unchanged.png", "updated.png", "removed.png"):
        (source / name).write_bytes(b"old")
    verified = {}
    module.copy_cache_tree(source, maps, "form-cache", verified=verified)
    modified = maps / "updated.png"
    earlier = modified.stat()
    modified.write_bytes(b"new")
    os.utime(modified, ns=(earlier.st_atime_ns, earlier.st_mtime_ns))
    (maps / "removed.png").unlink()
    (maps / "added.png").write_bytes(b"add")
    expected, stamps = {}, {}
    for relative, (digest, stamp) in verified.items():
        key = (maps / relative).relative_to(root).as_posix()
        expected[key], stamps[key] = digest, stamp
    actual = runtime_hashes(root, expected=expected, stamps=stamps)
    assert actual == {
        (maps / name).relative_to(root).as_posix(): hashlib.sha256(content).hexdigest()
        for name, content in (
            ("unchanged.png", b"old"),
            ("updated.png", b"new"),
            ("added.png", b"add"),
        )
    }


@pytest.mark.parametrize("mode", ["transfer", "different-volume", "locked", "commit-failure"])
def test_disposable_cache_publication(tmp_path, monkeypatch, mode):
    project = tmp_path / "project"
    managed = tmp_path / "working"
    source = managed / ".scenelight_cache"
    source.mkdir(parents=True)
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "projects"))
    destination = cli.analysis_cache_root(project)
    destination.mkdir(parents=True)
    (destination / "previous").write_bytes(b"previous build")
    for name in ("capture_result.json", "capture_state.json"):
        (source / name).write_text('{"version": 1}')
    (source / "sprite.png").write_bytes(b"prepared")
    inode = (source / "sprite.png").stat().st_ino
    (source / "capture.tmp").write_bytes(b"temporary")
    replace = os.replace

    def replace_checked(src, dst):
        if src == source and mode in ("different-volume", "locked"):
            raise OSError(errno.EXDEV if mode == "different-volume" else errno.EACCES, mode)
        if mode == "commit-failure" and dst == destination and src.suffix == ".tmp":
            raise PermissionError("cannot publish")
        replace(src, dst)

    monkeypatch.setattr(cli.os, "replace", replace_checked)
    if mode == "commit-failure":
        with pytest.raises(PermissionError, match="cannot publish"):
            cli._preserve_analysis_cache(project, managed, consume=True)
        assert (destination / "previous").read_bytes() == b"previous build"
        assert (source / "sprite.png").read_bytes() == b"prepared"
    else:
        assert cli._preserve_analysis_cache(project, managed, consume=True) == destination
        assert (destination / "sprite.png").read_bytes() == b"prepared"
        assert not (destination / "capture.tmp").exists()
        if mode == "transfer":
            assert (destination / "sprite.png").stat().st_ino == inode
            assert not source.exists()
        else:
            assert (source / "sprite.png").read_bytes() == b"prepared"
    assert not list(destination.parent.glob(".slc-*"))


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

    class Label:
        text = ""

        def set(self, text):
            self.text = text

        def configure(self, *, text):
            self.text = text

        def grid(self):
            pass

        def grid_remove(self):
            self.text = ""

    live = ui.OperationProgress("Starting", 80)
    live.observe("form 14501/14501: last", 98)
    state = types.SimpleNamespace(
        _events=events,
        _live_progress=live,
        _last_progress_view=(live.step, "", "", "", (), (), ()),
        _cancel_requested=threading.Event(),
        _active_operation="embed",
        progress=bar,
        operation_var=Label(),
        progress_count=Label(),
        progress_percent=Label(),
        progress_clock=Label(),
        progress_eta=Label(),
        progress_detail=Label(),
        progress_receipt=Label(),
        _append_log=lambda *_args, **_kw: None,
        after=lambda *_args: None,
        _drain_events=lambda: None,
        worker_strip=types.SimpleNamespace(show=lambda *_args: None),
        stage_ribbon=types.SimpleNamespace(show=lambda *_args: None),
    )
    state._refresh_elapsed_progress = types.MethodType(
        ui.SceneLightSetup._refresh_elapsed_progress, state
    )

    def pump(line=None):
        if line:
            events.put(("log", line))
        ui.SceneLightSetup._drain_events(state)

    pump("SceneLight stage form-workers 0/0: Waiting for workers")
    assert bar.state["mode"] == "indeterminate" and bar.starts == 1
    assert (
        "Finishing sprite-map workers" in state.operation_var.text
        and "%" not in state.progress_count.text
    )
    now[0] += 9
    pump()
    assert (
        "Total elapsed 29s" in state.progress_clock.text
        and "This step 9s" in state.progress_clock.text
    )
    pump("SceneLight stage cache-save 0/0: Counting files")
    now[0] += 3
    pump("SceneLight stage cache-save 0/40000: map.png")
    assert bar.state["mode"] == "determinate" and bar.state["maximum"] == 40000
    assert "Saving reusable analysis files" in state.operation_var.text
    assert "This step 3s" in state.progress_clock.text
    pump("SceneLight stage cache-save 17000/40000: map-17000.png")
    assert (
        "17,000 of 40,000" in state.progress_count.text
        and "map-17000.png" in state.progress_detail.text
    )
    before = state.progress_clock.text
    state.progress_eta.text = "Under 1 min left overall"
    state._cancel_requested.set()
    state.operation_var.set("Cancelling")
    now[0] += 20
    pump("SceneLight stage cache-save 22000/40000: later.png")
    assert state.operation_var.text == "Cancelling" and state.progress_clock.text == before
    assert not state.progress_eta.text


def test_worker_retries_and_restored_batches_leave_the_sprite_count_intact():
    live = ui.OperationProgress("Starting", 0)
    live.observe("SceneLight sprite batches: 6", 1)
    live.observe("SceneLight worker 1/6: restored", 1)
    live.observe("SceneLight parallel forms 3000/18000: 6 workers", 2)
    live.observe("SceneLight worker copies 2/6: ready", 3)
    live.observe("SceneLight worker 3/6: retrying with the gl2 renderer", 4)
    assert live.worker_states() == ("restored", "queued", "retrying", "queued", "queued", "queued")
    live.observe("SceneLight parallel forms 100/18000: catching up", 5)
    live.observe("SceneLight worker 2/6: saved", 6)
    assert (live.step.current, live.step.total) == (3000, 18000)
    assert "2 of 6" in live.detail() and "Worker 3 retrying" in live.detail()
    live.observe("SceneLight worker 3/6: saved", 7)
    live.observe("SceneLight worker 3/6: saved", 8)
    assert "3 of 6" in live.detail() and "retrying" not in live.detail()
    live.observe("SceneLight worker cleanup 1/1: releasing runtimes", 9)
    assert live.step.total == 0
    live.observe("SceneLight sprite batches: 2", 10)
    assert not live.batches


def test_step_clock_and_estimate_follow_measured_work_and_survive_an_idle_renderer():
    live = ui.OperationProgress("Starting", 10)
    live.observe("SceneLight renderer 1/3: trying the native game", 20)
    assert live.step.total == 0 and "Attempt 1 of 3" in live.detail()
    live.observe("SceneLight resolver capturing form 100/150: yuri smile", 30)
    assert "yuri smile" in live.detail()
    live.observe("SceneLight resolver form 105/150", 32)
    live.observe("SceneLight resolver form 110/150", 34)
    assert "About 16s left in this step" in live.timing(35)
    assert "left" not in live.timing(64)
    assert "Total elapsed 54s" in live.timing(64)
    live.observe(
        "SceneLight capture outcome: 18142 sprite forms ready (18141 reused); 2 skipped. Background captures reused: 1010.",
        70,
    )
    live.observe("SceneLight background cache: 1008/1010 reused; 2 analyzed", 72)
    assert "18,141 sprites reused · 1 captured · 2 skipped" in live.summary()
    assert "1,008 backgrounds reused · 2 analyzed" in live.summary()
    live.observe(r"scene 3/4: C:\Users\PrivateName\mod\art.png", 73)
    assert "PrivateName" not in live.detail()
    live.observe("SceneLight applied 4 changed files; 900 existing sprite maps retained.", 75)
    assert live.detail().startswith("4 changed files") and live.step.total == 0


def test_worker_totals_match_the_meter_through_a_retry_and_plan_change():
    live = ui.OperationProgress("Updating", 0, operation="refresh")
    live.observe("SceneLight sprite batches: 2", 1)
    live.observe("SceneLight parallel forms 70/100: 2 workers | batches 50/50 20/50", 2)
    live.observe("SceneLight worker 2/2: retrying with the gl2 renderer", 3)
    live.observe("SceneLight parallel forms 55/100: catching up | batches 50/50 5/50", 4)
    assert live.batch_counts == ((50, 50), (20, 50)) and live.step.current == 70
    assert live.milestone_states()[1] == ("Capture artwork", "active")
    assert "Last update 22s ago" in live.timing(25)
    live.observe("SceneLight sprite batches: 1", 26)
    assert live.batch_counts == ()


def test_fast_update_skips_unused_phases_and_early_cleanup_does_not_imply_install():
    live = ui.OperationProgress("Updating", 0, operation="refresh")
    live.observe("SceneLight stage workspace-cleanup 0/0: cleaning up", 1)
    assert live.milestone_states()[0] == ("Check project", "active")
    live.observe("SceneLight stage runtime-copy 0/8: runtime scripts", 2)
    assert [status for _, status in live.milestone_states()] == [
        "done",
        "skipped",
        "skipped",
        "active",
    ]
    live.observe("SceneLight stage install-verify 1/8: checking", 3)
    assert live.milestone_states()[-1] == ("Apply files", "active")
    scan = ui.OperationProgress("Scanning", 0, operation="scan")
    scan.observe("SceneLight scan 4/4: finalizing backgrounds and character candidates", 3)
    assert scan.milestone_states()[-1] == ("Review assets", "active")


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


def test_activity_retains_worker_receipts_and_retries_without_a_spurious_fraction(tmp_path):
    session = diagnostics.Session("setup", root=tmp_path)
    lines = [
        "SceneLight worker 3/6: running",
        "SceneLight worker 3/6: retrying with the gl2 renderer",
        "SceneLight worker 3/6: saved",
        "SceneLight background cache: 2/2 reused; 0 analyzed",
    ]
    for line in lines:
        session.output(line)
    rows = [row for row in diagnostics.read_events(session.path) if row["message"] in lines]
    assert {row["message"] for row in rows} == set(lines)
    assert all("current" not in row["details"] for row in rows)


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
        workflow_steps=Widget(),
        selection_card=Widget(),
        setup_toolbar=Widget(),
        setup_flow=Widget(),
        _last_run_text="",
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
        "live_edit_check",
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


@pytest.mark.parametrize("stopped", [False, True])
def test_update_borrows_cache_without_copy_and_recovers_checkout(tmp_path, monkeypatch, stopped):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "projects"))
    project = tmp_path / "game-project"
    managed = cli.managed_project_root(project)
    managed.mkdir(parents=True)
    saved = cli.analysis_cache_root(project)
    saved.mkdir(parents=True)
    (saved / "pixels.png").write_bytes(b"verified pixels")
    identity = (saved / "pixels.png").stat().st_ino
    monkeypatch.setattr(cli, "copy_cache_tree", lambda *a: pytest.fail("copied the cache"))
    assert cli._restore_analysis_cache(project, managed, transfer=True)
    working = managed / ".scenelight_cache"
    assert cli.analysis_cache_root(project) == working
    assert (working / "pixels.png").stat().st_ino == identity
    (working / "new.png").write_bytes(b"new pixels")
    if stopped:
        suspended = working / "suspended-runtime"
        suspended.mkdir()
        (suspended / "scenelight_runtime.rpy").write_bytes(b"playback runtime")
        cli._return_checked_out_cache(project)
        assert (managed / "game/scenelight_runtime.rpy").read_bytes() == b"playback runtime"
        assert not (saved / "suspended-runtime").exists()
    else:
        assert cli._preserve_analysis_cache(project, managed, consume=True) == saved
    assert (saved / "pixels.png").stat().st_ino == identity
    assert (saved / "new.png").read_bytes() == b"new pixels"
    assert cli.analysis_cache_root(project) == saved
    assert not working.exists()
    assert not cli.cache_checkout_marker(saved).exists()
    cli._return_checked_out_cache(project)


def test_checkout_uses_legacy_cache_once(tmp_path, monkeypatch):
    from scenelight import sidecar

    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "projects"))
    project = tmp_path / "project"
    managed = cli.managed_project_root(project)
    managed.mkdir(parents=True)
    legacy = tmp_path / "old-volume" / "cache"
    legacy.mkdir(parents=True)
    (legacy / "image.png").write_bytes(b"cached")
    monkeypatch.setattr(sidecar, "_legacy_analysis_cache", lambda root: legacy)
    assert cli.analysis_cache_root(project) == legacy
    assert cli._restore_analysis_cache(project, managed, transfer=True)
    current = cli._preserve_analysis_cache(project, managed, consume=True)
    assert current != legacy and cli.analysis_cache_root(project) == current
    assert (current / "image.png").read_bytes() == b"cached"


@pytest.mark.parametrize("command", [["launch"], ["scan", "--runtime-review"]])
def test_other_workspace_operations_refuse_concurrent_update(tmp_path, monkeypatch, command):
    from scenelight.updates import operation_lock

    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "projects"))
    with operation_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another SceneLight update"):
            cli._main([*command, "--project", str(tmp_path)])
