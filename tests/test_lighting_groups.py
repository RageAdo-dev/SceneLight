import copy
from types import SimpleNamespace

import pytest
from test_developer_guide import _runtime_api

from scenelight.calibration import Calibration
from scenelight.runtime.inspector import describe


def test_members_share_settings_without_losing_glow_or_disable_rules():
    ns = _runtime_api()
    api = ns["scenelight"]
    api.background("room", strength=0.7, exposure_bias=-0.2)
    api.character("body", strength=0.2, ambient_strength=0.1, glow_strength=3)
    api.image("head happy", strength=0.9, exposure_bias=1)
    api.group("hug", ["body", "head"], ambient_strength=0.8)
    snapshot = ns["_scenelight_control_snapshot"]
    for tag, image in [("body", "body"), ("head", "head happy")]:
        result = snapshot("room", tag, image)
        assert result["strength"] == 0.7
        assert result["calibration"]["exposure_bias"] == -0.2
        assert result["calibration"]["ambient_strength"] == 0.8
        report = describe(
            Calibration().as_dict(), 1, {}, {}, api.state(), "room", tag, image, True, 1
        )
        assert report["group"]["name"] == "hug"
        assert report["values"]["strength"] == result["strength"]
        assert report["origins"]["ambient_strength"] == "Lighting group: hug"
    assert snapshot("room", "body", "body")["calibration"]["glow_strength"] == 3
    api.character("head", enabled=False)
    assert not snapshot("room", "head", "head happy")["enabled"]
    api.group("hug", strength=0.4, glow_strength=2)
    assert snapshot("room", "body", "body")["calibration"]["glow_strength"] == 2
    api.off()
    assert not snapshot("room", "body", "body")["enabled"]
    api.clear_scene()
    api.clear_group("hug")
    assert snapshot("room", "body", "body")["strength"] == 0.2


@pytest.mark.parametrize(
    "settings",
    [
        {"members": []},
        {"members": "body"},
        {"members": ["body", "body"]},
        {"members": ["body idle"]},
        {"anchor": "missing"},
        {"anchor": (float("nan"), 0.5)},
        {"anchor": (0.5, 2)},
        {"strength": "bad"},
        {"unknown_setting": 1},
    ],
)
def test_invalid_group_edit_is_atomic(settings):
    ns = _runtime_api()
    api = ns["scenelight"]
    api.group("hug", ["body", "head"])
    before = copy.deepcopy(api.state())
    with pytest.raises((ValueError, TypeError)):
        api.group("hug", **settings)
    assert api.state() == before


def test_conflicting_members_and_removing_anchor_are_rejected():
    ns = _runtime_api()
    api = ns["scenelight"]
    api.group("hug", ["body", "head"], anchor="body")
    with pytest.raises(ValueError):
        api.group("other", ["head", "extra"])
    with pytest.raises(ValueError):
        api.group("hug", ["head"])
    api.reset()
    assert api.state()["groups"] == {}


def test_groups_seed_new_games_and_restore_saved_or_rolled_back_state():
    ns = _runtime_api()
    engine = ns["renpy"]
    api = ns["scenelight"]
    engine.is_init_phase = lambda: True
    api.group("pieces", ["head", "body"], strength=0.6)
    engine.is_init_phase = lambda: False
    engine.store.scenelight_control_state = ns["_scenelight_control_initial_state"]()
    checkpoint = api.state()
    api.group("pieces", anchor=(0.1, 0.2), strength=0.9)
    assert checkpoint["groups"]["pieces"]["settings"]["strength"] == 0.6
    engine.store.scenelight_control_state = checkpoint
    assert api.state()["groups"]["pieces"]["anchor"] == "center"
    assert ns["_scenelight_control_snapshot"]("room", "head", "head happy")["strength"] == 0.6
    api.reset()
    assert not api.state()["groups"]
    assert (
        ns["_scenelight_control_initial_state"]()["groups"]["pieces"]["settings"]["strength"] == 0.6
    )


def test_shared_anchor_tracks_movement_hidden_leader_and_frame_cache():
    ns = _runtime_api()
    engine = ns["renpy"]
    engine.display = SimpleNamespace()
    engine.game = SimpleNamespace(interface=SimpleNamespace(frame_time=1))
    ns["config"] = SimpleNamespace(screen_width=1000, screen_height=1000)
    ns["_SCENELIGHT_MEASURING_EMITTERS"] = False
    rectangles = {"body": (100, 300, 200, 400), "head": (300, 100, 100, 200)}
    engine.get_showing_tags = lambda **kw: list(rectangles)
    calls = []

    def bounds(tag, *args):
        assert ns["_SCENELIGHT_MEASURING_EMITTERS"]
        calls.append(tag)
        return rectangles[tag]

    engine.get_image_bounds = bounds
    api = ns["scenelight"]
    api.group("hug", ["body", "head"])
    resolve = ns["_scenelight_control_group_anchor"]
    group = api.state()["groups"]["hug"]
    assert resolve(group) == (0.25, 0.4)
    assert resolve(group) == (0.25, 0.4)
    assert len(calls) == 2
    assert not ns["_SCENELIGHT_MEASURING_EMITTERS"]
    engine.game.interface.frame_time += 1
    rectangles["head"] = (500, 100, 100, 200)
    assert resolve(group) == (0.35, 0.4)
    api.group("hug", anchor="head")
    group = api.state()["groups"]["hug"]
    assert resolve(group) == (0.55, 0.2)
    del rectangles["head"]
    assert resolve(group) == (0.2, 0.5)
    rectangles.clear()
    assert resolve(group) is None
    api.group("hug", anchor=(0.1, 0.9))
    assert resolve(api.state()["groups"]["hug"]) == (0.1, 0.9)
