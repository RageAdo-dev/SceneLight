import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scenelight.calibration import Calibration, CalibrationProfile
from scenelight.preview import ui


@pytest.mark.parametrize("kind", ["background", "sprite"])
def test_corrupt_first_frame_preserves_open_composition(tmp_path, monkeypatch, kind):
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    source = tmp_path / "truncated.png"
    pixels = np.random.default_rng(7).integers(0, 256, (64, 64, 4), dtype=np.uint8)
    Image.fromarray(pixels).save(source)
    source.write_bytes(source.read_bytes()[:100])
    opened, closed, errors = [], [], []
    original = ui.MediaClip

    def candidate(*args, **kwargs):
        clip = original(*args, **kwargs)
        opened.append(clip)
        close = clip.close
        clip.close = lambda: (closed.append(clip), close())
        return clip

    monkeypatch.setattr(ui, "MediaClip", candidate)
    opener = ui.open_media
    monkeypatch.setattr(
        ui, "open_media", lambda path, cache, parent, **kwargs: opener(path, cache, None, **kwargs)
    )
    previous = SimpleNamespace(close=lambda: pytest.fail("Existing media must stay open"))
    window = SimpleNamespace(
        _cache=SimpleNamespace(root=tmp_path / "cache"),
        _background_media=previous,
        _sprite_media=previous,
        _background_path=tmp_path / "existing.png",
        _sprite_path=tmp_path / "actor.png",
        _scene_generation=4,
        _form_generation=7,
        _on_failed=lambda *args: errors.append(args),
    )
    before = dict(vars(window))
    getattr(ui.MainWindow, "_load_" + kind)(window, source)
    assert vars(window) == before
    assert len(opened) == 1 and closed == opened
    assert len(errors) == 1 and "media" in errors[0][0]
    app.processEvents()


@pytest.mark.parametrize("kind", ["scene", "form"])
def test_queued_failure_from_replaced_media_is_ignored(kind):
    errors = []
    window = SimpleNamespace(
        _scene_generation=5, _form_generation=5, _on_failed=lambda *args: errors.append(args)
    )
    ui.MainWindow._on_media_failed(window, kind, 4, "Analysis", "old failure")
    assert not errors
    ui.MainWindow._on_media_failed(window, kind, 5, "Analysis", "current failure")
    assert errors == [("Analysis", "current failure")]


@pytest.mark.parametrize(
    "method,attribute", [("open_background", "_background_path"), ("open_sprite", "_sprite_path")]
)
@pytest.mark.parametrize("project_selected", [False, True])
def test_media_picker_starts_in_project_or_user_home(
    tmp_path, monkeypatch, method, attribute, project_selected
):
    starts = []
    monkeypatch.setattr(
        ui.QFileDialog,
        "getOpenFileName",
        lambda parent, title, start, filters: (starts.append(start) or "", ""),
    )
    window = SimpleNamespace(_project_root=tmp_path if project_selected else None)
    setattr(window, attribute, None)
    getattr(ui.MainWindow, method)(window)
    assert starts == [str(tmp_path if project_selected else Path.home())]


class _ExportProgress:
    def __init__(self, cancelled: bool) -> None:
        self.cancelled = cancelled

    def wasCanceled(self) -> bool:
        return self.cancelled


def test_video_scheduler_waits_for_decode_then_uses_presentation_deadline(monkeypatch):
    calls = []
    timer = SimpleNamespace(
        start=lambda delay: calls.append(delay), stop=lambda: calls.append("stop")
    )
    future = Future()
    state = SimpleNamespace(
        _animation_timer=timer,
        _background_media=SimpleNamespace(animated=True, kind="video", fps=60.0),
        _background_animation_ready=True,
        _background_animation_epoch=10.0,
        _background_playback=SimpleNamespace(future=future, requested=2),
        _sprite_media=None,
        _sprite_animation_ready=False,
        _sprite_animation_epoch=10.0,
    )
    monkeypatch.setattr(ui.time, "perf_counter", lambda: 10.025)
    ui.MainWindow._schedule_animation_tick(state)
    assert calls == ["stop"]
    future.set_result(None)
    ui.MainWindow._schedule_animation_tick(state)
    assert calls == ["stop", 9]


