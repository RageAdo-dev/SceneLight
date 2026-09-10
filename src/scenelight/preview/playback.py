"""Timestamped, bounded decoding independent of the lighting analyzer."""

from __future__ import annotations

import math
from concurrent.futures import Executor, Future

from .media import MediaClip, MediaFrame


class VideoPlayback:
    """Keep one frame ahead without blocking the UI or accumulating stale work.

    Absolute frame numbers distinguish consecutive loops. A completed future is
    retained until its presentation time, and its successor is submitted in the
    same call that consumes it. The executor owns access to the clip's decoder.
    """

    def __init__(
        self, media: MediaClip, executor: Executor, *, on_ready=None, initially_presented=-1
    ):
        if not math.isfinite(media.fps) or media.fps <= 0 or media.frame_count < 1:
            raise ValueError("Video playback requires a valid frame rate and frame count")
        self.media = media
        self.executor = executor
        self.future: Future | None = None
        self.requested = -1
        self.presented = int(initially_presented)
        self.on_ready = on_ready
        self.last_target = -1
        self.closed = False
        self._retired: list[Future] = []

    def _submit(self, absolute_index: int) -> None:
        self.requested = absolute_index
        index = absolute_index % self.media.frame_count
        self.future = self.executor.submit(self.media.frame_by_index, index)
        if self.on_ready is not None:
            self.future.add_done_callback(lambda _future: self.on_ready())

    def poll(self, elapsed_ms: float) -> MediaFrame | None:
        if self.closed:
            return None
        if not math.isfinite(elapsed_ms):
            raise ValueError("Playback time must be finite")
        target = int(max(0.0, elapsed_ms) * self.media.fps / 1000.0)
        self._retired = [future for future in self._retired if not future.done()]
        if target < self.last_target:
            # The executor is serial, so a running old seek finishes before the
            # new request touches this same decoder. Its result is discarded.
            if self.future is not None:
                if not self.future.cancel() and not self.future.done():
                    self._retired.append(self.future)
            self.future = None
            self.presented = -1
        self.last_target = target
        if self.future is None:
            self._submit(max(target, self.presented + 1))
        future = self.future
        if not future.done() or self.requested > target:
            return None
        frame = future.result()
        ready = self.requested
        self.future = None
        # Catch up directly after a stall. Delivering the obsolete frame and
        # queueing every intervening frame would make latency grow unbounded.
        if target - ready > 1:
            self._submit(target)
            return None
        self._submit(max(target, ready + 1))
        if ready <= self.presented:
            return None
        self.presented = ready
        return frame

    def stop(self) -> tuple[Future, ...]:
        """Detach; return all work the owner must drain before closing the clip."""
        self.closed = True
        future = self.future
        self.future = None
        if future is not None:
            future.cancel()
        pending = tuple(self._retired) + ((future,) if future is not None else ())
        self._retired = []
        return pending
