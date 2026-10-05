"""Run the inspector's real numeric callbacks without a Ren'Py window."""

import ast
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_developer_guide import _runtime_api

from scenelight.runtime import inspector


@pytest.fixture
def controls():
    ns = _runtime_api()
    session = inspector.Session()
    session.selected = ("room", "hero", "hero base")
    session.report = {"visible_name": "hero idle", "values": {"strength": 0.7}}
    changes = []
    ns.update(
        BarValue=object,
        ui=SimpleNamespace(adjustment=lambda **kwargs: SimpleNamespace(**kwargs)),
        json=json,
        _sc_inspector_module=inspector,
        _scenelight_inspector_session=lambda: session,
        _scenelight_inspector_changed=lambda: changes.append(session.serializable()),
    )
    ns["renpy"].show_screen = lambda *_: None
    ns["renpy"].hide_screen = lambda *_: None
    source = (
        Path(__file__).resolve().parents[1] / "src/scenelight/runtime/inspector.rpy"
    ).read_text(encoding="utf-8")
    block = source.split("init 1001 python:\n", 1)[1].split("\nstyle sc_inspector_text", 1)[0]
    names = {
        "_SceneLightInspectorValue",
        "_scenelight_inspector_value_target",
        "_scenelight_inspector_set_value",
        "_scenelight_inspector_edit",
        "_scenelight_inspector_apply_edit",
    }
    nodes = [
        node
        for node in ast.parse(textwrap.dedent(block)).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "inspector-controls", "exec"), ns)
    return ns, session, changes


@pytest.mark.parametrize(
    "name,low,high",
    [
        ("strength", 0, 2),
        ("exposure_bias", -4, 4),
        ("light_color_amount", -1, 1),
        ("glow_strength", 0, 10),
        ("glow_color_mix", 0, 1),
        ("master_strength", 0, 1.5),
    ],
)
def test_sliders_use_full_range_and_same_scope_as_exact_edits(controls, name, low, high):
    ns, session, changes = controls
    initial = (low + high) / 2
    slider = ns["_SceneLightInspectorValue"](name, initial)
    adjustment = slider.get_adjustment()
    assert adjustment.value == initial - low
    assert adjustment.range == high - low
    rules = ns["scenelight"].state()
    for value in (0, (high - low) * 0.3, high - low):
        adjustment.changed(value)
        actual = round(value + low, 3)
        if name == "master_strength":
            assert session.master["strength"] == actual
        else:
            target = ("room", "hero", "hero idle" if name.startswith("glow_") else "hero base")
            expected = ns["_scenelight_control_values"]({name: actual})
            assert session.values(*target) == expected
        assert ns["scenelight"].state() == rules
    assert len(changes) == 3
    assert not vars(ns["persistent"])


def test_edit_dialog_and_slider_keep_exact_values_synchronized(controls):
    ns, session, _changes = controls
    ns["_scenelight_inspector_edit"]("strength")
    session.edit_text = "0.781234"
    ns["_scenelight_inspector_apply_edit"]()
    assert session.values(*session.selected)["strength"] == 0.781234
    slider = ns["_SceneLightInspectorValue"]("strength", 0.781234)
    assert slider.get_adjustment().value == 0.781234
    slider.changed(0.234)
    assert session.values(*session.selected)["strength"] == 0.234
    session.clear(session.selected, "strength")
    assert not session.active()


def test_drag_target_does_not_follow_a_new_selection_or_edit_unrelated_values(controls):
    ns, session, _changes = controls
    session.update(session.selected, {"exposure_bias": -0.123456})
    slider = ns["_SceneLightInspectorValue"]("strength", 0.7)
    session.selected = ("room", "other", "other idle")
    slider.changed(0.43)
    assert session.values("room", "hero", "hero base") == {
        "strength": 0.43,
        "exposure_bias": -0.123456,
    }
    assert not session.values(*session.selected)
    before = session.serializable()
    with pytest.raises(ValueError):
        slider.changed(float("nan"))
    assert session.serializable() == before


def test_unmanaged_sprite_slider_cannot_apply_edits(controls):
    ns, session, changes = controls
    slider = ns["_SceneLightInspectorValue"]("strength", 0.7, enabled=False)
    assert not slider.get_adjustment().adjustable
    assert slider.get_adjustment().changed is None
    slider.changed(0.4)
    assert not session.active() and not changes
