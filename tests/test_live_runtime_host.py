import ast
import copy
import gc
import sys
import textwrap
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenelight.runtime.live_renpy import Renderer, TextureUploadState


def test_restored_backgrounds_are_routed_without_a_new_show_statement():
    path = Path(__file__).resolve().parents[1] / "src/scenelight/runtime/scenelight_runtime.rpy"
    text = path.read_text(encoding="utf-8")
    start = text.index("    def _scenelight_wrap_backgrounds(")
    end = text.index("\n    def ", start + 5)
    node = ast.parse(textwrap.dedent(text[start:end]))

    class Tap:
        def __init__(self, child, key):
            self.child, self.key = child, key

    class Entry:
        def __init__(self, name, tag):
            self.name, self.tag, self.displayable = name, tag, object()

        def copy(self):
            return copy.copy(self)

    room, dynamic, sprite = (
        Entry(("room", "day"), "room"),
        Entry(("bg", "procedural"), "bg"),
        Entry(("actor", "idle"), "actor"),
    )
    owner = SimpleNamespace(layers={"master": [room, dynamic, sprite]})
    namespace = {
        "renpy": SimpleNamespace(display=SimpleNamespace(_scenelight_live_renderer=object())),
        "_SceneLightBackground": Tap,
        "_SCENELIGHT_STRING_TYPES": (str,),
        "SCENELIGHT_SCENES": {"room day": {}},
        "SCENELIGHT_SCENE_SEQUENCES": {},
    }
    exec(compile(node, str(path), "exec"), namespace)
    start = text.index("    def _scenelight_unwrap_replaced_background(")
    end = text.index("\n    def ", start + 5)
    node = ast.parse(textwrap.dedent(text[start:end]))
    exec(compile(node, str(path), "exec"), namespace)
    wrap = namespace["_scenelight_wrap_backgrounds"]
    assert wrap(owner)
    assert owner.layers["master"][0].displayable.child is room.displayable
    assert owner.layers["master"][1].displayable.child is dynamic.displayable
    assert owner.layers["master"][2] is sprite
    assert not wrap(owner)
    namespace["_scenelight_unwrap_replaced_background"](owner, "room")
    assert owner.layers["master"][0].displayable is room.displayable
    assert isinstance(owner.layers["master"][1].displayable, Tap)
    assert wrap(owner)


class Render:
    def __init__(self, width=1280, height=720):
        self.size = width, height

    def get_size(self):
        return self.size


class Frame:
    pass


class Background:
    def __init__(self):
        self.placement = (0, 0, 0, 0, 0, 0, False)
        self.child = SimpleNamespace(get_placement=lambda: self.placement, place=lambda *args: None)


class State:
    def __init__(self, gl):
        self.gl = gl

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_current_store_copy_shares_the_showing_binding():
    renderer, _, _, _, _ = renderer_fixture()
    background = Background()
    background.binding = Frame()
    displayed_copy = copy.copy(background)
    renderer.capture(displayed_copy, Render(), 1280, 720, Frame)
    assert renderer.frame(background) is renderer.frame(displayed_copy)
    assert renderer.fields(renderer.frame(background)) is not None


def test_texture_upload_restores_pixel_unpack_and_texture_state_on_failure():
    import pytest

    values = {0x84E0: 0x84C3, 0x8069: 12, 0x88EF: 9, 0x0CF5: 8, 0x0CF2: 33, 0x0CF3: 2, 0x0CF4: 4}
    original = dict(values)
    gl = SimpleNamespace(
        integer=lambda key: values[key],
        ActiveTexture=lambda value: values.update({0x84E0: value}),
        BindTexture=lambda target, value: values.update({0x8069: value}),
        BindBuffer=lambda target, value: values.update({0x88EF: value}),
        PixelStorei=lambda key, value: values.update({key: value}),
    )
    with pytest.raises(RuntimeError):
        with TextureUploadState(SimpleNamespace(TEXTURE0=0x84C0, TEXTURE_2D=0x0DE1), gl):
            assert values[0x88EF] == 0
            assert [values[key] for key in (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)] == [4, 0, 0, 0]
            raise RuntimeError("upload failed")
    assert values == original


