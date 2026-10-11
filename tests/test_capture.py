import json
import struct
import textwrap
import zlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import scenelight.capture as capture_module
from scenelight.capture import (
    CaptureResult,
    _capture_command,
    _capture_content_signature,
    _capture_exit_grace_seconds,
    _capture_form_worker_count,
    _capture_process_options,
    _capture_progress_line,
    _capture_temporary_path,
    _capture_worker_renderers,
    _CaptureProgressState,
    _clone_capture_runtime,
    _composite_pipeline_worker_count,
    _deduplicate_normalized_captures,
    _durable_form_checkpoint_count,
    _materialize_composite_captures,
    _merge_parallel_capture_payloads,
    _normalize_surface_captures,
    _partition_capture_forms,
    _project_signature,
    _relativize_capture_payload,
    _run_capture_request,
    _run_capture_request_resumable,
    _runtime_diagnostic,
    _schedule_capture_worker_cleanup,
    _surface_normalization_worker_count,
    _validate_result,
    capture_runtime_review,
    capture_source,
    merge_capture,
    preflight_runtime,
)
from scenelight.cli import _renderer_attempts, _runtime_capture_launchers
from scenelight.project import ProjectDiscovery
from scenelight.sidecar import sync_project


def test_native_runtime_capture_uses_the_game_launcher_without_sdk_arguments(
    tmp_path: Path,
) -> None:
    game = tmp_path / "Example.exe"
    project = tmp_path / "Example"

    assert _capture_command(game, project, native_runtime=True) == [str(game)]


def test_sdk_capture_receives_the_project_and_run_command(tmp_path: Path) -> None:
    sdk = tmp_path / "renpy.exe"
    project = tmp_path / "Example"

    assert _capture_command(sdk, project, native_runtime=False) == [
        str(sdk),
        str(project),
        "run",
    ]


def test_form_worker_count_adapts_to_work_cpu_and_live_memory(monkeypatch) -> None:
    class Memory:
        available = 64 * 1024**3

    monkeypatch.setattr(capture_module.psutil, "virtual_memory", lambda: Memory())
    monkeypatch.setattr(capture_module.os, "cpu_count", lambda: 32)

    assert _capture_form_worker_count(1499) == 1
    assert _capture_form_worker_count(1500) == 2
    assert _capture_form_worker_count(7386) == 6

    Memory.available = 4 * 1024**3
    assert _capture_form_worker_count(7386) == 1


def test_windows_sprite_workers_prefer_angle_before_gl2(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "gl2").mkdir()
    monkeypatch.setattr(capture_module.os, "name", "nt")

    assert _capture_worker_renderers(None, tmp_path) == ["angle2", "gl2"]
    assert _capture_worker_renderers("gl2", tmp_path) == ["gl2", "angle2"]


def test_legacy_or_non_windows_worker_keeps_the_default_renderer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(capture_module.os, "name", "posix")
    assert _capture_worker_renderers(None, tmp_path) == [None]


def test_parallel_worker_payloads_merge_into_the_normal_capture_contract() -> None:
    master = {
        "version": capture_module.CAPTURE_VERSION,
        "plan_only": True,
        "character_tags": ["hero"],
        "character_candidates": {"hero": None},
        "scenes": {"room": "captured/room.png"},
        "errors": ["scene missing: unresolved"],
    }
    workers = [
        {
            "version": capture_module.CAPTURE_VERSION,
            "plan_only": False,
            "sprites": {"hero idle": "worker/hero.png"},
            "composite_captures": {
                "worker/hero.png": {"size": [10, 10], "layers": []},
                "worker/unreferenced.png": {"size": [1, 1], "layers": []},
            },
            "surface_captures": [],
            "normalized_captures": [],
            "errors": [],
        }
    ]

    merged = _merge_parallel_capture_payloads(
        master,
        workers,
        {"hero": ["hero idle"], "hero idle": ["hero idle"]},
    )

    assert merged["plan_only"] is False
    assert merged["sprites"] == {"hero idle": "worker/hero.png"}
    assert list(merged["composite_captures"]) == ["worker/hero.png"]
    assert merged["resolved_requests"] == ["hero", "hero idle"]
    assert merged["character_candidates"] == {"hero": "worker/hero.png"}


def test_capture_worker_clone_links_assets_but_isolates_writable_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    game = source / "game"
    (game / "cache").mkdir(parents=True)
    (game / "saves").mkdir()
    (source / "renpy").mkdir()
    (source / ".scenelight_cache").mkdir()
    archive = game / "images.rpa"
    script = game / "script.rpy"
    engine_bytecode = source / "renpy" / "engine.pyc"
    archive.write_bytes(b"archive")
    script.write_text("label start:\n    return\n", encoding="utf-8")
    engine_bytecode.write_bytes(b"engine")
    (game / "cache" / "bytecode.rpyb").write_bytes(b"cache")
    (game / "saves" / "persistent").write_bytes(b"save")
    (source / ".scenelight_cache" / "result.json").write_text("{}", encoding="utf-8")

    destination = tmp_path / "worker"
    _clone_capture_runtime(source, destination)

    assert (destination / "game" / "images.rpa").samefile(archive)
    assert (destination / "renpy" / "engine.pyc").samefile(engine_bytecode)
    assert not (destination / "game" / "script.rpy").samefile(script)
    assert not (destination / "game" / "cache").exists()
    assert not (destination / "game" / "saves").exists()
    assert not (destination / ".scenelight_cache").exists()


def test_completed_worker_tree_is_removed_in_the_background(tmp_path: Path) -> None:
    worker_group = tmp_path / ".slw-test"
    (worker_group / "w1" / "game").mkdir(parents=True)
    (worker_group / "w1" / "game" / "cache.rpyc").write_bytes(b"cache")

    cleanup = _schedule_capture_worker_cleanup(worker_group)
    cleanup.join(timeout=5)

    assert not cleanup.is_alive()
    assert not worker_group.exists()


def test_worker_capture_paths_are_made_portable_inside_the_project(tmp_path: Path) -> None:
    component = tmp_path / ".scenelight_cache" / "worker" / "component.png"
    destination = tmp_path / ".scenelight_cache" / "worker" / "sprite.png"
    component.parent.mkdir(parents=True)
    component.touch()
    destination.touch()
    payload = {
        "sprites": {"hero": str(destination)},
        "surface_captures": [str(destination)],
        "normalized_captures": [],
        "composite_captures": {
            str(destination): {
                "size": [1, 1],
                "layers": [{"source": str(component), "position": [0, 0]}],
            }
        },
    }

    _relativize_capture_payload(tmp_path, payload)

    relative_destination = ".scenelight_cache/worker/sprite.png"
    assert payload["sprites"] == {"hero": relative_destination}
    assert payload["surface_captures"] == [relative_destination]
    manifest = payload["composite_captures"][relative_destination]
    assert manifest["layers"][0]["source"] == ".scenelight_cache/worker/component.png"


