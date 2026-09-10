"""Execute the shipped Ren'Py resolver, not a second implementation of its math."""

import ast
import copy
import gc
import textwrap
import weakref
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names):
    source = path.read_text(encoding="utf-8")
    namespace = {}
    for name in names:
        start = source.index(f"    def {name}(")
        tail = source[start:]
        end = tail.find("\n    def ", 5)
        function = ast.parse(textwrap.dedent(tail[:end]))
        exec(
            compile(ast.Module(body=[function.body[0]], type_ignores=[]), str(path), "exec"),
            namespace,
        )
    return namespace


@pytest.fixture
def runtime():
    ns = load_functions(
        ROOT / "src/scenelight/runtime/scenelight_runtime.rpy",
        [
            "_scenelight_visible_sources",
            "_scenelight_movie_position",
            "_scenelight_movie_texture_hook",
            "_scenelight_lerp_scene_value",
            "_scenelight_blended_scene",
            "_scenelight_timed_scene",
            "_scenelight_transport_frame",
        ],
    )
    ns.update(
        SCENELIGHT_SCENES={"room": {"id": "base"}, "red": {"id": "red"}, "blue": {"id": "blue"}},
        SCENELIGHT_SCENE_SEQUENCES={},
    )
    ns["renpy"] = NS(game=NS(interface=NS(frame_time=100.0)), music=NS(), log=lambda text: None)
    ns["_SCENELIGHT_UNSEEN_TEMPORAL_STATES"] = set()
    ns["_SCENELIGHT_MOVIE_CLOCK_FRAME"] = None
    ns["_SCENELIGHT_MOVIE_POSITIONS"] = {}
    ns["_SceneLightMapping"] = Mapping
    ns["copy"] = copy
    ns["dict"] = type("RevertableDict", (dict,), {})
    return ns


def test_presented_movie_cache_releases_textures_in_a_rollback_enabled_runtime(runtime):
    history = []

    class RevertableDict(dict):
        def __setitem__(self, key, value):
            if key in self:
                history.append(self[key])
            super().__setitem__(key, value)

    class RenpyLiterals(ast.NodeTransformer):
        # Ren'Py's compiler wraps literals in its rollback-dict constructor.
        def visit_Dict(self, node):
            assert not node.keys
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="__renpy__dict__", ctx=ast.Load()), args=[node], keywords=[]
                ),
                node,
            )

    path = ROOT / "src/scenelight/runtime/scenelight_runtime.rpy"
    line = next(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("renpy.display._scenelight_presented_movies =")
    )
    runtime.update(__renpy__dict__=RevertableDict, _SceneLightOrderedDict=OrderedDict)
    runtime["renpy"].display = NS()
    code = ast.fix_missing_locations(RenpyLiterals().visit(ast.parse(line)))
    exec(compile(code, str(path), "exec"), runtime)
    cache = runtime["renpy"].display._scenelight_presented_movies

    class Texture:
        pass

    old = Texture()
    reference = weakref.ref(old)
    cache["movie"] = ("background.webm", 0.0, old, "signature")
    del old
    cache["movie"] = ("background.webm", 0.1, Texture(), "next-signature")
    gc.collect()
    assert reference() is None
    assert not history


def test_dynamic_follows_visible_child_not_elapsed_guess_or_dialogue(runtime):
    runtime["SCENELIGHT_SCENE_SEQUENCES"]["room"] = {
        "mode": "visible-source",
        "sources": {"red.png": "red", "blue.png": "blue"},
    }
    dynamic = NS(child=NS(filename="red.png"))
    entry = NS(displayable=dynamic, show_time=50, animation_time=50)
    resolve = runtime["_scenelight_timed_scene"]
    for index in range(101):
        color = "blue" if index % 2 else "red"
        dynamic.child = NS(filename=color + ".png")
        runtime["renpy"].game.interface.frame_time += 0.18
        assert resolve("room", entry)["id"] == color
    # An unobserved state cannot leak the last known lighting.
    dynamic.child = NS(filename="unseen.png")
    assert resolve("room", entry) is None


