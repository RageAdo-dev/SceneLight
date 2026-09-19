"""The saved controls and real Ren'Py author API agree on selective emission."""

import json
from dataclasses import replace

import pytest
from test_developer_guide import _runtime_api
from test_runtime_render_graph import _load_runtime_definitions

from scenelight.calibration import (
    Calibration,
    CalibrationProfile,
    ColorGlowRule,
    color_glow_blur_steps,
)


def test_rules_normalize_round_trip_inherit_and_do_not_share_mutable_state():
    rule = ColorGlowRule(
        name=" Gem ", color=(2, -1, 0.5), strength=3, radius=-1, tolerance=2, softness=0.2
    )
    value = Calibration(glow_rules=(rule,)).normalized()
    assert value.glow_rules[0] == replace(
        rule, name="Gem", color=(1, 0, 0.5), strength=2, radius=0, tolerance=1
    )
    payload = json.loads(json.dumps(CalibrationProfile(value).to_payload()))
    assert CalibrationProfile.from_payload(payload).calibration == value
    assert (
        Calibration.from_mapping({"exposure_bias": 0.2}, base=value).glow_rules == value.glow_rules
    )
    assert Calibration.from_mapping({"glow_rules": []}, base=value).glow_rules == ()
    payload["calibration"]["glow_rules"][0]["color"][0] = 0
    assert value.glow_rules[0].color[0] == 1
    many = Calibration(glow_rules=tuple(ColorGlowRule(name=str(i)) for i in range(25)))
    assert len(Calibration.from_mapping(many.as_dict()).glow_rules) == 25


@pytest.mark.parametrize(
    "value",
    [
        None,
        3,
        {},
        [3],
        [{"colour": [1, 0, 0]}],
        [{"color": [1, 0]}],
        [{"strength": float("nan")}],
        [{"radius": float("inf")}],
        [{"enabled": "false"}],
        [{"softness": True}],
    ],
)
def test_rules_reject_invalid_shapes_values_and_nonfinite_numbers(value):
    with pytest.raises(ValueError):
        Calibration.from_mapping({"glow_rules": value})
    with pytest.raises(ValueError):
        _runtime_api()["scenelight"].character("hero", glow_rules=value)


def test_real_author_api_scope_snapshot_clear_and_renpy_revertable_container_compatibility():
    ns = _runtime_api()
    # Ren'Py shadows list and dict with rollback-aware subclasses; manifest JSON
    # still contains ordinary builtins. Both forms must be accepted.
    ns["list"] = type("RevertableList", (list,), {})
    ns["dict"] = type("RevertableDict", (dict,), {})
    normalize = ns["_scenelight_control_glow_rules"]
    value = [{"name": "red", "color": [0.9, 0.04, 0.02]}]
    assert normalize(value) == normalize(ns["list"]([ns["dict"](value[0])]))
    del ns["list"], ns["dict"]
    api = ns["scenelight"]
    api.character("hero", glow_rules=value)
    value[0]["color"][0] = 0
    snapshot = ns["_scenelight_control_snapshot"]("room", "hero", "hero happy")
    assert snapshot["calibration"]["glow_rules"][0]["color"][0] == 0.9
    api.image("hero worried", glow_rules=[])
    assert (
        ns["_scenelight_control_snapshot"]("room", "hero", "hero worried")["calibration"][
            "glow_rules"
        ]
        == []
    )
    assert ns["_scenelight_control_snapshot"]("room", "friend", "friend happy")["calibration"] == {}
    api.clear_image("hero worried")
    assert ns["_scenelight_control_snapshot"]("room", "hero", "hero worried") == snapshot
    snapshot["calibration"]["glow_rules"][0]["strength"] = 0
    assert (
        ns["_scenelight_control_snapshot"]("room", "hero", "hero happy")["calibration"][
            "glow_rules"
        ][0]["strength"]
        == 1
    )
    api.off()
    assert ns["_scenelight_control_snapshot"]("room", "hero", "hero happy")["enabled"] is False


def test_runtime_profile_rules_and_blur_steps_match_preview():
    ns = _runtime_api()
    ns["SCENELIGHT_MANIFEST"] = {"calibration": {"glow_rules": [ColorGlowRule().as_dict()]}}
    _load_runtime_definitions(ns, "_scenelight_color_glow_rules", "_scenelight_color_glow_steps")
    resolve = ns["_scenelight_color_glow_rules"]
    assert len(resolve(None, {})) == 1
    assert resolve({}, {"calibration": {"glow_rules": []}}) == ()
    assert resolve({"calibration": {"glow_rules": []}}, {}) == ()
    for size in [(160, 240), (960, 960), (4096, 1024)]:
        for radius in (0, 0.1, 1, 2):
            assert tuple(ns["_scenelight_color_glow_steps"](size, radius)) == color_glow_blur_steps(
                size, radius
            )
    assert color_glow_blur_steps((160, 240), 1) == color_glow_blur_steps((240, 160), 1)


