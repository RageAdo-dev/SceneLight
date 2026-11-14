"""The controller and the Ren'Py helper agree on form names and skip lists."""

import ast
import hashlib
import inspect
import io
import json
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import scenelight.capture as capture

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy"


def helper_functions(*names, **scope):
    source = textwrap.dedent("\n".join(HELPER.read_text(encoding="utf-8").splitlines()[2:]))
    nodes = {
        node.name: node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
    }
    scope.update(inspect=inspect, os=os)
    for name in names:
        exec(compile(ast.Module(body=[nodes[name]], type_ignores=[]), str(HELPER), "exec"), scope)
    return scope


@pytest.mark.parametrize(
    "baseline, growth, bits, expected",
    [(1400, 1024, 64, 2424), (800, 1024, 32, 1536), (1200, 256, 32, 1456), (1400, 0, 64, 0)],
)
def test_capture_memory_budget_accounts_for_the_loaded_game(baseline, growth, bits, expected):
    ceiling = helper_functions("_scenelight_capture_memory_ceiling")[
        "_scenelight_capture_memory_ceiling"
    ]
    mib = 1048576
    assert ceiling(baseline * mib, growth * mib, bits) == expected * mib


def test_32_bit_game_without_capture_headroom_stops_instead_of_restarting_each_form():
    ceiling = helper_functions("_scenelight_capture_memory_ceiling")[
        "_scenelight_capture_memory_ceiling"
    ]
    with pytest.raises(RuntimeError, match="compatible 64-bit runtime"):
        ceiling(1600 * 1048576, 1024 * 1048576, 32)


def test_static_form_reuse_follows_resolved_layer_bytes_and_renderer():
    style = SimpleNamespace(__getstate__=lambda: {"parent": None})
    image = type("Image", (), {"__module__": "renpy.display.im", "get_oversample": lambda self: 1})
    fixed = type("MultiBox", (), {"__module__": "renpy.display.layout"})
    source = {"coat.png": b"coat", "eyes.png": b"open", "other.png": b"blue"}

    def form(*names):
        box = fixed()
        box.style, box.default_layout, box.layers, box.scene_list = style, "fixed", None, None
        box.children = []
        for name in names:
            child = image()
            child.filename, child.style = name, style
            box.children.append(child)
        box.child = box.children[-1]
        return box

    def load(name, directory):
        assert directory == "images"
        return io.BytesIO(source[name])

    registry = {"a": form("coat.png", "eyes.png"), "b": form("other.png"), "custom": object()}
    key = helper_functions(
        "_scenelight_callable_arguments",
        "_scenelight_pixel_key",
        renpy=SimpleNamespace(loader=SimpleNamespace(load=load)),
        hashlib=hashlib,
        json=json,
        _scenelight_image_spelling=lambda parts: parts,
        _scenelight_get_registered_image=lambda parts: registry.get(" ".join(parts)),
        _scenelight_capture_displayable=registry.__getitem__,
    )["_scenelight_pixel_key"]

    first = [key(n, ["gl2"], {}, {}) for n in registry]
    assert first[0] and first[1] and first[2] is None
    source["eyes.png"] = b"shut"
    assert key("a", ["gl2"], {}, {}) != first[0]
    assert key("b", ["gl2"], {}, {}) == first[1]
    assert key("b", ["angle2"], {}, {}) != first[1]


@pytest.mark.parametrize("modern", [False, True])
def test_png_copy_matches_the_engines_image_loader(tmp_path, modern):
    content = b"exact archived image bytes"
    calls = []
    if modern:

        def load(name, directory=None, tl=True):
            calls.append((name, directory, tl))
            return io.BytesIO(content)
    else:

        def load(name, tl=True):
            calls.append((name, None, tl))
            return io.BytesIO(content)

    scope = helper_functions(
        "_scenelight_callable_arguments",
        "_scenelight_copy_source_png",
        config=SimpleNamespace(basedir=str(tmp_path)),
        renpy=SimpleNamespace(loader=SimpleNamespace(load=load)),
        _scenelight_capture_temporary=lambda name, *args: name + ".tmp",
        _scenelight_atomic_replace=os.replace,
    )
    scope["_scenelight_copy_source_png"]("monika.png", "captures/monika.png")
    assert (tmp_path / "captures/monika.png").read_bytes() == content
    assert calls == [("monika.png", "images" if modern else None, True)]


@pytest.mark.parametrize("legacy", [False, True])
def test_screenshot_uses_the_renderer_signature(legacy):
    calls = []
    if legacy:

        def screenshot(tree, fullscreen_video):
            calls.append((tree, fullscreen_video))
            return "pixels"
    else:

        def screenshot(tree):
            calls.append((tree,))
            return "pixels"

    scope = helper_functions(
        "_scenelight_callable_arguments",
        "_scenelight_screenshot",
        renpy=SimpleNamespace(display=SimpleNamespace(draw=SimpleNamespace(screenshot=screenshot))),
    )
    assert scope["_scenelight_screenshot"]("render") == "pixels"
    assert calls == [("render", False) if legacy else ("render",)]