def test_prepared_texture_pool_preserves_frozen_frames_and_reuses_released_frames():
    from scenelight.runtime.prepared import FIELDS

    renderer, draw, analysis, _, errors = renderer_fixture()
    gl = analysis.device.gl
    gl.TexSubImage2D = lambda *args: None
    gl.integer = lambda key: 0
    gl.BindBuffer = gl.PixelStorei = lambda *args: None
    renderer.gpu.RGBA, renderer.gpu.UNSIGNED_BYTE = 0x1908, 0x1401
    raw = {name: b"\0" * (width * height * 4) for name, width, height in FIELDS}
    current = [0]
    renderer.prepared = SimpleNamespace(frame=lambda *args: (("texture", current[0]), raw))
    background = Background()
    renderer.capture(background, Render(), 1280, 720, Frame)
    frozen = renderer.frame(background)
    first = {value.number for value in renderer.fields(frozen).values()}
    current[0] = 1
    renderer.capture(background, Render(), 1280, 720, Frame)
    second = {value.number for value in renderer.fields(renderer.frame(background)).values()}
    assert first.isdisjoint(second)
    assert not renderer.prepared_pool
    del frozen
    gc.collect()
    assert len(renderer.prepared_pool) == 1
    current[0] = 2
    renderer.capture(background, Render(), 1280, 720, Frame)
    assert {value.number for value in renderer.fields(renderer.frame(background)).values()} == first
    assert renderer.prepared_frames == 3
    renderer.capture(background, Render(), 1280, 720, Frame)
    assert renderer.prepared_frames == 3
    assert draw.current_fbo == 7
    assert not errors


def test_light_history_is_isolated_between_background_bindings():
    renderer, _, analysis, _, _ = renderer_fixture()
    histories = []

    def evaluate(*args, **kwargs):
        histories.append(kwargs["previous"])
        return dict(
            zip(
                ("irradiance", "emitter", "wrap", "transport", "_history_lights", "_history_image"),
                range(6),
            )
        )

    analysis.evaluate = evaluate
    first, second = Background(), Background()
    renderer.capture(first, Render(), 1280, 720, Frame)
    fields = renderer.fields(renderer.frame(first))
    expected = tuple(fields[k].number for k in ("_history_lights", "_history_image"))
    renderer.capture(second, Render(), 1280, 720, Frame)
    renderer.capture(first, Render(), 1280, 720, Frame)
    assert histories == [(), (), expected]


def test_time_shader_updates_even_when_the_child_render_is_cached(monkeypatch):
    renderer, _, _, copies, _ = renderer_fixture()
    renderer.api.game = SimpleNamespace(interface=SimpleNamespace(frame_time=1.0))
    parts = {
        "example.time": SimpleNamespace(uniforms=["u_time"]),
        "example.static": SimpleNamespace(uniforms=["u_color"]),
    }
    monkeypatch.setitem(sys.modules, "renpy.gl2.gl2shadercache", SimpleNamespace(shader_part=parts))
    background, source = Background(), Render()
    source.children = [(SimpleNamespace(shaders=("example.time",)), (0, 0))]
    renderer.capture(background, source, 1280, 720, Frame)
    first = renderer.frame(background)
    assert renderer.animated(background)
    snapshot = Frame()
    assert renderer.pin_canvas(background, snapshot)
    pinned = renderer.frozen_canvas(snapshot)
    renderer.api.game.interface.frame_time = 1.016
    renderer.capture(background, source, 1280, 720, Frame)
    assert renderer.frame(background) is not first
    assert len(copies) == 8
    assert renderer.frozen_canvas(snapshot) == pinned
    assert renderer.canvas(background)[0].cached_texture is not pinned[0]
    del snapshot
    gc.collect()
    assert not renderer.frozen_canvases
    assert not Renderer._animated_shader(SimpleNamespace(shaders=("example.static",)))