def test_legacy_animation_short_frames_and_independent_timebases(runtime):
    sources = runtime["_scenelight_visible_sources"]
    animation = NS(
        images=[NS(filename="a"), NS(filename="b")], delays=[0.11, 0.045], anim_timebase=True
    )
    assert sources(animation, 0, 0.112) == ["b"]
    assert sources(animation, 0, 0.156) == ["a"]
    animation.anim_timebase = False
    assert sources(animation, 0.112, 0) == ["b"]


def test_source_walk_does_not_execute_callbacks_or_visit_all_animation_frames(runtime):
    def fail(*_args):
        raise AssertionError("Callback must not be invoked a second time")

    dynamic = NS(child=NS(filename="actual.png"), visit=fail, function=fail)
    dynamic.target = dynamic
    assert runtime["_scenelight_visible_sources"](dynamic) == ["actual.png"]


def test_movie_uses_decoder_position_including_pause_seek_loop_and_expression(runtime):
    Movie = type("Movie", (), {})
    movie = Movie()
    movie.channel = "independent-video-channel"
    entry = NS(displayable=NS(child=movie), show_time=1, animation_time=1)
    runtime["SCENELIGHT_SCENE_SEQUENCES"]["room"] = {
        "mode": "movie-position",
        "source": "clip.webm",
        "duration_ms": 5000,
        "frames": [[0, "red"], [100, "blue"]],
    }
    runtime["renpy"].music.get_playing = lambda **_: "clip.webm"
    for position, expected in [
        (0, "red"),
        (0.13, "blue"),
        (0.13, "blue"),
        (0, "red"),
        (4.999, "blue"),
        (None, "base"),
    ]:
        runtime["renpy"].music.get_pos = lambda **_: position
        runtime["renpy"].game.interface.frame_time += 0.04
        assert runtime["_scenelight_timed_scene"]("room", entry)["id"] == expected
    runtime["renpy"].music.get_playing = lambda **_: "other.webm"
    assert runtime["_scenelight_timed_scene"]("room", entry)["id"] == "base"


def test_static_field_is_unchanged_without_a_timeline(runtime):
    assert runtime["_scenelight_timed_scene"]("room") is runtime["SCENELIGHT_SCENES"]["room"]


def test_movie_lighting_blends_between_samples_without_moving_atlas_tiles(runtime):
    left = {"uv": [0.0, 0.0, 0.5, 1.0], "local_luminance": 0.1}
    right = {"uv": [0.5, 0.0, 0.5, 1.0], "local_luminance": 0.5}
    blend = runtime["_scenelight_blended_scene"]
    assert blend(left, right, 0) is left
    assert blend(left, right, 1) is right
    middle = blend(left, right, 0.5)
    assert middle["uv"] == left["uv"]
    assert middle["_sc_next_uv"] == right["uv"]
    assert middle["local_luminance"] == pytest.approx(0.3)
    assert middle["_sc_blend"] == 0.5
    assert "_sc_blend" not in left


def test_movie_cut_holds_prior_lighting_until_the_authored_boundary(runtime):
    movie = type("Movie", (), {})()
    movie.channel = "movie"
    entry = NS(displayable=movie, show_time=1, animation_time=1)
    runtime["SCENELIGHT_SCENE_SEQUENCES"]["room"] = {
        "mode": "movie-position",
        "source": "cut.webm",
        "frames": [[0, "red"], [100, "blue"]],
        "cuts_ms": [100],
    }
    runtime["renpy"].music.get_playing = lambda **_: "cut.webm"
    runtime["renpy"].music.get_pos = lambda **_: 0.099
    assert runtime["_scenelight_timed_scene"]("room", entry) is runtime["SCENELIGHT_SCENES"]["red"]
    runtime["renpy"].game.interface.frame_time += 0.01
    runtime["renpy"].music.get_pos = lambda **_: 0.100
    assert runtime["_scenelight_timed_scene"]("room", entry) is runtime["SCENELIGHT_SCENES"]["blue"]


