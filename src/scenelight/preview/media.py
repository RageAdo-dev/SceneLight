"""Decode still and animated media for the live GPU preview."""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import subprocess
import tempfile
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageSequence

from ..source_types import VIDEO_SOURCE_SUFFIXES

ANIMATED_IMAGE_EXTENSIONS = {".gif", ".apng", ".webp"}
VIDEO_EXTENSIONS = VIDEO_SOURCE_SUFFIXES
SUPPORTED_BACKGROUND_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    *ANIMATED_IMAGE_EXTENSIONS,
    *VIDEO_EXTENSIONS,
}
SUPPORTED_SPRITE_EXTENSIONS = {".png", ".webp", ".gif", ".apng"}
MEDIA_CACHE_VERSION = b"scenelight-media-v2\0"
TEMPORAL_TRANSPORT_HZ = 4.0
LOW_FPS_EXACT_LIMIT = 12.0


def _verified_video_frame_count(source: Path, declared: int, fps: float) -> int:
    """Correct container frame counts that point past the decodable tail.

    Some MP4 muxers leave one or two empty samples in ``nb_frames``. OpenCV
    exposes that declaration as ``CAP_PROP_FRAME_COUNT`` even though seeking or
    decoding the final sample fails. Probing only the declared tail is fast for
    long videos and avoids a full pre-playback decode.
    """

    declared = max(1, int(declared))
    if declared <= 1:
        return declared
    probe = cv2.VideoCapture(str(source))
    if not probe.isOpened():
        probe.release()
        return declared
    try:
        last_index = declared - 1
        probe.set(cv2.CAP_PROP_POS_FRAMES, last_index)
        ok, frame = probe.read()
        position = int(round(probe.get(cv2.CAP_PROP_POS_FRAMES)))
        if ok and frame is not None and abs(position - declared) <= 1:
            return declared

        # A failed end seek commonly leaves OpenCV at the first nonexistent
        # sample, which gives the exact candidate count immediately. Verify it
        # by decoding the preceding frame before trusting the correction.
        candidates: list[int] = []
        if 0 < position < declared:
            candidates.append(position)
        search = max(8, min(64, round(max(float(fps), 1.0) * 2.0)))
        candidates.extend(range(declared - 1, max(0, declared - search) - 1, -1))
        for candidate_count in dict.fromkeys(candidates):
            if candidate_count <= 0 or candidate_count >= declared:
                continue
            probe.set(cv2.CAP_PROP_POS_FRAMES, candidate_count - 1)
            ok, frame = probe.read()
            reached = int(round(probe.get(cv2.CAP_PROP_POS_FRAMES)))
            if ok and frame is not None and abs(reached - candidate_count) <= 1:
                return candidate_count
        return declared
    finally:
        probe.release()


def _digest(path: Path) -> str:
    digest = hashlib.sha256(MEDIA_CACHE_VERSION)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _video_identity(path: Path) -> str:
    """Identify a streamed file without reading its entire compressed payload."""
    stat = path.stat()
    stamp = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    return hashlib.sha256(b"scenelight-stream-v1\0" + repr(stamp).encode("utf-8")).hexdigest()


