import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from scenelight.preview import ui


@pytest.mark.parametrize("running", [False, True])
def test_cancelled_export_restarts_fallback_analysis_and_can_be_retried(
    tmp_path, monkeypatch, running
):
    def noop(*args, **kwargs):
        pass

    class CancelDialog:
        canceled = SimpleNamespace(connect=noop)

        def wasCanceled(self):
            return True

        def __getattr__(self, _name):
            return noop

    monkeypatch.setattr(ui, "QProgressDialog", lambda *args: CancelDialog())
    monkeypatch.setattr(ui.QApplication, "processEvents", noop)
    cancelled = threading.Event()
    old = Future()
    if running:
        old.set_running_or_notify_cancel()
    else:
        old.cancel()
    media = SimpleNamespace(
        animated=True,
        source=tmp_path / "movie.gif",
        frame_by_index=lambda _: SimpleNamespace(rgba=np.zeros((2, 2, 4), np.uint8)),
    )
    output = tmp_path / "existing.gif"
    output.write_bytes(b"previous export")
    calls = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        window = SimpleNamespace(
            _background_path=media.source,
            _sprite_path=tmp_path / "sprite.png",
            _background_media=media,
            _sprite_media=None,
            _animation_timer=SimpleNamespace(start=noop, stop=noop),
            _stop_background_decode=noop,
            _temporal_cancel=cancelled,
            _temporal_future=old,
            _gpu_live_background=False,
            _scene_artifacts=object(),
            _scene_generation=4,
            _view=SimpleNamespace(reset_live_history=noop, set_background_frame=noop),
            _apply_temporal_scene=noop,
            _restart_background_animation=noop,
            _restart_sprite_animation=noop,
            _cache=SimpleNamespace(root=tmp_path / "cache"),
            _temporal_executor=executor,
            _warm_temporal_scenes=lambda generation, source, cache, token: (
                calls.append((generation, token.is_set())) or ((0, 1), {})
            ),
        )
        window._resume_background_analysis = lambda: ui.MainWindow._resume_background_analysis(
            window
        )
        window._start_temporal_analysis = lambda *args: ui.MainWindow._start_temporal_analysis(
            window, *args
        )
        window._temporal_finished = lambda *args: ui.MainWindow._temporal_finished(window, *args)
        for attempt in range(2):
            with pytest.raises(InterruptedError):
                ui.MainWindow._export_animation(window, output)
            assert not window._exporting_animation
            assert window._temporal_future is not old
            assert window._temporal_future.result(timeout=5) == ((0, 1), {})
            assert not window._temporal_cancel.is_set()
        assert calls == [(5, False), (6, False)]
        assert cancelled.is_set()
        assert output.read_bytes() == b"previous export"


def test_background_analysis_failure_is_silent_when_its_worker_was_cancelled():
    future = Future()
    future.set_exception(ValueError("cancelled work"))
    cancelled = threading.Event()
    cancelled.set()
    ui.MainWindow._temporal_finished(SimpleNamespace(), 1, future, cancelled)


def test_png_export_waits_for_fallback_background_lighting(tmp_path, monkeypatch):
    notices = []
    monkeypatch.setattr(ui.QInputDialog, "getItem", lambda *args: ("1080p (1920 × 1080)", True))
    monkeypatch.setattr(ui.QMessageBox, "information", lambda *args: notices.append(args[1:]))
    monkeypatch.setattr(
        ui.QFileDialog,
        "getSaveFileName",
        lambda *args: pytest.fail("No output destination should be requested yet"),
    )
    window = SimpleNamespace(
        _background_path=tmp_path / "background.png",
        _sprite_path=tmp_path / "sprite.png",
        _background_media=SimpleNamespace(kind="image"),
        _sprite_media=SimpleNamespace(kind="image", frame_count=1),
        _form_artifacts_by_frame={0: object()},
        _scene_artifacts=None,
        _gpu_live_background=False,
    )
    ui.MainWindow.export(window)
    assert notices and notices[0][0] == "Preparing background"
