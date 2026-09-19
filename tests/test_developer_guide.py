import ast
import copy
import json
import os
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenelight.developer_guide import CATEGORIES, SETTINGS, TOPICS, search_topics

ROOT = Path(__file__).resolve().parents[1]


def _runtime_api():
    """Run the real author controls without constructing a renderer or game."""
    source = (ROOT / "src/scenelight/runtime/scenelight_runtime.rpy").read_text(encoding="utf-8")
    block = source.split("init -50 python:\n", 1)[1].split("\ninit 999 python:", 1)[0]
    tree = ast.parse(textwrap.dedent(block))
    assignments = {
        "_SCENELIGHT_CALIBRATION_DEFAULTS",
        "_SCENELIGHT_CONTROL_KEYS",
        "_SCENELIGHT_CONTROL_ALIASES",
        "_SCENELIGHT_PHYSICAL_MODE",
        "_SCENELIGHT_SEPARATE_MODE",
        "_SCENELIGHT_LIGHT_MODES",
        "_SCENELIGHT_INITIAL_CONTROL_STATE",
        "scenelight",
    }
    functions = {
        "_scenelight_light_mode_values",
        "_SceneLightAPI",
        "scenelight_set_enabled",
        "scenelight_set_strength",
        "scenelight_register_tag",
    }
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in assignments for target in node.targets
            )
        )
        or (
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and (node.name in functions or node.name.startswith("_scenelight_control_"))
        )
    ]
    namespace = {
        "copy": copy,
        "renpy": SimpleNamespace(store=SimpleNamespace(), restart_interaction=lambda: None),
        "persistent": SimpleNamespace(),
        "_scenelight_redraw_visible_sprites": lambda: None,
        "_SCENELIGHT_STRING_TYPES": (str,),
        "_SCENELIGHT_SHADER_AVAILABLE": False,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "author-api", "exec"), namespace)
    return namespace


def test_search_accepts_commands_aliases_plain_language_and_category():
    assert search_topics("  CLEAR_SCENE  ")
    assert search_topics("scenelight.clear_scene")[0].key == "clear-scene"
    assert search_topics("brightness")[0].key == "setting-exposure_bias"
    assert any(topic.key == "off" for topic in search_topics("turn off"))
    assert any(topic.key == "setting-exposure_bias" for topic in search_topics("brightness"))
    assert any(topic.key == "setting-color_adaptation" for topic in search_topics("green"))
    assert any(topic.key == "setting-strength" for topic in search_topics("lighting_strength"))
    assert all(topic.category == SETTINGS for topic in search_topics("", SETTINGS))
    assert search_topics("not_a_real_command") == ()
    assert search_topics("", "unknown category") == ()
    assert len({topic.key for topic in TOPICS}) == len(TOPICS)
    assert {topic.category for topic in TOPICS} == set(CATEGORIES)


def test_guide_covers_runtime_settings_and_public_api():
    namespace = _runtime_api()
    settings = {
        topic.key.removeprefix("setting-") for topic in TOPICS if topic.category == SETTINGS
    }
    assert settings == namespace["_SCENELIGHT_CONTROL_KEYS"]
    reference = "\n".join(
        " ".join((topic.summary, *topic.details, topic.example, topic.keywords)) for topic in TOPICS
    )
    for name in vars(type(namespace["scenelight"])):
        if not name.startswith("_"):
            assert f"scenelight.{name}(" in reference, f"Undocumented command: scenelight.{name}"


def test_every_copyable_example_uses_the_real_author_api():
    namespace = _runtime_api()
    for topic in TOPICS:
        example = topic.example
        if not example:
            continue
        assert topic.placement, topic.key
        if example.startswith("{"):
            assert isinstance(json.loads(example), dict)
        elif example.startswith("init python:\n"):
            exec(textwrap.dedent(example.split("\n", 1)[1]), namespace)
        elif example.startswith("textbutton"):
            # Screen-language Function arguments reference the real functions.
            for line in example.splitlines():
                call = ast.parse(line.split(" action ", 1)[1], mode="eval").body
                assert isinstance(call, ast.Call) and call.func.id == "Function"
                name = call.args[0].id
                namespace[name](*(ast.literal_eval(value) for value in call.args[1:]))
        else:
            statements = []
            for line in example.splitlines():
                assert line.startswith(("$ ", "#")), (topic.key, line)
                statements.append(line[2:] if line.startswith("$ ") else line)
            exec("\n".join(statements), namespace)


@pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"), reason="Requires a desktop display"
)
def test_native_browser_search_selection_and_copy(monkeypatch):
    import tkinter as tk
    from tkinter import ttk

    from scenelight.developer_guide_ui import DeveloperGuide

    root = tk.Tk()
    root.withdraw()
    ttk.Style(root).theme_use("clam")
    guide = DeveloperGuide(root)
    guide.withdraw()
    copied = []
    # Do not replace the user's clipboard during the test.
    monkeypatch.setattr(guide, "clipboard_clear", lambda: copied.clear())
    monkeypatch.setattr(guide, "clipboard_append", copied.append)
    try:
        guide.query.set("brightness")
        guide._refresh_topics()
        root.update_idletasks()
        assert "setting-exposure_bias" in guide.results.get_children()
        guide.results.selection_set("setting-exposure_bias")
        guide._selected()
        guide.copy_button.invoke()
        assert copied == ["$ scenelight.scene(exposure_bias=0.2)"]
        assert guide.copy_button.cget("text") == "Copied"
        guide.query.set("no matching command")
        guide._refresh_topics()
        assert guide.current_topic is None
        assert guide.copy_button.instate(["disabled"])
        assert "No matching topics" in guide.reader.get("1.0", "end")
        guide.clear_search()
        assert len(guide.results.get_children()) == len(TOPICS)
        assert guide.current_topic.key == "start"
        assert guide.reader.cget("state") == "disabled"
        # A pending debounce must not fire after the help window closes.
        guide.query.set("color")
        guide.destroy()
        assert not guide.query.trace_info()
        assert not guide.category.trace_info()
        root.update()
    finally:
        root.destroy()


def test_launch_guide_does_not_expose_post_launch_effects():
    assert "Effects" not in CATEGORIES
    assert search_topics("scenelight_fx") == ()
    assert search_topics("glitch") == ()
    assert search_topics("effect-packs") == ()
    for name in (
        "README.md",
        "docs/README.md",
        "docs/AUTHOR_QUICKSTART.md",
        "docs/MOD_AUTHOR_API.md",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "scenelight_fx" not in text
        assert "EFFECT_PACKS.md" not in text
