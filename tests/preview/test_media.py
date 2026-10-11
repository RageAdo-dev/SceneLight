from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from scenelight.preview.media import (
    MediaClip,
    _digest,
    _verified_video_frame_count,
    environment_wrap,
)
from scenelight.source_types import VIDEO_SOURCE_SUFFIXES


@pytest.mark.parametrize("suffix", sorted(VIDEO_SOURCE_SUFFIXES))
def test_native_movie_formats_use_video_decoder(tmp_path, monkeypatch, suffix):
    source = tmp_path / ("movie" + suffix)
    source.write_bytes(b"decoder selection fixture")
    opened = []
    monkeypatch.setattr(MediaClip, "_open_video", lambda self: opened.append(self.source))
    MediaClip(source, tmp_path / "cache")
    assert opened == [source]


def test_stream_identity_does_not_hash_the_entire_movie(tmp_path, monkeypatch):
    from scenelight.preview import media

    source = tmp_path / "stream.mp4"
    source.write_bytes(b"first version")
    monkeypatch.setattr(MediaClip, "_open", lambda self: None)

    def forbidden(*args):
        raise AssertionError("Streaming must not hash the full movie before opening")

    monkeypatch.setattr(media, "_digest", forbidden)
    first = MediaClip(source, tmp_path / "cache").identity
    assert MediaClip(source, tmp_path / "cache").identity == first
    source.write_bytes(b"second version, changed")
    assert MediaClip(source, tmp_path / "cache").identity != first


def test_video_frame_count_drops_only_verified_empty_tail(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "overreported.mp4"
    source.write_bytes(b"fixture")

    class FakeCapture:
        def __init__(self, _source: str) -> None:
            self.index = 0
            self.position = 0.0

        def isOpened(self) -> bool:
            return True

        def set(self, _property: int, value: float) -> bool:
            self.index = int(value)
            self.position = float(value)
            return True

        def read(self):
            if self.index >= 3:
                self.position = 3.0
                return False, None
            self.position = float(self.index + 1)
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def get(self, _property: int) -> float:
            return self.position

        def release(self) -> None:
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)

    assert _verified_video_frame_count(source, 5, 30.0) == 3


def test_animated_gif_keeps_timing_alpha_and_cached_frames(tmp_path: Path) -> None:
    frames = []
    for index, color in enumerate(((255, 30, 20), (20, 220, 60), (30, 60, 255))):
        rgba = np.zeros((32, 40, 4), dtype=np.uint8)
        rgba[5:28, 6 + index : 30 + index, :3] = color
        rgba[5:28, 6 + index : 30 + index, 3] = 255
        frames.append(Image.fromarray(rgba, "RGBA"))
    source = tmp_path / "sprite.gif"
    frames[0].save(
        source,
        save_all=True,
        append_images=frames[1:],
        duration=(40, 80, 120),
        loop=0,
        disposal=2,
    )

    clip = MediaClip(source, tmp_path / "media-cache")
    try:
        assert clip.kind == "animated-image"
        assert clip.animated
        assert clip.frame_count == 3
        assert clip.index_at(0) == 0
        assert clip.index_at(45) == 1
        assert clip.index_at(130) == 2
        assert clip.index_at(245) == 0
        assert clip.frame_at(45).rgba.shape == (32, 40, 4)
        assert clip.frame_at(45).rgba[..., 3].max() == 255
        assert all(path.is_file() for path in clip.frame_paths)
        assert clip.temporal_anchor_indices() == (0, 1, 2)
    finally:
        clip.close()


