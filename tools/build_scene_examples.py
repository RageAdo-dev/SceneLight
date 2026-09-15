"""Render documentation scenes using Preview's production lighting.

Source artwork and intermediate frames stay in a scratch folder. The output
contains rendered examples only. Install the Preview dependencies before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe
from OpenGL import GL
from PIL import Image
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneLightGPUView
from scenelight.preview.hardware import detect_hardware_profile
from scenelight.preview.shader_source import production_shader_sha256
from scenelight.source_types import VIDEO_SOURCE_SUFFIXES

SIZE = (1920, 1080)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def crop_box(size, center=(0.5, 0.5)):
    """Fit a 16:9 crop inside the source without stretching either axis."""
    width, height = size
    if width <= 0 or height <= 0 or any(not 0 <= c <= 1 for c in center):
        raise ValueError("Expected positive dimensions and a crop center between 0 and 1")
    crop_width = min(width, height * 16 / 9)
    crop_height = crop_width * 9 / 16
    left = min(max(center[0] * width - crop_width / 2, 0), width - crop_width)
    top = min(max(center[1] * height - crop_height / 2, 0), height - crop_height)
    return left, top, left + crop_width, top + crop_height


def frame_image(image, center):
    return image.convert("RGBA").resize(
        SIZE, Image.Resampling.LANCZOS, box=crop_box(image.size, center)
    )


def encode_animation(
    frames,
    destination,
    fps,
    frame_count,
    *,
    lossless=False,
    size=SIZE,
    formats=(".webp", ".mp4", ".gif", "-preview.webp"),
):
    """Encode from disk so long, high-resolution clips do not accumulate in RAM."""
    base = [
        get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        str(fps),
        "-t",
        str(frame_count / fps),
        "-i",
        str(frames / "%05d.png"),
    ]
    preview_size = (min(size[0], 1280), min(size[1], 720))
    outputs = (
        (
            ".webp",
            [
                "-c:v",
                "libwebp_anim",
                "-lossless",
                str(int(lossless)),
                "-quality",
                "90",
                "-compression_level",
                "4",
                "-loop",
                "0",
            ],
        ),
        (
            ".mp4",
            [
                "-c:v",
                "libx264",
                "-crf",
                "16",
                "-preset",
                "slow",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ],
        ),
        (
            ".gif",
            [
                "-filter_complex",
                "fps=50:eof_action=pass,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                "-loop",
                "0",
            ],
        ),
        (
            "-preview.webp",
            [
                "-vf",
                f"scale={preview_size[0]}:{preview_size[1]}:flags=lanczos",
                "-c:v",
                "libwebp_anim",
                "-lossless",
                "0",
                "-quality",
                "90",
                "-compression_level",
                "4",
                "-loop",
                "0",
            ],
        ),
    )
    records = {}
    for suffix, options in outputs:
        if suffix not in formats:
            continue
        target = destination.with_name(destination.name + suffix)
        print(f"Encoding {target.name}", flush=True)
        subprocess.run(base + options + [str(target)], check=True)
        if target.stat().st_size >= 100 * 1024 * 1024:
            raise RuntimeError(f"{target.name} exceeds the repository's per-file size limit")
        record = {"bytes": target.stat().st_size, "sha256": digest(target)}
        if suffix == ".mp4":
            video = cv2.VideoCapture(str(target))
            try:
                decoded = 0
                if abs(video.get(cv2.CAP_PROP_FPS) - fps) > 0.01:
                    raise RuntimeError(f"{target.name} changed frame rate")
                while True:
                    ok, pixels = video.read()
                    if not ok:
                        break
                    if (pixels.shape[1], pixels.shape[0]) != size:
                        raise RuntimeError(f"{target.name} changed frame size")
                    decoded += 1
                if decoded != frame_count:
                    raise RuntimeError(f"{target.name} lost frames during export")
                record.update(frames=decoded, fps=fps)
            finally:
                video.release()
        if target.suffix in (".gif", ".webp"):
            with Image.open(target) as encoded:
                count = encoded.n_frames
                expected = round(frame_count * (50 if suffix == ".gif" else fps) / fps)
                target_size = preview_size if suffix == "-preview.webp" else size
                if encoded.size != target_size or count != expected:
                    raise RuntimeError(
                        f"{target.name} lost frames or changed size: {encoded.size}, {count}"
                    )
                elapsed = 0
                timings = set()
                for index in range(count):
                    encoded.seek(index)
                    encoded.load()
                    duration = encoded.info["duration"]
                    timings.add(duration)
                    elapsed += duration
                if abs(elapsed - frame_count / fps * 1000) > (
                    1 if target.suffix == ".webp" else 10
                ):
                    raise RuntimeError(f"{target.name} changed playback duration")
                record.update(frames=count, duration_ms=elapsed, frame_durations_ms=sorted(timings))
                if suffix == ".webp" and lossless:
                    for index in range(count):
                        encoded.seek(index)
                        with Image.open(frames / f"{index:05d}.png") as original:
                            if not np.array_equal(
                                np.asarray(encoded.convert("RGB")),
                                np.asarray(original.convert("RGB")),
                            ):
                                raise RuntimeError(f"Lossless animation changed frame {index}")
        records[target.name] = record
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("background", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--output", type=Path, default=Path("docs/media"))
    parser.add_argument("--name", default="scene-example")
    parser.add_argument("--horizontal", type=float, default=0.38)
    parser.add_argument("--baseline", type=float, default=1.08)
    parser.add_argument("--height", type=float, default=1.02)
    parser.add_argument("--crop-x", type=float, default=0.5)
    parser.add_argument("--crop-y", type=float, default=0.5)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--movement", type=float, default=0.0, help="Horizontal movement radius")
    parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args()
    if not args.name or Path(args.name).name != args.name or "." in args.name:
        parser.error("Use a plain output name without an extension")
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("Duration must be positive and finite")
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    frames = Path(tempfile.mkdtemp(prefix=args.name + "-", dir=args.work))
    center = (args.crop_x, args.crop_y)
    is_video = args.background.suffix.lower() in VIDEO_SOURCE_SUFFIXES
    capture = None
    if is_video:
        capture = cv2.VideoCapture(str(args.background))
        ok, bgr = capture.read()
        if not ok:
            raise ValueError("Could not decode the background video")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("The video does not declare a valid frame rate")
        first = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
    else:
        fps = 60.0
        with Image.open(args.background) as opened:
            first = opened.convert("RGBA")
    count = max(1, round(args.seconds * fps)) if is_video or args.movement else 1
    first_frame = np.asarray(frame_image(first, center))

    app = QApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("Could not create the documentation renderer")

    class View(SceneLightGPUView):
        def makeCurrent(self):
            if not context.makeCurrent(surface):
                raise RuntimeError("Lost the documentation OpenGL context")

        def doneCurrent(self):
            context.doneCurrent()

        def context(self):
            return context

        def defaultFramebufferObject(self):
            return 0

        def update(self, *args):
            pass

    cache = ArtifactCache(args.work / "cache", hardware_profile=detect_hardware_profile(cuda=False))
    view = View()
    try:
        view.initializeGL()
        if not view.live_analysis_supported:
            raise RuntimeError("The documentation examples require Preview's live analyzer")
        form = cache.form(args.sprite)
        view.set_sprite(args.sprite, form)
        view.set_calibration(Calibration())
        view.set_placement(args.horizontal, args.baseline, args.height)
        view.set_live_analysis_enabled(True)
        view.set_live_background(is_video)
        view.set_background_frame(first_frame)
        view.set_compare_mode(1)
        before = view.render_rgba(SIZE)
        Image.fromarray(before).convert("RGB").save(args.output / f"{args.name}-original.png")
        view.set_compare_mode(0)
        after = view.render_rgba(SIZE)
        Image.fromarray(after).convert("RGB").save(args.output / f"{args.name}.png")
        if args.sample_only:
            return
        for index in range(count):
            if is_video and index:
                ok, bgr = capture.read()
                if not ok:
                    raise ValueError("The source video is shorter than the requested example")
                source = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
                view.set_background_frame(np.asarray(frame_image(source, center)))
            if args.movement:
                horizontal = args.horizontal - args.movement * math.cos(2 * math.pi * index / count)
                view.set_placement(horizontal, args.baseline, args.height)
            rendered = view.render_rgba(SIZE)
            Image.fromarray(rendered).convert("RGB").save(
                frames / f"{index:05d}.png", compress_level=1
            )
            if index % 60 == 0:
                print(f"Rendered {index + 1}/{count} frames", flush=True)
        metadata = {
            "background_sha256": digest(args.background),
            "source_size": list(first.size),
            "crop_box": list(crop_box(first.size, center)),
            "sprite_sha256": digest(args.sprite),
            "shader_sha256": production_shader_sha256(),
            "size": list(SIZE),
            "placement": [args.horizontal, args.baseline, args.height],
            "movement_radius": args.movement,
            "calibration": "Default",
            "analysis": "Production live GPU analyzer, once per source frame",
            "changed_pixels": int(np.any(before != after, axis=2).sum()),
            "frames": count,
            "fps": fps,
        }
    finally:
        if capture is not None:
            capture.release()
        view.makeCurrent()
        # This offscreen host has no Qt paint cycle to clear its final bindings.
        # Leave no deleted analyzer texture bound when its device restores GL state.
        GL.glUseProgram(0)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        for unit in range(int(GL.glGetIntegerv(GL.GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS))):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        view.close()
        cache.shutdown()
        app.processEvents()
    if count > 1:
        metadata["encodings"] = encode_animation(frames, args.output / args.name, fps, count)
    (args.output / f"{args.name}.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
