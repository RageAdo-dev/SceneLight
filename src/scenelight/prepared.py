"""Prepare every authored video frame with the production GPU analyzer."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

from .runtime import live_gpu
from .runtime.prepared import FIELDS, VERSION, Reader


def engine_identity() -> str:
    digest = hashlib.sha256(b"scenelight-prepared-v4")
    for name in ("live_gpu.py", "live_opencl.py"):
        digest.update((Path(__file__).parent / "runtime" / name).read_bytes())
    return digest.hexdigest()


def source_identity(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Writer:
    """Publish only complete archives; retain an older valid cache on failure."""

    def __init__(self, destination: Path, metadata: dict):
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination = destination
        self.metadata = dict(metadata, version=VERSION)
        fd, name = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".partial", dir=destination.parent
        )
        os.close(fd)
        self.temporary = Path(name)
        self.archive = zipfile.ZipFile(name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1)
        self.count = 0

    def append(self, fields: dict[str, bytes], signature: str | None = None) -> None:
        for name, width, height in FIELDS:
            if len(fields[name]) != width * height * 4:
                raise ValueError("Invalid prepared field: " + name)
        raw = b"".join(fields[name] for name, _, _ in FIELDS)
        self.archive.writestr("frames/%d" % self.count, raw)
        if signature is not None:
            self.metadata.setdefault("frame_signatures", []).append(signature)
            self.metadata.setdefault("field_hashes", []).append(hashlib.sha256(raw).hexdigest())
        self.count += 1

    def finish(self) -> None:
        if self.count != self.metadata["frame_count"]:
            raise ValueError("Incomplete prepared lighting")
        self.archive.writestr("manifest.json", json.dumps(self.metadata, sort_keys=True))
        self.archive.close()
        os.replace(self.temporary, self.destination)

    def close(self) -> None:
        self.archive.close()
        self.temporary.unlink(missing_ok=True)


class FramePreparer:
    """Own one analyzer and its sequential history in the current GL context."""

    def __init__(self, *, preview: bool):
        self.analysis = live_gpu.Analysis()
        self.preview = preview
        self.history = ()

    def frame(self, rgba: np.ndarray) -> dict[str, bytes]:
        pixels = np.ascontiguousarray(rgba, dtype=np.uint8)
        height, width = pixels.shape[:2]
        device = self.analysis.device
        gl = device.gl
        with live_gpu.State(gl):
            source = device.target("prepared_input", width, height, live_gpu.RGBA8)
            gl.BindTexture(live_gpu.TEXTURE_2D, source)
            gl.TexSubImage2D(
                live_gpu.TEXTURE_2D,
                0,
                0,
                0,
                width,
                height,
                live_gpu.RGBA,
                live_gpu.UNSIGNED_BYTE,
                ctypes.c_void_p(pixels.ctypes.data),
            )
            fields = self.analysis.evaluate(
                source, (width, height), preview=self.preview, animated=True, previous=self.history
            )
            self.history = (fields["_history_lights"], fields["_history_image"])
            result = {}
            for name, width, height in FIELDS:
                array = np.empty((height, width, 4), np.uint8)
                device.bind_targets((fields[name],))
                gl.ReadPixels(
                    0,
                    0,
                    width,
                    height,
                    live_gpu.RGBA,
                    live_gpu.UNSIGNED_BYTE,
                    ctypes.c_void_p(array.ctypes.data),
                )
                result[name] = array.tobytes()
            return result

    def close(self) -> None:
        self.analysis.device.close()


def cached_metadata(destination: Path, expected: dict) -> dict | None:
    if destination.is_file():
        try:
            reader = Reader(str(destination), expected)
            try:
                if reader.archive.testzip() is not None:
                    raise ValueError("Prepared lighting checksum failed")
                metadata = reader.metadata
            finally:
                reader.close()
            return dict(
                {
                    key: value
                    for key, value in metadata.items()
                    if key not in ("frame_signatures", "field_hashes")
                },
                cached=True,
            )
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            pass
    return None


def _tagged_video_frames(source: Path, size: tuple[int, int]):
    """Decode tagged YUV colors as current Ren'Py does, without resampling time."""
    from imageio_ffmpeg import read_frames

    frames = read_frames(
        str(source), pix_fmt="rgba", bits_per_pixel=32, output_params=["-vsync", "0"]
    )
    try:
        metadata = next(frames)
        if tuple(metadata["size"]) != tuple(size):
            raise ValueError("Video decoders disagree about the displayed frame size")
        width, height = size
        for raw in frames:
            yield np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    finally:
        frames.close()