def test_decode_notifications_ignore_old_media_and_paused_exports():
    calls = []
    state = SimpleNamespace(
        _background_decode_generation=4,
        _background_animation_ready=True,
        _exporting_animation=False,
        _advance_animation=lambda: calls.append("advance"),
    )
    ui.MainWindow._on_video_frame_ready(state, 3)
    assert not calls
    state._exporting_animation = True
    ui.MainWindow._on_video_frame_ready(state, 4)
    assert not calls
    state._exporting_animation = False
    ui.MainWindow._on_video_frame_ready(state, 4)
    assert calls == ["advance"]


def test_export_cancel_is_available_while_live_analysis_stops(monkeypatch) -> None:
    future = Future()
    cancelled = threading.Event()
    monkeypatch.setattr(ui.QApplication, "processEvents", lambda: None)

    with pytest.raises(InterruptedError):
        ui._wait_for_export_future(future, _ExportProgress(True), cancelled)

    assert cancelled.is_set()
    assert future.cancelled()


def test_export_wait_returns_completed_live_analysis(monkeypatch) -> None:
    future = Future()
    future.set_result(((0, 3), {3: "scene"}))
    monkeypatch.setattr(ui.QApplication, "processEvents", lambda: None)

    result = ui._wait_for_export_future(
        future,
        _ExportProgress(False),
        threading.Event(),
    )

    assert result == ((0, 3), {3: "scene"})


class _Media:
    animated = True
    fps = 30.0

    def __init__(self, frame_index: int) -> None:
        self.frame_index = frame_index
        self.elapsed: list[float] = []

    def changed_at(self, elapsed_ms: float):
        self.elapsed.append(elapsed_ms)
        return SimpleNamespace(
            index=self.frame_index,
            rgba=np.zeros((2, 2, 4), dtype=np.uint8),
        )

    def index_at(self, elapsed_ms: float) -> int:
        return self.frame_index


class _View:
    def __init__(self) -> None:
        self.background_frames = []
        self.sprite_frames = []

    def set_background_frame(self, rgba, wrap) -> None:
        self.background_frames.append((rgba, wrap))

    def set_sprite_frame(self, rgba, artifacts) -> None:
        self.sprite_frames.append((rgba, artifacts))


class _ValueControl:
    def __init__(self, text: str = "Cinematic") -> None:
        self.value = None
        self.text = text
        self.blocked: list[bool] = []

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(blocked)

    def setValue(self, value: int) -> None:
        self.value = value

    def setText(self, value: str) -> None:
        self.text = value

    def currentText(self) -> str:
        return self.text


def test_light_count_ignores_reserved_disabled_hue_slots() -> None:
    metadata = {
        "light_transport": [
            {
                "position_radius_intensity": (0.5, 0.2, 0.4, 1.0),
                "emission_enabled": (0.8, 1.0),
            },
            {
                "position_radius_intensity": (0.2, 0.4, 0.4, 0.0),
                "emission_enabled": (0.9, 0.0),
            },
            {
                "position_radius_intensity": (0.5, 0.2, 1.0, 0.0),
                "emission_enabled": (0.0, 0.0),
            },
        ]
    }

    assert ui._active_light_count(metadata) == 2


def test_cinematic_quick_look_applies_strength_and_calibration_together() -> None:
    strength_control = _ValueControl()
    strength_label = _ValueControl()
    look = _ValueControl()
    view = SimpleNamespace(
        strengths=[],
        calibrations=[],
        set_strength=lambda value: view.strengths.append(value),
        set_calibration=lambda value: view.calibrations.append(value),
    )
    statuses: list[str] = []
    window = SimpleNamespace(
        _strength_slider=strength_control,
        _strength_value=strength_label,
        _lighting_look=look,
        _view=view,
        statusBar=lambda: SimpleNamespace(showMessage=statuses.append),
        _sync_settings_pages=lambda: None,
    )

    ui.MainWindow._lighting_look_changed(window, 2)

    assert strength_control.value == 72
    assert strength_label.text == "72%"
    assert view.strengths == [0.72]
    assert view.calibrations[0].exposure_bias == -0.22
    assert view.calibrations[0].color_adaptation == 0.92
    assert view.calibrations[0].individual_light_colors == 1.0
    assert statuses == ["Cinematic lighting applied to the live preview"]