def test_screenshot_does_not_retry_an_internal_type_error():
    calls = []

    def screenshot(tree):
        calls.append(tree)
        raise TypeError("invalid shader value")

    scope = helper_functions(
        "_scenelight_callable_arguments",
        "_scenelight_screenshot",
        renpy=SimpleNamespace(display=SimpleNamespace(draw=SimpleNamespace(screenshot=screenshot))),
    )
    with pytest.raises(TypeError, match="invalid shader value"):
        scope["_scenelight_screenshot"]("render")
    assert calls == ["render"]


@pytest.mark.parametrize("complete_pair", [True, False])
def test_resume_recognizes_a_matting_pair_before_the_combined_png_exists(
    tmp_path, monkeypatch, complete_pair
):
    output = tmp_path / "previews"
    output.mkdir()
    filename = output / "sprite_hero.png"
    entry = {"relative": "previews/sprite_hero.png", "size": [16, 16], "crop": [16, 16]}
    Path(str(filename) + ".matting.json").write_text(json.dumps(entry))
    Image.new("RGB", (16, 16), "black").save(str(filename) + ".black.png")
    if complete_pair:
        Image.new("RGB", (16, 16), "white").save(str(filename) + ".white.png")
    source = textwrap.dedent("\n".join(HELPER.read_text(encoding="utf-8").splitlines()[2:]))
    functions = {
        node.name: node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
    }
    from types import SimpleNamespace

    scope = {
        "os": os,
        "json": json,
        "hashlib": hashlib,
        "config": SimpleNamespace(basedir=str(tmp_path)),
        "_scenelight_is_mapping": lambda value: isinstance(value, dict),
        "_scenelight_capture_filename": lambda *_: filename.name,
        "_scenelight_form_key": lambda value: value,
        "_scenelight_composite_job_path": lambda _: str(output / "unused.json"),
        "_scenelight_deferred_form_paths": [None],
        "_scenelight_matting_captures": [],
        "output_relative": "previews",
        "surface_captures": set(),
        "normalized_captures": set(),
        "composite_captures": {},
        "legacy_sprite_paths": {},
        "restore_stats": {"exact": 0, "recovered": 0, "unmarked": 0, "missing": 0},
        "captures": {"sprites": {}},
    }
    for name in ("_scenelight_resume_matted", "restore_sprite_checkpoint"):
        module = ast.Module(body=[functions[name]], type_ignores=[])
        exec(compile(module, str(HELPER), "exec"), scope)
    monkeypatch.setattr(
        os, "listdir", lambda *_args: pytest.fail("Rescanned the cache for one form")
    )
    assert scope["restore_sprite_checkpoint"]("hero") is complete_pair
    assert scope["_scenelight_matting_captures"] == ([entry] if complete_pair else [])
    assert scope["captures"]["sprites"] == ({"hero": entry["relative"]} if complete_pair else {})
    assert not filename.exists()


def test_helper_leaves_out_the_forms_the_controller_records():
    text = HELPER.read_text(encoding="utf-8")

    assert 'request.get("skip_forms")' in text
    assert "if actual_name not in host_skips" in text


def test_helper_names_character_captures_by_form_digest_only():
    text = HELPER.read_text(encoding="utf-8")

    # A readable prefix would make the path depend on the planned spelling,
    # which is what made earlier restores miss their own files.
    assert 'return "sprite_%s.png" % digest' in text


def test_helper_recovers_pixels_that_lost_their_checkpoint_marker():
    text = HELPER.read_text(encoding="utf-8")

    assert "_scenelight_is_raw_surface(absolute)" in text
    assert 'restore_stats["recovered"] += 1' in text


def test_helper_records_each_render_stage_for_a_stopped_form():
    text = HELPER.read_text(encoding="utf-8")

    # A crash between these records says whether Ren'Py died in the render
    # tree, in the software blit, or while saving the pixels.
    for stage in ('"stage": "rendering"', '"stage": "rendered"', '"stage": "composited"'):
        assert stage in text


def test_helper_releases_each_forms_render_tree_before_the_next_one():
    text = HELPER.read_text(encoding="utf-8")

    # Nine layered surfaces per form accumulate in Ren'Py's render cache; the
    # capture must drop them once the pixels are copied out.
    composited = text.index('"stage": "composited"')
    release = text.index("renpy.display.render.free_memory()", composited)
    assert release > composited


def test_helper_records_the_displayable_tree_for_comparison():
    text = HELPER.read_text(encoding="utf-8")

    assert '"tree": _scenelight_structure_summary(displayable)' in text


def test_helper_controller_form_key_matches_the_helper_definition():
    # The helper builds tag + sorted(unique attributes), lowercased.
    assert capture._form_key("Yuri  GJ  wings6 1") == "yuri 1 gj wings6"
    assert capture._form_key("andres") == "andres"
    assert capture._form_key("  ") == ""