def _rgba(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def environment_wrap(frame: np.ndarray, size: tuple[int, int] = (160, 90)) -> np.ndarray:
    """Return a fast broad-color field for one already-decoded animation frame."""

    # A decoded RGBA frame is contiguous, but ``frame[..., :3]`` is a strided
    # view. OpenCV silently copies that multi-megabyte view before resizing.
    # Resize/blur all independent channels first and discard alpha afterward;
    # the RGB bytes are identical and the hidden full-frame copy disappears.
    source = np.asarray(frame, dtype=np.uint8)
    reduced = cv2.resize(source, size, interpolation=cv2.INTER_AREA)
    sigma = max(1.0, min(size) / 40.0)
    blurred = cv2.GaussianBlur(reduced, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return np.ascontiguousarray(blurred[..., :3])


@dataclass(frozen=True, slots=True)
class MediaFrame:
    index: int
    rgba: np.ndarray


class MediaClip:
    """A loopable still, animated image, or streamed video.

    Animated image frames are losslessly composited once into a content-addressed
    cache. Videos remain streamed so long clips never expand into RAM or a large
    frame directory.
    """

    def __init__(self, source: Path, cache_root: Path):
        self.source = source.resolve(strict=True)
        self.cache_root = cache_root.resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.identity = (
            _video_identity(self.source)
            if self.source.suffix.lower() in VIDEO_EXTENSIONS
            else _digest(self.source)
        )
        self.kind = "static"
        self.frame_paths: tuple[Path, ...] = (self.source,)
        self.durations_ms: tuple[int, ...] = (1000,)
        self.cumulative_ms: tuple[int, ...] = (1000,)
        self.duration_ms = 1000
        self.fps = 0.0
        self.frame_count = 1
        self.size = (1, 1)
        self.reference_path = self.source
        self._memory_frames: OrderedDict[int, np.ndarray] = OrderedDict()
        self._capture: cv2.VideoCapture | None = None
        self._video_index = -1
        self._video_frame: np.ndarray | None = None
        self._last_index = -1
        self._video_cuts: set[int] = set()
        self._video_change_cache: tuple[int, ...] | None = None
        self._open()

    @property
    def animated(self) -> bool:
        return self.frame_count > 1

    def _open(self) -> None:
        suffix = self.source.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            self._open_video()
            return
        with Image.open(self.source) as image:
            self.size = image.size
            frame_count = int(getattr(image, "n_frames", 1))
        if frame_count > 1:
            self._open_animated_image()

    def _open_animated_image(self) -> None:
        root = self.cache_root / self.identity
        marker = root / "media.json"
        with Image.open(self.source) as image:
            # APNG may include a still poster which is not part of the loop.
            skip_poster = image.format == "PNG" and bool(image.info.get("default_image"))
            expected_count = image.n_frames - int(skip_poster)
            expected_size = list(image.size)
        payload = None
        if marker.is_file():
            try:
                candidate = json.loads(marker.read_text(encoding="utf-8"))
                names = candidate["frames"]
                durations = candidate["durations_ms"]
                expected_names = [f"frame_{index:06d}.png" for index in range(expected_count)]
                if (
                    names == expected_names
                    and isinstance(durations, list)
                    and len(durations) == expected_count
                    and all(type(value) is int and value >= 10 for value in durations)
                    and candidate["size"] == expected_size
                    and all((root / name).is_file() for name in expected_names)
                ):
                    payload = candidate
            except (OSError, ValueError, KeyError, TypeError):
                payload = None
        if payload is None:
            root.mkdir(parents=True, exist_ok=True)
            names: list[str] = []
            durations: list[int] = []
            with Image.open(self.source) as image:
                for index, frame in enumerate(ImageSequence.Iterator(image)):
                    if skip_poster and index == 0:
                        continue
                    name = f"frame_{len(names):06d}.png"
                    _image = frame.convert("RGBA")
                    _image.save(root / name, compress_level=1)
                    names.append(name)
                    durations.append(max(10, int(frame.info.get("duration", 100))))
                size = list(image.size)
            payload = {"frames": names, "durations_ms": durations, "size": size}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=root, suffix=".tmp", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(payload, stream, indent=2)
                os.replace(temporary, marker)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        self.kind = "animated-image"
        self.frame_paths = tuple(root / name for name in payload["frames"])
        self.durations_ms = tuple(max(10, int(value)) for value in payload["durations_ms"])
        cumulative: list[int] = []
        elapsed = 0
        for duration in self.durations_ms:
            elapsed += duration
            cumulative.append(elapsed)
        self.cumulative_ms = tuple(cumulative)
        self.duration_ms = max(1, elapsed)
        self.frame_count = len(self.frame_paths)
        self.size = tuple(int(value) for value in payload["size"])
        self.reference_path = self.frame_paths[0]

    def _open_video(self) -> None:
        capture = cv2.VideoCapture(str(self.source))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"Could not decode video: {self.source}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0.0:
            fps = 30.0
        declared_frame_count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        frame_count = _verified_video_frame_count(self.source, declared_frame_count, fps)
        width = max(1, int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = max(1, int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        ok, bgr = capture.read()
        if not ok or bgr is None:
            capture.release()
            raise ValueError(f"Video contains no decodable frames: {self.source}")
        first = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        root = self.cache_root / self.identity
        root.mkdir(parents=True, exist_ok=True)
        reference = root / "frame_000000.png"
        if not reference.is_file():
            Image.fromarray(first, "RGBA").save(reference, compress_level=1)
        self.kind = "video"
        self.frame_paths = (reference,)
        self.durations_ms = (max(1, round(1000.0 / fps)),)
        self.cumulative_ms = (max(1, round(frame_count * 1000.0 / fps)),)
        self.duration_ms = self.cumulative_ms[0]
        self.fps = fps
        self.frame_count = frame_count
        self.size = (width, height)
        self.reference_path = reference
        self._capture = capture
        self._video_index = 0
        self._video_frame = first

    def index_at(self, elapsed_ms: float) -> int:
        if not self.animated:
            return 0
        if self.kind == "animated-image":
            loop_time = int(max(0.0, elapsed_ms)) % self.duration_ms
            return min(bisect.bisect_right(self.cumulative_ms, loop_time), self.frame_count - 1)
        frame = int(max(0.0, elapsed_ms) * self.fps / 1000.0)
        return frame % self.frame_count

    def frame_at(self, elapsed_ms: float) -> MediaFrame:
        index = self.index_at(elapsed_ms)
        if self.kind == "video":
            rgba = self._video_frame_at(index)
        else:
            rgba = self._image_frame_at(index)
        self._last_index = index
        return MediaFrame(index, rgba)

    def frame_by_index(self, index: int) -> MediaFrame:
        """Decode one exact frame without converting through a time stamp."""

        index = min(max(int(index), 0), self.frame_count - 1)
        rgba = self._video_frame_at(index) if self.kind == "video" else self._image_frame_at(index)
        return MediaFrame(index, rgba)

    def iter_frames(self, indices: Iterable[int]) -> Iterator[MediaFrame]:
        """Decode sorted exact frames without repeatedly seeking a video.

        OpenCV seeking is disproportionately expensive for compressed video.
        Temporal analysis always consumes sorted anchors, so walking forward
        with ``grab`` preserves the exact decoded target frames while avoiding
        a fresh keyframe seek for every anchor.
        """

        requested = tuple(
            sorted({min(max(int(index), 0), self.frame_count - 1) for index in indices})
        )
        if self.kind != "video":
            for index in requested:
                yield MediaFrame(index, self._image_frame_at(index))
            return

        assert self._capture is not None
        for index in requested:
            if self._video_frame is not None and index == self._video_index:
                yield MediaFrame(index, self._video_frame)
                continue
            if index <= self._video_index:
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                self._video_index = index - 1
            while self._video_index + 1 < index:
                if not self._capture.grab():
                    raise ValueError(f"Video frame {index} could not be reached: {self.source}")
                self._video_index += 1
            ok, bgr = self._capture.read()
            if not ok or bgr is None:
                raise ValueError(f"Video frame {index} could not be decoded: {self.source}")
            self._video_index = index
            self._video_frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
            yield MediaFrame(index, self._video_frame)

    def changed_at(self, elapsed_ms: float) -> MediaFrame | None:
        index = self.index_at(elapsed_ms)
        if index == self._last_index:
            return None
        return self.frame_at(elapsed_ms)

    def _image_frame_at(self, index: int) -> np.ndarray:
        cached = self._memory_frames.get(index)
        if cached is not None:
            self._memory_frames.move_to_end(index)
            return cached
        with Image.open(self.frame_paths[index]) as image:
            rgba = _rgba(image)
        self._memory_frames[index] = rgba
        self._memory_frames.move_to_end(index)
        while len(self._memory_frames) > 8:
            self._memory_frames.popitem(last=False)
        return rgba

    def _video_frame_at(self, index: int) -> np.ndarray:
        assert self._capture is not None
        if self._video_frame is not None and index == self._video_index:
            return self._video_frame
        forward_gap = index - self._video_index
        # GUI timers occasionally skip one or two source frames. Seeking for
        # that tiny forward jump can cost hundreds of milliseconds on an MP4;
        # grabbing the intervening decoded frames preserves the exact target
        # frame and keeps 60 fps playback smooth.
        if 1 < forward_gap <= max(2, round(self.fps * 2.0)):
            reached = True
            while self._video_index + 1 < index:
                if not self._capture.grab():
                    reached = False
                    break
                self._video_index += 1
            if not reached:
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                self._video_index = index - 1
        elif index != self._video_index + 1:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, bgr = self._capture.read()
            index = 0
        if not ok or bgr is None:
            raise ValueError(f"Video frame {index} could not be decoded: {self.source}")
        self._video_index = index
        self._video_frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        return self._video_frame

    def frame_path(self, index: int) -> Path:
        if self.kind == "video":
            raise ValueError("Streamed video frames do not have individual cache paths")
        return self.frame_paths[index]

    def temporal_cache_key(self, index: int) -> str:
        return f"{self.identity}:{min(max(int(index), 0), self.frame_count - 1)}"

    def analysis_frame_path(self, frame: MediaFrame) -> tuple[Path, bool]:
        """Materialize a streamed frame for exact analysis.

        The returned boolean marks a transient video PNG that callers should
        remove after the content-addressed transport result has been stored.
        """

        if self.kind != "video":
            return self.frame_path(frame.index), False
        if frame.index == 0:
            return self.reference_path, False
        root = self.reference_path.parent / "temporal_frames"
        root.mkdir(parents=True, exist_ok=True)
        # BMP is an uncompressed, byte-exact interchange file. The analyzers
        # see the same RGB pixels as the old PNG path, but writing and reopening
        # a 1080p anchor is roughly an order of magnitude faster.
        path = root / f"frame_{frame.index:08d}.bmp"
        Image.fromarray(frame.rgba, "RGBA").save(path, format="BMP")
        return path, True

    def temporal_anchor_indices(
        self,
        rate_hz: float = TEMPORAL_TRANSPORT_HZ,
        *,
        detect_changes: bool = False,
    ) -> tuple[int, ...]:
        """Return exact full-scene anchor frames for temporal animation.

        Animated image frames retain their authored variable timing and each
        receive an exact solution. Low-frame-rate video also receives an exact
        solution for every frame. Normal video uses regular anchors plus the
        frames on both sides of cuts, flashes, and abrupt illumination/color
        changes, preventing brief lighting events from disappearing between
        the regular samples.

        Change detection intentionally runs only in the temporal worker (or at
        export), never on the UI thread.
        """

        if not self.animated:
            return (0,)
        if self.kind == "animated-image":
            return tuple(range(self.frame_count))
        if self.fps <= LOW_FPS_EXACT_LIMIT:
            return tuple(range(self.frame_count))
        interval = max(1, round(self.fps / max(float(rate_hz), 0.1)))
        anchors = set(range(0, self.frame_count, interval))
        anchors.add(self.frame_count - 1)
        if detect_changes:
            anchors.update(self._abrupt_video_change_indices())
        return tuple(sorted(anchors))

    def _abrupt_video_change_indices(self) -> tuple[int, ...]:
        """Cheaply locate video frames that cannot safely be interpolated over."""

        if self.kind != "video" or self.frame_count < 2:
            return ()
        if self._video_change_cache is not None:
            return self._video_change_cache
        fast = self._abrupt_video_change_indices_ffmpeg()
        if fast is not None:
            self._video_change_cache = fast
            return fast
        capture = cv2.VideoCapture(str(self.source))
        if not capture.isOpened():
            capture.release()
            return ()
        changes: set[int] = set()
        previous: np.ndarray | None = None
        previous_mean: np.ndarray | None = None
        previous_highlight = 0.0
        index = 0
        try:
            while index < self.frame_count:
                ok, bgr = capture.read()
                if not ok or bgr is None:
                    break
                reduced = cv2.resize(bgr, (48, 27), interpolation=cv2.INTER_AREA)
                lab = cv2.cvtColor(reduced, cv2.COLOR_BGR2LAB).astype(np.float32)
                mean = lab.reshape(-1, 3).mean(axis=0)
                luminance = lab[..., 0]
                highlight = float(np.percentile(luminance, 95.0))
                if previous is not None and previous_mean is not None:
                    pixel_delta = float(np.mean(np.abs(lab - previous)))
                    luminance_delta = abs(float(mean[0] - previous_mean[0]))
                    chroma_delta = float(np.linalg.norm(mean[1:] - previous_mean[1:]))
                    highlight_delta = abs(highlight - previous_highlight)
                    if (
                        pixel_delta >= 14.0
                        or luminance_delta >= 8.0
                        or chroma_delta >= 7.0
                        or highlight_delta >= 13.0
                    ):
                        changes.add(index - 1)
                        changes.add(index)
                        self._video_cuts.add(index)
                previous = lab
                previous_mean = mean
                previous_highlight = highlight
                index += 1
        finally:
            capture.release()
        self._video_change_cache = tuple(sorted(changes))
        return self._video_change_cache

    def temporal_cut_indices(self) -> tuple[int, ...]:
        """Return actual right-hand cut frames, distinct from their before/after anchors."""
        self._abrupt_video_change_indices()
        return tuple(sorted(self._video_cuts))

    def _abrupt_video_change_indices_ffmpeg(self) -> tuple[int, ...] | None:
        """Run the same cut/flash metrics on an FFmpeg thumbnail stream.

        FFmpeg decodes and area-downsamples inside its native pipeline instead
        of transferring every 1080p frame through Python first. Validation on
        the five supplied stress videos retained every legacy change anchor
        (and conservatively added three borderline frames) while running more
        than ten times faster.
        """

        try:
            changes = {
                index
                for _scanned_through, window_changes in self.iter_video_change_windows(
                    self.frame_count
                )
                for index in window_changes
            }
            return tuple(sorted(changes))
        except (ImportError, OSError, RuntimeError, subprocess.SubprocessError):
            return None

    def iter_video_change_windows(
        self,
        window_frames: int,
    ) -> Iterator[tuple[int, tuple[int, ...]]]:
        """Stream exact cut/flash decisions in bounded look-ahead windows.

        The metric and thresholds are intentionally identical to the complete
        scan above. Yielding prefixes lets the temporal analyzer solve the
        first seconds and start exact playback while FFmpeg remains paused on
        its pipe, instead of making the viewer wait for an entire first pass.
        """

        if self.kind != "video" or self.frame_count < 2:
            yield 0, ()
            return
        from imageio_ffmpeg import get_ffmpeg_exe

        window_frames = max(2, int(window_frames))
        command = [
            get_ffmpeg_exe(),
            "-loglevel",
            "error",
            "-i",
            str(self.source),
            "-vf",
            "scale=48:27:flags=area",
            # Keep decoded frame indices aligned with OpenCV. FFmpeg's auto
            # mode may duplicate/drop frames to regularize WebM timestamps.
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "pipe:1",
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        frame_bytes = 48 * 27 * 3
        changes: set[int] = set()
        previous: np.ndarray | None = None
        previous_mean: np.ndarray | None = None
        previous_highlight = 0.0
        index = 0
        last_yielded = -1
        try:
            while True:
                data = bytearray()
                while len(data) < frame_bytes:
                    chunk = process.stdout.read(frame_bytes - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                if len(data) != frame_bytes:
                    break
                reduced = np.frombuffer(data, dtype=np.uint8).reshape(27, 48, 3)
                lab = cv2.cvtColor(reduced, cv2.COLOR_BGR2LAB).astype(np.float32)
                mean = lab.reshape(-1, 3).mean(axis=0)
                highlight = float(np.percentile(lab[..., 0], 95.0))
                if previous is not None and previous_mean is not None:
                    pixel_delta = float(np.mean(np.abs(lab - previous)))
                    luminance_delta = abs(float(mean[0] - previous_mean[0]))
                    chroma_delta = float(np.linalg.norm(mean[1:] - previous_mean[1:]))
                    highlight_delta = abs(highlight - previous_highlight)
                    if (
                        pixel_delta >= 14.0
                        or luminance_delta >= 8.0
                        or chroma_delta >= 7.0
                        or highlight_delta >= 13.0
                    ):
                        changes.update((index - 1, index))
                        self._video_cuts.add(index)
                previous = lab
                previous_mean = mean
                previous_highlight = highlight
                index += 1
                if index % window_frames == 0:
                    last_yielded = index - 1
                    yield last_yielded, tuple(sorted(changes))
                    changes.clear()
            stderr = process.stderr.read()
            return_code = process.wait()
            if return_code or index == 0:
                message = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(message or "FFmpeg temporal scan failed")
            if index - 1 > last_yielded:
                yield index - 1, tuple(sorted(changes))
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        finally:
            process.stdout.close()
            process.stderr.close()

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
