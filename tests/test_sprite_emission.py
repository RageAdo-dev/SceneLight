"""Exercise actual author rules and scene resolution, without a game install."""

from types import SimpleNamespace

import pytest
from test_developer_guide import _runtime_api
from test_runtime_render_graph import _exposure_runtime, _load_runtime_definitions

from scenelight.calibration import Calibration


def _emission_runtime():
    ns = _runtime_api()
    ns.update(
        SCENELIGHT_MANIFEST={},
        SCENELIGHT_CHARACTER_TAGS={"hero", "fire", "orb"},
        _SCENELIGHT_MEASURING_EMITTERS=False,
        _scenelight_live_scene_entry=lambda: ("room", {}),
        config=SimpleNamespace(screen_width=1280, screen_height=720),
    )
    _load_runtime_definitions(ns, "_scenelight_calibration_blocks", "_scenelight_sprite_emitters")
    _load_runtime_definitions(ns, "_scenelight_emission_controls")
    ns["entries"] = []
    ns["renpy"].game = SimpleNamespace(
        context=lambda: SimpleNamespace(
            scene_lists=SimpleNamespace(layers={"master": ns["entries"]})
        )
    )
    ns["bounds"] = {"fire": (200, 200, 100, 160), "orb": (800, 200, 100, 100)}

    def bounds(tag, *args):
        assert ns["_SCENELIGHT_MEASURING_EMITTERS"]
        assert ns["_scenelight_sprite_emitters"]("hero") == ()
        return ns["bounds"].get(tag)

    ns["renpy"].get_image_bounds = bounds
    return ns


def test_every_lighting_setting_is_independent_per_tag_and_exact_image():
    ns = _runtime_api()
    api = ns["scenelight"]
    values = {name: 0.37 for name in ns["_SCENELIGHT_CALIBRATION_DEFAULTS"]}
    api.character("hero", strength=0.45, **values)
    api.character("friend", strength=0.85, rim_strength=0.9)
    api.image("hero worried", strength=1.2, glow_strength=0.0, exposure_bias=-0.4)
    hero = ns["_scenelight_control_snapshot"]("room", "hero", "hero happy")
    friend = ns["_scenelight_control_snapshot"]("room", "friend", "friend happy")
    worried = ns["_scenelight_control_snapshot"]("room", "hero", "hero worried")
    assert hero["calibration"] == values
    assert hero["strength"] == 0.45
    assert friend["calibration"] == {"rim_strength": 0.9}
    assert friend["strength"] == 0.85
    assert worried["strength"] == 1.2
    assert worried["calibration"] == {**values, "glow_strength": 0.0, "exposure_bias": -0.4}
    api.clear_image("hero worried")
    assert ns["_scenelight_control_snapshot"]("room", "hero", "hero worried") == hero


def test_emission_moves_hides_excludes_self_and_is_independent_of_glow_and_draw_order():
    ns = _emission_runtime()
    api = ns["scenelight"]
    fire = SimpleNamespace(tag="fire", name=("fire", "burning"))
    hero = SimpleNamespace(tag="hero", name=("hero", "happy"))
    ns["entries"][:] = [hero, fire]
    api.image(
        "fire burning",
        emission_strength=1.0,
        emission_radius=0.4,
        emission_red=1.0,
        emission_green=0.25,
        emission_blue=0.0,
    )
    collect = ns["_scenelight_sprite_emitters"]
    expected = (((250 / 1280, 280 / 720, 0.4, 1.0), (1.0, 0.25, 0.0)),)
    assert collect("hero") == expected
    ns["entries"].reverse()
    assert collect("hero") == expected
    assert collect("fire") == ()
    api.image("fire burning", glow_strength=1.2)
    assert collect("hero") == expected
    ns["bounds"]["fire"] = (400, 100, 100, 160)
    assert collect("hero")[0][0][:2] == (450 / 1280, 180 / 720)
    ns["entries"].remove(fire)
    assert collect("hero") == ()
    ns["entries"].append(fire)
    api.image("fire burning", emission_strength=0)
    assert collect("hero") == ()
    assert (
        ns["_scenelight_control_snapshot"]("room", "fire", "fire burning")["calibration"][
            "glow_strength"
        ]
        == 1.2
    )
    api.image("fire burning", emission_strength=1)
    api.off()
    assert collect("hero") == ()


