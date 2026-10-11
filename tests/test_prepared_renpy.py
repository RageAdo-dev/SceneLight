import gc
import hashlib
import io
import json
import weakref
from types import SimpleNamespace

import pytest

from scenelight.runtime.prepared_renpy import Movies


class ImageReference:
    def __init__(self, target):
        self.target = target


class TransformState:
    alpha = 1.0
    zoom = 1.0
    matrixcolor = None
    shader = None
    xanchoraround = 0.5


class Transform:
    def __init__(self, child):
        self.child = child
        self.function = None
        self.state = TransformState()
        self.state.xanchoraround = 0.0


class Movie:
    channel = "movie"
    mask = None
    side_mask = False


@pytest.fixture
def host():
    texture = object()
    entry = {"video.webm": {"cache": "frames.slframes", "size": [1280, 720]}}
    files = {
        "scenelight_runtime/prepared_movies.json": json.dumps(entry).encode(),
        "scenelight_runtime/live_gpu.txt": b"gpu",
        "scenelight_runtime/live_opencl.txt": b"cl",
        "video.webm": b"video",
        "frames.slframes": b"cache",
    }
    api = SimpleNamespace(
        file=lambda path: io.BytesIO(files[path]),
        display=SimpleNamespace(
            image=SimpleNamespace(ImageReference=ImageReference),
            transform=SimpleNamespace(
                Transform=Transform,
                TransformState=TransformState,
                all_properties=("alpha", "zoom", "matrixcolor", "shader", "xanchoraround"),
            ),
            video=SimpleNamespace(Movie=Movie, texture={"movie": texture}),
            _scenelight_presented_movies={"movie": ("video.webm", 1.125, texture, "decoded-frame")},
            log=SimpleNamespace(write=lambda _: None),
        ),
        music=SimpleNamespace(get_playing=lambda **_: "video.webm"),
    )
    reader = SimpleNamespace(
        metadata={"fps": 24},
        count=120,
        signatures={"decoded-frame": 28},
        frame=lambda index: {"index": index},
    )
    return Movies(api, lambda stream, expected: reader), Transform(ImageReference(Movie()))


def test_neutral_engine_wrapper_uses_decoded_frame_instead_of_clock(host):
    movies, child = host
    key, fields = movies.frame(
        SimpleNamespace(child=child), SimpleNamespace(get_size=lambda: (1280, 720)), 1280, 720
    )
    assert key[1] == 28
    assert fields == {"index": 28}
    # A newer audio time cannot advance lighting while its decoded texture is held.
    assert (
        movies.frame(
            SimpleNamespace(child=child), SimpleNamespace(get_size=lambda: (1280, 720)), 1280, 720
        )[1]
        == fields
    )


def test_prepared_identity_reuses_verified_fields_without_retaining_decoder_textures(host):
    movies, child = host
    display = movies.api.display

    class Texture:
        pass

    old = Texture()
    reference = weakref.ref(old)
    display.video.texture["movie"] = old
    display._scenelight_presented_movies["movie"] = ("video.webm", 1.0, old, "decoded-frame")
    args = SimpleNamespace(child=child), SimpleNamespace(get_size=lambda: (1280, 720)), 1280, 720
    old_key, fields = movies.frame(*args)
    replacement = Texture()
    display.video.texture["movie"] = replacement
    display._scenelight_presented_movies["movie"] = (
        "video.webm",
        6.0,
        replacement,
        "decoded-frame",
    )
    new_key, repeated_fields = movies.frame(*args)
    del old
    gc.collect()
    assert reference() is None
    assert old_key == new_key == ("video.webm", 28)
    assert fields == repeated_fields

    movies.entries["other.webm"] = movies.entries["video.webm"]
    original_file = movies.api.file
    movies.api.file = lambda name: original_file("video.webm" if name == "other.webm" else name)
    movies.api.music.get_playing = lambda **_: "other.webm"
    display._scenelight_presented_movies["movie"] = (
        "other.webm",
        1.0,
        replacement,
        "decoded-frame",
    )
    other_key, _ = movies.frame(*args)
    assert other_key != old_key


@pytest.mark.parametrize(
    "property,value",
    [("alpha", 0.5), ("zoom", 1.1), ("matrixcolor", object()), ("shader", "custom")],
)
def test_visual_transform_keeps_actual_render_analysis(host, property, value):
    movies, child = host
    setattr(child.state, property, value)
    assert (
        movies.frame(
            SimpleNamespace(child=child), SimpleNamespace(get_size=lambda: (1280, 720)), 1280, 720
        )
        is None
    )


def test_stale_texture_and_mask_cannot_reuse_movie_fields(host):
    movies, child = host
    child.child.target.mask = "mask.webm"
    args = SimpleNamespace(child=child), SimpleNamespace(get_size=lambda: (1280, 720)), 1280, 720
    assert movies.frame(*args) is None
    child.child.target.mask = None
    movies.api.display.video.texture["movie"] = object()
    assert movies.frame(*args) is None


def test_decode_observer_matches_preparer_sampling_without_second_decode(host):
    import numpy as np

    movies, _ = host
    pixels = np.random.default_rng(42).integers(0, 256, (73, 129, 4), dtype=np.uint8)
    surface = SimpleNamespace(get_size=lambda: (129, 73), get_at=lambda xy: pixels[xy[1], xy[0]])
    calls = []

    class Channel:
        name = "movie"

        def read_video(self):
            calls.append(1)
            return surface

    movies.api.audio = SimpleNamespace(audio=SimpleNamespace(Channel=Channel))
    movies.install_decode_hook()
    assert Channel().read_video() is surface
    assert calls == [1]
    sample = pixels[(np.arange(9) * 73 // 9)[:, None], np.arange(16) * 129 // 16]
    assert movies.decoded["movie"] == ("video.webm", hashlib.sha256(sample.tobytes()).hexdigest())
