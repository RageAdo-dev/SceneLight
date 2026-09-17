"""Verify the transition graph preserves viewport coordinates and input events."""

import ast
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace


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
    assert "directional_ramp / sqrt(1.0 + directional_ramp * directional_ramp)" in source
    assert "/ sqrt(dot(relative_form_position, relative_form_position) + 0.0064)" in source
    assert "float lower_body_ramp = clamp(" in source
    assert "0.5 + dot(relative_form_position, average_light_direction) * 0.9" not in source
    assert "max(length(relative_form_position), 0.08)" not in source


def _creative_partition_profile(power, steps=513, spread=0.84, surface_tilt=-0.10):
    """Green-lamp share across the sprite's horizontal centre line.

    Mirrors the creative path: each detected hue family gets a lobe built from
    the pixel's surface direction, the lobes are raised to ``sc_creative_power``
    and renormalised.  The radial direction field is the one the shader ships,
    sampled one step per form-map pixel so a handover that completes inside a
    step or two is the hard seam users see.  ``surface_tilt`` stands in for the
    small sideways lean the reconstructed normals of a flat sprite carry.
    """

    directions = ((0.62, -0.78), (-0.90, -0.42))
    normal_z = (1.0 - surface_tilt * surface_tilt) ** 0.5
    profile = []
    for index in range(steps):
        x = -0.5 + index / (steps - 1)
        sx = surface_tilt + _form_direction_field(x) * spread * 1.35
        magnitude = (sx * sx + normal_z * normal_z) ** 0.5
        sx = sx / magnitude
        influences = []
        for dx, dy in directions:
            lobe = min(1.0, max(0.035, 0.50 + 0.50 * (sx * dx + 0.0 * dy)))
            lambert = min(1.0, max(0.035, dx * surface_tilt + 0.45 * normal_z))
            influences.append(max(lambert * (1.0 - spread) + lobe * spread, 1e-6) ** power)
        profile.append(influences[0] / sum(influences))
    return profile


def _form_direction_field(x):
    """The radial direction ramp the sprite shader feeds into the lobes."""

    return x / (x * x + 0.0064) ** 0.5


def _handover_width(profile):
    """Form-map pixels between the 10% and 90% points of the lamp handover."""

    low = min(profile)
    inside = [
        index
        for index, value in enumerate(profile)
        if low + 0.1 * (1.0 - low) < value < low + 0.9 * (1.0 - low)
    ]
    return 0.0 if not inside else float(inside[-1] - inside[0] + 1)


def _runtime_source():
    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    return path.read_text()


def test_creative_light_partition_widens_the_lamp_handover():
    """The per-lamp handover must read as a gradient, not a cut.

    The exponent used to be ``2.0 + 3.0 * evidence`` (5.0 at a typical single
    detected hue family, 8.0 with two), which turns the renormalised lobes into
    a winner-take-all partition: the border between two lamps lands on the
    artwork as a straight-edged region across a face, hands or cardigan.  The
    regions, lamp colours and lighting model are unchanged here; only the width
    of the handover moves.
    """

    source = _runtime_source()
    match = re.search(
        r"float sc_creative_power = ([0-9.]+)"
        r"\s*\n\s*\+ ([0-9.]+) \* sc_individual_light_colors;",
        source,
    )
    assert match, "sc_creative_power is no longer a linear exponent"
    base, slope = float(match.group(1)), float(match.group(2))
    assert base < 2.0 and slope < 3.0, (base, slope)

    for evidence in (1.0, 2.0):
        old = _handover_width(_creative_partition_profile(2.0 + 3.0 * evidence))
        new = _handover_width(_creative_partition_profile(base + slope * evidence))
        assert new > 1.9 * old, (evidence, old, new)
        assert new >= 30.0, (evidence, old, new)
