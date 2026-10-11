"""Exercise the capture helper against compiled dialogue AST shapes."""

import ast
import json
import os
import textwrap
from types import SimpleNamespace as NS

import pytest

from scenelight.capture import CAPTURE_PLAN_VERSION, capture_source


class Say:
    def __init__(self, who="s", attributes=None, temporary_attributes=None, **kwargs):
        self.who = who
        self.attributes = attributes
        self.temporary_attributes = temporary_attributes
        self.filename = "game/story.rpy"
        self.interact = True
        self.__dict__.update(kwargs)


class TranslateSay(Say):
    pass


class CustomTranslatedDialogue(TranslateSay):
    pass


def statement(kind, name=None, **kwargs):
    result = type(kind, (), {})()
    result.filename = "game/story.rpy"
    result.imspec = (tuple(name.split()),) if name else None
    result.__dict__.update(kwargs)
    return result


def capture_functions(**namespace):
    source = capture_source().read_text(encoding="utf-8")
    block = source.split("init -999 python:\n", 1)[1].split("\ninit ", 1)[0]
    tree = ast.parse(textwrap.dedent(block))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace.update(json=json, os=os, _scenelight_string_types=(str,))
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(capture_source()), "exec"),
        namespace,
    )
    return namespace


@pytest.fixture
def inventory():
    def run(statements, tags=None, progress=None, **config):
        runtime = NS(
            ast=NS(Say=Say),
            game=NS(script=NS(all_stmts=statements)),
            config=NS(**config),
        )
        functions = capture_functions(renpy=runtime, config=runtime.config)
        return functions["_scenelight_script_inventory"](
            tags or {"s": "sayori", "m": "monika"}, progress
        )

    return run


@pytest.mark.parametrize("dialogue_type", [Say, TranslateSay, CustomTranslatedDialogue])
def test_compiled_dialogue_updates_inventory_and_retains_negative_attributes(
    inventory, dialogue_type
):
    scenes, counts, hidden, names, sequences = inventory(
        [
            statement("Scene", "bg office"),
            statement("Show", "sayori tap lateafternoon happy"),
            dialogue_type(attributes=("turned", "-happy", "sad")),
            statement("Show", "monika forward lateafternoon e1a md"),
            dialogue_type(who="m", attributes=("e1b", "mb")),
        ]
    )

    assert scenes == {"bg office"}
    assert counts == {"sayori": 2, "monika": 2}
    assert hidden == set()
    assert "sayori turned -happy sad" in names
    assert "monika e1b mb" in names
    assert sequences[-1] == [
        "scene",
        "show sayori tap lateafternoon happy",
        "show sayori turned -happy sad",
        "show monika forward lateafternoon e1a md",
        "show monika e1b mb",
    ]


def test_inventory_ignores_common_dialogue_unknown_speakers_and_attribute_free_lines(inventory):
    events = []
    _scenes, counts, _hidden, names, sequences = inventory(
        [
            TranslateSay(attributes=("menu",), filename="renpy/common/00start.rpy"),
            TranslateSay(attributes=("menu",), filename="C:\\sdk\\renpy\\common\\00start.rpy"),
            TranslateSay(who="narrator", attributes=("unknown",)),
            TranslateSay(),
            TranslateSay(attributes=("happy",)),
        ],
        progress=lambda *event: events.append(event),
    )

    assert names == {"sayori happy"}
    assert counts == {"sayori": 1}
    assert sequences[-1] == ["show sayori happy"]
    assert events[0] == ("inventory", 0, 5)
    assert events[-1] == ("inventory", 5, 5)


def test_bare_scene_clears_remembered_character_state(inventory):
    scenes, _counts, _hidden, _names, sequences = inventory(
        [statement("Show", "hero night sad"), statement("Scene"), statement("Show", "hero happy")]
    )

    assert scenes == set()
    assert sequences[-1] == ["show hero night sad", "scene", "show hero happy"]


def test_inventory_preserves_dialogue_changes_across_label_boundaries(inventory):
    _scenes, _counts, hidden, _names, sequences = inventory(
        [
            statement("Label"),
            statement("Show", "sayori tap lateafternoon"),
            statement("Label"),
            TranslateSay(attributes=("turned", "happy")),
            statement("Hide", "sayori"),
        ]
    )

    assert hidden == {"sayori"}
    assert sequences == [
        ["show sayori tap lateafternoon"],
        ["show sayori turned happy", "hide sayori"],
        ["show sayori tap lateafternoon", "show sayori turned happy", "hide sayori"],
    ]


def test_inventory_captures_temporary_attributes_after_permanent_changes(inventory):
    _scenes, counts, _hidden, names, sequences = inventory(
        [
            TranslateSay(attributes=("turned", "happy"), temporary_attributes=("-happy", "sad")),
            TranslateSay(temporary_attributes=("eyesclosed",)),
        ]
    )

    assert names == {"sayori turned happy", "sayori -happy sad", "sayori eyesclosed"}
    assert counts["sayori"] >= 1
    assert sequences[-1] == [
        "show sayori turned happy",
        "temporary sayori -happy sad",
        "temporary sayori eyesclosed",
    ]


