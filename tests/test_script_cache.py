import pytest

from scenelight.script_cache import preserve_playback_bytecode
from scenelight.sidecar import sync_project


def test_player_sync_keeps_native_statement_ids_but_removes_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text("label start:\n    return\n")
    (game / "logic_ren.py").write_text("# native Python script source")
    managed = sync_project(project).managed
    for name in ("script.rpyc", "logic.rpyc", "orphan.rpyc"):
        (managed / "game" / name).write_bytes(b"native statement identities")
    (game / "script.rpy").write_text("label start:\n    pass\n    return\n")
    sync_project(project)
    assert (managed / "game/script.rpyc").read_bytes() == b"native statement identities"
    assert (managed / "game/logic.rpyc").is_file()
    assert not (managed / "game/orphan.rpyc").exists()
    (game / "script.rpy").unlink()
    sync_project(project)
    assert not (managed / "game/script.rpyc").exists()


@pytest.mark.parametrize("failure", [False, True])
def test_analysis_restores_native_bytecode_and_drops_new_compiler_output(tmp_path, failure):
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text("label start:\n    return\n")
    (game / "other.rpy").write_text("label other:\n    return\n")
    (game / "script.rpyc").write_bytes(b"native IDs")
    (game / "compiled-only.rpyc").write_bytes(b"authored compiled-only script")
    try:
        with preserve_playback_bytecode(game):
            (game / "script.rpyc").write_bytes(b"foreign compiler IDs")
            (game / "other.rpyc").write_bytes(b"new foreign output")
            if failure:
                raise RuntimeError("capture failed")
    except RuntimeError:
        assert failure
    assert (game / "script.rpyc").read_bytes() == b"native IDs"
    assert (game / "compiled-only.rpyc").read_bytes() == b"authored compiled-only script"
    assert not (game / "other.rpyc").exists()
    assert not (tmp_path / ".scenelight_cache/playback-bytecode").exists()


def test_interrupted_analysis_restores_before_next_source_sync(tmp_path, monkeypatch):
    from scenelight import script_cache

    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = tmp_path / "source"
    (project / "game").mkdir(parents=True)
    (project / "game/script.rpy").write_text("label start:\n    return\n")
    managed = sync_project(project).managed
    game = managed / "game"
    compiled = game / "script.rpyc"
    compiled.write_bytes(b"native IDs")
    original_restore = script_cache.restore_playback_bytecode
    with preserve_playback_bytecode(game):
        compiled.write_bytes(b"interrupted foreign output")
        monkeypatch.setattr(script_cache, "restore_playback_bytecode", lambda _: None)
    monkeypatch.setattr(script_cache, "restore_playback_bytecode", original_restore)
    assert (managed / ".scenelight_cache/playback-bytecode/index.json").exists()
    sync_project(project)
    assert compiled.read_bytes() == b"native IDs"


def test_changed_recovery_bytes_are_not_silently_used(tmp_path, monkeypatch):
    from scenelight import script_cache

    game = tmp_path / "game"
    game.mkdir()
    (game / "story.rpy").write_text("label start:\n    return\n")
    (game / "story.rpyc").write_bytes(b"native")
    restore = script_cache.restore_playback_bytecode
    with preserve_playback_bytecode(game):
        monkeypatch.setattr(script_cache, "restore_playback_bytecode", lambda _: None)
    saved = next((tmp_path / ".scenelight_cache/playback-bytecode/files").iterdir())
    saved.write_bytes(b"damaged")
    with pytest.raises(RuntimeError, match="changed"):
        restore(game)
    assert (game / "story.rpyc").read_bytes() == b"native"


def test_code_only_update_also_recovers_pending_playback_bytecode(tmp_path, monkeypatch):
    from test_incremental_updates import installation

    from scenelight import script_cache, updates

    project, root, _record = installation(tmp_path, monkeypatch)
    game = root / "game"
    compiled = game / "story.rpyc"
    compiled.write_bytes(b"native IDs")
    restore = script_cache.restore_playback_bytecode
    with preserve_playback_bytecode(game):
        compiled.write_bytes(b"interrupted analyzer IDs")
        monkeypatch.setattr(script_cache, "restore_playback_bytecode", lambda _: None)
    monkeypatch.setattr(script_cache, "restore_playback_bytecode", restore)
    result = updates.try_runtime_update(project, config=None, grid=(16, 9), embedded=True)
    assert result["sprites_reanalyzed"] == 0
    assert compiled.read_bytes() == b"native IDs"