def test_measurement_guard_restores_on_error_and_player_switch_disables_emitters():
    ns = _emission_runtime()
    ns["scenelight"].character("fire", emission_strength=1)
    ns["entries"].append(SimpleNamespace(tag="fire", name=("fire",)))
    ns["renpy"].get_image_bounds = lambda *args: (_ for _ in ()).throw(RuntimeError("bounds"))
    with pytest.raises(RuntimeError, match="bounds"):
        ns["_scenelight_sprite_emitters"]("hero")
    assert not ns["_SCENELIGHT_MEASURING_EMITTERS"]
    ns["persistent"].scenelight_enabled = False
    assert ns["_scenelight_sprite_emitters"]("hero") == ()


def test_calibration_round_trip_keeps_glow_and_emission_separate():
    settings = Calibration(glow_strength=1.2, emission_strength=0.6, emission_green=0.3)
    assert Calibration.from_mapping(settings.as_dict()) == settings
    ns = _emission_runtime()
    assert ns["_scenelight_calibration_blocks"]({}, settings.as_dict()) == settings.uniform_blocks()
    assert Calibration.from_mapping({}).glow_strength == 0
    assert Calibration.from_mapping({}).emission_strength == 0


def test_exact_shown_alias_override_controls_inner_glow_without_changing_other_lighting():
    ns = _emission_runtime()
    ns["entries"].append(SimpleNamespace(tag="fire", name=("fire", "alias")))
    ns["scenelight"].character("fire", glow_strength=1.2, exposure_bias=-0.5)
    ns["scenelight"].image("fire alias", glow_strength=0)
    original = ns["_scenelight_control_snapshot"]("room", "fire", "fire burning")
    effective = ns["_scenelight_emission_controls"]("room", "fire", original)
    assert effective["calibration"] == {"glow_strength": 0.0, "exposure_bias": -0.5}
    assert original["calibration"]["glow_strength"] == 1.2


def test_capture_lock_failure_is_explained_without_a_graphics_error():
    from scenelight.setup_gui import describe_operation_failure

    title, message = describe_operation_failure(
        "CaptureInstanceConflict: single-instance protection blocked capture"
    )
    assert "one running copy" in title
    assert "checkpoints" in message


def test_cpu_compositor_does_not_add_floor_geometry():
    import numpy as np
    from PIL import Image, ImageDraw

    from scenelight.engine import Placement, RelightSettings, composite_scene

    background = Image.new("RGBA", (320, 180), (70, 80, 90, 255))
    sprite = Image.new("RGBA", (160, 240))
    ImageDraw.Draw(sprite).ellipse((40, 20, 120, 170), fill=(180, 150, 120, 255))
    result = composite_scene(
        background, sprite, Placement(), settings=RelightSettings(shadow_strength=2)
    )
    reference = composite_scene(
        background, sprite, Placement(), settings=RelightSettings(shadow_strength=0)
    )
    np.testing.assert_array_equal(np.asarray(result), np.asarray(reference))


def test_nested_alias_receives_light_and_glows_once_and_snapshot_retains_sources():
    Sprite, Displayable, _ = _exposure_runtime()
    ns = Sprite.__init__.__globals__
    inner = Sprite(Displayable(), ("fire", "burning"))
    outer = Sprite(inner, ("fire", "burning"))
    ns["_SceneLightAPI"]().image("fire burning", glow_strength=1)
    assert inner._sc_emission_coverage() == (False, False)
    assert outer._sc_emission_coverage() == (True, True)
    inner._sc_last_rendered_emitters = (((0.4, 0.2, 0.3, 1.0), (1.0, 0.5, 0.1)),)
    frozen = inner._in_current_store()
    inner._sc_last_rendered_emitters = ()
    assert frozen._sc_frozen_emitters == (((0.4, 0.2, 0.3, 1.0), (1.0, 0.5, 0.1)),)