def test_inventory_speaking_attribute_is_temporary_and_can_be_negated(inventory):
    _scenes, _counts, _hidden, names, sequences = inventory(
        [
            TranslateSay(),
            TranslateSay(temporary_attributes=("-speaking", "silent")),
            TranslateSay(attributes=("happy",), interact=False),
        ],
        speaking_attribute="speaking",
    )

    assert names == {"sayori speaking", "sayori speaking -speaking silent", "sayori happy"}
    assert sequences[-1] == [
        "temporary sayori speaking",
        "temporary sayori speaking -speaking silent",
        "show sayori happy",
    ]


def test_sequence_resolves_dialogue_against_permanent_state_and_restores_temporary_state():
    """Stub only the engine resolver; execute the production sequence planner."""
    resolver_calls = []
    base = ("sayori", "tap", "lateafternoon", "happy", "open")
    turned = ("sayori", "turned", "lateafternoon", "happy", "open")
    temporary = ("sayori", "turned", "lateafternoon", "sad", "open")
    next_line = ("sayori", "turned", "lateafternoon", "happy", "closed")
    resolutions = {
        ((), base): base,
        (base, ("sayori", "turned")): turned,
        (turned, ("sayori", "-happy", "sad")): temporary,
        (turned, ("sayori", "closed")): next_line,
    }

    class ShownImageInfo:
        def __init__(self):
            self.current = ()

        def apply_attributes(self, layer, tag, requested):
            resolver_calls.append((self.current, requested))
            return resolutions[(self.current, requested)]

        def predict_show(self, layer, name):
            self.current = name

    functions = capture_functions(renpy=NS(display=NS(image=NS(ShownImageInfo=ShownImageInfo))))
    forms = []
    names = {" ".join(name) for _state, name in resolutions}
    functions["_scenelight_plan_sequence"](
        [
            "show " + " ".join(base),
            "show sayori turned",
            "temporary sayori -happy sad",
            "show sayori closed",
        ],
        names,
        lambda requested, canonical: forms.append((requested, canonical)),
    )

    assert resolver_calls == list(resolutions)
    assert forms == [
        (" ".join(requested), " ".join(canonical))
        for (_state, requested), canonical in resolutions.items()
    ]
    assert forms[-1][1] == "sayori turned lateafternoon happy closed"


def test_sequence_only_plans_valid_requested_forms_and_clears_state_at_hide_and_scene():
    states = []
    calls = []

    class ShownImageInfo:
        def __init__(self):
            self.shown = {}
            states.append(self)

        def apply_attributes(self, layer, tag, requested):
            calls.append((dict(self.shown), requested))
            if "invalid" in requested:
                return None
            if "ambiguous" in requested:
                raise ValueError("ambiguous image")
            return requested

        def predict_show(self, layer, name):
            self.shown[name[0]] = name

        def predict_hide(self, layer, name):
            self.shown.pop(name[0], None)

    functions = capture_functions(renpy=NS(display=NS(image=NS(ShownImageInfo=ShownImageInfo))))
    forms = []
    functions["_scenelight_plan_sequence"](
        [
            "show sayori initial",
            "hide sayori",
            "show sayori next",
            "show sayori invalid",
            "show sayori ambiguous",
            "scene",
            "show monika final",
            "unknown sayori ignored",
        ],
        {"sayori next", "sayori invalid", "sayori ambiguous", "monika final"},
        lambda requested, canonical: forms.append((requested, canonical)),
    )

    assert forms == [("sayori next", "sayori next"), ("monika final", "monika final")]
    assert calls[1] == ({}, ("sayori", "next"))
    assert calls[-1] == ({}, ("monika", "final"))
    assert len(states) == 2


def test_capture_plan_roundtrip_uses_host_version_and_rejects_old_inventory(tmp_path):
    functions = capture_functions()
    functions["_scenelight_atomic_replace"] = os.replace
    destination = str(tmp_path / "capture_plan.json")
    names = {"sayori happy"}
    forms = {"sayori turned lateafternoon happy"}
    requests = {"sayori happy": forms}

    functions["_scenelight_save_capture_plan"](destination, "signature", names, forms, requests)
    payload = json.loads((tmp_path / "capture_plan.json").read_text())
    assert payload["version"] == CAPTURE_PLAN_VERSION
    assert CAPTURE_PLAN_VERSION > 2
    assert functions["_scenelight_load_capture_plan"](destination, "signature", names) == (
        forms,
        requests,
    )

    payload["version"] = 2
    (tmp_path / "capture_plan.json").write_text(json.dumps(payload))
    assert functions["_scenelight_load_capture_plan"](destination, "signature", names) is None
