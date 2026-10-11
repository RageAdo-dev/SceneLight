import errno
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from test_developer import _projects

from scenelight import developer
from scenelight.updates import runtime_hashes


def _prepared(project, managed):
    stamps = {}
    record = {
        "source": str(project),
        "source_state": developer._installation_source_state(project),
        "runtime_files": runtime_hashes(managed, verified_out=stamps),
        "runtime_file_stamps": stamps,
    }
    (managed / ".scenelight_install.json").write_text(json.dumps(record))
    return record


def test_consumable_runtime_is_moved_without_copying_maps_and_remains_owned(tmp_path, monkeypatch):
    project, managed = _projects(tmp_path)
    _prepared(project, managed)
    original_map = managed / developer.EMBED_ROOT / "transport_atlas.png"
    identity = original_map.stat().st_ino
    copy = shutil.copy2

    def copying(source, target, **kwargs):
        assert Path(source) != original_map, "The prepared map was copied instead of transferred"
        return copy(source, target, **kwargs)

    monkeypatch.setattr(developer.shutil, "copy2", copying)
    result = developer.embed_from_managed(project, managed, consume_managed=True)
    destination = project / developer.EMBED_ROOT / original_map.name
    assert result["prepared_runtime_transferred"]
    assert not (managed / developer.EMBED_ROOT).exists()
    assert destination.stat().st_ino == identity
    assert developer.developer_status(project).clean
    old = destination.stat()
    destination.write_bytes(b"different")
    os.utime(destination, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert not developer.developer_status(project).clean


def test_other_volume_uses_copy_fallback(tmp_path, monkeypatch):
    project, managed = _projects(tmp_path)
    _prepared(project, managed)
    source = managed / developer.EMBED_ROOT
    real_replace = os.replace

    def replacing(before, after):
        if Path(before) == source:
            raise OSError(errno.EXDEV, "different volume")
        return real_replace(before, after)

    monkeypatch.setattr(developer.os, "replace", replacing)
    result = developer.embed_from_managed(project, managed, consume_managed=True)
    assert not result["prepared_runtime_transferred"] and source.is_dir()
    assert developer.developer_status(project).clean


def test_failed_refresh_restores_both_installed_runtime_and_prepared_data(tmp_path, monkeypatch):
    project, managed = _projects(tmp_path)
    developer.embed_from_managed(project, managed)
    destination = project / developer.EMBED_ROOT
    manifest = project / developer.MANIFEST_NAME
    before = manifest.read_bytes()
    source = managed / developer.EMBED_ROOT / "transport_atlas.png"
    source.write_bytes(b"new prepared map")
    _prepared(project, managed)
    real_replace = os.replace

    def replacing(old, new):
        if Path(old).name == "runtime" and Path(new) == destination:
            raise OSError("swap failed")
        return real_replace(old, new)

    monkeypatch.setattr(developer.os, "replace", replacing)
    with pytest.raises(OSError, match="swap failed"):
        developer.refresh_embedded_from_managed(project, managed, consume_managed=True)
    assert (destination / source.name).read_bytes() == b"transport"
    assert source.read_bytes() == b"new prepared map"
    assert manifest.read_bytes() == before
    assert developer.developer_status(project).clean
    assert not list((project / "game").glob(".sl-*"))


def test_prepared_tampering_is_rejected_even_when_timestamp_is_restored(tmp_path):
    project, managed = _projects(tmp_path)
    _prepared(project, managed)
    path = managed / developer.EMBED_ROOT / "transport_atlas.png"
    before = path.stat()
    path.write_bytes(b"tampering")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(RuntimeError, match="changed after verification"):
        developer.embed_from_managed(project, managed, consume_managed=True)
    assert not (project / developer.EMBED_ROOT).exists()
    assert path.read_bytes() == b"tampering"


def test_hardlinked_prepared_map_is_isolated_by_copy(tmp_path):
    project, managed = _projects(tmp_path)
    map_path = managed / developer.EMBED_ROOT / "transport_atlas.png"
    outside = tmp_path / "cached-map.png"
    os.link(map_path, outside)
    _prepared(project, managed)
    result = developer.embed_from_managed(project, managed, consume_managed=True)
    assert not result["prepared_runtime_transferred"]
    (project / developer.EMBED_ROOT / map_path.name).write_bytes(b"user edit")
    assert outside.read_bytes() == b"transport"


def test_changes_after_analysis_remain_pending_after_install(tmp_path):
    project, managed = _projects(tmp_path)
    record = _prepared(project, managed)
    (project / "game/script.rpy").write_text("label start:\n    pass\n")
    developer.embed_from_managed(project, managed, consume_managed=True)
    manifest = json.loads((project / developer.MANIFEST_NAME).read_text())
    assert manifest["source_state"] == record["source_state"]
    assert developer.developer_status(project).refresh_required
    for name, digest in manifest["files"].items():
        assert digest == hashlib.sha256((project / name).read_bytes()).hexdigest()


@pytest.mark.parametrize("change_manifest", [False, True])
def test_concurrent_edit_during_staging_is_preserved(tmp_path, monkeypatch, change_manifest):
    project, managed = _projects(tmp_path)
    _prepared(project, managed)
    developer.embed_from_managed(project, managed)
    _prepared(project, managed)
    stage_runtime = developer._stage_runtime
    path = project / (
        developer.MANIFEST_NAME if change_manifest else developer.EMBED_ROOT / "transport_atlas.png"
    )
    before = path.stat()
    changed = path.read_bytes() + b"\n" if change_manifest else b"user edit"

    def staging(*args, **kwargs):
        result = stage_runtime(*args, **kwargs)
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return result

    monkeypatch.setattr(developer, "_stage_runtime", staging)
    match = "ownership changed" if change_manifest else "ownership verification"
    with pytest.raises(RuntimeError, match=match):
        developer.refresh_embedded_from_managed(
            project, managed, consume_managed=True, preflight_complete=True
        )
    assert path.read_bytes() == changed
    assert (managed / developer.EMBED_ROOT / "transport_atlas.png").read_bytes() == b"transport"
    assert not list((project / "game").glob(".sl-*"))


def test_missing_prepared_file_is_rejected_and_other_files_returned(tmp_path):
    project, managed = _projects(tmp_path)
    _prepared(project, managed)
    (managed / developer.EMBED_ROOT / "transport_atlas.png").unlink()
    with pytest.raises(RuntimeError, match="files disappeared"):
        developer.embed_from_managed(project, managed, consume_managed=True)
    assert not (project / developer.EMBED_ROOT).exists()
    assert (managed / developer.EMBED_ROOT / "manifest.json").is_file()


@pytest.mark.parametrize("refresh", [False, True])
def test_manifest_write_failure_returns_prepared_files(tmp_path, monkeypatch, refresh):
    project, managed = _projects(tmp_path)
    if refresh:
        developer.embed_from_managed(project, managed)
    manifest = project / developer.MANIFEST_NAME
    before = manifest.read_bytes() if refresh else None
    prepared = managed / developer.EMBED_ROOT / "transport_atlas.png"
    prepared.write_bytes(b"new data")
    _prepared(project, managed)

    def fail(*args, **kwargs):
        raise OSError("cannot write manifest")

    monkeypatch.setattr(developer, "_save_install_manifest", fail)
    publish = developer.refresh_embedded_from_managed if refresh else developer.embed_from_managed
    with pytest.raises(OSError, match="cannot write manifest"):
        publish(project, managed, consume_managed=True)
    assert prepared.read_bytes() == b"new data"
    assert not list((project / "game").glob(".sl-*"))
    if refresh:
        assert manifest.read_bytes() == before
        assert developer.developer_status(project).clean
    else:
        assert not manifest.exists() and not (project / developer.EMBED_ROOT).exists()


def test_consumed_install_and_refresh_preserve_native_launcher_recovery(tmp_path, monkeypatch):
    project, managed = _projects(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "state/projects"))
    compatibility = tmp_path / "renpy7/renpy.exe"
    compatibility.parent.mkdir()
    compatibility.touch()
    record = _prepared(project, managed)
    record.update(playback_native=False, playback_executable=str(compatibility))
    (managed / ".scenelight_install.json").write_text(json.dumps(record))
    assert developer.embed_from_managed(project, managed, consume_managed=True)[
        "prepared_runtime_transferred"
    ]
    first = json.loads((project / developer.MANIFEST_NAME).read_text())
    launcher = project / first["native_launcher"]["executable"]
    backup = project / first["native_launcher"]["original_backup"]
    launcher_bytes = launcher.read_bytes()
    shutil.copytree(project / developer.EMBED_ROOT, managed / developer.EMBED_ROOT)
    (managed / developer.EMBED_ROOT / "transport_atlas.png").write_bytes(b"new map")
    _prepared(project, managed)
    assert developer.refresh_embedded_from_managed(project, managed, consume_managed=True)[
        "prepared_runtime_transferred"
    ]
    assert launcher.read_bytes() == launcher_bytes
    assert backup.read_bytes() == b"original game executable"
    assert developer.developer_status(project).clean
    developer.remove_embedded(project)
    assert launcher.read_bytes() == b"original game executable"


def test_manifest_snapshot_cannot_adopt_a_concurrent_change(tmp_path, monkeypatch):
    project, managed = _projects(tmp_path)
    developer.embed_from_managed(project, managed)
    _prepared(project, managed)
    path = project / developer.MANIFEST_NAME
    changed = path.read_bytes() + b"\n"
    read_manifest = developer._manifest
    calls = []

    def reading(root):
        result = read_manifest(root)
        if not calls:
            path.write_bytes(changed)
        calls.append(root)
        return result

    monkeypatch.setattr(developer, "_manifest", reading)
    with pytest.raises(RuntimeError, match="ownership changed"):
        developer.refresh_embedded_from_managed(
            project, managed, consume_managed=True, preflight_complete=True
        )
    assert path.read_bytes() == changed
    assert (managed / developer.EMBED_ROOT / "transport_atlas.png").is_file()