def test_current_preview_profile_keeps_lighting_strength() -> None:
    window = SimpleNamespace(
        _calibration=Calibration(exposure_bias=-0.22),
        _calibration_profile=CalibrationProfile(scenes={"hallway": Calibration(rim_strength=0.4)}),
        _view=SimpleNamespace(_strength=0.72),
    )

    profile = ui.MainWindow._current_profile(window)

    assert profile.strength == 0.72
    assert profile.calibration.exposure_bias == -0.22
    assert profile.scenes["hallway"].rim_strength == 0.4


def test_background_animation_does_not_wait_for_sprite_analysis(monkeypatch) -> None:
    background = _Media(7)
    sprite = _Media(3)
    view = _View()
    window = SimpleNamespace(
        _background_animation_ready=True,
        _sprite_animation_ready=False,
        _background_media=background,
        _sprite_media=sprite,
        _background_animation_epoch=8.0,
        _sprite_animation_epoch=9.0,
        _current_background_index=0,
        _view=view,
        _form_artifacts_by_frame={3: object()},
        _apply_temporal_scene=lambda index: None,
    )
    monkeypatch.setattr(ui.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(ui, "environment_wrap", lambda rgba: "exact-wrap")

    ui.MainWindow._advance_animation(window)

    assert background.elapsed == [2000.0]
    assert sprite.elapsed == []
    assert window._current_background_index == 7
    assert len(view.background_frames) == 1
    assert view.background_frames[0][1] == "exact-wrap"
    assert view.sprite_frames == []


def test_video_decode_is_queued_without_blocking_ui_thread() -> None:
    release = threading.Event()
    frame = SimpleNamespace(index=5, rgba=np.zeros((2, 2, 4), dtype=np.uint8))

    class _Video:
        fps = 25.0
        frame_count = 30

        def index_at(self, _elapsed_ms: float) -> int:
            return 5

        def frame_by_index(self, _index: int):
            release.wait(timeout=2.0)
            return frame

    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(lambda: None).result()
    window = SimpleNamespace(
        _background_playback=None,
        _background_decode_generation=0,
        _current_background_index=0,
        _video_decode_executor=executor,
    )
    try:
        started = time.perf_counter()
        assert ui.MainWindow._poll_background_video_frame(window, _Video(), 200.0) is None
        assert time.perf_counter() - started < 0.05
        release.set()
        window._background_playback.future.result(timeout=2.0)

        assert ui.MainWindow._poll_background_video_frame(window, _Video(), 200.0) is frame
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_background_and_sprite_keep_independent_animation_clocks(monkeypatch) -> None:
    background = _Media(7)
    sprite = _Media(3)
    view = _View()
    form = object()
    window = SimpleNamespace(
        _background_animation_ready=True,
        _sprite_animation_ready=True,
        _background_media=background,
        _sprite_media=sprite,
        _background_animation_epoch=7.0,
        _sprite_animation_epoch=9.0,
        _current_background_index=0,
        _view=view,
        _form_artifacts_by_frame={3: form},
        _apply_temporal_scene=lambda index: None,
    )
    monkeypatch.setattr(ui.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(ui, "environment_wrap", lambda rgba: "exact-wrap")

    ui.MainWindow._advance_animation(window)

    assert background.elapsed == [3000.0]
    assert sprite.elapsed == [1000.0]
    assert len(view.background_frames) == 1
    assert view.sprite_frames[0][1] is form


def test_temporal_horizon_stops_before_a_missing_exact_anchor() -> None:
    window = SimpleNamespace(
        _temporal_plan_complete=True,
        _temporal_anchors=(0, 10, 20, 30),
        _temporal_scenes={0: object(), 10: object(), 30: object()},
        _temporal_ready_through=0,
    )

    ui.MainWindow._update_temporal_horizon(window)

    assert window._temporal_ready_through == 10


def test_playback_starts_as_soon_as_exact_first_scene_is_ready() -> None:
    statuses: list[str] = []
    restarted: list[bool] = []
    media = SimpleNamespace(animated=True, fps=10.0, frame_count=100)
    window = SimpleNamespace(
        _background_media=media,
        _scene_artifacts=object(),
        _temporal_plan_complete=True,
        _temporal_plan_known_through=10,
        _temporal_anchors=(0, 10, 20, 30),
        _temporal_ready_through=10,
        _background_animation_ready=False,
        _temporal_playback_started=False,
        _temporal_lookahead_seconds=3.0,
        _restart_background_animation=lambda: restarted.append(True),
        statusBar=lambda: SimpleNamespace(showMessage=statuses.append),
    )

    ui.MainWindow._maybe_start_background_animation(window)
    assert window._background_animation_ready
    assert window._temporal_playback_started
    assert restarted == [True]
    assert statuses == ["Video playing · preparing lighting in the background"]


def test_playback_can_start_from_a_complete_exact_streaming_prefix() -> None:
    restarted: list[bool] = []
    media = SimpleNamespace(animated=True, fps=10.0, frame_count=100)
    window = SimpleNamespace(
        _background_media=media,
        _scene_artifacts=object(),
        _temporal_plan_complete=False,
        _temporal_plan_known_through=20,
        _temporal_anchors=(0, 10, 20),
        _temporal_ready_through=20,
        _background_animation_ready=False,
        _temporal_playback_started=False,
        _restart_background_animation=lambda: restarted.append(True),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    ui.MainWindow._maybe_start_background_animation(window)

    assert window._background_animation_ready
    assert window._temporal_playback_started
    assert restarted == [True]


def test_high_change_video_starts_from_exact_rolling_prefix() -> None:
    restarted: list[bool] = []
    media = SimpleNamespace(animated=True, fps=10.0, frame_count=100)
    window = SimpleNamespace(
        _background_media=media,
        _scene_artifacts=object(),
        _temporal_plan_complete=False,
        _temporal_plan_known_through=30,
        _temporal_anchors=(0, 10, 20, 30),
        _temporal_ready_through=30,
        _temporal_start_allowed=True,
        _background_animation_ready=False,
        _temporal_playback_started=False,
        _restart_background_animation=lambda: restarted.append(True),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _message: None),
    )

    ui.MainWindow._maybe_start_background_animation(window)

    assert window._background_animation_ready
    assert window._temporal_playback_started
    assert restarted == [True]


def test_background_keeps_playing_while_future_anchors_are_built(monkeypatch) -> None:
    background = _Media(25)
    sprite = _Media(3)
    view = _View()
    form = object()
    window = SimpleNamespace(
        _background_animation_ready=True,
        _sprite_animation_ready=True,
        _background_media=background,
        _sprite_media=sprite,
        _background_animation_epoch=9.0,
        _sprite_animation_epoch=9.0,
        _current_background_index=18,
        _view=view,
        _form_artifacts_by_frame={3: form},
        _apply_temporal_scene=lambda index: applied.append(index),
        _temporal_plan_complete=True,
        _temporal_ready_through=20,
        _temporal_scenes={0: object(), 10: object(), 20: object()},
        _temporal_anchors=(0, 10, 20, 30),
    )
    applied: list[int] = []
    monkeypatch.setattr(ui.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(ui, "environment_wrap", lambda rgba: "live-wrap")

    ui.MainWindow._advance_animation(window)

    assert background.elapsed == [1000.0]
    assert window._current_background_index == 25
    assert sprite.elapsed == [1000.0]
    assert view.background_frames[0][1] == "live-wrap"
    assert applied == [25]
    assert view.sprite_frames[0][1] is form
