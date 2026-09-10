from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from scenelight.preview.playback import VideoPlayback


class ImmediateExecutor:
    def submit(self, callback, *args):
        future = Future()
        try:
            future.set_result(callback(*args))
        except Exception as error:
            future.set_exception(error)
        return future


class Video:
    fps = 60.0
    frame_count = 60

    def frame_by_index(self, index):
        return SimpleNamespace(index=index)


def test_initial_frame_is_not_decoded_again_and_completion_notifies_owner():
    notified = []
    playback = VideoPlayback(
        Video(), ImmediateExecutor(), initially_presented=0, on_ready=lambda: notified.append(True)
    )
    assert playback.poll(0) is None
    assert playback.requested == 1
    assert notified == [True]
    assert playback.poll(17).index == 1
    assert len(notified) == 2


def test_sixty_fps_source_is_not_halved_by_fifteen_ms_timer():
    playback = VideoPlayback(Video(), ImmediateExecutor())
    frames = []
    for elapsed in range(0, 6000, 15):
        frame = playback.poll(elapsed)
        if frame is not None:
            frames.append((elapsed, frame.index))
    assert len(frames) >= 359
    assert [index for _time, index in frames] == [i % 60 for i in range(len(frames))]


def test_prefetched_frame_waits_for_its_timestamp_and_wraps_without_restarting_clock():
    playback = VideoPlayback(Video(), ImmediateExecutor())
    assert playback.poll(0).index == 0
    assert playback.poll(1) is None
    assert playback.poll(16) is None
    assert playback.poll(17).index == 1
    for index in range(2, 60):
        assert playback.poll(index * 1000 / 60 + 0.01).index == index
    assert playback.poll(1000.01).index == 0
    assert playback.presented == 60


def test_backward_seek_discards_prefetched_future():
    playback = VideoPlayback(Video(), ImmediateExecutor())
    assert playback.poll(700).index == 42
    assert playback.poll(100).index == 6
    assert playback.poll(117).index == 7


def test_stall_skips_obsolete_decodes_without_building_backlog():
    playback = VideoPlayback(Video(), ImmediateExecutor())
    assert playback.poll(0).index == 0
    assert playback.poll(900) is None
    assert playback.requested == 54
    assert playback.poll(900).index == 54
    assert playback.poll(900) is None


def test_decode_failure_is_propagated_to_owner():
    class BrokenVideo(Video):
        def frame_by_index(self, index):
            raise OSError("Decoder failed")

    with pytest.raises(OSError, match="Decoder failed"):
        VideoPlayback(BrokenVideo(), ImmediateExecutor()).poll(0)


def test_stop_returns_inflight_work_and_never_presents_it():
    class DelayedExecutor:
        def submit(self, callback, *args):
            future = Future()
            future.set_running_or_notify_cancel()
            return future

    playback = VideoPlayback(Video(), DelayedExecutor())
    assert playback.poll(0) is None
    future = playback.future
    assert playback.stop() == (future,)
    future.set_result(SimpleNamespace(index=0))
    assert playback.poll(0) is None


def test_stop_also_drains_a_running_decode_superseded_by_a_seek():
    class DelayedExecutor:
        def submit(self, callback, *args):
            future = Future()
            future.set_running_or_notify_cancel()
            return future

    playback = VideoPlayback(Video(), DelayedExecutor())
    playback.poll(500)
    previous = playback.future
    playback.poll(100)
    current = playback.future
    assert playback.stop() == (previous, current)
