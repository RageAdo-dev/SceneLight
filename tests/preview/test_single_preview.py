"""Single-sprite Preview keeps precise placement and modern lighting controls."""

import time
from concurrent.futures import Future

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
from test_gpu_lighting import renderer as renderer

from scenelight import diagnostics
from scenelight.calibration import Calibration, ColorGlowRule
from scenelight.preview import ui
from scenelight.preview.artifacts import ArtifactCache


@pytest.fixture
def single_preview(renderer, tmp_path, monkeypatch):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "userdata" / "projects"))
    monkeypatch.setattr(diagnostics, "_session", None)
    monkeypatch.setattr(ui, "ArtifactCache", lambda: ArtifactCache(tmp_path / "analysis"))
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, title, message: errors.append((title, message))
    )
    paths = []
    for name, color in (("first", (180, 50, 30, 255)), ("second", (20, 120, 180, 255))):
        path = tmp_path / (name + ".png")
        image = Image.new("RGBA", (100, 160))
        ImageDraw.Draw(image).ellipse((15, 10, 85, 145), fill=color)
        image.save(path)
        paths.append(path)
    background = tmp_path / "room.png"
    Image.new("RGB", (640, 360), (25, 30, 40)).save(background)
    window = ui.MainWindow()
    window._cache._cuda_available = False
    window.show()
    QApplication.processEvents()
    window._load_background(background)
    try:
        yield window, paths, errors
        assert not errors, errors
    finally:
        window.close()
        QApplication.processEvents()


def _wait_for_sprite(window):
    deadline = time.monotonic() + 20
    while len(window._form_artifacts_by_frame) != window._sprite_media.frame_count:
        QApplication.processEvents()
        assert time.monotonic() < deadline, "Surface preparation did not finish"
        time.sleep(0.01)
    QApplication.processEvents()


def test_simple_controls_replace_sprite_keep_glow_and_ignore_stale_results(single_preview):
    window, paths, _errors = single_preview
    buttons = {button.text() for button in window.findChildren(QPushButton)}
    assert buttons == {
        "Open background  Ctrl+O",
        "Open sprite / animation",
        "Calibrate",
        "Save profile",
        "Export config",
        "Export PNG / GIF / video",
    }
    labels = {label.text() for label in window.findChildren(QLabel)}
    assert {
        "Horizontal",
        "Baseline",
        "Character height",
        "Lighting preset",
        "Lighting strength",
    } <= labels
    assert "Exact lighting strength" not in labels
    window._load_sprite(paths[0])
    _wait_for_sprite(window)
    old_generation = window._form_generation
    old_form = window._form_artifacts_by_frame[0]
    calibration = Calibration(glow_strength=7.5, glow_rules=(ColorGlowRule(strength=10),))
    window._set_calibration(calibration)
    window._strength_slider.setValue(47)
    window._load_sprite(paths[1])
    _wait_for_sprite(window)
    assert window._sprite_path == paths[1]
    assert window._view._sprite_path == paths[1]
    assert window._view._scene_sprites is None
    assert window._calibration == window._view._calibration == calibration
    assert window._view._strength == 0.47
    window._on_form_ready(old_generation, paths[0], old_form, old_form.metadata)
    old_error = Future()
    old_error.set_exception(ValueError("old source replaced"))
    window._form_finished(old_generation, paths[0], old_error)
    assert window._view._sprite_path == paths[1]
    assert len(window._form_artifacts_by_frame) == 1
    window._view.export_png(paths[1].parent / "output.png", (320, 180))


def test_drag_keeps_subpercent_coordinates_across_frames_and_slider_changes(single_preview):
    window, paths, _errors = single_preview
    window._load_sprite(paths[0])
    _wait_for_sprite(window)
    view = window._view
    view.set_placement(0.5032, 0.9113, 0.8057)
    view.placementChanged.emit(view._horizontal, view._baseline, view._character_height)
    view._viewport_qt = (0, 0, 1000, 600)
    origin = QPointF(200, 200)
    view.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, origin, origin, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    for step in range(1, 6):
        position = origin + QPointF(step, step)
        view.mouseMoveEvent(
            QMouseEvent(
                QEvent.MouseMove, position, position, Qt.NoButton, Qt.LeftButton, Qt.NoModifier
            )
        )
        view.render_rgba((320, 180))
        assert view._horizontal == pytest.approx(0.5032 + step / 1000)
        assert view._baseline == pytest.approx(0.9113 + step / 600)
    view.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease, position, position, Qt.LeftButton, Qt.NoButton, Qt.NoModifier
        )
    )
    precise = (view._horizontal, view._baseline)
    window._height_slider.setValue(85)
    assert (view._horizontal, view._baseline) == precise
    assert view._character_height == 0.85
    window._horizontal_slider.setValue(60)
    assert view._baseline == precise[1]