def prepare(
    source: Path, destination: Path, *, preview: bool, progress=None, on_started=None
) -> dict:
    expected = {"engine": engine_identity(), "source": source_identity(source), "preview": preview}
    cached = cached_metadata(destination, expected)
    if cached is not None:
        return cached
    from .preview.media import MediaClip

    media = MediaClip(source, destination.parent / "media")
    builder = writer = None
    started = time.perf_counter()
    try:
        profiles = ["opencv"]
        if not preview and media.kind == "video":
            profiles.append("ffmpeg-tagged")
        metadata = dict(
            expected,
            frame_count=media.frame_count * len(profiles),
            source_frame_count=media.frame_count,
            decode_profiles=profiles,
            fps=media.fps,
            size=list(media.size),
            durations_ms=list(media.durations_ms),
            history="sequential-from-source-start",
        )
        writer = Writer(destination, metadata)
        if on_started is not None:
            on_started(writer.temporary)
        builder = FramePreparer(preview=preview)
        for frame in media.iter_frames(range(media.frame_count)):
            height, width = frame.rgba.shape[:2]
            sample = frame.rgba[(np.arange(9) * height // 9)[:, None], np.arange(16) * width // 16]
            signature = hashlib.sha256(sample.tobytes()).hexdigest()
            writer.append(builder.frame(frame.rgba), signature)
            if progress is not None:
                progress(frame.index + 1, metadata["frame_count"])
        if len(profiles) > 1:
            # Ren'Py generations can decode the same YUV movie to different
            # RGB bytes. Retain each exact sequence under its own signatures;
            # playback still holds only two lighting frames, and never guesses
            # an index from the audio clock or approximate image similarity.
            media.close()
            builder.history = ()
            count = 0
            for rgba in _tagged_video_frames(source, media.size):
                if count >= media.frame_count:
                    raise ValueError("Video decoders disagree about the frame count")
                height, width = rgba.shape[:2]
                sample = rgba[(np.arange(9) * height // 9)[:, None], np.arange(16) * width // 16]
                writer.append(builder.frame(rgba), hashlib.sha256(sample.tobytes()).hexdigest())
                count += 1
                if progress is not None:
                    progress(media.frame_count + count, metadata["frame_count"])
            if count != media.frame_count:
                raise ValueError("Video decoders disagree about the frame count")
        if source_identity(source) != expected["source"]:
            raise ValueError("Video changed during lighting preparation; reopen it to retry")
        writer.finish()
        return dict(
            metadata,
            cached=False,
            seconds=time.perf_counter() - started,
            disk_bytes=destination.stat().st_size,
        )
    finally:
        if builder is not None:
            builder.close()
        if writer is not None:
            writer.close()
        media.close()


def prepare_project_movies(discovery) -> dict:
    """Build portable full-frame caches in the installer's managed game copy."""
    sources = sorted(set(discovery.scene_media.values()))
    if sources and any(
        importlib.util.find_spec(name) is None for name in ("PySide6", "cv2", "imageio_ffmpeg")
    ):
        raise RuntimeError(
            "Movie preparation requires SceneLight's playback components. "
            "Run SceneLight Setup to install or repair the required components, "
            "then retry this installation. Preview is not required."
        )
    root = discovery.game_root / "scenelight_runtime"
    entries = {}
    engine = engine_identity()
    for source in sources:
        relative = source.resolve().relative_to(discovery.game_root.resolve()).as_posix()
        key = hashlib.sha256((relative + engine).encode("utf-8")).hexdigest()
        destination = root / "prepared_movies" / (key + ".slframes")
        print("Preparing full-quality movie lighting: " + relative, flush=True)
        subprocess.run(
            [sys.executable, "-m", "scenelight.prepared", str(source), str(destination), "--game"],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(
                os.environ,
                PYTHONPATH=str(Path(__file__).resolve().parents[1])
                + os.pathsep
                + os.environ.get("PYTHONPATH", ""),
            ),
        )
        reader = Reader(str(destination), {"engine": engine, "preview": False})
        try:
            entries[relative] = {
                "cache": destination.relative_to(discovery.game_root).as_posix(),
                "size": reader.metadata["size"],
                "frames": reader.metadata.get("source_frame_count", reader.count),
            }
        finally:
            reader.close()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "prepared_movies.json"
    temporary = destination.with_suffix(".json.partial")
    temporary.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--game", action="store_true")
    args = parser.parse_args()
    if args.destination.is_file():
        cached = cached_metadata(
            args.destination,
            {
                "engine": engine_identity(),
                "source": source_identity(args.source),
                "preview": not args.game,
            },
        )
        if cached is not None:
            print(json.dumps(cached), flush=True)
            return
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

    app = QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create():
        raise RuntimeError("Could not create lighting preparation context")
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    if not context.makeCurrent(surface):
        raise RuntimeError("Could not activate lighting preparation context")
    try:
        result = prepare(
            args.source,
            args.destination,
            preview=not args.game,
            progress=lambda done, total: print(
                json.dumps({"done": done, "total": total}), flush=True
            ),
            on_started=lambda path: print(json.dumps({"temporary": str(path)}), flush=True),
        )
        print(json.dumps(result), flush=True)
    finally:
        context.doneCurrent()
        app.quit()


if __name__ == "__main__":
    main()
