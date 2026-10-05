import json
import os
from pathlib import Path

import numpy as np
import pytest

from scenelight import builder, cli, updates
from scenelight.developer import EMBED_ROOT, MANIFEST_NAME, _tracked_source_state
from scenelight.release import release_record
from scenelight.sidecar import managed_project_root


def installation(tmp_path, monkeypatch, embedded=True, count=2):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = tmp_path / "mod"
    (project / "game").mkdir(parents=True)
    (project / "game/story.rpy").write_text("label start:\n    return\n")
    root = project if embedded else managed_project_root(project)
    data = root / EMBED_ROOT
    data.mkdir(parents=True)
    (data / "manifest.json").write_text(
        json.dumps({"transport_atlas": {"grid_size": [16, 9]}, "scenes": {}})
    )
    (data / "install_report.json").write_text(
        json.dumps({"scene_count": 1000, "sprite_count": count})
    )
    for i in range(count):
        (data / ("map_%s.png" % i)).write_bytes(b"exact existing map")
    for relative, source in updates.runtime_payload(embedded=embedded).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes() + b"\n# older compatible runtime\n")
    record = {
        "version": 3 if embedded else 1,
        "release": release_record(),
        "namespace": EMBED_ROOT.as_posix(),
        "source_state": _tracked_source_state(project),
        "config": None,
        "config_sha256": None,
    }
    hashes = updates.runtime_hashes(root)
    record["files" if embedded else "runtime_files"] = hashes
    path = root / (MANIFEST_NAME if embedded else ".scenelight_install.json")
    path.write_text(json.dumps(record))
    return project, root, path


@pytest.mark.parametrize("embedded", [True, False])
def test_code_update_skips_capture_build_and_preserves_maps(tmp_path, monkeypatch, embedded):
    project, root, record = installation(tmp_path, monkeypatch, embedded)
    maps = list((root / EMBED_ROOT).glob("map_*.png"))
    before = [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps]
    monkeypatch.setattr(cli, "_install_managed", lambda *a, **k: pytest.fail("No full install"))
    assert cli._main(["refresh" if embedded else "install", "--project", str(project)]) == 0
    assert [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in maps] == before
    assert json.loads(record.read_text())["last_update"]["mode"] == "runtime-only"
    result = updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=embedded)
    assert result["update_mode"] == "unchanged"
    assert result["sprites_reanalyzed"] == result["backgrounds_reanalyzed"] == 0


@pytest.mark.parametrize(
    "change", ["bytes", "new", "python", "data", "removed", "contract", "config", "grid"]
)
def test_fast_update_never_reuses_changed_inputs(tmp_path, monkeypatch, change):
    project, root, record = installation(tmp_path, monkeypatch)
    source = project / "game/story.rpy"
    config = None
    grid = (16, 9)
    if change == "bytes":
        stamp = source.stat()
        source.write_text(source.read_text().replace("return", "pass  "))
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == "new":
        (project / "game/new.png").write_bytes(b"new asset")
    elif change in {"python", "data"}:
        (project / "game" / ("registry.py" if change == "python" else "registry.json")).write_text(
            "{}"
        )
    elif change == "removed":
        source.unlink()
    elif change == "contract":
        state = json.loads(record.read_text())
        state["release"]["sprite_form_version"] = -1
        record.write_text(json.dumps(state))
    elif change == "config":
        config = project / "profile.json"
        config.write_text('{"strength": 0.5}')
    else:
        grid = (32, 18)
    assert updates.try_runtime_update(project, config=config, grid=grid, embedded=True) is None


def test_owned_modification_is_not_overwritten(tmp_path, monkeypatch):
    project, root, record = installation(tmp_path, monkeypatch)
    target = root / EMBED_ROOT / "bootstrap.rpy"
    target.write_bytes(b"user changed this")
    with pytest.raises(RuntimeError, match="refused"):
        updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=True)
    assert target.read_bytes() == b"user changed this"


