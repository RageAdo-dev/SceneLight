import json
import zipfile
from types import SimpleNamespace

import pytest

from scenelight.prepared import Writer
from scenelight.runtime.prepared import FIELDS, VERSION, Reader


def test_movie_install_requires_playback_components_instead_of_silent_live_fallback(
    tmp_path, monkeypatch
):
    from scenelight import prepared

    monkeypatch.setattr(prepared.importlib.util, "find_spec", lambda name: None)
    discovery = SimpleNamespace(game_root=tmp_path, scene_media={"movie": tmp_path / "clip.webm"})
    with pytest.raises(RuntimeError, match="playback components"):
        prepared.prepare_project_movies(discovery)
    assert not (tmp_path / "scenelight_runtime/prepared_movies.json").exists()


def test_static_install_does_not_launch_movie_preparation(tmp_path, monkeypatch):
    from scenelight import prepared

    def unexpected(*args, **kwargs):
        raise AssertionError("Static scenes must not launch movie preparation")

    monkeypatch.setattr(prepared.subprocess, "run", unexpected)
    monkeypatch.setattr(prepared.importlib.util, "find_spec", lambda name: None)
    assert (
        prepared.prepare_project_movies(SimpleNamespace(game_root=tmp_path, scene_media={})) == {}
    )
    assert json.loads((tmp_path / "scenelight_runtime/prepared_movies.json").read_text()) == {}


def fields(seed):
    return {
        name: bytes((seed + index) % 256 for index in range(width * height * 4))
        for name, width, height in FIELDS
    }


def test_lossless_frames_random_access_and_bounded_memory(tmp_path):
    path = tmp_path / "movie.slframes"
    writer = Writer(path, {"frame_count": 5, "engine": "current", "preview": True})
    try:
        for index in range(5):
            writer.append(fields(index))
        writer.finish()
    finally:
        writer.close()
    reader = Reader(str(path), {"engine": "current", "preview": True})
    try:
        for index in (0, 4, 2, 0, 1, 3):
            assert reader.frame(index) == fields(index)
            assert len(reader.frames) <= 2
        with pytest.raises(IndexError):
            reader.frame(5)
    finally:
        reader.close()
    with pytest.raises(ValueError, match="engine"):
        Reader(str(path), {"engine": "old"})
    with pytest.raises(ValueError, match="preview"):
        Reader(str(path), {"preview": False})


def test_interrupted_preparation_preserves_previous_cache(tmp_path):
    path = tmp_path / "movie.slframes"
    path.write_bytes(b"existing cache")
    writer = Writer(path, {"frame_count": 2})
    writer.append(fields(0))
    with pytest.raises(ValueError, match="Incomplete"):
        writer.finish()
    writer.close()
    assert path.read_bytes() == b"existing cache"
    assert list(tmp_path.iterdir()) == [path]


def test_rejects_missing_or_malformed_frame(tmp_path):
    path = tmp_path / "broken.slframes"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", '{"version":%d,"frame_count":1}' % VERSION)
        archive.writestr("frames/0", b"short")
    with pytest.raises(ValueError, match="size"):
        Reader(str(path))


def test_ambiguous_sample_never_selects_different_lighting(tmp_path):
    path = tmp_path / "ambiguous.slframes"
    writer = Writer(path, {"frame_count": 4})
    try:
        writer.append(fields(0), "ambiguous")
        writer.append(fields(1), "ambiguous")
        writer.append(fields(2), "identical")
        writer.append(fields(2), "identical")
        writer.finish()
    finally:
        writer.close()
    reader = Reader(str(path))
    try:
        assert reader.signatures["ambiguous"] is None
        assert reader.signatures["identical"] == 2
    finally:
        reader.close()


def test_prepare_publishes_all_frames_and_warm_open_needs_no_analyzer(tmp_path, monkeypatch):
    from PIL import Image

    from scenelight import prepared

    source = tmp_path / "animation.gif"
    images = [Image.new("RGBA", (32, 32), (value, 30, 40, 255)) for value in (10, 20, 30)]
    images[0].save(source, save_all=True, append_images=images[1:], duration=50, loop=0)
    closed, started, progress = [], [], []

    class Builder:
        def __init__(self, **kwargs):
            pass

        def frame(self, rgba):
            return fields(int(rgba[0, 0, 0]))

        def close(self):
            closed.append(True)

    monkeypatch.setattr(prepared, "FramePreparer", Builder)
    target = tmp_path / "animation.slframes"
    result = prepared.prepare(
        source,
        target,
        preview=True,
        on_started=started.append,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert not result["cached"]
    assert result["frame_count"] == 3
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert closed == [True]
    assert len(started) == 1 and not started[0].exists()
    monkeypatch.setattr(
        prepared, "FramePreparer", lambda **kwargs: pytest.fail("warm cache rebuilt")
    )
    assert prepared.prepare(source, target, preview=True)["cached"]
