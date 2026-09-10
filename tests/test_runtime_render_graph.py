"""Verify the transition graph preserves viewport coordinates and input events."""

import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace


def test_incoming_transition_is_live_clipped_and_forwards_events():
    class Displayable:
        pass

    class Render:
        def __init__(self, width, height):
            self.size = width, height
            self.children = []
            self.shaders = []
            self.properties = {}

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
    assert result.size == (1280, 720)
    assert result.mesh is True
    viewport = result.children[0]
    assert viewport.size == (1280, 720)
    assert viewport.xclipping and viewport.yclipping
    assert viewport.children == [child_render]
    assert result.properties["drawable_resolution"] is True
    assert side.event("input", 20, 30, 0.5) == "handled"
    assert calls[-1] == ("input", 20, 30, 0.5)