@pytest.mark.parametrize("format,suffix", [("MPO", ".jpeg"), ("MPO", ".mpo"), ("TIFF", ".tiff")])
def test_auxiliary_images_and_document_pages_do_not_play_as_animation(tmp_path, format, suffix):
    primary = Image.new("RGB", (40, 32), (40, 145, 215))
    auxiliary = Image.new("RGB", (40, 32), (65, 65, 65))
    source = tmp_path / ("still" + suffix)
    primary.save(source, format=format, save_all=True, append_images=[auxiliary])
    original = source.read_bytes()
    with Image.open(source) as image:
        assert image.n_frames == 2
        expected = np.asarray(image.convert("RGBA"))

    # Even an extracted animation left by an older build must be ignored.
    cache = tmp_path / "cache"
    stale = cache / _digest(source)
    stale.mkdir(parents=True)
    primary.save(stale / "frame_000000.png")
    auxiliary.save(stale / "frame_000001.png")
    (stale / "media.json").write_text(
        '{"frames":["frame_000000.png","frame_000001.png"],"durations_ms":[100,100],"size":[40,32]}'
    )
    clip = MediaClip(source, cache)
    try:
        assert clip.kind == "static"
        assert not clip.animated and clip.frame_count == 1
        assert clip.reference_path == source
        for timestamp in (0, 100, 200, 350, 1000, 10_000):
            frame = clip.frame_at(timestamp)
            assert frame.index == 0
            np.testing.assert_array_equal(frame.rgba, expected)
    finally:
        clip.close()
    assert source.read_bytes() == original


def test_actual_animation_is_detected_from_content_not_extension(tmp_path):
    source = tmp_path / "animation.jpeg"
    Image.new("RGB", (20, 16), "red").save(
        source,
        format="GIF",
        save_all=True,
        append_images=[Image.new("RGB", (20, 16), "blue")],
        duration=[100, 150],
        loop=0,
    )
    clip = MediaClip(source, tmp_path / "cache")
    try:
        assert clip.animated and clip.frame_count == 2
        assert clip.frame_at(0).index == 0
        assert clip.frame_at(100).index == 1
        assert clip.durations_ms == (100, 150)
    finally:
        clip.close()


def test_streamed_video_loops_without_expanding_every_frame(tmp_path: Path) -> None:
    source = tmp_path / "background.avi"
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (64, 36),
    )
    assert writer.isOpened()
    for value in (20, 90, 170, 240):
        writer.write(np.full((36, 64, 3), (value, 40, 255 - value), dtype=np.uint8))
    writer.release()

    clip = MediaClip(source, tmp_path / "media-cache")
    try:
        assert clip.kind == "video"
        assert clip.animated
        assert clip.frame_count == 4
        assert clip.frame_at(0).rgba.shape == (36, 64, 4)
        assert clip.frame_at(110).index == 1
        assert clip.frame_at(410).index == 0
        assert len(clip.frame_paths) == 1
        assert clip.frame_by_index(3).index == 3
        assert clip.temporal_anchor_indices() == (0, 1, 2, 3)
        analyzed_frame = clip.frame_by_index(2)
        path, transient = clip.analysis_frame_path(analyzed_frame)
        assert transient
        assert path.is_file()
        assert path.suffix == ".bmp"
        with Image.open(path) as image:
            assert np.array_equal(
                np.asarray(image.convert("RGB"), dtype=np.uint8),
                analyzed_frame.rgba[..., :3],
            )
        path.unlink()
    finally:
        clip.close()

    expected_clip = MediaClip(source, tmp_path / "expected-media-cache")
    sequential_clip = MediaClip(source, tmp_path / "sequential-media-cache")
    try:
        expected = {index: expected_clip.frame_by_index(index).rgba.copy() for index in (0, 2, 3)}
        decoded = {
            frame.index: frame.rgba.copy() for frame in sequential_clip.iter_frames((3, 0, 2, 2))
        }
        assert tuple(decoded) == (0, 2, 3)
        assert all(np.array_equal(decoded[index], expected[index]) for index in expected)
    finally:
        expected_clip.close()
        sequential_clip.close()


