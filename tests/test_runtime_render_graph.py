"""Verify the transition graph preserves viewport coordinates and input events."""

import ast
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenelight.runtime.shader_data import SHADERS


def test_incoming_transition_is_live_in_transition_coordinates_and_forwards_events():
    class Displayable:
        pass

    class Render:
        def __init__(self, width, height):
            self.size = width, height
            self.children = []
            self.shaders = []
            self.properties = {}
            self.mesh = False

        def blit(self, child, position):
            self.children.append(child)

        def add_shader(self, name):
            self.shaders.append(name)

        def add_property(self, name, value):
            self.properties[name] = value

    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    source = path.read_text()
    start = source.index("    class _SceneLightLiveTransitionSide(")
    end = source.index("    # Scene-wide transitions", start)
    node = ast.parse(textwrap.dedent(source[start:end])).body[0]
    calls = []
    child_render = Render(1600, 1000)
    child = SimpleNamespace(
        get_placement=lambda: (0, 0, 0, 0, 0, 0, False),
        event=lambda *args: calls.append(args) or "handled",
    )
    namespace = {
        "renpy": SimpleNamespace(
            Displayable=Displayable,
            Render=Render,
            render=lambda *args: calls.append(args) or child_render,
            config=SimpleNamespace(mipmap_dissolves=False),
        ),
        "config": SimpleNamespace(screen_width=1280, screen_height=720),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    side = namespace["_SceneLightLiveTransitionSide"](child)
    result = side.render(1280, 720, 0.4, 0.8)
    assert calls == [(child, 1280, 720, 0.4, 0.8)]
    # The incoming side must be handed back exactly as Ren'Py rendered it. An
    # extra clipped or mesh-wrapped render put this side in a different
    # coordinate system from the outgoing side, which scaled the scene wrongly
    # and made screen-space sprite lighting sample outside its field, showing up
    # as an opaque black sprite quad and a black silhouette mid-transition.
    assert result is child_render
    assert result.size == (1600, 1000)
    assert result.mesh is False
    assert result.children == []
    assert result.properties == {}
    assert side.event("input", 20, 30, 0.5) == "handled"
    assert calls[-1] == ("input", 20, 30, 0.5)


def test_live_scene_resolution_never_mixes_live_uvs_with_packaged_fields():
    """A frame without fields must not keep live-atlas coordinates.

    The sprite samples the live field textures at live UVs. When a frame
    survives the binding lookup but its fields were retired (a window resize
    drops them), returning the live UVs alongside the packaged atlas mixes two
    coordinate spaces: the character is shaded from unrelated texels instead of
    falling back to lighting that matches the textures it is given.
    """

    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    source = path.read_text()
    start = source.index("    def _scenelight_resolve_live_scene(scene):")
    end = source.index("\n    def ", start + 10)
    node = ast.parse(textwrap.dedent(source[start:end])).body[0]

    packaged = {"room": {"uv": (0.25, 0.5, 0.1, 0.1)}}
    live_scene = {"_sc_live_binding": "binding", "_sc_live_key": "room", "uv": (0.0, 0.0, 1.0, 1.0)}

    class Renderer:
        def __init__(self, fields):
            self._fields = fields

        def frame(self, binding):
            return object()

        def fields(self, frame):
            return self._fields

    def resolve(fields):
        namespace = {
            "renpy": SimpleNamespace(
                display=SimpleNamespace(_scenelight_live_renderer=Renderer(fields))
            ),
            "SCENELIGHT_SCENES": packaged,
            "_scenelight_live_fields": lambda scene: None,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        return namespace["_scenelight_resolve_live_scene"](live_scene)

    # A frame that still owns its fields may use live-atlas coordinates.
    assert resolve({"irradiance": object()})["uv"] == (0.0, 0.0, 1.0, 1.0)
    # Without them, fall back to the packaged entry whose UVs match its atlas.
    assert resolve(None) is packaged["room"]


def test_sprite_space_ramps_have_no_hard_saturation_edges():
    """A clamped sprite-space ramp draws a straight line across the character.

    Three terms in the fragment shader vary with position across the sprite
    rather than with the surface: the directional bias along the light, a
    direction field around the sprite centre, and the ground bounce that rises
    up the lower body. Each was written as a linear ramp with a hard clamp, so
    shading stops changing on one side of the saturation line and keeps ramping
    on the other. That discontinuity is the straight seam users see across a
    face, sleeve or cardigan. The shader now uses saturating forms that keep
    the middle slope and the limits but bend into them.
    """

    def slope_jump(values, spacing):
        slopes = [(b - a) / spacing for a, b in zip(values, values[1:])]
        return max(abs(b - a) for a, b in zip(slopes, slopes[1:]))

    steps = 400
    spacing = 0.01
    domain = [-spacing * steps / 2 + spacing * i for i in range(steps)]

    def smooth_directional(x):
        ramp = x * 1.8
        return 0.5 + 0.5 * ramp / (1.0 + ramp * ramp) ** 0.5

    def clamped_directional(x):
        return min(1.0, max(0.0, 0.5 + 0.9 * x))

    def smooth_lower_body(y):
        ramp = min(1.0, max(0.0, (y + 0.30) * 1.45))
        return ramp * ramp * (3.0 - 2.0 * ramp)

    def clamped_lower_body(y):
        return min(1.0, max(0.0, (y + 0.30) * 1.45))

    smooth_direction = slope_jump([smooth_directional(x) for x in domain], spacing)
    clamped_direction = slope_jump([clamped_directional(x) for x in domain], spacing)
    smooth_bounce = slope_jump([smooth_lower_body(y) for y in domain], spacing)
    clamped_bounce = slope_jump([clamped_lower_body(y) for y in domain], spacing)

    assert clamped_direction > 0.4
    assert smooth_direction < clamped_direction / 4.0
    assert clamped_bounce > 0.4
    assert smooth_bounce < clamped_bounce / 4.0

    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    source = path.read_text()
    source += "\n" + "\n".join(SHADERS.values())
    assert "directional_ramp / sqrt(1.0 + directional_ramp * directional_ramp)" in source
    assert "/ sqrt(dot(relative_form_position, relative_form_position) + 0.0064)" in source
    assert "float lower_body_ramp = clamp(" in source
    assert "0.5 + dot(relative_form_position, average_light_direction) * 0.9" not in source
    assert "max(length(relative_form_position), 0.08)" not in source


def _runtime_source():
    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    return path.read_text()


def test_ray_occlusion_requires_height_map_without_flattening_fallback_lighting():
    """Painted eyes can shape local normals, but cannot cast distant shadows.

    Source guard for the exact classroom engine A/B: only missing-map ray
    occlusion is rejected. This does not establish visual correctness by itself;
    matched engine captures cover that, and render tests cover enabled lighting.
    """
    source = _runtime_source()
    source += "\n" + "\n".join(SHADERS.values())
    ray = source.split("float scenelight_ray_shadow(", 1)[1].split(
        "void scenelight_accumulate_probe(", 1
    )[0]
    ray = re.sub(r"//[^\n]*", "", ray)
    body = ray.split(") {", 1)[1].strip()
    assert re.match(r"if\s*\(u_sc_has_form\s*<\s*0\.5\)\s*return\s+0\.0;", body)
    # A matching prepared map still runs the existing multi-tap shadow search.
    assert body.index("return 0.0;") < body.index("float center_height")
    assert "for (int ray_step = 1; ray_step <= 6; ray_step++)" in body
    assert "scenelight_height(ray_uv, source_texture, lod_bias)" in body
    assert "return clamp(shadow * 4.4, 0.0, 1.0) * step(0.001, alpha);" in body

    normal = source.split("vec3 scenelight_form_normal(", 1)[1].split(
        "vec4 scenelight_light_vector_weight(", 1
    )[0]
    # The fallback remains directional relief derived from the actual source,
    # rather than the all-flat normal workaround that also hid the artifact.
    assert "if (u_sc_has_form > 0.5)" in normal
    for direction in ("left", "right", "up", "down"):
        assert f"float height_{direction} = scenelight_height(" in normal
    assert "(height_left - height_right) * 2.8" in normal
    assert "(height_up - height_down) * 2.8" in normal
    assert "return normalize(vec3(" in normal
    assert "return vec3(0.0, 0.0, 1.0)" not in normal
    assert (
        "vec3 normal = scenelight_form_normal(v_tex_coord, sprite_texel, tex0, u_lod_bias);"
        in source
    )
    assert (
        "scenelight_filtered_lambert(light0.xyz, normal, normal1, normal2, normal3, normal4)"
        in source
    )


@pytest.mark.parametrize("has_form", [False, True])
@pytest.mark.parametrize("viewport", [(1280, 720), (1920, 1080)])
def test_sprite_lighting_uses_child_dimensions_with_or_without_form_map(has_form, viewport):
    """Both lighting paths bind the sprite canvas, independently of the viewport."""
    import copy

    class Stop(Exception):
        pass

    class Displayable:
        def __init__(self, **properties):
            pass

    class Render:
        def __init__(self, *size):
            builds.append(size)

        def blit(self, rendered_child, position):
            assert rendered_child is child_render
            assert position == (0, 0)

        def add_uniform(self, name, value):
            uniforms[name] = value
            raise Stop()

    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    source = path.read_text(encoding="utf-8")
    start = source.index("    class SceneLightSprite(")
    end = source.index("    def _scenelight_authored_grade_strength(", start)
    node = ast.parse(textwrap.dedent(source[start:end])).body[0]

    builds = []
    uniforms = {}
    child_render = SimpleNamespace(get_size=lambda: (640, 960))
    child = SimpleNamespace()
    form_entry = {
        "normal_noise": "normal",
        "height_ao_edge": "height",
        "response": "response",
        "source_size": (512, 512),
        "response_size": (64, 64),
        "center": (0.5, 0.5),
        "mean_form_visibility": 1.0,
        "contrast_mid": 0.5,
        "height_range": (-0.25, 1.25),
        "noise_range": 4.0,
    }
    controls = {"enabled": True, "strength": 1.0, "calibration": {}}
    scene = {"uv": (0.0, 0.0, 1.0, 1.0)}
    namespace = {
        "renpy": SimpleNamespace(
            Displayable=Displayable,
            Render=Render,
            displayable=lambda value: value,
            render=lambda *args: child_render,
            redraw=lambda *args: None,
            get_game_runtime=lambda: 0.0,
        ),
        "persistent": SimpleNamespace(scenelight_enabled=True, scenelight_strength=1.0),
        "copy": copy,
        "SCENELIGHT_PROFILE_STRENGTH": 1.0,
        "SCENELIGHT_FORM_FALLBACK": {
            "normal_noise": "fallback-normal",
            "height_ao_edge": "fallback-height",
            "response": "fallback-response",
        },
        "SCENELIGHT_ATLAS": {"irradiance": "i", "emitter": "e", "wrap": "w"},
        "SCENELIGHT_TRANSPORT_ATLAS": {"texture": "t"},
        "SCENELIGHT_STABLE_SCENE_KEY": "_sc_stable",
        "SCENELIGHT_SCENE_SEQUENCES": {},
        "SCENELIGHT_LAST_PRESENTED_SCENE": None,
        "_SCENELIGHT_SHADER_AVAILABLE": True,
        "_scenelight_texture": lambda spec: spec,
        "_scenelight_resolve_form_entry": lambda *args: form_entry if has_form else None,
        "_scenelight_live_scene_entry": lambda: ("scene-key", scene),
        "_scenelight_control_snapshot": lambda *args: controls,
        "_scenelight_fx_snapshot": lambda name: {},
        "_scenelight_resolve_live_scene": lambda value: value,
        "_scenelight_active_custom_effects": lambda effects: [],
        "_scenelight_sprite_emitters": lambda tag: (),
        "_scenelight_color_glow_rules": lambda *args: (),
        "_scenelight_emission_controls": lambda scene, tag, controls: controls,
        "_scenelight_fx_active": lambda name: False,
        "_scenelight_calibration_blocks": lambda *args: ((1.0, 0.0, 1.0, 1.0),),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    sprite_class = namespace["SceneLightSprite"]
    _load_runtime_definitions(
        namespace, "_scenelight_master_enabled", "_scenelight_master_strength"
    )

    sprite = sprite_class(child, ("sayori", "1a"))
    assert sprite.has_form is has_form
    # Stop at the first uniform binding; execute the real render method up to
    # that boundary without simulating the engine's GPU texture allocation.
    with pytest.raises(Stop):
        sprite.render(*viewport, 0.0, 0.0)
    assert builds == [(640, 960)]
    assert uniforms == {"u_sc_sprite_size": (640.0, 960.0)}

    # Turning lighting off still returns the original render in either path.
    controls["enabled"] = False
    builds.clear()
    uniforms.clear()
    assert sprite.render(*viewport, 0.0, 0.0) is child_render
    assert builds == []
    assert uniforms == {}


def test_sprite_shader_does_not_depend_on_sampler_allocation_resolution():
    """Ren'Py's res0 can describe a light-field sampler rather than tex0."""
    from scenelight.runtime.shader_data import SHADERS

    shader = "\n".join(SHADERS.values())
    assert not re.search(r"\bres0\b", shader)
    assert "uniform vec2 u_sc_sprite_size;" in shader
    assert "vec2 sprite_texel = 1.0 / max(u_sc_sprite_size, vec2(1.0));" in shader


def _load_runtime_definitions(namespace, *names):
    """Execute the real init definitions without starting an engine or GPU."""
    if "SceneLightSprite" in names:
        names += ("_scenelight_master_enabled", "_scenelight_master_strength")
    source = _runtime_source()
    nodes = []
    for name in names:
        match = re.search(r"^    (?:def|class) " + re.escape(name) + r"\b", source, re.M)
        assert match, name
        following = re.search(r"^    (?:def|class) |^init ", source[match.end() :], re.M)
        end = match.end() + following.start() if following else len(source)
        nodes.append(ast.parse(textwrap.dedent(source[match.start() : end])).body[0])
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "runtime-definitions", "exec"), namespace)
    return namespace


def test_form_map_matches_complete_attributes_not_another_expression():
    mouth_closed = {"normal_noise": "closed-mouth.png"}
    mouth_open = {"normal_noise": "open-mouth.png"}
    entries = {
        "monika forward afternoon cm e1a": mouth_closed,
        "monika forward afternoon md e1a": mouth_open,
        "monika": {"normal_noise": "default-expression.png"},
    }
    namespace = _load_runtime_definitions(
        {
            "SCENELIGHT_FORM_SPRITES": entries,
            "SCENELIGHT_FORM_CANDIDATES": {
                "monika": [
                    (frozenset(name.split()[1:]), name, value) for name, value in entries.items()
                ]
            },
        },
        "_scenelight_resolve_form_entry",
    )
    resolve = namespace["_scenelight_resolve_form_entry"]
    assert resolve("monika forward afternoon md e1a", "monika") is mouth_open
    assert resolve("monika e1a md afternoon forward", "monika") is mouth_open
    assert resolve("monika forward afternoon cm e1a", "monika") is mouth_closed
    # Neither an underspecified alias nor an uncaptured mouth can borrow a map
    # carrying painted details from a different expression.
    assert resolve("monika forward afternoon", "monika") is None
    assert resolve("monika forward afternoon mo e1a", "monika") is None


def test_image_alias_wraps_resolved_attributes_and_preserves_authored_grade():
    calls = []
    raw_composite = object()
    original = SimpleNamespace(
        _duplicate=lambda args: calls.append(args) or raw_composite,
        marker="original",
    )
    namespace = _load_runtime_definitions(
        {
            "SceneLightSprite": lambda child, image_name, form_key, **kwargs: SimpleNamespace(
                child=child, image_name=image_name, form_key=form_key, **kwargs
            ),
            "_scenelight_authored_grade_strength": lambda child: 0.75,
        },
        "SceneLightImageLike",
    )
    alias = namespace["SceneLightImageLike"](original, ("sayori", "turned"))
    arguments = SimpleNamespace(name=("sayori", "turned"), args=("md", "e1b"))
    wrapped = alias._duplicate(arguments)
    assert wrapped.child is raw_composite
    assert wrapped.form_key == ("sayori", "turned", "md", "e1b")
    assert wrapped.authored_grade_strength == 0.75
    assert calls == [arguments]
    assert alias.marker == "original"


def _registration_runtime():
    import copy

    class Transform:
        def __init__(self, child, marker):
            self.child = child
            self.marker = marker
            self.state = SimpleNamespace(matrixcolor=None)

        def _change_transform_child(self, child):
            replacement = copy.copy(self)
            if isinstance(self.child, Transform):
                replacement.child = self.child._change_transform_child(child)
            else:
                replacement.child = child
            return replacement

    class Sprite:
        def __init__(self, child, image_name, **kwargs):
            self.child = child
            self.image_name = tuple(image_name)
            self._sc_scene_boundary = True
            self.authored_grade_strength = kwargs.get("authored_grade_strength", 0.0)

    namespace = {
        "renpy": SimpleNamespace(
            display=SimpleNamespace(transform=SimpleNamespace(Transform=Transform))
        ),
        "SceneLightSprite": Sprite,
        "SCENELIGHT_CHARACTER_TAGS": {"sayori", "monika"},
        "_SCENELIGHT_STRING_TYPES": (str, bytes),
        "_SCENELIGHT_SHADER_AVAILABLE": True,
        "_scenelight_authored_grade_strength": lambda child: 0.75,
    }
    _load_runtime_definitions(namespace, "SceneLightImageLike")
    namespace["_scenelight_get_registered_image"] = lambda name: None
    return namespace, Transform, Sprite


def test_loaded_sprite_rebinds_current_map_once_without_changing_its_child():
    class Displayable:
        pass

    selected = None
    resolutions = []
    redraws = []
    fallback = {
        "normal_noise": "fallback-n",
        "height_ao_edge": "fallback-h",
        "response": "fallback-r",
    }
    namespace = _load_runtime_definitions(
        {
            "renpy": SimpleNamespace(
                Displayable=Displayable, redraw=lambda *args: redraws.append(args)
            ),
            "SCENELIGHT_FORM_FALLBACK": fallback,
            "_scenelight_resolve_form_entry": lambda *args: resolutions.append(args) or selected,
            "_scenelight_texture": lambda path: ("texture", path),
            "_scenelight_fx_active": lambda tag: False,
        },
        "SceneLightSprite",
    )
    sprite_class = namespace["SceneLightSprite"]
    sprite = sprite_class.__new__(sprite_class)
    sprite._sc_exposure_coefficients = lambda: (1.0, 0.0, 1.0)
    child = object()
    sprite.__dict__.update(
        child=child,
        image_name=("sayori",),
        form_key="sayori turned md",
        base_form_key="sayori",
        _sc_snapshot_frozen=False,
        _sc_last_rendered_scene=None,
        form_entry={"normal_noise": "old-expression"},
        has_form=True,
    )
    # Ren'Py Object.__setstate__ calls after_setstate after restoring the dict.
    # It must not resolve textures while the save graph is being unpickled.
    sprite.after_setstate()
    assert resolutions == []
    selected = {"normal_noise": "new-n", "height_ao_edge": "new-h", "response": "new-r"}
    sprite.per_interact()
    assert sprite.child is child
    assert sprite.has_form
    assert sprite.form_entry is selected
    assert sprite.form_normal_noise == ("texture", "new-n")
    assert sprite.form_height_ao_edge == ("texture", "new-h")
    assert sprite.form_response == ("texture", "new-r")
    assert resolutions == [("sayori turned md", "sayori")]
    assert redraws == [(sprite, 0.0)]
    sprite.per_interact()
    assert len(resolutions) == 1
    # A removed map also clears all stale texture bindings after a load.
    selected = None
    sprite.after_setstate()
    sprite.per_interact()
    assert sprite.form_entry is None
    assert not sprite.has_form
    assert sprite.form_normal_noise == ("texture", "fallback-n")
    assert sprite.form_height_ao_edge == ("texture", "fallback-h")
    assert sprite.form_response == ("texture", "fallback-r")


@pytest.mark.parametrize("replacement_name", [("sayori", "1l"), "sayori 1l"])
@pytest.mark.parametrize("mapped", [False, True])
def test_retained_transform_rebinds_map_to_named_replacement(replacement_name, mapped):
    import copy

    class Displayable:
        def _copy(self):
            return copy.copy(self)

    class ImageReference:
        def __init__(self, name):
            self.name = name

    old_map = {"normal_noise": "old-n", "height_ao_edge": "old-h", "response": "old-r"}
    new_map = {"normal_noise": "new-n", "height_ao_edge": "new-h", "response": "new-r"}
    fallback = {
        "normal_noise": "fallback-n",
        "height_ao_edge": "fallback-h",
        "response": "fallback-r",
    }
    resolved = []

    def resolve(form_key, base_key):
        resolved.append((form_key, base_key))
        return new_map if mapped and form_key == "sayori 1l" else None

    namespace = _load_runtime_definitions(
        {
            "renpy": SimpleNamespace(
                Displayable=Displayable,
                display=SimpleNamespace(image=SimpleNamespace(ImageReference=ImageReference)),
            ),
            "_SCENELIGHT_STRING_TYPES": (str,),
            "SCENELIGHT_FORM_FALLBACK": fallback,
            "_scenelight_resolve_form_entry": resolve,
            "_scenelight_texture": lambda path: ("texture", path),
        },
        "SceneLightSprite",
    )
    sprite_class = namespace["SceneLightSprite"]
    sprite = sprite_class.__new__(sprite_class)
    old_child = ImageReference(("sayori", "turned", "e1b", "me", "rup"))
    placement = object()
    sprite.__dict__.update(
        child=old_child,
        image_name=("guest", "turned", "e1b", "me", "rup"),
        form_key="sayori turned e1b me rup",
        base_form_key="sayori turned",
        form_entry=old_map,
        has_form=True,
        authored_grade_strength=1.0,
        style=placement,
        _sc_last_rendered_scene={"uv": (0, 0, 1, 1)},
    )
    replacement = ImageReference(replacement_name)
    updated = sprite._change_transform_child(replacement)
    assert updated is not sprite
    assert updated.child is replacement
    assert updated.form_key == updated.base_form_key == "sayori 1l"
    assert updated.image_name == ("guest", "1l")
    assert resolved == [("sayori 1l", "sayori 1l")]
    assert updated.has_form is mapped
    assert updated.form_entry is (new_map if mapped else None)
    selected = new_map if mapped else fallback
    for field in ("normal_noise", "height_ao_edge", "response"):
        assert getattr(updated, "form_" + field) == ("texture", selected[field])
    assert updated.authored_grade_strength == 1.0
    assert updated.style is placement
    assert updated._sc_last_rendered_scene is sprite._sc_last_rendered_scene
    assert sprite.child is old_child
    assert sprite.form_entry is old_map
    assert sprite.form_key == "sayori turned e1b me rup"
    # The router may already supply a fully wrapped replacement.
    assert sprite._change_transform_child(updated) is updated
    assert len(resolved) == 1
    # ImageReference can also contain an anonymous displayable. It has no
    # resolved image identity from which to derive a replacement map key.
    anonymous = ImageReference(object())
    unchanged = sprite._change_transform_child(anonymous)
    assert unchanged.child is anonymous
    assert unchanged.form_key == sprite.form_key
    assert len(resolved) == 1


def test_character_registration_preserves_existing_wrappers_and_wraps_new_aliases():
    namespace, _, Sprite = _registration_runtime()
    _load_runtime_definitions(namespace, "SceneLightImageLike", "scenelight_register_tag")
    raw = object()
    alias = namespace["SceneLightImageLike"](raw, ("sayori",))
    registry = {
        ("sayori",): alias,
        ("sayori", "tap"): Sprite(raw, ("sayori", "tap")),
        ("sayori", "new"): raw,
        ("monika",): object(),
        ("bg", "room"): object(),
    }
    namespace.update(
        {
            "SCENELIGHT_CHARACTER_TAGS": set(),
            "SCENELIGHT_WRAPPED_IMAGES": [],
            "_scenelight_registered_image_names": lambda: [" ".join(name) for name in registry],
            "_scenelight_get_registered_image": registry.get,
        }
    )
    namespace["renpy"].Displayable = Sprite
    namespace["renpy"].image = lambda name, value: registry.__setitem__(name, value)
    before_monika = registry[("monika",)]
    register = namespace["scenelight_register_tag"]
    register("sayori")
    register("sayori")
    register("bg")
    register("")
    namespace["SCENELIGHT_MANIFEST"] = {"excluded_character_tags": ["monika"]}
    register("monika")
    assert namespace["SCENELIGHT_CHARACTER_TAGS"] == {"sayori"}
    assert registry[("sayori",)] is alias
    assert isinstance(registry[("sayori", "tap")], Sprite)
    assert registry[("sayori", "new")].original is raw
    assert registry[("monika",)] is before_monika
    assert namespace["SCENELIGHT_WRAPPED_IMAGES"] == ["sayori new"]


@pytest.mark.parametrize("keyword_arguments", [False, True])
def test_scene_router_wraps_final_character_only_on_master(keyword_arguments):
    namespace, Transform, Sprite = _registration_runtime()
    _load_runtime_definitions(namespace, "_scenelight_route_scene_add")
    namespace.update(
        {
            "_scenelight_unwrap_replaced_background": lambda *args: None,
            "_scenelight_wrap_backgrounds": lambda *args: None,
            "_scenelight_redraw_visible_sprites": lambda *args: None,
        }
    )
    route = namespace["_scenelight_route_scene_add"]
    owner = object()
    calls = []

    def add(current_owner, *args, **kwargs):
        assert current_owner is owner
        child = kwargs["thing"] if "thing" in kwargs else args[1]
        calls.append(child)
        return "engine-result"

    composite = object()
    original = Transform(composite, "ATL")
    name = ("sayori", "turned", "md")
    for layer, tag in (("master", "sayori"), ("screens", "sayori"), ("master", "prop")):
        args = (layer, original, tag, None, None, None, name)
        kwargs = {}
        if keyword_arguments:
            args = ()
            kwargs = {"layer": layer, "thing": original, "key": tag, "name": name}
        assert route(add, owner, args, kwargs) == "engine-result"
        if layer == "master" and tag == "sayori":
            assert isinstance(calls[-1].child, Sprite)
            assert calls[-1].child.child is composite
            assert calls[-1].child.image_name == name
        else:
            assert calls[-1] is original

    wrapped = calls[0]
    namespace["_scenelight_get_registered_image"] = lambda name: Sprite(composite, name)
    assert (
        route(add, owner, ("master", wrapped, "sayori", None, None, None, name), {})
        == "engine-result"
    )
    assert calls[-1] is wrapped


def _exposure_runtime():
    import copy

    defaults = ast.literal_eval(
        re.search(
            r"^    _SCENELIGHT_CALIBRATION_DEFAULTS = (\{.*?^    \})",
            _runtime_source(),
            re.M | re.S,
        ).group(1)
    )

    class Displayable:
        def __init__(self, **properties):
            pass

        def _copy(self):
            return copy.copy(self)

        def _in_current_store(self):
            return self

        def visit(self):
            return []

    redraws = []
    namespace = _load_runtime_definitions(
        {
            "renpy": SimpleNamespace(
                Displayable=Displayable,
                displayable=lambda child: child,
                redraw=lambda *args: redraws.append(args),
                display=SimpleNamespace(image=SimpleNamespace(), transform=SimpleNamespace()),
                store=SimpleNamespace(),
                get_game_runtime=lambda: 0.0,
            ),
            "copy": copy,
            "persistent": SimpleNamespace(scenelight_enabled=True, scenelight_strength=1.0),
            "SCENELIGHT_PROFILE_STRENGTH": 1.0,
            # Nonidentity bias exercises ownership of both independent terms.
            "SCENELIGHT_MANIFEST": {"calibration": {"auto_strength": 1.0, "exposure_bias": 0.25}},
            "_SCENELIGHT_SHADER_AVAILABLE": True,
            "_SCENELIGHT_STRING_TYPES": (str,),
            "_SCENELIGHT_CONTROL_ALIASES": {},
            "_SCENELIGHT_INITIAL_CONTROL_STATE": {
                "version": 1,
                "revision": 0,
                "defaults": {},
                "scene": {},
                "backgrounds": {},
                "characters": {},
                "images": {},
            },
            "_SCENELIGHT_CONTROL_KEYS": set(defaults) | {"enabled", "strength"},
            "_SCENELIGHT_CALIBRATION_DEFAULTS": defaults,
            "SCENELIGHT_FORM_FALLBACK": {
                "normal_noise": "n",
                "height_ao_edge": "h",
                "response": "r",
            },
            "SCENELIGHT_ATLAS": {"irradiance": "i", "emitter": "e"},
            "SCENELIGHT_TRANSPORT_ATLAS": {},
            "_scenelight_texture": lambda path: path,
            "_scenelight_resolve_form_entry": lambda *args: None,
            "_scenelight_fx_active": lambda tag: False,
            "_scenelight_fx_snapshot": lambda tag: {},
            "_scenelight_live_scene_entry": lambda: ("room", {"uv": (0, 0, 1, 1)}),
            "_scenelight_resolve_live_scene": lambda scene: scene,
        },
        "SceneLightSprite",
        "_scenelight_control_initial_state",
        "_scenelight_control_current_state",
        "_scenelight_control_assign",
        "_scenelight_control_name",
        "_scenelight_control_values",
        "_scenelight_control_glow_rules",
        "_scenelight_control_update",
        "_scenelight_control_snapshot",
        "_scenelight_control_group_for_tag",
        "_scenelight_control_group_anchor",
        "_scenelight_calibration_blocks",
        "_scenelight_emission_controls",
        "_scenelight_color_glow_rules",
        "_SceneLightAPI",
    )
    return namespace["SceneLightSprite"], Displayable, redraws


@pytest.mark.parametrize(
    "grades, expected",
    [
        ([0.0, 1.0, 0.0], [(True, True), (False, False), (False, False)]),
        ([1.0, 0.0], [(False, True), (True, False)]),
        ([1.0, 1.0], [(False, True), (False, False)]),
        ([0.0], [(True, True)]),
    ],
)
def test_exposure_and_bias_are_owned_once_without_removing_form_passes(grades, expected):
    sprite_class, Displayable, redraws = _exposure_runtime()
    child = Displayable()
    wrappers = []
    for grade in grades:
        child = sprite_class(child, ("yuri",), authored_grade_strength=grade)
        wrappers.append(child)
    wrappers[-1].per_interact()
    assert [(s._sc_exposure_owner, s._sc_exposure_bias_owner) for s in wrappers] == expected
    # Wrappers and authored grades survive unchanged; only exposure is owned.
    for index, sprite in enumerate(wrappers):
        assert sprite.authored_grade_strength == grades[index]
        if index:
            assert sprite.child is wrappers[index - 1]
    initial_redraws = list(redraws)
    wrappers[-1].per_interact()
    assert redraws == initial_redraws


def test_exposure_owner_is_stable_for_shared_subtrees_and_multiple_characters():
    sprite_class, Displayable, redraws = _exposure_runtime()
    shared = sprite_class(Displayable(), ("yuri",))
    alias1 = sprite_class(shared, ("yuri", "first"))
    alias2 = sprite_class(shared, ("yuri", "second"))
    monika = sprite_class(Displayable(), ("monika",))
    for sprite in (alias1, shared, monika, alias2, alias1):
        sprite._sc_prepare_exposure_ownership()
    assert shared._sc_exposure_owner and shared._sc_exposure_bias_owner
    assert monika._sc_exposure_owner and monika._sc_exposure_bias_owner
    assert not alias1._sc_exposure_owner and not alias2._sc_exposure_owner
    assert redraws == []


def test_exposure_ownership_resolves_late_reference_and_replacement_children():
    sprite_class, Displayable, redraws = _exposure_runtime()

    class ImageReference(Displayable):
        target = None

        def visit(self):
            if self.target is None:
                self.target = sprite_class(Displayable(), ("yuri", "new"))
            return [self.target]

    sprite_class.render.__globals__["renpy"].display.image.ImageReference = ImageReference
    reference = ImageReference()
    outer = sprite_class(reference, ("yuri",))
    outer.per_interact()
    first_target = reference.target
    assert first_target._sc_exposure_owner
    assert not outer._sc_exposure_owner
    # Ren'Py can resolve a new target after per_interact. Render performs this
    # same subtree refresh after the child renders and before uniform binding.
    reference.target = None
    outer._sc_prepare_exposure_ownership()
    assert reference.target is not first_target
    assert reference.target._sc_exposure_owner
    assert not outer._sc_exposure_owner
    outer.child = Displayable()
    outer._sc_prepare_exposure_ownership()
    assert outer._sc_exposure_owner and outer._sc_exposure_bias_owner
    assert redraws[-1] == (outer, 0.0)


@pytest.mark.parametrize("old_save", [False, True])
def test_loaded_exposure_ownership_recomputes_from_saved_tree(old_save):
    sprite_class, Displayable, _redraws = _exposure_runtime()
    inner = sprite_class(Displayable(), ("yuri",))
    outer = sprite_class(inner, ("yuri", "lamp"))
    if old_save:
        for sprite in (inner, outer):
            del sprite._sc_exposure_owner
            del sprite._sc_exposure_bias_owner
            del sprite._sc_exposure_auto
            del sprite._sc_exposure_bias
            del sprite._sc_exposure_subtree
    else:
        inner._sc_exposure_owner = False
        outer._sc_exposure_owner = True
    for sprite in (inner, outer):
        sprite.after_setstate()
    outer.per_interact()
    assert inner._sc_exposure_owner and inner._sc_exposure_bias_owner
    assert not outer._sc_exposure_owner and not outer._sc_exposure_bias_owner


def test_frozen_transition_keeps_exposure_ownership_when_live_child_changes():
    sprite_class, Displayable, _redraws = _exposure_runtime()
    inner = sprite_class(Displayable(), ("yuri",))
    outer = sprite_class(inner, ("yuri", "lamp"))
    for sprite in (inner, outer):
        sprite._sc_last_rendered_scene = {"uv": (0, 0, 1, 1)}
        sprite._scenelight_screen_rect = lambda: (0, 0, 1, 1)
    frozen = outer._in_current_store()
    assert frozen._sc_snapshot_frozen
    assert frozen.child._sc_snapshot_frozen
    assert frozen.child._sc_exposure_owner and not frozen._sc_exposure_owner
    outer.child = Displayable()
    outer._sc_prepare_exposure_ownership()
    frozen._sc_prepare_exposure_ownership()
    assert outer._sc_exposure_owner
    assert frozen.child._sc_exposure_owner and not frozen._sc_exposure_owner


def test_exposure_ownership_uniforms_gate_only_exposure_terms():
    source = _runtime_source()
    source += "\n" + "\n".join(SHADERS.values())
    assert "uniform float u_sc_exposure_owner;" in source
    assert "uniform float u_sc_exposure_bias_owner;" in source
    assert "uniform float u_sc_exposure_auto;" in source
    assert "uniform float u_sc_exposure_bias;" in source
    assert "auto_amount * sc_environment_adaptation * u_sc_exposure_owner" in source
    assert "u_sc_calibration0.y * u_sc_strength * u_sc_exposure_bias_owner" in source
    assert 'result.add_uniform("u_sc_exposure_owner", float(self._sc_exposure_owner))' in source
    assert (
        'result.add_uniform("u_sc_exposure_bias_owner", float(self._sc_exposure_bias_owner))'
        in source
    )
    render = source.split("    class SceneLightSprite(", 1)[1].split("        def render(", 1)[1]
    assert render.index("child_render = renpy.render(") < render.index(
        "self._sc_prepare_exposure_ownership()"
    )
    assert render.index("self._sc_prepare_exposure_ownership()") < render.index(
        'result.add_uniform("u_sc_exposure_owner"'
    )


@pytest.mark.parametrize("branch_count", [1, 2])
def test_unknown_and_branching_composites_do_not_claim_full_exposure(branch_count):
    sprite_class, Displayable, _ = _exposure_runtime()

    class Composite(Displayable):
        def visit(self):
            return self.children

    inner = sprite_class(Displayable(), ("yuri",))
    composite = Composite()
    composite.children = [inner] + [Displayable()] * (branch_count - 1)
    outer = sprite_class(composite, ("yuri",))
    outer._sc_prepare_exposure_ownership()
    assert inner._sc_exposure_owner
    # A visit dependency is not proof of pixel coverage, even with one child.
    # Preserve the previous composite behavior instead of leaving raw branches
    # unexposed. General partial-coverage exposure is deliberately not inferred.
    assert outer._sc_exposure_owner and outer._sc_exposure_bias_owner


def test_known_whole_image_transform_forwards_exposure_without_changing_shared_child():
    sprite_class, Displayable, redraws = _exposure_runtime()

    class Transform(Displayable):
        def visit(self):
            return [self.child]

    sprite_class.render.__globals__["renpy"].display.transform.Transform = Transform
    inner = sprite_class(Displayable(), ("yuri",))
    transform = Transform()
    transform.child = inner
    outer = sprite_class(transform, ("yuri",))
    outer._sc_prepare_exposure_ownership()
    inner._sc_prepare_exposure_ownership()
    assert inner._sc_exposure_owner and inner._sc_exposure_bias_owner
    assert not outer._sc_exposure_owner and not outer._sc_exposure_bias_owner
    assert redraws == []


@pytest.mark.parametrize(
    "grades, expected",
    [([0, 1, 0], [1, 1, 1]), ([1, 0], [0, 1]), ([1, 1], [0, 0]), ([0.5, 1, 0], [0.5, 0.5, 0.5])],
)
def test_absolute_exposure_survives_mixed_authored_grade_chains(grades, expected):
    sprite_class, Displayable, _ = _exposure_runtime()
    child = Displayable()
    wrappers = []
    for grade in grades:
        child = sprite_class(child, ("yuri",), authored_grade_strength=grade)
        wrappers.append(child)
    child._sc_prepare_exposure_ownership()
    assert [wrapper._sc_exposure_auto for wrapper in wrappers] == expected


def test_incoming_paint_and_new_additive_light_use_separate_exposure():
    source = _runtime_source()
    source += "\n" + "\n".join(SHADERS.values())
    assert (
        "vec3 lit = base * input_exposure * mix(1.0, u_sc_calibration0.z, sc_adjustment_strength)"
        in source
    )
    assert "lit += base * input_exposure * ground_chroma * bounce;" in source
    # Absolute attenuation must survive even when this pass does not own the
    # input multiplier. Otherwise new rim/specular light ignores a dark room.
    assert "float exposure = pow(scene_exposure, u_sc_exposure_auto)" in source
    assert "* exp2(u_sc_exposure_bias);" in source
    assert "lit += sc_rim_chroma * rim * 0.52 * exposure;" in source
    assert "form_detail_visibility * u_sc_strength * exposure;" in source
    assert "float contrast_mid = max(u_sc_form_contrast_mid * exposure, 0.006);" in source


@pytest.mark.parametrize(
    "settings",
    [{"enabled": False}, {"strength": 0.0}, {"auto_strength": 0.0, "exposure_bias": 0.0}],
)
def test_bypassed_inner_image_does_not_claim_outer_exposure(settings):
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    api.image("hero base", **settings)
    outer._sc_prepare_exposure_ownership()
    assert inner._sc_exposure_subtree == (0.0, 0.0)
    assert not inner._sc_exposure_owner and not inner._sc_exposure_bias_owner
    assert outer._sc_exposure_owner and outer._sc_exposure_bias_owner
    assert outer._sc_exposure_subtree == (1.0, 0.25)


@pytest.mark.parametrize("outer_grade", [0.0, 1.0])
def test_distinct_authored_exposure_contributions_accumulate(outer_grade):
    sprite_class, Displayable, redraws = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    inner = sprite_class(Displayable(), ("hero", "base"), authored_grade_strength=0.5)
    outer = sprite_class(inner, ("hero", "alias"), authored_grade_strength=outer_grade)
    api.image("hero base", strength=0.4, auto_strength=0.5, exposure_bias=-2.0)
    api.image("hero alias", strength=1.5, auto_strength=2.0, exposure_bias=1.0)
    outer._sc_prepare_exposure_ownership()
    assert inner._sc_exposure_subtree == pytest.approx((0.1, -0.8))
    assert outer._sc_exposure_subtree == pytest.approx((3.1 - 3.0 * outer_grade, 0.7))
    assert outer._sc_exposure_owner == (outer_grade == 0.0)
    assert outer._sc_exposure_bias_owner
    assert outer._sc_exposure_auto == pytest.approx(3.1 - 3.0 * outer_grade)
    assert outer._sc_exposure_bias == pytest.approx(0.7)
    # The coefficients stay stable whether the cached child is traversed on
    # its own or through its differently calibrated alias.
    inner._sc_prepare_exposure_ownership()
    outer._sc_prepare_exposure_ownership()
    assert redraws == []


@pytest.mark.parametrize(
    "inner_settings, expected, inner_owners, outer_owners",
    [
        ({"auto_strength": 0.0}, (1.0, -0.75), (False, True), (True, True)),
        ({"exposure_bias": 0.0}, (1.0, -1.0), (True, False), (False, True)),
    ],
)
def test_zero_image_coefficients_leave_only_that_term_for_the_outer_alias(
    inner_settings, expected, inner_owners, outer_owners
):
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    api.image("hero base", **inner_settings)
    api.image("hero alias", exposure_bias=-1.0)
    outer._sc_prepare_exposure_ownership()
    assert (inner._sc_exposure_owner, inner._sc_exposure_bias_owner) == inner_owners
    assert (outer._sc_exposure_owner, outer._sc_exposure_bias_owner) == outer_owners
    assert outer._sc_exposure_subtree == expected


def test_control_change_refreshes_both_aliases_without_changing_shared_ownership():
    sprite_class, Displayable, redraws = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    outer._sc_prepare_exposure_ownership()
    api.image("hero base", enabled=False)
    outer._sc_prepare_exposure_ownership()
    assert redraws == [(inner, 0.0), (outer, 0.0)]
    assert not inner._sc_exposure_owner and outer._sc_exposure_owner
    initial_redraws = list(redraws)
    inner._sc_prepare_exposure_ownership()
    outer._sc_prepare_exposure_ownership()
    assert redraws == initial_redraws


def test_outer_authored_bias_survives_repeated_auto_exposure():
    sprite_class, Displayable, redraws = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    api.configure(auto_strength=0.88)
    api.image("hero base", exposure_bias=-2.0)
    api.image("hero alias", exposure_bias=-1.0)
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    outer._sc_prepare_exposure_ownership()
    assert inner._sc_exposure_subtree == (0.88, -2.0)
    assert outer._sc_exposure_subtree == (0.88, -3.0)
    assert not outer._sc_exposure_owner and outer._sc_exposure_bias_owner
    # New highlights use all applied stops, not just this alias's -1 stop.
    assert (outer._sc_exposure_auto, outer._sc_exposure_bias) == (0.88, -3.0)
    inner._sc_prepare_exposure_ownership()
    outer._sc_prepare_exposure_ownership()
    assert redraws == []


@pytest.mark.parametrize("biases, expected", [([-1.0, 1.0, -1.0], 0.0), ([-2.0, -1.0, -2.0], -3.0)])
def test_exposure_deduplicates_all_prior_coefficients_not_their_sum(biases, expected):
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    child = Displayable()
    wrappers = []
    for index, (auto, bias) in enumerate(zip([0.5, 1.0, 0.5], biases, strict=True)):
        name = ("hero", str(index))
        api.image(" ".join(name), auto_strength=auto, exposure_bias=bias)
        child = sprite_class(child, name)
        wrappers.append(child)
    child._sc_prepare_exposure_ownership()
    assert [(s._sc_exposure_owner, s._sc_exposure_bias_owner) for s in wrappers] == [
        (True, True),
        (True, True),
        (False, False),
    ]
    assert child._sc_exposure_subtree == (1.5, expected)


def test_fully_graded_alias_does_not_claim_an_unused_distinct_auto_profile():
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    api.image("hero base", auto_strength=0.5)
    api.image("hero graded", auto_strength=1.5)
    api.image("hero outer", auto_strength=1.5)
    inner = sprite_class(Displayable(), ("hero", "base"))
    graded = sprite_class(inner, ("hero", "graded"), authored_grade_strength=1.0)
    outer = sprite_class(graded, ("hero", "outer"))
    outer._sc_prepare_exposure_ownership()
    assert graded._sc_exposure_auto == 0.5
    assert not graded._sc_exposure_owner
    assert outer._sc_exposure_owner
    assert outer._sc_exposure_auto == 2.0
    assert outer._sc_exposure_bias == 0.25


def test_legacy_frozen_exposure_without_coefficient_history_is_recomputed():
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    api.image("hero base", exposure_bias=-2.0)
    api.image("hero alias", exposure_bias=-1.0)
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    for sprite in (inner, outer):
        sprite._scenelight_screen_rect = lambda: (0, 0, 1, 1)
    frozen = outer._in_current_store()
    del frozen._sc_exposure_terms
    frozen._sc_exposure_subtree = (1.0, -2.0)
    frozen._sc_exposure_bias = -2.0
    api.image("hero alias", exposure_bias=3.0)
    frozen._sc_prepare_exposure_ownership()
    assert frozen._sc_exposure_subtree == (1.0, -3.0)
    assert frozen._sc_exposure_bias == -3.0


def test_transition_exposure_uses_last_rendered_controls_when_live_rules_changed():
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    inner = sprite_class(Displayable(), ("hero", "base"))
    outer = sprite_class(inner, ("hero", "alias"))
    api.image("hero base", strength=0.5, auto_strength=0.4, exposure_bias=-2.0)
    api.image("hero alias", auto_strength=2.0, exposure_bias=2.0)
    outer._sc_prepare_exposure_ownership()
    for sprite in (inner, outer):
        (
            sprite._sc_last_rendered_scene,
            sprite._sc_last_rendered_enabled,
            sprite._sc_last_rendered_strength,
            sprite._sc_last_rendered_effects,
            sprite._sc_last_rendered_effect_time,
            sprite._sc_last_rendered_controls,
        ) = sprite._live_lighting_state()
        sprite._scenelight_screen_rect = lambda: (0, 0, 1, 1)
    api.image("hero base", enabled=False)
    outer._sc_prepare_exposure_ownership()
    frozen = outer._in_current_store()
    assert outer._sc_exposure_subtree == (2.0, 2.0)
    assert frozen._sc_exposure_subtree == pytest.approx((2.2, 1.0))
    assert frozen.child._sc_exposure_subtree == pytest.approx((0.2, -1.0))
    assert frozen.child._sc_exposure_owner and frozen._sc_exposure_owner
    api.image("hero base", enabled=True, exposure_bias=1.0)
    outer._sc_prepare_exposure_ownership()
    frozen._sc_prepare_exposure_ownership()
    assert frozen._sc_exposure_subtree == pytest.approx((2.2, 1.0))


def test_frozen_legacy_ownership_is_recomputed_from_frozen_controls():
    sprite_class, Displayable, _ = _exposure_runtime()
    api = sprite_class.render.__globals__["_SceneLightAPI"]()
    live = sprite_class(Displayable(), ("hero", "base"))
    live._scenelight_screen_rect = lambda: (0, 0, 1, 1)
    api.image("hero base", auto_strength=0.4, exposure_bias=-2.0)
    frozen = live._in_current_store()
    # Earlier ownership state encoded bias presence as a boolean rather than
    # storing its actual stops. It must not be reused as a +1-stop exposure.
    frozen._sc_exposure_subtree = (1.0, True)
    del frozen._sc_exposure_auto
    del frozen._sc_exposure_bias
    api.image("hero base", auto_strength=1.0, exposure_bias=1.0)
    frozen.after_setstate()
    frozen._sc_prepare_exposure_ownership()
    assert frozen._sc_exposure_subtree == (0.4, -2.0)