def test_parallel_updates_refuse_same_project_but_allow_another(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    with updates.operation_lock(tmp_path / "a"):
        with pytest.raises(RuntimeError, match="already"):
            with updates.operation_lock(tmp_path / "a"):
                pytest.fail("second writer acquired lock")
        with updates.operation_lock(tmp_path / "b"):
            pass


@pytest.mark.parametrize("embedded", [True, False])
def test_failed_commit_restores_runtime_and_record(tmp_path, monkeypatch, embedded):
    project, root, record = installation(tmp_path, monkeypatch, embedded)
    original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    replace = os.replace

    def fail_commit(src, dst):
        if Path(src).name == "next-record.json":
            raise OSError("simulated disk failure")
        return replace(src, dst)

    monkeypatch.setattr(updates.os, "replace", fail_commit)
    with pytest.raises(OSError, match="disk failure"):
        updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=embedded)
    for path, expected in original.items():
        assert (root / path).read_bytes() == expected
    assert not (root / updates.JOURNAL).exists()


def test_interrupted_update_and_interrupted_recovery_can_resume(tmp_path, monkeypatch):
    project, root, record = installation(tmp_path, monkeypatch)
    before = {name: (root / name).read_bytes() for name in updates.runtime_payload(embedded=True)}
    replace = os.replace
    recover = updates.recover_update

    def fail_commit(src, dst):
        if Path(src).name == "next-record.json":
            raise OSError("power loss before commit")
        return replace(src, dst)

    def interrupted_recovery(path):
        if (path / updates.JOURNAL).exists():
            raise InterruptedError("process stopped before recovery")

    monkeypatch.setattr(updates.os, "replace", fail_commit)
    monkeypatch.setattr(updates, "recover_update", interrupted_recovery)
    with pytest.raises(InterruptedError):
        updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=True)
    assert (root / updates.JOURNAL).exists()
    restored = []

    def fail_once_in_recovery(src, dst):
        if "previous" in Path(src).parts:
            if restored:
                raise OSError("second interruption")
            restored.append(str(src))
        return replace(src, dst)

    monkeypatch.setattr(updates.os, "replace", fail_once_in_recovery)
    with pytest.raises(OSError, match="second interruption"):
        recover(root)
    monkeypatch.setattr(updates.os, "replace", replace)
    recover(root)
    assert not (root / updates.JOURNAL).exists()
    assert all((root / name).read_bytes() == contents for name, contents in before.items())


def test_background_cache_reuses_exact_pixels_and_recovers_corruption(tmp_path, monkeypatch):
    source = tmp_path / "bg.png"
    source.write_bytes(b"source A")
    calls = []
    arrays = (np.zeros((90, 160, 4), dtype=np.uint8), np.ones((90, 160, 4), dtype=np.uint8))
    wrap = np.full((90, 160, 3), 22, dtype=np.uint8)
    monkeypatch.setattr(
        builder, "_scene_maps", lambda p: calls.append(p) or (*arrays, {"energy": 0.3})
    )
    monkeypatch.setattr(builder, "_wrap_map", lambda p: wrap)
    key = builder._transport_cache_path(tmp_path, "room", source, (16, 9))
    first = builder._cached_scene_fields(source, key)
    second = builder._cached_scene_fields(source, key)
    assert len(calls) == 1 and not first[-1] and second[-1]
    for a, b in zip(first[:3], second[:3], strict=True):
        np.testing.assert_array_equal(a, b)
    assert first[3] == second[3]
    source.write_bytes(b"source B")
    new_key = builder._transport_cache_path(tmp_path, "room", source, (16, 9))
    assert new_key != key and not builder._cached_scene_fields(source, new_key)[-1]
    key.with_name(key.stem + "_fields_v1.npz").write_bytes(b"broken")
    assert not builder._cached_scene_fields(source, key)[-1]