def test_dynamic_environment_wrap_is_small_and_deterministic() -> None:
    frame = np.zeros((72, 128, 4), dtype=np.uint8)
    frame[..., 0] = np.arange(128, dtype=np.uint8)
    frame[..., 1] = 80
    frame[..., 2] = 170
    frame[..., 3] = 255

    first = environment_wrap(frame)
    second = environment_wrap(frame)
    legacy = cv2.GaussianBlur(
        cv2.resize(frame[..., :3], (160, 90), interpolation=cv2.INTER_AREA),
        (0, 0),
        sigmaX=2.25,
        sigmaY=2.25,
    )

    assert first.shape == (90, 160, 3)
    assert np.array_equal(first, second)
    assert np.array_equal(first, legacy)


def test_video_flash_adds_exact_temporal_anchors(tmp_path: Path) -> None:
    source = tmp_path / "flash.avi"
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        30.0,
        (96, 54),
    )
    assert writer.isOpened()
    for index in range(12):
        value = 245 if index == 5 else 24
        writer.write(np.full((54, 96, 3), (value, value, value), dtype=np.uint8))
    writer.release()

    clip = MediaClip(source, tmp_path / "media-cache")
    try:
        regular = clip.temporal_anchor_indices()
        adaptive = clip.temporal_anchor_indices(detect_changes=True)
        window_changes = {
            index for _through, changes in clip.iter_video_change_windows(4) for index in changes
        }
        assert 5 not in regular
        assert {4, 5, 6}.issubset(adaptive)
        assert set(regular) | window_changes == set(adaptive)
        assert clip.temporal_cut_indices() == (5, 6)
        assert clip.temporal_cut_indices() == (5, 6)
    finally:
        clip.close()


def test_video_change_scan_keeps_indices_across_timestamp_gaps(tmp_path: Path) -> None:
    from imageio_ffmpeg import get_ffmpeg_exe

    source = tmp_path / "irregular.mkv"
    frames = np.full((12, 54, 96, 3), 24, dtype=np.uint8)
    frames[5] = 245
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            "96x54",
            "-r",
            "30",
            "-i",
            "pipe:0",
            "-vf",
            "setpts=PTS+gte(N\\,5)*0.1/TB",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            str(source),
        ],
        input=frames.tobytes(),
        capture_output=True,
        check=True,
        timeout=30,
    )
    clip = MediaClip(source, tmp_path / "media-cache")
    try:
        windows = list(clip.iter_video_change_windows(4))
        assert clip.frame_count == 12
        assert windows[-1][0] == 11
        assert clip.temporal_cut_indices() == (5, 6)
    finally:
        clip.close()


@pytest.mark.parametrize("transient", [False, True])
def test_exact_video_decode_retries_requested_frame_without_substituting_zero(tmp_path, transient):
    class Capture:
        def __init__(self):
            self.position = 0
            self.failed = False
            self.seeks = []

        def set(self, _property, value):
            self.position = int(value)
            self.seeks.append(self.position)
            return True

        def read(self):
            index = self.position
            self.position += 1
            if index == 5 and (not transient or not self.failed):
                self.failed = True
                return False, None
            return True, np.full((2, 2, 3), index, np.uint8)

    capture = Capture()
    clip = MediaClip.__new__(MediaClip)
    clip._capture = capture
    clip._video_frame = None
    clip._video_index = -1
    clip.kind, clip.frame_count, clip.fps = "video", 10, 1
    clip.source = tmp_path / "damaged.mp4"
    if transient:
        frame = clip.frame_by_index(5)
        assert frame.index == 5
        np.testing.assert_array_equal(frame.rgba[..., :3], 5)
    else:
        with pytest.raises(ValueError, match="Video frame 5"):
            clip.frame_by_index(5)
        assert clip._video_frame is None
        first = clip.frame_by_index(0)
        assert first.index == 0
        np.testing.assert_array_equal(first.rgba[..., :3], 0)
    assert capture.seeks[:2] == [5, 5]
