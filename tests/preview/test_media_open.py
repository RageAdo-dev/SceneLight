import threading
from concurrent.futures import CancelledError
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from scenelight.preview import media_open
from scenelight.preview.media import MediaClip


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_slow_open_keeps_event_loop_running_and_cancel_closes_candidate(app, tmp_path, monkeypatch):
    made, closed, ready = [], [], threading.Event()
    dialogs = []
    original = media_open.QProgressDialog

    def dialog(*args):
        value = original(*args)
        dialogs.append(value)
        return value

    def factory(*args, cancelled, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        clip = SimpleNamespace(close=lambda: closed.append(True))

        def frame_at(_):
            ready.set()
            assert cancelled.wait(3), "Cancel never reached the worker"
            raise CancelledError()

        clip.frame_at = frame_at
        made.append(clip)
        return clip

    monkeypatch.setattr(media_open, "QProgressDialog", dialog)
    timer = QTimer()
    ticks = []

    def cancel():
        ticks.append(True)
        if ready.is_set():
            dialogs[0].findChild(QPushButton).click()

    timer.timeout.connect(cancel)
    timer.start(10)
    try:
        assert media_open.open_media(Path("slow.apng"), tmp_path, None, factory=factory) is None
    finally:
        timer.stop()
    assert ticks and made
    # Closing the candidate happens on the worker after Cancel wakes it.
    for _ in range(100):
        if closed:
            break
        threading.Event().wait(0.01)
    assert closed == [True]


def test_cancelled_animation_extraction_can_be_reopened(tmp_path):
    source = tmp_path / "animation.png"
    frames = [Image.new("RGBA", (40, 40), (i * 30, 20, 10, 255)) for i in range(6)]
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=30, loop=0)
    cancelled = threading.Event()

    def progress(_message, current, _total):
        if current == 2:
            cancelled.set()

    with pytest.raises(CancelledError):
        MediaClip(source, tmp_path / "cache", cancelled=cancelled, progress=progress)
    assert not list((tmp_path / "cache").glob("*/media.json"))
    clip = MediaClip(source, tmp_path / "cache")
    assert clip.frame_count == 6
    assert clip.frame_at(90).rgba[0, 0, 0] == 90
    clip.close()


def test_successful_open_returns_decoded_first_frame(app, tmp_path):
    source = tmp_path / "still.png"
    Image.new("RGBA", (9, 7), (10, 20, 30, 100)).save(source)
    clip, frame = media_open.open_media(source, tmp_path / "cache", None)
    assert frame.rgba.shape == (7, 9, 4)
    assert tuple(frame.rgba[0, 0]) == (10, 20, 30, 100)
    clip.close()