def test_runtime_glow_passes_reuse_original_artwork_and_never_relight():
    ns = _runtime_api()

    class Render:
        def __init__(self, *size):
            self.size, self.children, self.shaders, self.uniforms = size, [], [], {}

        def get_size(self):
            return self.size

        def blit(self, child, position):
            self.children.append(child)

        def add_shader(self, shader):
            self.shaders.append(shader)

        def add_uniform(self, key, value):
            self.uniforms[key] = value

    ns["renpy"].Render = Render
    _load_runtime_definitions(ns, "_scenelight_color_glow_render", "_scenelight_color_glow_steps")
    source, lit = Render(160, 240), Render(160, 240)
    rules = [ColorGlowRule(name=str(i), radius=0).as_dict() for i in range(19)]
    apply = ns["_scenelight_color_glow_render"]
    assert apply(lit, source, rules, 0) is lit
    result = apply(lit, source, rules)
    count = 0
    while result is not lit:
        assert result.shaders == ["renpy.texture", "scenelight.color_glow"]
        assert result.children[1] is source
        assert result.children[2].children == [source]
        result = result.children[0]
        count += 1
    assert count == 19


def test_composite_mask_recovers_original_art_and_geometry_without_mutating_cached_render():
    ns = _runtime_api()

    class Render:
        def __init__(self, *size):
            self.size, self.children, self.shaders = size, [], ()
            self.alpha, self.over, self.mesh = 1.0, 1.0, None
            self.focus_dependencies = []

        def get_size(self):
            return self.size

        def subpixel_blit(self, child, position, focus=True, main=True):
            self.children.append((child, *position, focus, main))

        def depends_on(self, render, focus=False):
            self.focus_dependencies.append((render, focus))

    ns["renpy"].Render = Render
    ns["_scenelight_sprite_shader"] = "scenelight.sprite"
    _load_runtime_definitions(ns, "_scenelight_color_glow_tree")
    source = Render(60, 100)
    lit = Render(60, 100)
    lit.shaders = ("renpy.texture", "scenelight.sprite")
    lit.subpixel_blit(source, (0, 0))
    glow = Render(60, 100)
    glow.shaders = ("renpy.texture", "scenelight.color_glow")
    glow.subpixel_blit(lit, (0, 0))
    glow.subpixel_blit(source, (0, 0))
    composite = Render(160, 240)
    composite.subpixel_blit(glow, (12.5, 18.25))
    composite.subpixel_blit(source, (95.5, 64.25))
    composite.alpha, composite.over = 0.6, 0.8
    composite.xclipping, composite.yclipping = True, True
    composite.shaders = ("renpy.texture", "game.authored_tint")
    composite.uniforms = {"tint": (0.9, 0.4, 0.2)}
    original_children = tuple(composite.children)
    recover = ns["_scenelight_color_glow_tree"]
    base = recover(composite)
    original = recover(composite, original=True)
    assert base.children[0][0] is lit
    assert original.children[0][0] is source
    for result in (base, original):
        assert result.children[0][1:3] == (12.5, 18.25)
        assert result.children[1][0] is source
        assert result.alpha == 0.6 and result.over == 0.8
        assert result.xclipping and result.yclipping
        assert result.shaders == composite.shaders and result.uniforms == composite.uniforms
        assert result.focus_dependencies == [(composite, True)]
    assert tuple(composite.children) == original_children
    assert recover(source) is source


def test_runtime_selective_glow_alias_coverage_and_frozen_rules():
    from test_runtime_render_graph import _exposure_runtime

    Sprite, Displayable, _redraws = _exposure_runtime()
    ns = Sprite._live_lighting_state.__globals__
    api = ns["_SceneLightAPI"]()
    rule = ColorGlowRule(radius=0).as_dict()
    api.character("hero", glow_rules=[rule])
    inner = Sprite(Displayable(), ("hero", "base"))
    outer = Sprite(inner, ("hero", "alias"))
    # Selective emission is rebuilt from original art at the outer boundary;
    # it must not suppress the preexisting alias lighting path.
    assert outer._sc_emission_coverage() == (True, False)
    inner._sc_last_rendered_scene = {"uv": (0, 0, 1, 1)}
    inner._sc_last_rendered_controls = inner._live_lighting_state()[-1]
    frozen = inner._in_current_store()
    api.character("hero", glow_rules=[])
    assert outer._sc_emission_coverage() == (True, False)
    frozen_outer = Sprite(frozen, ("hero", "alias"))
    assert frozen_outer._sc_emission_coverage() == (True, False)
    assert frozen._sc_frozen_controls["calibration"]["glow_rules"] == ns[
        "_scenelight_control_glow_rules"
    ]([rule])