def test_all_characters_share_movie_clock_within_a_frame(runtime):
    clock = iter([0.124, 0.126])
    runtime["renpy"].music.get_pos = lambda **_: next(clock)
    position = runtime["_scenelight_movie_position"]
    assert position("movie") == 0.124
    assert position("movie") == 0.124
    runtime["renpy"].game.interface.frame_time += 0.04
    assert position("movie") == 0.126


def test_movie_clock_advances_with_the_displayed_texture_not_a_later_audio_tick(runtime):
    textures = {}
    runtime["renpy"].display = NS(video=NS(texture=textures), _scenelight_presented_movies={})
    runtime["renpy"].music.get_playing = lambda **_: "clip.webm"
    positions = iter([0.12, 0.16])
    runtime["renpy"].music.get_pos = lambda **_: next(positions)
    first, second = object(), object()
    decoded = iter([(first, True), (first, False), (second, True)])

    def original(channel):
        result = next(decoded)
        textures[channel] = result[0]
        return result

    hook = runtime["_scenelight_movie_texture_hook"](original)
    position = runtime["_scenelight_movie_position"]
    assert hook("movie") == (first, True)
    assert position("movie") == 0.12
    runtime["renpy"].game.interface.frame_time += 0.01
    assert hook("movie") == (first, False)
    assert position("movie") == 0.12
    runtime["renpy"].game.interface.frame_time += 0.04
    assert hook("movie") == (second, True)
    assert position("movie") == 0.16


def test_capture_and_runtime_use_identical_visible_source_rules():
    names = ["_scenelight_visible_sources"]
    paths = [
        ROOT / "src/scenelight/runtime" / name
        for name in ("scenelight_capture.rpy", "scenelight_runtime.rpy")
    ]
    functions = [load_functions(path, names)[names[0]] for path in paths]
    assert functions[0].__code__.co_code == functions[1].__code__.co_code
    assert functions[0].__code__.co_consts == functions[1].__code__.co_consts


def test_movie_observer_releases_stopped_channels_and_preserves_backend_errors(runtime):
    old, current = object(), object()
    frames = {"stopped": ("old.webm", 0.1, old)}
    runtime["renpy"].display = NS(video=NS(texture={}), _scenelight_presented_movies=frames)

    def unavailable(**_):
        raise RuntimeError("no clock on this backend")

    runtime["renpy"].music.get_playing = unavailable
    hook = runtime["_scenelight_movie_texture_hook"](lambda channel: (current, True))
    assert hook("movie") == (current, True)
    assert not frames

    def broken_decode(channel):
        raise RuntimeError("decoder failed")

    hook = runtime["_scenelight_movie_texture_hook"](broken_decode)
    with pytest.raises(RuntimeError, match="decoder failed"):
        hook("movie")


def test_transport_cache_rebuilds_after_engine_collection_or_renderer_change(runtime):
    class Render:
        killed = False
        cache_killed = False

        def __init__(self, *size):
            self.children = []

        def blit(self, child, position):
            self.children.append(child)

        def add_shader(self, *_):
            pass

        def add_uniform(self, *_):
            pass

    display = NS(draw=object())
    runtime.update(
        _SceneLightOrderedDict=OrderedDict,
        SCENELIGHT_TRANSPORT_ATLAS={},
        Solid=lambda *a, **k: object(),
    )
    runtime["renpy"].display = display
    runtime["renpy"].Render = Render
    runtime["renpy"].render = lambda child, *a: child
    scene = {
        "transport_uv": [0, 0, 0.01, 1],
        "_sc_next_transport_uv": [0.5, 0, 0.01, 1],
        "_sc_blend": 0.5,
    }
    atlas = object()
    prepare = runtime["_scenelight_transport_frame"]
    first = prepare(scene, atlas, 0, 0)
    assert prepare(scene, atlas, 1, 1) is first
    first.killed = True
    first.children.clear()
    second = prepare(scene, atlas, 2, 2)
    assert second is not first and len(second.children) == 2
    second.cache_killed = True
    third = prepare(scene, atlas, 3, 3)
    assert third is not second
    display.draw = object()
    assert prepare(scene, atlas, 4, 4) is not third
