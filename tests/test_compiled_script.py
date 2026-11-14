import hashlib
import json
import pickle
import struct
import sys
import types
import zlib

import pytest

from scenelight.capture_reuse import record_pixels, verified_pixels
from scenelight.compiled_script import compiled_fingerprint
from scenelight.developer import _tracked_source_state


@pytest.fixture
def compile_slot(monkeypatch):
    renpy = types.ModuleType("renpy")
    renpy.ast = types.ModuleType("renpy.ast")
    monkeypatch.setitem(sys.modules, "renpy", renpy)
    monkeypatch.setitem(sys.modules, "renpy.ast", renpy.ast)
    renpy.ast.Image = type(
        "Image",
        (),
        {"__module__": "renpy.ast", "__slots__": ("name", "filename", "code", "priority")},
    )
    renpy.ast.PyCode = type(
        "PyCode", (), {"__module__": "renpy.ast", "__getstate__": lambda self: self.state}
    )

    def slot(stamp, *, image="room.png", priority=100, shared=False):
        node = renpy.ast.Image()
        node.filename = "game/rooms.rpy"
        node.name = (node.filename, stamp, stamp % 257)
        node.code = renpy.ast.PyCode()
        node.code.state = (1, image, (node.filename, 10, stamp), "eval", 3)
        node.priority = priority
        return pickle.dumps([node, node.name] if shared else [node], protocol=2)

    return slot


def test_regenerated_screen_keeps_its_identity_but_tracks_property_edits(tmp_path, monkeypatch):
    renpy = types.ModuleType("renpy")
    sl2 = renpy.sl2 = types.ModuleType("renpy.sl2")
    slast = sl2.slast = types.ModuleType("renpy.sl2.slast")
    for mod in (renpy, sl2, slast):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
    slast.SLScreen = type("SLScreen", (), {"__module__": slast.__name__})
    node = slast.SLScreen()
    node.location = ("game/ui.rpy", 12)
    node.serial = 1794033275346424
    node.priority = 12
    path = tmp_path / "ui.rpyc"
    first = pickle.dumps([node], protocol=2)
    old = write_rpc2(path, first, first)
    node.serial += 60000000
    second = pickle.dumps([node], protocol=2)
    assert old and write_rpc2(path, second, second) == old
    node.priority += 1
    changed = pickle.dumps([node], protocol=2)
    assert write_rpc2(path, second, changed) != old


def test_update_scan_detects_bytecode_only_edits_with_matching_source_footer(
    tmp_path, compile_slot
):
    game = tmp_path / "game"
    game.mkdir()
    source = b'image bg room = "room.png"'
    (game / "rooms.rpy").write_bytes(source)
    path = game / "rooms.rpyc"

    def scan(slot):
        write_rpc2(path, slot, slot)
        with path.open("r+b") as stream:
            stream.seek(-16, 2)
            stream.write(hashlib.md5(source, usedforsecurity=False).digest())
        return _tracked_source_state(tmp_path)

    old = scan(compile_slot(1700000000))
    assert scan(compile_slot(1700001222)) == old
    edited = scan(compile_slot(1700000000, image="forest.png"))
    assert edited["game/rooms.rpy"] == old["game/rooms.rpy"]
    assert edited["game/rooms.rpyc"] != old["game/rooms.rpyc"]


def test_playtest_creating_first_bytecode_matches_setup_compilation(
    tmp_path, monkeypatch, compile_slot
):
    game, cache = tmp_path / "game", tmp_path / "analysis"
    game.mkdir()
    cache.mkdir()
    monkeypatch.setattr("scenelight.developer.analysis_cache_root", lambda _: cache)
    source = b'image bg room = "room.png"'
    path = game / "rooms.rpyc"
    (game / "rooms.rpy").write_bytes(source)
    raw = compile_slot(1700000000)
    proof = write_rpc2(path, raw, raw)
    entry = [hashlib.sha256(source).hexdigest(), "setup binary", proof, True]
    index = cache / "capture_pixels.json"
    index.write_text(json.dumps({"compiled": {"rooms.rpyc": entry}}))
    path.unlink()
    before = _tracked_source_state(tmp_path)
    changed = compile_slot(1700000050)
    write_rpc2(path, changed, changed)
    with path.open("r+b") as stream:
        stream.seek(-16, 2)
        stream.write(hashlib.md5(source, usedforsecurity=False).digest())
    assert before == _tracked_source_state(tmp_path)
    path.unlink()
    entry[3] = False
    index.write_text(json.dumps({"compiled": {"rooms.rpyc": entry}}))
    assert "game/rooms.rpyc" not in _tracked_source_state(tmp_path)


def write_rpc2(path, first, second, compression=3):
    a, b = (zlib.compress(slot, compression) for slot in (first, second))
    path.write_bytes(
        b"RENPY RPC2"
        + struct.pack("<9I", 1, 46, len(a), 2, 46 + len(a), len(b), 0, 0, 0)
        + a
        + b
        + bytes(16)
    )
    return compiled_fingerprint(path)


def test_recompile_ignores_only_compiler_metadata_in_both_slots(tmp_path, compile_slot):
    path = tmp_path / "rooms.rpyc"
    baseline, rebuilt = compile_slot(1700000000), compile_slot(1800000149)
    proof = write_rpc2(path, baseline, baseline)
    assert proof is not None
    assert write_rpc2(path, rebuilt, rebuilt, compression=9) == proof
    for changed in (
        compile_slot(1700000000, image="forest.png"),
        compile_slot(1700000000, priority=101),
    ):
        assert write_rpc2(path, changed, baseline) != proof
        assert write_rpc2(path, baseline, changed) != proof
    shared = compile_slot(1700000000, shared=True)
    assert write_rpc2(path, shared, shared) is None


@pytest.mark.parametrize("raw", [b"", b"RENPY RPC2" + bytes(60), b"old engine data"])
def test_unrecognized_bytecode_uses_exact_file_identity(tmp_path, raw):
    path = tmp_path / "opaque.rpyc"
    path.write_bytes(raw)
    assert compiled_fingerprint(path) is None
    assert write_rpc2(path, b"invalid slot", pickle.dumps([], protocol=2)) is None


def test_independent_script_edits_invalidate_while_matching_recompiles_reuse(
    tmp_path, compile_slot
):
    path = tmp_path / "rooms.rpyc"
    initial, rebuilt = compile_slot(1700000000), compile_slot(1700000010)
    old = write_rpc2(path, initial, initial)
    raw = hashlib.sha256(path.read_bytes()).hexdigest()
    record_pixels(tmp_path, "scope", {}, {"rooms.rpyc": ["source", raw, old]})
    equivalent = write_rpc2(path, rebuilt, rebuilt)
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    assert current != raw
    assert verified_pixels(tmp_path, "scope", {"rooms.rpyc": ["source", current, equivalent]}) == {
        "sprites": {},
        "scenes": {},
    }
    changed = write_rpc2(path, rebuilt, compile_slot(1700000010, image="day.png"))
    assert verified_pixels(tmp_path, "scope", {"rooms.rpyc": ["source", "changed", changed]}) == {}
    assert verified_pixels(tmp_path, "scope", {"rooms.rpyc": ["source", "unknown", None]}) == {}