def test_durable_form_count_uses_semantic_journal_keys(tmp_path: Path) -> None:
    journal = tmp_path / "capture_forms.jsonl"
    journal.write_text(
        "\n".join(
            (
                json.dumps({"key": "hero a b", "name": "hero a b", "relative": "a.png"}),
                json.dumps({"key": "hero a b", "name": "hero b a", "relative": "b.png"}),
                json.dumps({"key": "hero c", "name": "hero c", "relative": "c.png"}),
                "{interrupted",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert _durable_form_checkpoint_count(tmp_path) == 2


def test_checkpointed_renderer_exit_uses_short_recovery_grace(tmp_path: Path) -> None:
    assert _capture_exit_grace_seconds(tmp_path, 0) == 10.0

    (tmp_path / "sprite_form.png.surface-checkpoint").write_text(
        "raw\n",
        encoding="utf-8",
    )

    assert _capture_exit_grace_seconds(tmp_path, 0) == 1.0
    assert _capture_exit_grace_seconds(tmp_path, 1) == 10.0


def test_capture_supervision_follows_detached_sdk_process_tree(monkeypatch) -> None:
    class Process:
        def __init__(self, pid: int, parent_pid: int) -> None:
            self.info = {"pid": pid, "ppid": parent_pid}

    processes = [
        Process(101, 100),
        Process(102, 101),
        Process(200, 1),
    ]
    monkeypatch.setattr(capture_module.psutil, "process_iter", lambda _fields: processes)

    assert capture_module._descendant_pids({100}) == {101, 102}


def test_active_runtime_capture_extends_its_stall_deadline(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    executable = project / "Example.exe"
    executable.touch()
    request_path = project / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    result_path = project / "result.json"
    progress_path = project / "progress.json"
    progress_path.write_text(
        json.dumps({"stage": "form", "current": 0, "total": 20}),
        encoding="utf-8",
    )
    discovery = ProjectDiscovery(
        project_root=project,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
    )

    class Process:
        pid = 123

        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    process = Process()
    monotonic_values = iter((0.0, 1.0, 1.0, 14.0, 14.0))
    sleeps = 0

    def fake_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            progress_path.write_text(
                json.dumps({"stage": "form", "current": 5, "total": 20}),
                encoding="utf-8",
            )
        else:
            result_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(capture_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(capture_module, "_managed_runtime_pids", lambda _root: set())
    monkeypatch.setattr(capture_module, "_descendant_pids", lambda _pids: set())
    monkeypatch.setattr(capture_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(capture_module.time, "sleep", fake_sleep)

    _run_capture_request(
        discovery,
        executable,
        request_path=request_path,
        result_path=result_path,
        native_runtime=True,
        timeout_seconds=10,
        purpose="capture test assets",
        progress_path=progress_path,
    )

    assert sleeps == 2
    assert result_path.is_file()


def test_native_renderer_exit_resumes_from_new_atomic_sprite_checkpoints(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    game = tmp_path / "game"
    capture_root = tmp_path / "captured"
    composite_root = capture_root / "composite_jobs"
    game.mkdir()
    capture_root.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
    )
    attempts = 0

    def fake_run(*_args, **_kwargs) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            marker = capture_root / f"sprite_form_{attempts}.png.surface-checkpoint"
            marker.write_text("raw\n", encoding="utf-8")
            raise RuntimeError("Ren'Py stopped (exit 3221225477).")

    monkeypatch.setattr(capture_module, "_run_capture_request", fake_run)
    monkeypatch.setattr(capture_module, "CAPTURE_LOW_YIELD_CRASH_LIMIT", 3)

    _run_capture_request_resumable(
        discovery,
        tmp_path / "Game.exe",
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        native_runtime=True,
        timeout_seconds=60,
        purpose="capture test forms",
        progress_path=tmp_path / "progress.json",
        composite_job_root=composite_root,
        renderer=None,
        capture_root=capture_root,
    )

    assert attempts == 3
    assert "Retrying from saved progress" in capsys.readouterr().out


def test_repeated_low_yield_renderer_crashes_promote_the_next_backend(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    game = tmp_path / "game"
    capture_root = tmp_path / "captured"
    game.mkdir()
    capture_root.mkdir()
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, [])
    attempts = 0

    def stop_after_one_form(*_args, **_kwargs) -> None:
        nonlocal attempts
        attempts += 1
        (capture_root / f"sprite_{attempts}.png.surface-checkpoint").write_text(
            "raw\n", encoding="utf-8"
        )
        raise RuntimeError("Ren'Py stopped (exit 3221225477).")

    monkeypatch.setattr(capture_module, "_run_capture_request", stop_after_one_form)

    with pytest.raises(RuntimeError, match="another renderer is required"):
        _run_capture_request_resumable(
            discovery,
            tmp_path / "Game.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=True,
            timeout_seconds=60,
            purpose="capture test forms",
            progress_path=tmp_path / "progress.json",
            composite_job_root=capture_root / "composite_jobs",
            renderer=None,
            capture_root=capture_root,
        )

    assert attempts == 2
    output = capsys.readouterr().out
    assert "Trying another compatible renderer" in output


def test_native_renderer_exit_without_a_new_checkpoint_is_not_retried(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game = tmp_path / "game"
    capture_root = tmp_path / "captured"
    game.mkdir()
    capture_root.mkdir()
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, [])
    attempts = 0

    def fail_without_progress(*_args, **_kwargs) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Ren'Py stopped (exit 3221225477).")

    monkeypatch.setattr(capture_module, "_run_capture_request", fail_without_progress)

    with pytest.raises(RuntimeError, match="3221225477"):
        _run_capture_request_resumable(
            discovery,
            tmp_path / "Game.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=True,
            timeout_seconds=60,
            purpose="capture test forms",
            progress_path=tmp_path / "progress.json",
            composite_job_root=capture_root / "composite_jobs",
            renderer=None,
            capture_root=capture_root,
        )

    assert attempts == 1


def test_controlled_capture_batch_continues_without_reporting_a_crash(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    game = tmp_path / "game"
    capture_root = tmp_path / "captured"
    game.mkdir()
    capture_root.mkdir()
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, [])
    attempts = 0
    progress_states: list[_CaptureProgressState] = []

    def finish_two_batches(*_args, **_kwargs) -> bool:
        nonlocal attempts
        attempts += 1
        progress_states.append(_kwargs["progress_state"])
        assert _kwargs["materialize_composites"] is False
        if attempts == 1:
            (capture_root / "sprite_form.png.surface-checkpoint").write_text(
                "raw\n", encoding="utf-8"
            )
            return False
        return True

    monkeypatch.setattr(capture_module, "_run_capture_request", finish_two_batches)

    _run_capture_request_resumable(
        discovery,
        tmp_path / "Game.exe",
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        native_runtime=True,
        timeout_seconds=60,
        purpose="capture test forms",
        progress_path=tmp_path / "progress.json",
        composite_job_root=capture_root / "composite_jobs",
        renderer=None,
        capture_root=capture_root,
    )

    output = capsys.readouterr().out
    assert attempts == 2
    assert progress_states[0] is progress_states[1]
    assert "memory-safe batch 1 complete" in output
    assert "renderer stopped unexpectedly" not in output


def test_native_runtime_is_not_started_without_a_graphics_window() -> None:
    startupinfo, creationflags = _capture_process_options(native_runtime=True)

    assert startupinfo is None
    assert creationflags == 0


def test_renderer_failure_explains_vm_graphics_limit(tmp_path: Path) -> None:
    (tmp_path / "log.txt").write_text(
        "Number of texture units: 0\nCan't find a workable environment.\n",
        encoding="utf-8",
    )

    detail = _runtime_diagnostic(tmp_path)

    assert "no usable GPU/OpenGL renderer" in detail
    assert "installing Python packages will not fix it" in detail
    assert "Windows Sandbox" in detail
    assert "--- log.txt (tail) ---" in detail


def test_native_runtime_is_preferred_before_sdk(tmp_path: Path) -> None:
    managed = tmp_path / "Green Eyes"
    managed.mkdir()
    native = managed / "GreenEyes.exe"
    native.touch()
    (managed / "renpy").mkdir()
    (managed / "renpy" / "vc_version.py").write_text('version = "8.2.1"\n', encoding="utf-8")
    sdk = tmp_path / "renpy-sdk" / "renpy.exe"
    sdk.parent.mkdir()
    sdk.touch()
    (sdk.parent / "renpy").mkdir()
    (sdk.parent / "renpy" / "vc_version.py").write_text('version = "8.3.7"\n', encoding="utf-8")

    launchers = _runtime_capture_launchers(managed, sdk)

    assert launchers == [
        (native.resolve(), True, "the mod's native Ren'Py runtime"),
        (sdk, False, "the selected Ren'Py SDK"),
    ]


def test_modern_runtime_never_falls_back_to_a_different_major_sdk(tmp_path: Path) -> None:
    managed = tmp_path / "modern-game"
    (managed / "renpy").mkdir(parents=True)
    native = managed / "ModernGame.exe"
    native.touch()
    (managed / "renpy" / "vc_version.py").write_text('version = "8.2.1"\n', encoding="utf-8")
    sdk = tmp_path / "renpy-7-sdk" / "renpy.exe"
    (sdk.parent / "renpy").mkdir(parents=True)
    sdk.touch()
    (sdk.parent / "renpy" / "vc_version.py").write_text('version = "7.8.7"\n', encoding="utf-8")

    assert _runtime_capture_launchers(managed, sdk) == [
        (native.resolve(), True, "the mod's native Ren'Py runtime")
    ]


def test_project_without_native_runtime_can_use_sdk(tmp_path: Path) -> None:
    managed = tmp_path / "source-project"
    managed.mkdir()
    sdk = tmp_path / "renpy-sdk" / "renpy.exe"
    sdk.parent.mkdir()
    sdk.touch()

    assert _runtime_capture_launchers(managed, sdk) == [(sdk, False, "the selected Ren'Py SDK")]


def test_old_renpy_expands_to_automatic_angle_and_gl_attempts(tmp_path: Path) -> None:
    project = tmp_path / "old-game"
    (project / "renpy" / "angle").mkdir(parents=True)
    (project / "renpy" / "gl").mkdir()
    executable = project / "Game.exe"
    executable.touch()

    assert _renderer_attempts([(executable, True, "native")]) == [
        (executable, True, "native (automatic renderer)", None),
        (executable, True, "native (angle renderer)", "angle"),
        (executable, True, "native (gl renderer)", "gl"),
    ]


def test_modern_renpy_expands_to_angle2_and_gl2_attempts(tmp_path: Path) -> None:
    sdk = tmp_path / "renpy-sdk"
    (sdk / "renpy" / "gl2").mkdir(parents=True)
    executable = sdk / "renpy.exe"
    executable.touch()

    assert [attempt[3] for attempt in _renderer_attempts([(executable, False, "sdk")])] == [
        None,
        "angle2",
        "gl2",
    ]


def test_archive_change_invalidates_runtime_capture_cache(tmp_path: Path) -> None:
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    archive = game / "images.rpa"
    archive.write_bytes(b"first archive")
    discovery = ProjectDiscovery(
        project_root=project,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
    )

    before = _project_signature(discovery)
    archive.write_bytes(b"changed archive payload")
    after = _project_signature(discovery)

    assert after != before


@pytest.mark.parametrize("suffix", [".rpy", ".rpym"])
def test_preflight_bytecode_does_not_invalidate_authored_capture_inputs(
    tmp_path: Path, monkeypatch, suffix: str
) -> None:
    project = tmp_path / "author"
    game = project / "game"
    game.mkdir(parents=True)
    source = game / ("story" + suffix)
    source.write_text('image bg room = "room.png"', encoding="utf-8")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = sync_project(project).managed
    discovery = ProjectDiscovery(
        project_root=managed, game_root=managed / "game", scenes={}, sprites={}, character_tags=[]
    )
    before = _project_signature(discovery)
    compiled = managed / "game" / ("story" + suffix + "c")
    compiled.write_bytes(b"first preflight compiler output")
    assert _project_signature(discovery) == before
    compiled.write_bytes(b"second preflight output with different serialized bytes")
    assert _project_signature(discovery) == before
    unknown = managed / "game" / "unknown.rpyc"
    unknown.write_bytes(b"generated bytecode with no known source counterpart")
    assert _project_signature(discovery) != before
    unknown.unlink()
    managed_source = managed / "game" / source.name
    managed_source.unlink()
    without_source = _project_signature(discovery)
    compiled.write_bytes(b"bytecode becomes authoritative when its source is gone")
    assert _project_signature(discovery) != without_source
    source.write_text('image bg room = "other.png"', encoding="utf-8")
    sync_project(project)
    assert _project_signature(discovery) != before


@pytest.mark.parametrize("with_source", [False, True])
def test_authored_bytecode_remains_a_capture_input(tmp_path: Path, monkeypatch, with_source):
    project = tmp_path / "author"
    game = project / "game"
    game.mkdir(parents=True)
    if with_source:
        (game / "story.rpy").write_text('image bg room = "room.png"', encoding="utf-8")
    compiled = game / "story.rpyc"
    compiled.write_bytes(b"authored compiled script")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = sync_project(project).managed
    discovery = ProjectDiscovery(
        project_root=managed, game_root=managed / "game", scenes={}, sprites={}, character_tags=[]
    )
    before = _project_signature(discovery)
    compiled.write_bytes(b"edited compiled script")
    sync_project(project)
    assert _project_signature(discovery) != before


def test_unverified_provenance_cannot_hide_compiled_capture_inputs(tmp_path: Path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "story.rpy").write_text('image bg room = "room.png"', encoding="utf-8")
    (tmp_path / ".scenelight_sidecar.json").write_text(
        json.dumps({"version": 1, "source": str(tmp_path), "source_files": {"game/story.rpy": {}}}),
        encoding="utf-8",
    )
    discovery = ProjectDiscovery(
        project_root=tmp_path, game_root=game, scenes={}, sprites={}, character_tags=[]
    )
    before = _project_signature(discovery)
    (game / "story.rpyc").write_bytes(b"a compiled input without verified provenance")
    assert _project_signature(discovery) != before


def test_new_sprite_requests_reuse_the_same_content_addressed_raw_capture_root(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=["hero"],
        runtime_sprite_names=["hero idle"],
    )

    content_before = _capture_content_signature(discovery)
    request_before = _project_signature(discovery)
    discovery.runtime_sprite_names.append("hero happy")

    assert _capture_content_signature(discovery) == content_before
    assert _project_signature(discovery) != request_before


def test_capture_cache_changes_only_for_pixel_or_planning_contracts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=["hero"],
    )

    content_before = _capture_content_signature(discovery)
    request_before = _project_signature(discovery)
    monkeypatch.setattr(
        capture_module,
        "capture_source",
        lambda: (_ for _ in ()).throw(AssertionError("helper bytes must not key pixels")),
    )
    assert _capture_content_signature(discovery) == content_before
    monkeypatch.setattr(
        capture_module,
        "CAPTURE_PLAN_VERSION",
        capture_module.CAPTURE_PLAN_VERSION + 1,
    )
    assert _capture_content_signature(discovery) == content_before
    assert _project_signature(discovery) != request_before
    monkeypatch.setattr(
        capture_module,
        "CAPTURE_PIXEL_VERSION",
        capture_module.CAPTURE_PIXEL_VERSION + 1,
    )
    assert _capture_content_signature(discovery) != content_before


def test_atomic_runtime_checkpoints_become_user_visible_progress() -> None:
    assert _capture_progress_line({"stage": "scene", "current": 4, "total": 39}) == (
        ("scene", 4, 39),
        "SceneLight resolver background 4/39",
    )
    assert _capture_progress_line(
        {"stage": "planned", "current": 0, "total": 1517, "requests": 1566}
    ) == (
        ("planned", 1517, 1566),
        "SceneLight resolver planned 1517 canonical forms for 1566 requests.",
    )
    assert _capture_progress_line({"stage": "form", "current": 842, "total": 1517}) == (
        ("form", 842, 1517, None),
        "SceneLight resolver form 842/1517",
    )
    assert _capture_progress_line(
        {
            "stage": "form",
            "current": 845,
            "total": 1517,
            "item": "sayori turned e1a b1a",
        }
    ) == (
        ("form", 845, 1517, "sayori turned e1a b1a"),
        "SceneLight resolver form 845/1517: sayori turned e1a b1a",
    )
    assert _capture_progress_line({"stage": "plan", "current": 75, "total": 400}) == (
        ("plan", 75, 400),
        "SceneLight resolver plan 75/400",
    )
    assert _capture_progress_line({"stage": "restore", "current": 1300, "total": 1517}) == (
        ("restore", 1300, 1517),
        "SceneLight restored 1300/1517 completed sprite forms; 217 remain.",
    )
    assert _capture_progress_line({"stage": "checkpoint", "current": 900, "total": 1517}) == (
        ("checkpoint", 900, 1517),
        "SceneLight checkpoint scan 900/1517",
    )


def test_invalid_runtime_checkpoint_is_ignored() -> None:
    assert _capture_progress_line({"stage": "form", "current": 1518, "total": 1517}) is None
    assert _capture_progress_line({"stage": "planned", "current": 0, "total": 1517}) is None


def test_runtime_capture_reports_the_actual_scene_failure(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
        requires_runtime_inventory=True,
    )
    result = CaptureResult(
        scenes={},
        sprites={},
        character_tags=[],
        background_inventory_requested=True,
        scene_requests=15,
        resolved_requests=[],
        errors=[
            "scene bg residential: TypeError: screenshot() takes exactly 2 positional arguments"
        ],
        cached=False,
    )

    try:
        _validate_result(discovery, result)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("an all-scene runtime capture failure must be rejected")

    assert "15 background image declarations" in message
    assert "screenshot() takes exactly 2 positional arguments" in message


def test_preflight_always_requests_renderer_start_without_capturing_art(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    discovery = ProjectDiscovery(
        project_root=project,
        game_root=game,
        scenes={"room": game / "room.png"},
        sprites={},
        character_tags=["nova"],
    )
    observed: list[dict[str, object]] = []
    renderers: list[str | None] = []

    def fake_run(_discovery, _executable, *, request_path, result_path, **_kwargs) -> None:
        observed.append(json.loads(request_path.read_text(encoding="utf-8")))
        renderers.append(_kwargs.get("renderer"))
        result_path.write_text(
            json.dumps(
                {
                    "version": capture_module.CAPTURE_VERSION,
                    "save_directory": "SceneLight-Test-Runtime",
                    "character_tags": ["nova"],
                    "scenes": {},
                    "sprites": {},
                    "resolved_requests": [],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(capture_module, "_run_capture_request", fake_run)

    save_directory = preflight_runtime(
        discovery,
        tmp_path / "Example.exe",
        native_runtime=True,
        renderer="angle",
    )

    assert observed[0]["sprite_names"] == []
    assert observed[0]["inventory_backgrounds"] is False
    assert observed[0]["inventory_characters"] is False
    assert observed[0]["probe_texture_cleanup"] is True
    assert observed[0]["character_selection"] == "automatic"
    assert renderers == ["angle"]
    assert save_directory == "SceneLight-Test-Runtime"


def test_preflight_rejects_engine_that_leaks_textures(tmp_path: Path, monkeypatch) -> None:
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path, game_root=game, scenes={}, sprites={}, character_tags=[]
    )

    def fake_run(_discovery, _executable, *, result_path, **kwargs):
        result_path.write_text(
            json.dumps(
                {
                    "version": capture_module.CAPTURE_VERSION,
                    "texture_cleanup_ok": False,
                    "renpy_version": "Ren'Py 7.8.7",
                }
            )
        )

    monkeypatch.setattr(capture_module, "_run_capture_request", fake_run)
    with pytest.raises(ValueError, match="7.8.7 leaks graphics textures"):
        preflight_runtime(discovery, tmp_path / "renpy.exe")


def test_full_capture_always_uses_runtime_background_inventory(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    scene = game / "known.png"
    Image.new("RGB", (32, 18), (40, 80, 120)).save(scene)
    discovery = ProjectDiscovery(
        project_root=project,
        game_root=game,
        scenes={"known": scene},
        sprites={},
        character_tags=["hero"],
        requires_runtime_inventory=False,
    )
    observed: list[dict[str, object]] = []
    scanned = []
    original_signature = capture_module._capture_content_signature

    def content_signature(discovery):
        scanned.append(discovery)
        return original_signature(discovery)

    monkeypatch.setattr(capture_module, "_capture_content_signature", content_signature)

    def fake_run(_discovery, _executable, *, request_path, result_path, **_kwargs) -> None:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        observed.append(request)
        captured = project / request["output_dir"] / "scene-extra.png"
        captured.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 18), (120, 80, 40)).save(captured)
        result_path.write_text(
            json.dumps(
                {
                    "version": capture_module.CAPTURE_VERSION,
                    "save_directory": "SceneLight-Test-Runtime",
                    "character_tags": ["hero"],
                    "background_inventory_requested": True,
                    "scene_requests": 1,
                    "scenes": {"extra": captured.relative_to(project).as_posix()},
                    "sprites": {},
                    "resolved_requests": [],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(capture_module, "_run_capture_request_resumable", fake_run)

    result = capture_module.capture_runtime_assets(
        discovery,
        tmp_path / "renpy.exe",
        native_runtime=False,
    )

    assert observed[0]["inventory_backgrounds"] is True
    assert result.scenes["extra"].is_file()
    assert scanned == [discovery]
    repeated = capture_module.capture_runtime_assets(discovery, tmp_path / "renpy.exe")
    assert repeated.cached
    assert len(observed) == 1  # No second runtime launch for unchanged input.
    assert scanned == [discovery, discovery]


def test_runtime_review_inventories_candidates_without_full_form_capture(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    discovery = ProjectDiscovery(
        project_root=project,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=["previous_selection"],
        explicit_character_tags=["previous_selection"],
        character_selection="manual",
        requires_runtime_inventory=True,
    )
    observed: list[dict[str, object]] = []

    def fake_run(_discovery, _executable, *, request_path, result_path, **_kwargs) -> None:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        observed.append(request)
        preview = project / request["output_dir"] / "sprite-hero.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 128), (220, 150, 130, 255)).save(preview)
        relative_preview = preview.relative_to(project).as_posix()
        result_path.write_text(
            json.dumps(
                {
                    "version": capture_module.CAPTURE_VERSION,
                    "character_tags": ["hero"],
                    "character_candidates": {"hero": relative_preview, "sticker": None},
                    "background_inventory_requested": False,
                    "scene_requests": 0,
                    "scenes": {},
                    "sprites": {"hero idle": relative_preview},
                    "resolved_requests": [],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(capture_module, "_run_capture_request", fake_run)

    result = capture_runtime_review(
        discovery,
        tmp_path / "Example.exe",
        native_runtime=True,
        renderer="angle",
    )

    assert observed[0]["review_only"] is True
    assert observed[0]["inventory_backgrounds"] is False
    assert observed[0]["inventory_characters"] is True
    assert observed[0]["character_selection"] == "automatic"
    assert observed[0]["explicit_character_tags"] == []
    assert result.character_tags == ["hero"]
    assert result.character_candidates["hero"].is_file()
    assert result.character_candidates["sticker"] is None


def test_runtime_inventory_reads_compiled_scene_statements_without_bg_prefix() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert 'getattr(script, "all_stmts", ())' in helper
    assert 'statement_type == "Scene"' in helper
    assert "else name" in helper


def test_runtime_inventory_limits_forms_to_compiled_story_use() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert "show_names.add(name)" in helper
    assert "isinstance(statement, say_type)" in helper
    assert "script_sprite_sequences" in helper
    assert "story_names_by_tag" in helper
    assert "registered_name in story_names_by_tag[parts[0]]" in helper


def test_runtime_character_inventory_requires_structural_or_character_evidence() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert 'original.__class__.__name__.lower() == "layeredimage"' in helper
    assert "for hint in character_hints:" in helper
    assert "hint in script_show_counts" in helper
    assert "tag not in registered_tags" in helper
    assert "tag in character_hints" in helper
    assert "count > 1 or tag in script_hidden_tags" in helper
    assert "height >= minimum_height" in helper
    assert "width < maximum_width" in helper
    assert "portrait_ratio <= 1.05" in helper
    assert "config.screen_height * 0.35" in helper
    assert "eligible_character_tags = explicit_character_tags & (" in helper
    assert "registered_tags | set(script_show_counts)" in helper
    assert "character_tags - explicit_character_tags - excluded_character_tags" in helper
    assert "character_tags = eligible_character_tags" in helper
    assert "story_tags = set(script_show_counts) | set(script_hidden_tags)" not in helper


def test_runtime_capture_keeps_shared_components_alive_until_the_process_batch_ends() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert "capture_count" not in helper
    assert "gc.collect()" not in helper
    assert "Release the final partial batch" in helper
    assert capture_module.CAPTURE_PROCESS_BATCH_SIZE == 512


def test_runtime_checkpoint_temp_names_do_not_extend_long_sprite_paths() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert "def _scenelight_checkpoint_temporary(marker):" in helper
    assert 'os.path.dirname(marker), ".slcp-%s.tmp" % digest' in helper
    assert 'temporary = marker + ".tmp"' not in helper
    assert "def _scenelight_capture_temporary(filename, purpose, suffix):" in helper
    assert '_scenelight_capture_temporary(filename, "surface", ".png")' in helper
    assert '_scenelight_capture_temporary(filename, "rgba", ".tmp")' in helper
    assert 'temporary = filename + ".surface.png"' not in helper
    assert 'temporary = filename + ".rgba-checkpoint"' not in helper
    assert 'temporary = filename + ".source-copy.%d"' not in helper


def test_host_capture_temp_names_are_compact_and_stay_beside_destination(tmp_path: Path) -> None:
    destination = tmp_path / ("sprite_" + "very_long_form_" * 12 + ".png.surface-normalized")

    temporary = _capture_temporary_path(destination, "marker")

    assert temporary.parent == destination.parent
    assert temporary.name.startswith(".sl-marker-")
    assert len(temporary.name) < 40
    assert len(str(temporary)) < len(str(destination))


def test_parallel_capture_keeps_healthy_renderers_alive() -> None:
    assert capture_module.CAPTURE_PARALLEL_PROCESS_BATCH_SIZE is None


def test_parallel_capture_preserves_ordered_family_locality() -> None:
    forms = ["monika 1", "monika 2", "monika 3", "sayori 1", "sayori 2", "yuri 1"]

    assert _partition_capture_forms(forms, 3) == [
        ["monika 1", "monika 2"],
        ["monika 3", "sayori 1"],
        ["sayori 2", "yuri 1"],
    ]


def test_runtime_capture_uses_exact_surface_fast_path_for_static_composites() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert 'getattr(image_module, "ImageBase", None)' in helper
    assert "isinstance(displayable, image_base)" in helper
    assert "load_surface(displayable)" in helper
    assert "image_save_unscaled(surface, filename)" in helper
    assert 'return "surface"' in helper
    assert '"surface_captures": sorted(surface_captures)' in helper
    assert "_scenelight_export_composite" in helper
    assert '"composite_captures": composite_captures' in helper


def test_dynamic_sprite_capture_preserves_alpha_before_any_gpu_readback() -> None:
    helper = capture_source().read_text(encoding="utf-8")
    capture = Path(capture_module.__file__).read_text(encoding="utf-8")

    assert capture_module.CAPTURE_VERSION == 42
    assert 'preserve_alpha=(kind == "sprite")' in helper
    assert "def _scenelight_save_alpha_surface" in helper
    assert 'getattr(swdraw_module, "SWDraw", None)' in helper
    assert "_scenelight_software_draw = [None]" in helper
    assert "_scenelight_prior_draw = [None]" in helper
    assert "renpy.display.draw = software_draw" in helper
    assert "if renpy.display.draw is not software_draw:" in helper
    switch_path = helper.index("if renpy.display.draw is not software_draw:")
    draw_swap_path = helper.index("renpy.display.draw = software_draw", switch_path)
    assert helper.index("renpy.display.render.free_memory()", switch_path) < draw_swap_path
    assert helper.index("renpy.display.im.free_memory()", switch_path) < draw_swap_path
    assert "if _scenelight_prior_draw[0] is not None:" in helper
    assert 'return "surface-checkpoint"' in helper
    assert 'return "surface-normalized"' in helper
    assert "_scenelight_mark_surface_checkpoint(filename)" in helper
    assert "_scenelight_mark_scene_checkpoint(absolute_filename)" in helper
    assert 'capture_mode = "renderer-checkpoint"' in helper
    alpha_path = helper.index("if preserve_alpha:")
    gpu_path = helper.index('render_to_file = getattr(renpy, "render_to_file", None)', alpha_path)
    assert alpha_path < gpu_path
    assert '"version": 42' in helper
    assert 'environment["PYTHONHASHSEED"] = "0"' in capture
    assert "_scenelight_load_capture_plan" in helper
    assert "_scenelight_save_capture_plan" in helper
    assert "def _scenelight_displayable_signature" in helper
    assert "capture_structures.json" in helper
    assert "_scenelight_pickle.dumps(displayable, protocol=2)" in helper
    assert "A resolved LayeredImage is normally Flatten(Fixed(...))" in helper
    assert "source_name = static_transform_source(child)" in helper
    assert "math.floor(xoffset)" in helper
    assert 'getattr(matrixcolor_type, "__name__", "") == "TintMatrix"' in helper
    assert 'displayable = getattr(displayable, "child", None)' in helper
    assert "SceneLight checkpoint scan" in capture
    assert "SceneLight capture work" in capture
    assert "_scenelight_composite_job_path" in helper
    assert 'capture_mode = "composite-manifest"' in helper
    assert "_merge_composite_capture_jobs" in capture
    assert "materialize_composites=False" in capture
    assert '"defer_composites": True' in capture
    assert "composite_manifest.jsonl" in helper
    assert "capture_forms.jsonl" in helper
    assert "def _scenelight_form_key(name):" in helper
    assert "saved_paths.get(_scenelight_form_key(normalized))" in helper
    assert 'raw_explicit_forms = request.get("explicit_forms")' in helper
    assert 'plan_only_threshold = request.get("plan_only_threshold")' in helper
    assert 'shared_component_value = request.get("component_dir")' in helper
    assert '"copy-%d" % os.getpid()' in helper
    assert "_scenelight_record_deferred_form" in helper
    assert helper.index("_scenelight_displayable_signature(displayable)") < helper.index(
        "capture_mode = _scenelight_render_to_file("
    )
    assert "planned_form_names = {}" in helper
    assert "representative = planned_form_names.get(form_key)" in helper
    assert "planned_forms.add(representative)" in helper
    generic_capture_path = helper.index("def capture(kind, name):")
    assert helper.index('if kind == "sprite":', generic_capture_path) < helper.index(
        "displayable = _scenelight_capture_displayable(name)", generic_capture_path
    )


def test_runtime_capture_rejects_missing_image_placeholders_and_normalizes_scenes() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert "def _scenelight_require_resolved_capture" in helper
    assert "if not displayable.find_target():" in helper
    assert "raise Exception(\"Image '%s' not found.\" % name)" in helper
    assert ").lower()" in helper
    assert 'captures["scenes"].setdefault(scene_key, relative)' in helper


def test_runtime_capture_python_block_compiles() -> None:
    helper = capture_source().read_text(encoding="utf-8")
    marker = "init -999 python:\n"

    assert helper.startswith("# SceneLight raw-asset resolver.")
    python_block = helper.split(marker, 1)[1]
    compile(textwrap.dedent(python_block), str(capture_source()), "exec")


def test_runtime_capture_samples_temporal_background_displayables() -> None:
    helper = capture_source().read_text(encoding="utf-8")

    assert "_scenelight_temporal_displayable" in helper
    assert "sample_count = 160 if _scenelight_temporal_displayable(displayable) else 1" in helper
    assert '"scene_sequences": scene_sequences' in helper


def test_surface_fast_path_is_normalized_to_renderer_alpha_semantics(tmp_path: Path) -> None:
    capture = tmp_path / "captured.png"
    image = Image.new("RGBA", (2, 1))
    image.putdata([(200, 100, 50, 128), (10, 20, 30, 255)])
    image.save(capture)
    marker = capture.with_name(capture.name + ".surface-checkpoint")
    marker.write_text("raw\n", encoding="utf-8")
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": capture.name},
        "surface_captures": [capture.name, capture.name],
    }

    _normalize_surface_captures(tmp_path, payload)

    with Image.open(capture) as normalized:
        assert list(normalized.convert("RGBA").get_flattened_data()) == [
            (100, 50, 25, 64),
            (9, 19, 29, 254),
        ]
    assert not marker.exists()
    assert capture.with_name(capture.name + ".surface-normalized").is_file()


def test_identical_surface_captures_share_one_normalized_source(tmp_path: Path) -> None:
    first = tmp_path / "sprite_a.png"
    second = tmp_path / "sprite_b.png"
    image = Image.new("RGBA", (2, 1), (200, 100, 50, 128))
    image.save(first)
    second.write_bytes(first.read_bytes())
    for path in (first, second):
        path.with_name(path.name + ".surface-checkpoint").write_text("raw\n", encoding="utf-8")
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero a": first.name, "hero b": second.name},
        "surface_captures": [first.name, second.name],
    }

    _normalize_surface_captures(tmp_path, payload)

    sprites = payload["sprites"]
    assert isinstance(sprites, dict)
    assert sprites["hero a"] == sprites["hero b"] == first.name
    assert first.is_file()
    assert not second.exists()
    assert first.with_name(first.name + ".surface-normalized").is_file()
    assert payload["surface_captures"] == []
    assert payload["surface_captures_normalized"] is True


def test_gpu_normalized_captures_are_deduplicated_without_a_second_alpha_pass(
    tmp_path: Path,
) -> None:
    first = tmp_path / "sprite_gpu_a.png"
    second = tmp_path / "sprite_gpu_b.png"
    image = Image.new("RGBA", (1, 1), (100, 50, 25, 64))
    image.save(first)
    second.write_bytes(first.read_bytes())
    for path in (first, second):
        path.with_name(path.name + ".surface-normalized").write_text("renderer\n", encoding="utf-8")
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero a": first.name, "hero b": second.name},
        "normalized_captures": [first.name, second.name],
    }

    _deduplicate_normalized_captures(tmp_path, payload)

    sprites = payload["sprites"]
    assert isinstance(sprites, dict)
    assert sprites["hero a"] == sprites["hero b"] == first.name
    with Image.open(first) as unchanged:
        assert unchanged.getpixel((0, 0)) == (100, 50, 25, 64)
    assert not second.exists()
    assert payload["normalized_captures"] == []
    assert payload["normalized_captures_deduplicated"] is True


def test_raw_rgba_checkpoint_is_normalized_to_the_same_png(tmp_path: Path) -> None:
    capture = tmp_path / "captured.png"
    raw = bytes((200, 100, 50, 128, 10, 20, 30, 255))
    capture.write_bytes(
        b"SCENELIGHT_RGBA1" + struct.pack("<III", 2, 1, len(raw)) + zlib.compress(raw, 1)
    )
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": capture.name},
        "surface_captures": [capture.name],
    }

    _normalize_surface_captures(tmp_path, payload)

    with Image.open(capture) as normalized:
        assert list(normalized.convert("RGBA").get_flattened_data()) == [
            (100, 50, 25, 64),
            (9, 19, 29, 254),
        ]


def test_static_composite_manifest_materializes_exact_renderer_pixels(tmp_path: Path) -> None:
    components = tmp_path / "captured" / "components"
    components.mkdir(parents=True)
    base = components / "base.png"
    overlay = components / "overlay.png"
    base_image = Image.new("RGBA", (2, 1))
    base_image.putdata([(0, 0, 0, 40), (200, 100, 50, 128)])
    base_image.save(base)
    overlay_image = Image.new("RGBA", (2, 1))
    overlay_image.putdata([(129, 37, 76, 236), (10, 20, 30, 255)])
    overlay_image.save(overlay)
    destination = tmp_path / "captured" / "hero.png"
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": "captured/hero.png"},
        "composite_captures": {
            "captured/hero.png": {
                "size": [2, 1],
                "layers": [
                    {"source": "captured/components/base.png", "position": [0, 0]},
                    {"source": "captured/components/overlay.png", "position": [0, 0]},
                ],
            }
        },
    }

    _materialize_composite_captures(tmp_path, payload)

    with Image.open(destination) as materialized:
        assert list(materialized.convert("RGBA").get_flattened_data()) == [
            (111, 31, 65, 223),
            (9, 19, 29, 254),
        ]
    assert payload["composite_captures"] == {}
    assert payload["composite_captures_materialized"] is True
    assert destination.with_name(destination.name + ".composite-normalized").is_file()


def test_static_composite_manifest_cannot_read_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.png"
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(outside)
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": "captured/hero.png"},
        "composite_captures": {
            "captured/hero.png": {
                "size": [1, 1],
                "layers": [{"source": "../outside.png", "position": [0, 0]}],
            }
        },
    }

    with pytest.raises(ValueError, match="escaped the project"):
        _materialize_composite_captures(tmp_path, payload)


def test_static_composite_manifest_cannot_write_outside_project(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(source)
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": "../outside.png"},
        "composite_captures": {
            "../outside.png": {
                "size": [1, 1],
                "layers": [{"source": source.name, "position": [0, 0]}],
            }
        },
    }

    with pytest.raises(ValueError, match="escaped the project"):
        _materialize_composite_captures(tmp_path, payload)


def test_composite_manifest_decodes_without_a_temporary_full_sprite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game = tmp_path / "game"
    components = tmp_path / "captured" / "components"
    components.mkdir(parents=True)
    game.mkdir()
    base = components / "base.png"
    overlay = components / "overlay.png"
    Image.new("RGBA", (2, 2), (100, 120, 140, 255)).save(base)
    Image.new("RGBA", (1, 1), (220, 30, 80, 192)).save(overlay)
    destination = "captured/hero.png"
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {"hero idle": destination, "hero smile": destination},
        "character_candidates": {},
        "character_tags": ["hero"],
        "composite_captures": {
            destination: {
                "size": [2, 2],
                "layers": [
                    {"source": "captured/components/base.png", "position": [0, 0]},
                    {"source": "captured/components/overlay.png", "position": [1, 1]},
                ],
            }
        },
        "resolved_requests": [],
        "errors": [],
    }
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=["hero"],
    )

    validation_calls = 0
    original_validate = capture_module._validated_composite_job

    def counted_validate(*args, **kwargs):
        nonlocal validation_calls
        validation_calls += 1
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(capture_module, "_validated_composite_job", counted_validate)

    assert capture_module._paths_exist(tmp_path, payload)
    result = capture_module._decode_result(discovery, payload, cached=False)
    spec = result.composite_sprites["hero idle"]

    assert not (tmp_path / destination).exists()
    assert spec.canvas_size == (2, 2)
    assert spec.positions == ((0, 0), (1, 1))
    assert spec.renderer_alpha
    assert spec.compose().size == (2, 2)
    assert result.composite_sprites["hero smile"].layers == spec.layers
    assert validation_calls == 1


def test_surface_normalization_ignores_unreported_checkpoints(tmp_path: Path) -> None:
    capture = tmp_path / "unreported.png"
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(capture)
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {},
        "surface_captures": [capture.name],
    }

    _normalize_surface_captures(tmp_path, payload)

    with Image.open(capture) as unchanged:
        assert unchanged.getpixel((0, 0)) == (255, 255, 255, 255)


def test_large_surface_batches_use_disposable_workers(tmp_path: Path, monkeypatch) -> None:
    paths: list[str] = []
    for index in range(9):
        path = tmp_path / f"capture-{index}.png"
        Image.new("RGBA", (1, 1), (80 + index, 60, 40, 200)).save(path)
        paths.append(path.name)
    observed: dict[str, object] = {}

    class ImmediateExecutor:
        def __init__(self, *, max_workers: int) -> None:
            observed["workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def submit(self, function, path):
            from concurrent.futures import Future

            observed.setdefault("paths", []).append(path)
            future = Future()
            try:
                future.set_result(function(path))
            except Exception as error:
                future.set_exception(error)
            return future

    monkeypatch.setattr(capture_module, "ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(capture_module.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(
        capture_module.psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"available": 4 * 1024**3})(),
    )
    payload: dict[str, object] = {
        "scenes": {},
        "sprites": {f"hero {index}": path for index, path in enumerate(paths)},
        "surface_captures": paths,
    }

    _normalize_surface_captures(tmp_path, payload)

    assert observed["workers"] == 4
    assert len(observed["paths"]) == 9
    assert payload["surface_captures_normalized"] is True


def test_surface_normalization_falls_back_to_one_worker_under_memory_pressure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(capture_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        capture_module.psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"available": 580 * 1024**2})(),
    )

    assert _surface_normalization_worker_count(449) == 1


def test_surface_workers_scale_up_and_pipeline_leaves_export_capacity(monkeypatch) -> None:
    monkeypatch.setattr(capture_module.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(
        capture_module.psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"available": 64 * 1024**3})(),
    )
    assert _surface_normalization_worker_count(449) == 16

    monkeypatch.setattr(capture_module.os, "cpu_count", lambda: 4)
    assert _surface_normalization_worker_count(449) == 4
    assert _composite_pipeline_worker_count(449) == 4


def test_merge_capture_rejects_sticker_and_ui_families_but_keeps_characters(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    background = tmp_path / "background.png"
    Image.new("RGB", (1280, 720), (18, 30, 42)).save(background)
    character = tmp_path / "character.png"
    character_image = Image.new("RGBA", (960, 960), (0, 0, 0, 0))
    ImageDraw.Draw(character_image).rectangle((280, 40, 680, 950), fill=(220, 150, 130, 255))
    character_image.save(character)
    sticker = tmp_path / "sticker.png"
    sticker_image = Image.new("RGBA", (122, 173), (0, 0, 0, 0))
    ImageDraw.Draw(sticker_image).ellipse((8, 6, 114, 168), fill=(245, 130, 170, 255))
    sticker_image.save(sticker)
    poem = tmp_path / "poem.png"
    Image.new("RGBA", (800, 720), (245, 245, 240, 255)).save(poem)
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
    )
    capture = CaptureResult(
        scenes={"room": background},
        sprites={
            "hero idle": character,
            "hero_sticker happy": sticker,
            "poem_special one": poem,
        },
        character_tags=["hero", "hero_sticker", "poem_special"],
        background_inventory_requested=True,
        scene_requests=1,
        resolved_requests=[],
        errors=[],
        cached=False,
    )

    merge_capture(discovery, capture)

    assert discovery.character_tags == ["hero"]
    assert list(discovery.sprites) == ["hero idle"]
    assert any("hero_sticker" in item for item in discovery.unsupported)
    assert any("poem_special" in item for item in discovery.unsupported)


def test_merge_capture_records_failed_sprite_as_structured_skip(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=[],
        character_selection="manual",
        explicit_character_tags=["broken"],
    )
    capture = CaptureResult(
        scenes={},
        sprites={},
        character_tags=["broken"],
        background_inventory_requested=False,
        scene_requests=0,
        resolved_requests=[],
        errors=[
            "sprite broken unsupported: RuntimeError: intentional failure",
            "scene room: ValueError: unrelated background failure",
        ],
        cached=False,
    )

    merge_capture(discovery, capture)

    assert discovery.skipped_sprites == [
        {
            "sprite": "broken unsupported",
            "stage": "runtime-capture",
            "error": "RuntimeError: intentional failure",
        }
    ]


def test_merge_capture_preserves_deduplicated_temporal_scene_timeline(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    authored = game / "authored.png"
    frame_zero = game / "frame-zero.png"
    frame_one = game / "frame-one.png"
    for path, color in (
        (authored, (20, 20, 20)),
        (frame_zero, (40, 80, 120)),
        (frame_one, (160, 70, 30)),
    ):
        Image.new("RGB", (32, 18), color).save(path)
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={"room": authored},
        sprites={},
        character_tags=[],
        scene_analysis="cached",
    )
    capture = CaptureResult(
        scenes={"room": frame_zero},
        sprites={},
        character_tags=[],
        background_inventory_requested=True,
        scene_requests=1,
        resolved_requests=[],
        errors=[],
        cached=False,
        scene_sequences={"room": [(0, frame_zero), (125, frame_one), (250, frame_zero)]},
    )

    merge_capture(discovery, capture)

    assert discovery.scenes["room"] == frame_zero
    assert discovery.scenes["room::t00125"] == frame_one
    assert discovery.scene_sequences["room"] == [
        (0, "room"),
        (125, "room::t00125"),
        (250, "room"),
    ]
    assert discovery.summary()["skipped_sprites"] == discovery.skipped_sprites


def test_manual_capture_never_adds_unselected_runtime_families(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    selected = tmp_path / "selected.png"
    other = tmp_path / "other.png"
    for path in (selected, other):
        image = Image.new("RGBA", (960, 960), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((280, 40, 680, 950), fill=(220, 150, 130, 255))
        image.save(path)
    discovery = ProjectDiscovery(
        project_root=tmp_path,
        game_root=game,
        scenes={},
        sprites={},
        character_tags=["hero"],
        explicit_character_tags=["hero"],
        character_selection="manual",
    )
    capture = CaptureResult(
        scenes={},
        sprites={"hero idle": selected, "sticker idle": other},
        character_tags=["hero", "sticker"],
        background_inventory_requested=False,
        scene_requests=0,
        resolved_requests=[],
        errors=[],
        cached=False,
    )

    merge_capture(discovery, capture)

    assert discovery.character_tags == ["hero"]
    assert list(discovery.sprites) == ["hero idle"]


def test_capture_policy_changes_invalidate_plan_but_reuse_unchanged_pixels(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text('image nova idle = "nova.png"\n')
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, ["nova"])
    content = _capture_content_signature(discovery)
    automatic = _project_signature(discovery)
    discovery.excluded_character_tags = ["nova"]
    excluded = _project_signature(discovery)
    discovery.character_selection = "manual"
    frozen = _project_signature(discovery)
    assert len({automatic, excluded, frozen}) == 3
    assert _capture_content_signature(discovery) == content
    (game / "new.rpa").write_bytes(b"new archived character")
    assert _capture_content_signature(discovery) != content


def test_runtime_merge_keeps_explicit_exclusions_and_removes_missing_family(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    sprite = game / "hero.png"
    image = Image.new("RGBA", (400, 720), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((80, 10, 300, 710), fill=(210, 120, 90, 255))
    image.save(sprite)
    discovery = ProjectDiscovery(
        tmp_path,
        game,
        {},
        {},
        ["hero", "removed"],
        explicit_character_tags=["hero", "removed"],
        excluded_character_tags=["blocked"],
    )
    capture = CaptureResult(
        scenes={},
        sprites={"hero idle": sprite, "guest idle": sprite, "blocked idle": sprite},
        character_tags=["hero", "guest", "blocked"],
        background_inventory_requested=True,
        scene_requests=0,
        resolved_requests=[],
        errors=[],
        cached=False,
    )
    merge_capture(discovery, capture)
    assert discovery.character_tags == ["guest", "hero"]
    assert set(discovery.sprites) == {"guest idle", "hero idle"}
    assert discovery.explicit_character_tags == ["hero", "removed"]
