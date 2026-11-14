import hashlib
import json
import os

from scenelight.capture_reuse import (
    compiled_source_digest,
    record_pixels,
    rendering_script,
    verified_pixels,
)


def test_replan_story_images_but_invalidate_shared_executable_inputs():
    init = b"init python:\n    setup_lighting()\n"
    story = b'image nova happy = "art/nova.png"\nlabel example:\n    show nova happy\n    return\n'
    assert rendering_script(init + story) == rendering_script(init)
    assert rendering_script(init + b"\nimage nova = DynamicDisplayable(draw)") != rendering_script(
        init
    )
    assert rendering_script(init + b"\ninit python:\n    alter_style()") != rendering_script(init)
    multiline = b'init python:\n    value = """\nimage nova = "example.png"\n"""'
    assert rendering_script(multiline) == multiline
    layers = b'layeredimage nova:\n    group eyes:\n        attribute open default:\n            "eyes.png"\n            rotate 3\n'
    assert rendering_script(layers) == b""
    assert rendering_script(layers.replace(b"rotate 3", b"rotate custom()"))


def test_matching_compiler_output_and_independently_modified_bytecode(tmp_path):
    source = tmp_path / "cast.rpy"
    compiled = tmp_path / "cast.rpyc"
    raw = b'image nova = "nova.png"'
    source.write_bytes(raw)
    compiled.write_bytes(
        b"RENPY RPC2" + bytes(60) + hashlib.md5(raw, usedforsecurity=False).digest()
    )
    digest = compiled_source_digest(compiled, (source,))
    assert digest == hashlib.sha256(raw).hexdigest()
    old = {"cast.rpyc": [digest, "old"]}
    record_pixels(tmp_path, "scope", {}, old)
    assert verified_pixels(tmp_path, "scope", old) == {"sprites": {}, "scenes": {}}
    assert verified_pixels(tmp_path, "scope", {"cast.rpyc": [digest, "new"]}) == {}
    source.write_bytes(raw + b"\n")
    assert compiled_source_digest(compiled, (source,)) is None


def test_only_verified_present_pixels_from_matching_scope_are_reused(tmp_path):
    cache = tmp_path / ".scenelight_cache"
    folder = cache / "captured" / "old"
    folder.mkdir(parents=True)
    first, second = folder / "a.png", folder / "b.png"
    first.write_bytes(b"first")
    second.write_bytes(b"other")
    a, b = (p.relative_to(tmp_path).as_posix() for p in (first, second))
    record_pixels(
        cache,
        "scope",
        {
            "sprites": {"a": a, "alias": a, "b": b},
            "scenes": {},
            "pixel_keys": {"sprites": {"a": "ka", "alias": "kc", "b": "kb", "skipped": "ks"}},
        },
    )
    assert set(verified_pixels(cache, "scope")["sprites"]) == {"a", "alias", "b"}
    assert verified_pixels(cache, "different runtime") == {}
    stamp = first.stat()
    first.write_bytes(b"stale")
    os.utime(first, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert set(verified_pixels(cache, "scope")["sprites"]) == {"b"}
    second.unlink()
    assert verified_pixels(cache, "scope")["sprites"] == {}
    manifest = cache / "capture_pixels.json"
    index = json.loads(manifest.read_bytes())
    index["sprites"]["a"][1] = "../outside.png"
    manifest.write_text(json.dumps(index))
    assert not verified_pixels(cache, "scope")["sprites"]


def test_capture_stamps_upgrade_old_indexes_and_reject_same_stat_replacements(tmp_path):
    cache = tmp_path / ".scenelight_cache"
    folder = cache / "captured"
    folder.mkdir(parents=True)
    art = folder / "head.png"
    art.write_bytes(b"old")
    relative = art.relative_to(tmp_path).as_posix()
    payload = {"sprites": {"hero": relative}, "pixel_keys": {"sprites": {"hero": "source"}}}
    record_pixels(cache, "scope", payload)
    index_path = cache / "capture_pixels.json"
    index = json.loads(index_path.read_bytes())
    index.pop("stamps")
    index_path.write_text(json.dumps(index))
    assert verified_pixels(cache, "scope")["sprites"] == {"hero": ["source", relative]}
    record_pixels(cache, "scope", payload)
    stat = art.stat()
    replacement = art.with_suffix(".tmp")
    replacement.write_bytes(b"new")
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    replacement.replace(art)
    assert verified_pixels(cache, "scope")["sprites"] == {}
