from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_project import make_project

import scenelight.cli as cli_module
from scenelight.cli import _capture_without_installed_runtime
from scenelight.sidecar import (
    analysis_cache_root,
    managed_project_root,
    remove_analysis_cache,
    remove_managed_project,
    renpy_runtime_major,
    sync_project,
    visual_sources_changed,
)


def test_source_only_managed_copy_launches_with_recorded_sdk(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "source"
    managed = tmp_path / "managed"
    runtime = tmp_path / "renpy-sdk" / "renpy.exe"
    project.mkdir()
    managed.mkdir()
    runtime.parent.mkdir()
    runtime.write_bytes(b"runtime")
    (managed / ".scenelight_install.json").write_text(
        '{"playback_executable": "'
        + str(runtime).replace("\\", "\\\\")
        + '", "playback_native": false}',
        encoding="utf-8",
    )
    launched: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        launched["command"] = command
        launched.update(kwargs)
        return SimpleNamespace(pid=42)

    monkeypatch.setattr(cli_module, "managed_project_root", lambda _project: managed)
    monkeypatch.setattr(cli_module, "sync_project", lambda _project: object())
    monkeypatch.setattr(cli_module, "visual_sources_changed", lambda _sync: False)
    monkeypatch.setattr(
        cli_module,
        "_verify",
        lambda _project: {"ok": True, "launcher": str(managed / "Launch with SceneLight.bat")},
    )
    monkeypatch.setattr(cli_module, "find_native_executable", lambda _project: None)
    monkeypatch.setattr(cli_module.subprocess, "Popen", fake_popen)

    result = cli_module._launch_managed(project)

    assert launched["command"] == [str(runtime.resolve()), str(managed.resolve()), "run"]
    assert launched["cwd"] == managed
    assert result["playback_native"] is False


def test_runtime_recapture_suspends_wrapper_and_restores_it_on_failure(tmp_path: Path) -> None:
    game = tmp_path / "managed" / "game"
    cache = game / "cache"
    cache.mkdir(parents=True)
    runtime = game / "scenelight_runtime.rpy"
    bytecode = game / "scenelight_runtime.rpyc"
    runtime_directory = game / "scenelight_runtime"
    runtime_directory.mkdir()
    bootstrap = runtime_directory / "bootstrap.rpy"
    runtime.write_text("runtime source", encoding="utf-8")
    bytecode.write_bytes(b"runtime bytecode")
    bootstrap.write_text("directory runtime", encoding="utf-8")
    (cache / "bytecode-27.rpyb").write_bytes(b"compiled scripts")
    unrelated = cache / "keep.txt"
    unrelated.write_text("unrelated", encoding="utf-8")

    with pytest.raises(RuntimeError, match="intentional capture failure"):
        with _capture_without_installed_runtime(game):
            assert not runtime.exists()
            assert not bytecode.exists()
            assert not runtime_directory.exists()
            assert not (cache / "bytecode-27.rpyb").exists()
            (game / "scenelight_capture.rpy").write_text("helper", encoding="utf-8")
            (game / "scenelight_capture.rpyc").write_bytes(b"helper bytecode")
            (cache / "screens.rpyb").write_bytes(b"helper cache")
            raise RuntimeError("intentional capture failure")

    assert runtime.read_text(encoding="utf-8") == "runtime source"
    assert bytecode.read_bytes() == b"runtime bytecode"
    assert bootstrap.read_text(encoding="utf-8") == "directory runtime"
    assert not (game / "scenelight_capture.rpy").exists()
    assert not (game / "scenelight_capture.rpyc").exists()
    assert not list(cache.glob("*.rpyb"))
    assert unrelated.read_text(encoding="utf-8") == "unrelated"


def test_killed_capture_recovery_preserves_conflicting_reseeded_files(tmp_path: Path):
    from scenelight.cli import _restore_suspended_runtime

    game = tmp_path / "game"
    suspended = tmp_path / ".scenelight_cache/suspended-runtime/scenelight_runtime"
    suspended.mkdir(parents=True)
    (suspended / "manifest.json").write_text("known prior runtime")
    reseeded = game / "scenelight_runtime"
    reseeded.mkdir(parents=True)
    (reseeded / "sprite_form_manifest.json").write_text("reseeded during retry")
    _restore_suspended_runtime(game)
    assert (reseeded / "manifest.json").read_text() == "known prior runtime"
    preserved = list(
        (tmp_path / ".scenelight_cache/recovered-runtime-conflicts").glob(
            "*/scenelight_runtime/sprite_form_manifest.json"
        )
    )
    assert len(preserved) == 1
    assert preserved[0].read_text() == "reseeded during retry"
    # Retrying recovery is idempotent; nothing else gets moved.
    _restore_suspended_runtime(game)
    assert (reseeded / "manifest.json").read_text() == "known prior runtime"


def test_runtime_major_detects_renpy_6_7_and_8_layouts(tmp_path: Path) -> None:
    renpy6 = tmp_path / "renpy6"
    renpy7 = tmp_path / "renpy7"
    renpy8 = tmp_path / "renpy8"
    for root in (renpy6, renpy7, renpy8):
        (root / "renpy").mkdir(parents=True)
        (root / "game.exe").touch()
    (renpy6 / "renpy" / "__init__.py").write_text(
        "version_tuple = (6, 99, 12, 4, 'test')\n", encoding="utf-8"
    )
    (renpy7 / "renpy" / "__init__.py").write_text(
        "version_tuple = (7, 5, 3, 'test')\n", encoding="utf-8"
    )
    (renpy8 / "renpy" / "vc_version.py").write_text(
        "version = '8.5.2.26010301'\n", encoding="utf-8"
    )

    assert renpy_runtime_major(renpy6 / "game.exe") == 6
    assert renpy_runtime_major(renpy7) == 7
    assert renpy_runtime_major(renpy8 / "game.exe") == 8
    assert renpy_runtime_major(tmp_path / "unknown") is None
    (renpy7 / "renpy" / "vc_version.py").write_text(
        "version = u'7.7.1.24030407'\n", encoding="utf-8"
    )
    (renpy7 / "renpy" / "__init__.py").write_text(
        "from renpy.vc_version import version\n", encoding="utf-8"
    )
    assert renpy_runtime_major(renpy7) == 7


def test_sidecar_sync_never_writes_into_selected_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    source_script = project / "game" / "script.rpy"
    before = source_script.read_bytes()

    first = sync_project(project)
    managed_script = managed_project_root(project) / "game" / "script.rpy"
    assert first.changed
    assert managed_script.read_bytes() == before

    managed_script.write_text("corrupted managed copy", encoding="utf-8")
    second = sync_project(project)
    assert managed_script.read_bytes() == before
    assert source_script.read_bytes() == before
    assert "game/script.rpy" in second.copied


def test_sidecar_sync_reports_bounded_file_progress(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    updates: list[tuple[int, int, str]] = []

    result = sync_project(
        project, progress=lambda current, total, item: updates.append((current, total, item))
    )

    assert result.changed
    assert updates[0][0] == 0
    assert updates[0][1] > 0
    assert updates[-1][0] == updates[-1][1]
    assert updates[-1][2]


def test_sidecar_sync_tracks_live_mod_edits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    sync_project(project)
    new_background = project / "game" / "new-background.png"
    new_background.write_bytes(b"new image")

    result = sync_project(project)

    assert visual_sources_changed(result)
    assert (result.managed / "game" / "new-background.png").read_bytes() == b"new image"


def test_compiled_script_change_triggers_visual_rebuild(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    sync_project(project)
    compiled_script = project / "game" / "dynamic-images.rpyc"
    compiled_script.write_bytes(b"compiled image declarations")

    result = sync_project(project)

    assert visual_sources_changed(result)


def test_project_lighting_config_change_triggers_visual_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    sync_project(project)
    (project / "scenelight.json").write_text('{"strength":0.72}', encoding="utf-8")

    result = sync_project(project)

    assert visual_sources_changed(result)


def test_legacy_scenelight_files_are_not_imported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    (project / "game" / "scenelight_runtime.rpy").write_text("legacy", encoding="utf-8")
    (project / "game" / "scenelight_runtime").mkdir()
    (project / "game" / "scenelight_runtime" / "legacy.bin").write_bytes(b"legacy")

    result = sync_project(project)

    assert not (result.managed / "game" / "scenelight_runtime.rpy").exists()
    assert not (result.managed / "game" / "scenelight_runtime" / "legacy.bin").exists()


def test_removing_sidecar_does_not_remove_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    result = sync_project(project)

    assert remove_managed_project(project)
    assert not result.managed.exists()
    assert (project / "game" / "script.rpy").is_file()


def test_removing_analysis_cache_targets_only_selected_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    other = make_project(tmp_path / "other-project")
    cache = analysis_cache_root(project)
    other_cache = analysis_cache_root(other)
    cache.mkdir(parents=True)
    other_cache.mkdir(parents=True)
    (cache / "capture.json").write_text("cached", encoding="utf-8")
    (other_cache / "capture.json").write_text("other", encoding="utf-8")

    assert remove_analysis_cache(project)
    assert not cache.exists()
    assert other_cache.is_dir()
    assert (project / "game" / "script.rpy").is_file()


def test_removing_sidecar_retries_a_transient_windows_process_handle(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    result = sync_project(project)
    real_rmtree = __import__("shutil").rmtree
    locked = PermissionError("directory is still in use")
    locked.winerror = 32  # type: ignore[attr-defined]
    attempts = Mock(side_effect=[locked, None])
    monkeypatch.setattr("scenelight.sidecar.shutil.rmtree", attempts)
    monkeypatch.setattr("scenelight.sidecar.time.sleep", lambda _delay: None)

    assert remove_managed_project(project)
    assert attempts.call_count == 2

    # The mock's successful second call represents Windows releasing the
    # handle. Remove the fixture with the real function for this test process.
    real_rmtree(result.managed)
    assert (project / "game" / "script.rpy").is_file()


def test_managed_runtime_saves_and_cache_survive_source_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    result = sync_project(project)
    managed_save = result.managed / "game" / "saves" / "slot.save"
    managed_cache = result.managed / "game" / "cache" / "bytecode.rpyb"
    managed_save.parent.mkdir(parents=True)
    managed_cache.parent.mkdir(parents=True)
    managed_save.write_bytes(b"managed save")
    managed_cache.write_bytes(b"native cache")

    sync_project(project)

    assert managed_save.read_bytes() == b"managed save"
    assert managed_cache.read_bytes() == b"native cache"
    assert not (project / "game" / "saves" / "slot.save").exists()


def test_native_runtime_logs_survive_source_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project = make_project(tmp_path / "source-project")
    result = sync_project(project)
    runtime_log = result.managed / "log.txt"
    runtime_traceback = result.managed / "traceback.txt"
    runtime_log.write_text("native log", encoding="utf-8")
    runtime_traceback.write_text("native traceback", encoding="utf-8")

    sync_project(project)

    assert runtime_log.read_text(encoding="utf-8") == "native log"
    assert runtime_traceback.read_text(encoding="utf-8") == "native traceback"