def test_shader_clock_detection_supports_older_renpy_declarations(monkeypatch):
    parts = {
        "example.time": SimpleNamespace(
            vertex_variables={("uniform", "float", "u_time")}, fragment_variables=set()
        ),
        "example.static": SimpleNamespace(
            vertex_variables=set(), fragment_variables={("uniform", "vec4", "u_color")}
        ),
    }
    monkeypatch.setitem(sys.modules, "renpy.gl2.gl2shadercache", SimpleNamespace(shader_part=parts))
    assert Renderer._animated_shader(SimpleNamespace(shaders=("example.time",)))
    assert not Renderer._animated_shader(SimpleNamespace(shaders=("example.static",)))


def test_leaking_engine_is_stopped_before_per_frame_allocations():
    renderer, draw, _, copies, errors = renderer_fixture()
    allocated_bytes = [0]
    draw.texture_loader = SimpleNamespace(get_texture_size=lambda: (allocated_bytes[0], 1))
    original = draw.render_to_texture

    def leaking_texture(render, **kwargs):
        allocated_bytes[0] += 16
        return original(render, **kwargs)

    draw.render_to_texture = leaking_texture
    renderer.capture(Background(), Render(), 1280, 720, Frame)
    assert renderer.disabled
    assert not copies
    assert not renderer.frames
    assert draw.current_fbo == 7
    assert "leaks graphics textures" in errors[0]


def renderer_fixture():
    copies, loaded, errors = [], [], []
    draw = SimpleNamespace(texture_loader=object(), current_fbo=7)
    allocated = []

    def to_texture(render, **kwargs):
        draw.current_fbo = 9
        texture = SimpleNamespace(
            number=100 + len(allocated), texture_width=render.size[0], texture_height=render.size[1]
        )
        allocated.append(texture)
        render.cached_texture = texture
        return texture

    draw.load_all_textures = loaded.append
    draw.render_to_texture = to_texture
    gl = SimpleNamespace(
        ActiveTexture=lambda *args: None,
        BindTexture=lambda *args: None,
        CopyTexSubImage2D=lambda *args: copies.append(args),
    )
    device = SimpleNamespace(gl=gl, bind_targets=lambda *args: None)
    outputs = dict(zip(("irradiance", "emitter", "wrap", "transport"), range(1, 5)))
    analysis = SimpleNamespace(device=device, evaluate=lambda *args, **kwargs: outputs)
    gpu = SimpleNamespace(
        Analysis=lambda: analysis, State=State, TEXTURE0=0x84C0, TEXTURE_2D=0x0DE1
    )
    api = SimpleNamespace(
        game=SimpleNamespace(interface=SimpleNamespace(frame_time=1.0)),
        Render=Render,
        display=SimpleNamespace(draw=draw, log=SimpleNamespace(write=errors.append)),
    )
    return Renderer(gpu, api, None), draw, analysis, copies, errors


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("upload_fails", [False, True])
def test_snapshot_resolves_samplers_before_allocation_and_restores_state(
    monkeypatch, modern, upload_fails
):
    renderer, draw, _, _, _ = renderer_fixture()
    source, allocated, loaded = Render(), [], []
    monkeypatch.setitem(sys.modules, "renpy.display.matrix", SimpleNamespace(MatrixStack=tuple))

    def prepare(what):
        loaded.append(what)
        draw.current_fbo = 99
        if upload_fails:
            raise RuntimeError("sampler upload failed")
        what.samplers_ready = True

    def load_modern(what, reverse):
        assert reverse == (1, 0, 0, 1)
        prepare(what)

    def allocate(what):
        allocated.append(what)
        assert what.samplers_ready  # Native RTT otherwise leaks before its draw fails.
        return "snapshot"

    draw.load_all_textures = load_modern if modern else prepare
    draw.render_to_texture = allocate
    if upload_fails:
        with pytest.raises(RuntimeError, match="sampler upload failed"):
            renderer.snapshot(source)
        assert not allocated
    else:
        assert renderer.snapshot(source) == "snapshot"
        assert allocated == [source]
    assert loaded == [source]
    assert draw.current_fbo == 7


