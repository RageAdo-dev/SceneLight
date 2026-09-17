"""Verify the transition graph preserves viewport coordinates and input events."""

import ast
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
