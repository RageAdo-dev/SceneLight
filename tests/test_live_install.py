from types import SimpleNamespace

import numpy as np
from PIL import Image

from scenelight.capture import (
    CaptureResult,
    _merge_video_scene_sequences,
    _project_signature,
    merge_capture,
)
from scenelight.cli import _install_runtime_files, _runtime_source
from scenelight.project import ProjectDiscovery


def test_installed_runtime_contains_exact_shared_solver_and_host_adapter(tmp_path):
    _install_runtime_files(tmp_path)
    for name in (
        "live_gpu",
        "live_renpy",
        "live_opencl",
        "shader_stages",
        "shader_renpy",
        "inspector",
    ):
        assert (
            tmp_path / "scenelight_runtime" / (name + ".txt")
        ).read_bytes() == _runtime_source().with_name(name + ".py").read_bytes()
    assert (
        tmp_path / "scenelight_runtime/inspector.rpy"
    ).read_bytes() == _runtime_source().with_name("inspector.rpy").read_bytes()


def test_live_movie_install_decodes_only_first_frame(tmp_path, monkeypatch):
    from scenelight.preview import media

    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(
        tmp_path, game, {}, {}, [], scene_media={"room": game / "movie.mp4"}
    )
    calls = []

    class Clip:
        identity = "fixture-identity"

        def __init__(self, *args):
            pass

        def frame_by_index(self, index):
            calls.append(index)
            return SimpleNamespace(rgba=np.full((18, 32, 4), 255, np.uint8))

        def temporal_cut_indices(self):
            raise AssertionError("A live install must not scan the movie")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(media, "MediaClip", Clip)
    _merge_video_scene_sequences(discovery)
    assert calls == [0, "close"]
    assert list(discovery.scenes) == ["room"]
    assert not discovery.scene_sequences
    with Image.open(discovery.scenes["room"]) as image:
        assert image.size == (32, 18)


def test_live_install_does_not_expand_cached_capture_timelines(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    first, second = game / "first.png", game / "second.png"
    Image.new("RGB", (32, 18)).save(first)
    Image.new("RGB", (32, 18), "white").save(second)
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, [])
    capture = CaptureResult(
        scenes={"room": first},
        sprites={},
        character_tags=[],
        resolved_requests=[],
        errors=[],
        cached=True,
        background_inventory_requested=True,
        scene_requests=1,
        scene_sequences={"room": [(0, first), (25, second)]},
    )
    merge_capture(discovery, capture)
    assert discovery.scenes == {"room": first}
    assert not discovery.scene_sequences
    signature = _project_signature(discovery)
    discovery.scene_analysis = "cached"
    assert _project_signature(discovery) != signature
