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
    assert buttons >= {
        "Open background  Ctrl+O",
        "Open sprite / animation",
        "Calibrate",
        "Save profile",
        "Export config",
        "Export PNG / GIF / video",
    }
    assert not buttons & {
        "Asset library…",
        "Add character…",
        "Save scene…",
        "Export sprite rules",
        "Logs & report…",
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
    window._open_calibration()
    assert window._sidebar_tabs.currentIndex() == 1
    assert QApplication.activeModalWidget() is None
    window._calibration_editor._controls["exposure_bias"].setValue(-0.35)
    assert window._view._calibration.exposure_bias == -0.35
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


def test_preset_and_strength_changes_render_the_same_as_direct_settings(single_preview, renderer):
    import numpy as np

    from scenelight.calibration import lighting_mode_preset

    window, paths, _errors = single_preview
    window._load_sprite(paths[0])
    _wait_for_sprite(window)
    for index, name in ((1, "physical"), (3, "separate"), (2, "cinematic"), (1, "physical")):
        window._lighting_look.setCurrentIndex(index)
        _strength, calibration = lighting_mode_preset(name)
        window._strength_slider.setValue(63)
        assert window._calibration == window._view._calibration == calibration
        assert window._calibration_editor.calibration == calibration
        assert window._settings_export._profile.calibration == calibration
        assert window._view._strength == 0.63
        frame = window._view.render_rgba((640, 360))
        # An independent GL view starts directly in the requested final state.
        renderer.set_sprite(paths[0], window._form_artifacts_by_frame[0])
        renderer.set_placement(
            window._view._horizontal, window._view._baseline, window._view._character_height
        )
        renderer.set_calibration(calibration)
        renderer.set_strength(0.63)
        renderer.set_live_analysis_enabled(True)
        renderer.set_background_frame(window._view._background_frame)
        reference = renderer.render_rgba((640, 360))
        np.testing.assert_array_equal(frame, reference)
    renderer.set_calibration(Calibration())
    renderer.set_strength(1.0)


def test_toolbar_save_and_export_open_review_without_writing_or_blocking(single_preview):
    window, paths, _errors = single_preview
    profile_path = paths[0].parent / "profile.json"
    config_path = paths[0].parent / "scenelight.json"
    window._settings_export.set_destination(profile_path)
    window._save_calibration_profile()
    assert window._sidebar_tabs.currentIndex() == 2
    assert QApplication.activeModalWidget() is None
    assert not profile_path.exists()
    window._export_calibration_config()
    window._settings_export.set_destination(config_path)
    assert not config_path.exists()
    window._strength_slider.setValue(78)
    window._settings_export.write_button.click()
    import json

    assert json.loads(config_path.read_bytes())["strength"] == 0.78
    assert not profile_path.exists()
    window._open_calibration()
    assert window._sidebar_tabs.currentIndex() == 1
    assert window._strength_slider.value() == 78


def test_adjustments_visible_on_open_and_navigation_stays_accessible(single_preview):
    from PySide6.QtCore import QPoint

    window, _paths, _errors = single_preview
    window.resize(1280, 720)
    assert window._sidebar_tabs.tabText(window._sidebar_tabs.currentIndex()) == "Adjust"
    editor = window._calibration_editor
    expected = {
        "Lighting": "ambient_strength",
        "Advanced": "key_strength",
        "Light color": "light_color_amount",
        "Sprite glow": "glow_strength",
        "Cast light": "emission_strength",
    }
    initial = editor.calibration
    for name in (*expected, "Color glow"):
        editor.category_buttons[name].click()
        QApplication.processEvents()
        assert editor.category_buttons[name].isChecked()
        assert sum(button.isChecked() for button in editor.category_buttons.values()) == 1
        if name in expected:
            assert editor._controls[expected[name]].isVisible()
        else:
            assert editor._color_glow.add_button.isVisible()
            assert not editor._color_glow.details.isVisible()
            editor._color_glow.add_button.click()
            QApplication.processEvents()
            assert editor._color_glow.details.isVisible()
            assert editor._color_glow.values["strength"].maximum() == 10
            editor._color_glow.remove_button.click()
        assert not editor.scroll.horizontalScrollBar().isVisible()
        positions = {
            key: button.mapTo(window, QPoint()) for key, button in editor.category_buttons.items()
        }
        editor.scroll.verticalScrollBar().setValue(editor.scroll.verticalScrollBar().maximum())
        QApplication.processEvents()
        for key, button in editor.category_buttons.items():
            assert button.isVisible()
            assert button.mapTo(window, QPoint()) == positions[key]
            assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
        assert editor.calibration == initial
    editor.category_buttons["Sprite glow"].click()
    QApplication.processEvents()
    # All the primary glow controls fit without scrolling on a 720p logical window.
    assert editor.scroll.verticalScrollBar().maximum() == 0


def test_glow_controls_drive_live_render_and_review(single_preview, renderer, monkeypatch):
    import numpy as np
    from PySide6.QtGui import QColor

    from scenelight.preview.calibration_dialog import QColorDialog

    window, paths, _errors = single_preview
    window._load_sprite(paths[0])
    _wait_for_sprite(window)
    baseline = window._view.render_rgba((640, 360))
    editor = window._calibration_editor
    editor.category_buttons["Sprite glow"].click()
    editor._sliders["glow_strength"].setValue(1000)
    assert editor.calibration.glow_strength == 10
    assert editor._controls["glow_strength"].value() == 10
    editor._controls["glow_strength"].setValue(1.75)
    assert editor._sliders["glow_strength"].value() == 175
    editor._sliders["glow_radius"].setValue(65)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor("#22aaff"))
    editor._color_button.click()
    editor._glow_mix_slider.setValue(35)
    editor.category_buttons["Color glow"].click()
    editor._color_glow.add_button.click()
    editor._color_glow.values["strength"].setValue(0.6)
    editor.category_buttons["Cast light"].click()
    editor._controls["emission_strength"].setValue(0.5)
    calibration = editor.calibration
    assert calibration.glow_strength == 1.75
    assert calibration.glow_radius == 0.65
    assert calibration.glow_color_mix == 0.35
    assert calibration.glow_rules[0].strength == 0.6
    assert calibration.emission_strength == 0.5
    assert window._view._calibration == window._settings_export._profile.calibration == calibration
    frame = window._view.render_rgba((640, 360))
    assert np.abs(frame.astype(float) - baseline).mean() > 1.0
    renderer.set_sprite(paths[0], window._form_artifacts_by_frame[0])
    renderer.set_placement(
        window._view._horizontal, window._view._baseline, window._view._character_height
    )
    renderer.set_calibration(calibration)
    renderer.set_strength(window._view._strength)
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(window._view._background_frame)
    np.testing.assert_array_equal(frame, renderer.render_rgba((640, 360)))
    renderer.set_calibration(Calibration())
    renderer.set_strength(1.0)


def test_sidebar_wheel_does_not_edit_glow_values(single_preview):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    window, _paths, _errors = single_preview
    editor = window._calibration_editor
    editor.category_buttons["Sprite glow"].click()
    editor._controls["glow_strength"].setValue(3.0)
    before = editor.calibration
    for widget in (editor._controls["glow_strength"], editor._sliders["glow_strength"]):
        widget.setFocus()
        center = widget.rect().center()
        event = QWheelEvent(
            QPointF(center),
            QPointF(widget.mapToGlobal(center)),
            QPoint(),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget, event)
        assert editor.calibration == before
    editor.category_buttons["Advanced"].click()
    window.resize(1280, 720)
    QApplication.processEvents()
    scroll = editor.scroll
    assert scroll.verticalScrollBar().maximum() > 0
    center = scroll.viewport().rect().center()
    QApplication.sendEvent(
        scroll.viewport(),
        QWheelEvent(
            QPointF(center),
            QPointF(scroll.viewport().mapToGlobal(center)),
            QPoint(),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        ),
    )
    assert scroll.verticalScrollBar().value() > 0
    assert editor.calibration == before