def test_new_renderer_receives_identity_texture_transform(monkeypatch):
    renderer, draw, _, _, errors = renderer_fixture()
    loaded = []
    monkeypatch.setitem(sys.modules, "renpy.display.matrix", SimpleNamespace(MatrixStack=tuple))

    def load(what, reverse):
        loaded.append((what, reverse))

    draw.load_all_textures = load
    background = Background()
    renderer.capture(background, Render(), 1280, 720, Frame)
    assert loaded[0][1] == (1, 0, 0, 1)
    assert renderer.evaluations == 1
    assert not errors


def test_texture_loader_internal_type_error_is_not_retried():
    renderer, draw, _, _, errors = renderer_fixture()
    loaded = []

    def load(what):
        loaded.append(what)
        raise TypeError("texture upload failed internally")

    draw.load_all_textures = load
    renderer.capture(Background(), Render(), 1280, 720, Frame)
    assert len(loaded) == 1
    assert renderer.disabled
    assert "texture upload failed internally" in errors[0]


def test_static_render_reuses_analysis_and_changes_preserve_frozen_fields():
    renderer, draw, _, copies, _ = renderer_fixture()
    background = Background()
    source = Render()
    renderer.capture(background, source, 1280, 720, Frame)
    frozen = renderer.frame(background)
    original_fields = renderer.fields(frozen)
    assert len(copies) == 4
    assert draw.current_fbo == 7
    renderer.capture(background, source, 1280, 720, Frame)
    assert renderer.frame(background) is frozen
    assert len(copies) == 4

    renderer.capture(background, Render(), 1280, 720, Frame)
    current = renderer.frame(background)
    assert current is not frozen
    assert renderer.fields(frozen) is original_fields
    assert {v.number for v in renderer.fields(current).values()}.isdisjoint(
        v.number for v in original_fields.values()
    )
    assert len(renderer.frames) == 2
    del frozen
    gc.collect()
    assert len(renderer.frames) == 1
    del background
    gc.collect()
    assert not renderer.backgrounds


def test_retired_source_graph_is_released_while_rollback_keeps_its_lighting():
    renderer, _, _, _, errors = renderer_fixture()
    retired_background, source = Background(), Render()
    source_reference = weakref.ref(source)
    renderer.capture(retired_background, source, 1280, 720, Frame)
    frozen_frame = renderer.frame(retired_background)
    frozen_fields = renderer.fields(frozen_frame)
    source.killed = True  # Ren'Py's completed mark/sweep, not merely a cache miss.
    del source
    renderer.api.game.interface.frame_time += 1.0
    renderer.capture(Background(), Render(), 1280, 720, Frame)
    gc.collect()
    assert source_reference() is None
    assert renderer.fields(frozen_frame) is frozen_fields
    assert renderer.frame(retired_background) is frozen_frame
    assert not errors


def test_placement_changes_reanalyze_and_context_recreation_discards_old_handles():
    renderer, draw, _, copies, _ = renderer_fixture()
    background, source = Background(), Render()
    renderer.capture(background, source, 1280, 720, Frame)
    old = renderer.frame(background)
    background.placement = (20, 0, 0, 0, 0, 0, False)
    renderer.capture(background, source, 1280, 720, Frame)
    assert len(copies) == 8
    draw.texture_loader = object()
    renderer.capture(background, source, 1280, 720, Frame)
    assert renderer.fields(old) is None
    assert renderer.frame(background) is not None
    assert draw.current_fbo == 7


def test_failed_analysis_restores_host_state_and_stops_returning_stale_frames():
    renderer, draw, analysis, _, errors = renderer_fixture()
    background = Background()
    renderer.capture(background, Render(), 1280, 720, Frame)
    frozen = renderer.frame(background)

    def fail(*args, **kwargs):
        raise RuntimeError("Injected device failure")

    analysis.evaluate = fail
    renderer.capture(background, Render(), 1280, 720, Frame)
    assert renderer.disabled
    assert renderer.frame(background) is None
    assert renderer.fields(frozen) is not None
    assert draw.current_fbo == 7
    assert "Injected device failure" in errors[0]
