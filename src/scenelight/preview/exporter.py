"""Streaming animation encoders for SceneLight GPU composites."""

from __future__ import annotations

import subprocess
from itertools import pairwise
from math import lcm
from pathlib import Path
from typing import Self

import numpy as np
from PIL import Image


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
    images = [
        Image.fromarray(np.asarray(frame[..., :3], dtype=np.uint8), "RGB").quantize(
            colors=256,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
        for frame in frames
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        destination,
        save_all=True,
        append_images=images[1:],
        duration=list(durations_ms),
        loop=0,
        disposal=2,
        optimize=False,
    )


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
        destination.parent.mkdir(parents=True, exist_ok=True)
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
            "-shortest",
            str(destination),
        ]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def write(self, rgba: np.ndarray) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Video encoder is already closed")
        rgb = np.ascontiguousarray(rgba[..., :3], dtype=np.uint8)
        self._process.stdin.write(rgb.tobytes())

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
            self._process.stdin = None
        stderr = self._process.stderr.read() if self._process.stderr is not None else b""
        return_code = self._process.wait()
        if self._process.stderr is not None:
            self._process.stderr.close()
            self._process.stderr = None
        if return_code:
            self.destination.unlink(missing_ok=True)
            raise RuntimeError(stderr.decode("utf-8", "replace").strip() or "FFmpeg failed")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.close()
            return
        if self._process.stdin is not None:
            self._process.stdin.close()
            self._process.stdin = None
        self._process.kill()
        self._process.wait()
        if self._process.stderr is not None:
            self._process.stderr.close()
            self._process.stderr = None
        self.destination.unlink(missing_ok=True)
