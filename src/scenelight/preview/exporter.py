"""Streaming animation encoders for SceneLight GPU composites."""

from __future__ import annotations

import os
import subprocess
import tempfile
from itertools import pairwise
from math import lcm
from pathlib import Path
from typing import TypeVar

import numpy as np
from PIL import GifImagePlugin, Image

_Writer = TypeVar("_Writer", bound="MP4Writer")


def export_extension(background_kind: str, sprite_kind: str = "static") -> str:
    if "video" in (background_kind, sprite_kind):
        return ".mp4"
    if "animated-image" in (background_kind, sprite_kind):
        return ".gif"
    return ".png"


def composite_gif_timeline(background, sprite) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return exact change times for one seamless combined GIF loop.

    Each input keeps its authored variable frame durations. When both inputs
    animate, the combined loop ends at their least common duration so neither
    animation is cut in the middle of a cycle.
    """

    animated = [clip for clip in (background, sprite) if clip.kind == "animated-image"]
    if not animated:
        return (0,), (1000,)
    loop_ms = animated[0].duration_ms
    for clip in animated[1:]:
        loop_ms = lcm(loop_ms, clip.duration_ms)
    events = {0, loop_ms}
    for clip in animated:
        cycle_start = 0
        while cycle_start < loop_ms:
            for boundary in clip.cumulative_ms:
                event = cycle_start + boundary
                if event < loop_ms:
                    events.add(event)
            cycle_start += clip.duration_ms
    ordered = sorted(events)
    timestamps = tuple(ordered[:-1])
    durations = tuple(right - left for left, right in pairwise(ordered))
    return timestamps, durations


def save_gif(
    destination: Path,
    frames: list[np.ndarray],
    durations_ms: tuple[int, ...],
) -> None:
    if not frames:
        raise ValueError("Cannot export an empty GIF")
    with GIFWriter(destination, durations_ms) as writer:
        for frame in frames:
            writer.write(frame)


class GIFWriter:
    """Encode one full frame at a time, retaining each frame's own palette."""

    def __init__(self, destination: Path, durations_ms: tuple[int, ...]):
        if not durations_ms or any(duration < 10 for duration in durations_ms):
            raise ValueError("GIF frames need durations of at least 10 ms")
        self.destination = destination
        self.durations = durations_ms
        self.count = 0
        self.size = None
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".partial", dir=destination.parent
        )
        self.temporary = Path(path)
        self.stream = os.fdopen(fd, "wb")

    def __enter__(self) -> "GIFWriter":
        return self

    def write(self, rgba: np.ndarray) -> None:
        if self.count >= len(self.durations):
            raise ValueError("More GIF frames than declared durations")
        image = Image.fromarray(np.asarray(rgba[..., :3], dtype=np.uint8)).quantize(
            colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG
        )
        if self.size is not None and image.size != self.size:
            raise ValueError("GIF frame dimensions changed")
        if self.count == 0:
            self.size = image.size
            header, _ = GifImagePlugin.getheader(image, info={"loop": 0, "optimize": False})
            for block in header:
                self.stream.write(block)
        for block in GifImagePlugin.getdata(
            image, duration=self.durations[self.count], disposal=2, include_color_table=True
        ):
            self.stream.write(block)
        self.count += 1

    def __exit__(self, kind, value, traceback) -> None:
        try:
            if kind is None:
                if self.count != len(self.durations):
                    raise ValueError("Incomplete GIF export")
                self.stream.write(b";")
                self.stream.close()
                os.replace(self.temporary, self.destination)
        finally:
            self.stream.close()
            self.temporary.unlink(missing_ok=True)


class MP4Writer:
    """Feed GPU-rendered RGB frames to a bundled modern FFmpeg.

    When the source video contains audio it is carried into the composite and
    encoded to AAC; videos without audio remain valid silent MP4 files.
    """

    def __init__(
        self,
        destination: Path,
        source: Path,
        size: tuple[int, int],
        fps: float,
    ):
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
        except ImportError as error:  # pragma: no cover - installation failure path.
            raise RuntimeError(
                "Video export needs imageio-ffmpeg. Install SceneLight's preview dependencies."
            ) from error
        self.destination = destination
        self.size = size
        self._published = False
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=destination.stem + ".", suffix=".mp4", dir=destination.parent
        )
        os.close(fd)
        self.temporary = Path(name)
        command = [
            get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s:v",
            f"{size[0]}x{size[1]}",
            "-r",
            f"{fps:.8f}",
            "-i",
            "pipe:0",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            "apad",
            "-shortest",
            "-movflags",
            "+faststart",
            str(self.temporary),
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError:
            self.temporary.unlink(missing_ok=True)
            raise

    def write(self, rgba: np.ndarray) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Video encoder is already closed")
        if rgba.shape[:2] != (self.size[1], self.size[0]):
            raise ValueError("Video frame dimensions changed")
        rgb = np.ascontiguousarray(rgba[..., :3], dtype=np.uint8)
        self._process.stdin.write(rgb.tobytes())

    def close(self) -> None:
        if self._published:
            return
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except BrokenPipeError:
                # Read FFmpeg's actual error below instead of losing it to a
                # pipe-close exception after the encoder has already exited.
                pass
            self._process.stdin = None
        stderr = self._process.stderr.read() if self._process.stderr is not None else b""
        return_code = self._process.wait()
        if self._process.stderr is not None:
            self._process.stderr.close()
            self._process.stderr = None
        if return_code:
            self.temporary.unlink(missing_ok=True)
            raise RuntimeError(stderr.decode("utf-8", "replace").strip() or "FFmpeg failed")
        os.replace(self.temporary, self.destination)
        self._published = True

    def __enter__(self: _Writer) -> _Writer:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.close()
            return
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except BrokenPipeError:
                pass
            self._process.stdin = None
        self._process.kill()
        self._process.wait()
        if self._process.stderr is not None:
            self._process.stderr.close()
            self._process.stderr = None
        self.temporary.unlink(missing_ok=True)
