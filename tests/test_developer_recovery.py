import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scenelight import developer as dev
from scenelight import developer_transaction as transaction


@pytest.fixture
def project_pair(tmp_path, monkeypatch):
    for name in ("LOCALAPPDATA", "APPDATA", "SCENELIGHT_MANAGED_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / name))
    project, managed = tmp_path / "project", tmp_path / "managed"
    (project / "game" / "saves").mkdir(parents=True)
    (project / "game" / "saves" / "persistent").write_bytes(b"player progress")
    (project / "game" / "script.rpy").write_text("label start:\n    return\n")
    (project / "game" / "original.png").write_bytes(b"authored asset")
    (project / "Game.exe").write_bytes(b"original executable")
    (managed / dev.EMBED_ROOT).mkdir(parents=True)
    (managed / "game" / "scenelight_runtime.rpy").write_text("init python:\n    pass\n")
    (managed / dev.EMBED_ROOT / "manifest.json").write_text('{"version": 5}')
    (managed / dev.EMBED_ROOT / "map.png").write_bytes(b"old maps")
    compatibility = tmp_path / "compatibility.exe"
    compatibility.write_bytes(b"test runtime")
    (managed / ".scenelight_install.json").write_text(
        json.dumps(
            {
                "playback_native": False,
                "playback_executable": str(compatibility),
            }
        )
    )
    return project, managed


CRASH_SCRIPT = r"""
import os, sys
from pathlib import Path
from scenelight import developer as dev
from scenelight import developer_transaction as tx
project, managed = map(Path, sys.argv[1:3])
operation, checkpoint, when = sys.argv[3:]
replace = os.replace
atomic = dev._atomic_json
cleanup = tx._cleanup
def stop(name, moment):
    if name == checkpoint and moment == when:
        os._exit(79)
def replace_checked(source, destination):
    source, destination = Path(source), Path(destination)
    name = None
    if destination == project / tx.JOURNAL:
        name = "journal"
    elif source == project / dev.EMBED_ROOT and destination.name == "previous":
        name = "backup"
    elif source.name == "runtime" and destination == project / dev.EMBED_ROOT:
        name = "runtime"
    elif destination == project / "Game.exe":
        name = "launcher"
    elif destination == project / dev.MANIFEST_NAME or destination.name == "removed-record.json":
        name = "manifest"
    stop(name, "before")
    replace(source, destination)
    stop(name, "after")
def atomic_checked(path, payload):
    if path == project / tx.JOURNAL and payload.get("state") == "committed":
        stop("commit", "before")
        atomic(path, payload)
        stop("commit", "after")
    else:
        atomic(path, payload)
def cleanup_checked(*args, **kwargs):
    stop("cleanup", "before")
    cleanup(*args, **kwargs)
    stop("cleanup", "after")
os.replace = replace_checked
dev._atomic_json = atomic_checked
tx._cleanup = cleanup_checked
if operation == "embed":
    dev.embed_from_managed(project, managed)
elif operation == "refresh":
    dev.refresh_embedded_from_managed(project, managed)
else:
    dev.remove_embedded(project)
raise AssertionError("Checkpoint was not reached")
"""


CHECKPOINTS = {
    "embed": ("journal", "runtime", "launcher", "manifest", "commit", "cleanup"),
    "refresh": ("journal", "backup", "runtime", "manifest", "commit", "cleanup"),
    "remove": ("journal", "backup", "launcher", "manifest", "commit", "cleanup"),
}


def interrupt(project, managed, operation, checkpoint, when):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASH_SCRIPT,
            str(project),
            str(managed),
            operation,
            checkpoint,
            when,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 79, result.stdout + result.stderr


def assert_authored_files(project):
    assert (project / "game" / "original.png").read_bytes() == b"authored asset"
    assert (project / "game" / "script.rpy").read_text() == "label start:\n    return\n"
    assert (project / "game" / "saves" / "persistent").read_bytes() == b"player progress"


@pytest.mark.parametrize(
    "operation,checkpoint",
    [(operation, checkpoint) for operation, points in CHECKPOINTS.items() for checkpoint in points],
)
@pytest.mark.parametrize("when", ["before", "after"])
def test_real_process_death_recovers_each_publication_boundary(
    project_pair, operation, checkpoint, when
):
    project, managed = project_pair
    if operation != "embed":
        dev.embed_from_managed(project, managed)
        (project / dev.EMBED_ROOT / "bootstrap.rpyc").write_bytes(b"compiled runtime")
    (managed / dev.EMBED_ROOT / "map.png").write_bytes(b"new maps")
    interrupt(project, managed, operation, checkpoint, when)
    transaction.recover(project)
    assert transaction.recover(project) is None
    status = dev.developer_status(project)
    committed = checkpoint in {"commit", "cleanup"} or (
        checkpoint == "manifest" and when == "after"
    )
    expected_installed = (
        committed if operation == "embed" else not committed if operation == "remove" else True
    )
    assert status.installed == expected_installed
    assert status.clean
    assert_authored_files(project)
    if status.installed:
        expected_maps = b"new maps" if committed or operation == "embed" else b"old maps"
        assert (project / dev.EMBED_ROOT / "map.png").read_bytes() == expected_maps
        dev.remove_embedded(project)
    assert (project / "Game.exe").read_bytes() == b"original executable"
    assert not (project / transaction.JOURNAL).exists()


def test_public_unembed_command_recovers_before_ownership_checks(project_pair):
    project, managed = project_pair
    dev.embed_from_managed(project, managed)
    (managed / dev.EMBED_ROOT / "map.png").write_bytes(b"new maps")
    interrupt(project, managed, "refresh", "runtime", "after")
    result = subprocess.run(
        [sys.executable, "-m", "scenelight", "unembed", "--project", str(project)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (project / dev.EMBED_ROOT).exists()
    assert (project / "Game.exe").read_bytes() == b"original executable"
    assert_authored_files(project)


def test_partial_cleanup_after_remove_is_retryable(project_pair, monkeypatch):
    project, managed = project_pair
    dev.embed_from_managed(project, managed)
    rmtree = transaction.shutil.rmtree

    def partial_failure(path, *args, **kwargs):
        path = Path(path)
        if path.name.startswith(".sl-"):
            (path / "previous" / "map.png").unlink()
            raise PermissionError("locked cleanup file")
        return rmtree(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(transaction.shutil, "rmtree", partial_failure)
        result = dev.remove_embedded(project)
    assert result["removed"]
    assert "locked cleanup file" in result["cleanup_warning"]
    assert (project / transaction.JOURNAL).exists()
    assert dev.remove_embedded(project)["reason"] == "not installed"
    assert not (project / transaction.JOURNAL).exists()
    assert not list((project / "game").glob(".sl-*"))
    assert (project / "Game.exe").read_bytes() == b"original executable"
    assert_authored_files(project)


def test_recovery_refuses_post_crash_edits_without_discarding_backup(project_pair):
    project, managed = project_pair
    dev.embed_from_managed(project, managed)
    (managed / dev.EMBED_ROOT / "map.png").write_bytes(b"new maps")
    interrupt(project, managed, "refresh", "runtime", "after")
    changed = project / dev.EMBED_ROOT / "map.png"
    changed.write_bytes(b"manual edit after interruption")
    with pytest.raises(RuntimeError, match="changed"):
        transaction.recover(project)
    assert changed.read_bytes() == b"manual edit after interruption"
    assert list((project / "game").glob(".sl-*/previous/map.png"))[0].read_bytes() == b"old maps"
    assert_authored_files(project)


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing integration")
def test_locked_native_launcher_rolls_back_and_removal_can_be_retried(project_pair):
    project, managed = project_pair
    dev.embed_from_managed(project, managed)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(project / "Game.exe"), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(PermissionError):
            dev.remove_embedded(project)
        assert dev.developer_status(project).clean
    finally:
        kernel.CloseHandle(handle)
    assert dev.remove_embedded(project)["removed"]
    assert (project / "Game.exe").read_bytes() == b"original executable"
    assert_authored_files(project)
