import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_incremental_updates import installation

from scenelight import cli, updates
from scenelight.developer import (
    EMBED_ROOT,
    developer_status,
    embed_from_managed,
    refresh_embedded_from_managed,
)
from scenelight.inspector_install import (
    INSPECTOR_CACHE,
    INSPECTOR_FILES,
    inspector_enabled,
    set_inspector_enabled,
)
from scenelight.setup_gui import SceneLightSetup


@pytest.mark.parametrize("embedded", [True, False])
def test_off_on_and_updates_preserve_assets_and_remove_compiled_inspector(
    tmp_path, monkeypatch, embedded
):
    project, root, manifest = installation(tmp_path, monkeypatch, embedded)
    updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=embedded)
    maps = list((root / EMBED_ROOT).glob("map_*.png"))
    before = [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps]
    cache = root / INSPECTOR_CACHE
    cache.write_bytes(b"RenPy compiled inspector")
    monkeypatch.setattr(
        cli, "_install_managed", lambda *a, **k: pytest.fail("Must not rebuild assets")
    )
    choice = "embedded" if embedded else "managed"
    assert (
        cli._main(
            ["inspector", "--project", str(project), "--installation", choice, "--enabled", "off"]
        )
        == 0
    )
    assert not inspector_enabled(project, embedded=embedded)
    assert not any((root / name).exists() for name in (*INSPECTOR_FILES, INSPECTOR_CACHE))
    assert (
        not set(INSPECTOR_FILES)
        & json.loads(manifest.read_text())["files" if embedded else "runtime_files"].keys()
    )
    assert cli._main(["refresh" if embedded else "install", "--project", str(project)]) == 0
    assert not any((root / name).exists() for name in INSPECTOR_FILES)
    assert (
        cli._main(
            ["inspector", "--project", str(project), "--installation", choice, "--enabled", "on"]
        )
        == 0
    )
    assert inspector_enabled(project, embedded=embedded)
    assert all((root / name).is_file() for name in INSPECTOR_FILES)
    assert [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps] == before
    if embedded:
        assert developer_status(project).clean


@pytest.mark.parametrize("embedded", [True, False])
def test_failed_inspector_removal_restores_source_compiled_cache_and_record(
    tmp_path, monkeypatch, embedded
):
    project, root, manifest = installation(tmp_path, monkeypatch, embedded)
    cache = root / INSPECTOR_CACHE
    cache.write_bytes(b"compiled inspector")
    before = {name: (root / name).read_bytes() for name in (*INSPECTOR_FILES, INSPECTOR_CACHE)}
    record = manifest.read_bytes()
    replace = updates.os.replace

    def fail_commit(source, destination):
        if Path(source).name == "next-record.json":
            raise OSError("test commit failed")
        return replace(source, destination)

    monkeypatch.setattr(updates.os, "replace", fail_commit)
    with pytest.raises(OSError, match="commit failed"):
        set_inspector_enabled(project, False, embedded=embedded)
    assert {name: (root / name).read_bytes() for name in before} == before
    assert manifest.read_bytes() == record
    assert not (root / updates.JOURNAL).exists()


def test_modified_inspector_is_not_deleted(tmp_path, monkeypatch):
    project, root, manifest = installation(tmp_path, monkeypatch)
    path = root / INSPECTOR_FILES[0]
    path.write_text("author's changes")
    record = manifest.read_bytes()
    with pytest.raises(RuntimeError, match="edited"):
        set_inspector_enabled(project, False, embedded=True)
    assert path.read_text() == "author's changes"
    assert manifest.read_bytes() == record


def test_fresh_project_option_is_external_and_installer_omits_inspector(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = tmp_path / "project"
    (project / "game").mkdir(parents=True)
    result = set_inspector_enabled(project, False, embedded=True)
    assert result["installed"] is False
    assert not inspector_enabled(project, embedded=True)
    assert not inspector_enabled(project, embedded=False)
    assert list((project / "game").iterdir()) == []
    staging = tmp_path / "staging/game"
    cli._install_runtime_files(staging, inspector=inspector_enabled(project, embedded=True))
    assert not (staging / "scenelight_runtime/inspector.rpy").exists()
    assert not (staging / "scenelight_runtime/inspector.txt").exists()
    assert (staging / "scenelight_runtime.rpy").is_file()


def test_embedding_and_full_refresh_keep_disabled_choice(tmp_path, monkeypatch):
    project, managed, manifest = installation(tmp_path, monkeypatch, embedded=False)
    updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=False)
    set_inspector_enabled(project, False, embedded=False)
    embed_from_managed(project, managed)
    assert inspector_enabled(project, embedded=True) is False
    assert not any((project / name).exists() for name in INSPECTOR_FILES)
    refresh_embedded_from_managed(project, managed)
    assert inspector_enabled(project, embedded=True) is False
    assert developer_status(project).clean


def test_setup_apply_uses_inspector_operation_and_explicit_installation(tmp_path):
    operations = []
    app = SimpleNamespace(
        _running=False,
        _project_checking=False,
        _inspector_selection_key=(tmp_path, False),
        inspector_var=SimpleNamespace(get=lambda: False),
        _command=lambda operation: [
            "python",
            "-m",
            "scenelight.cli",
            operation,
            "--project",
            str(tmp_path),
        ],
        _start_operation=lambda *args: operations.append(args),
    )
    SceneLightSetup._apply_inspector_option(app)
    assert operations[0][0] == "inspector"
    assert operations[0][1][-4:] == ["--enabled", "off", "--installation", "managed"]
    app._running = True
    SceneLightSetup._apply_inspector_option(app)
    assert len(operations) == 1


def test_inspector_option_can_load_before_analysis_dependencies_are_installed():
    import scenelight

    source = str(Path(scenelight.__file__).resolve().parent.parent)
    code = """
import importlib.abc, sys
class BlockAnalysis(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'PIL', 'cv2', 'PySide6'}:
            raise ImportError('Setup must not load analysis libraries: ' + fullname)
sys.meta_path.insert(0, BlockAnalysis())
sys.path.insert(0, sys.argv[1])
from scenelight.inspector_install import inspector_enabled
"""
    result = subprocess.run(
        [sys.executable, "-c", code, source], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
