import os
import sys

import pytest

from scenelight.calibration import Calibration, CalibrationProfile


def test_glow_picker_toggle_cancel_and_defaults_preserve_separate_cast_color(monkeypatch):
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from scenelight.preview.calibration_dialog import CalibrationDialog, QColorDialog

    app = QApplication.instance() or QApplication([])
    initial = Calibration(emission_red=0.8, emission_green=0.25, emission_blue=0.1)
    changes = []
    dialog = CalibrationDialog(initial, changes.append)
    try:
        assert "Glow is off" in dialog._glow_hint.text()
        dialog._controls["glow_strength"].setValue(1.0)
        monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor("#2040ff"))
        dialog._choose_glow_color()
        selected = dialog.calibration
        assert selected.glow_color_mix == 1
        assert selected.glow_red == pytest.approx(32 / 255, abs=0.00002)
        assert selected.glow_blue == 1
        assert (selected.emission_red, selected.emission_green, selected.emission_blue) == (
            0.8,
            0.25,
            0.1,
        )
        assert dialog._custom_glow.isChecked()
        assert "Custom color" in dialog._glow_hint.text()
        assert changes[-1] == selected
        assert (
            CalibrationProfile.from_payload(CalibrationProfile(selected).to_payload()).calibration
            == selected
        )
        count = len(changes)
        monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor())
        dialog._choose_glow_color()
        assert len(changes) == count
        assert dialog.calibration == selected
        dialog._custom_glow.setChecked(False)
        assert changes[-1].glow_color_mix == 0
        assert changes[-1].glow_blue == 1
        dialog._set_calibration(Calibration())
        assert dialog.calibration == Calibration()
        assert not dialog._custom_glow.isChecked()
        assert "Glow is off" in dialog._glow_hint.text()
        dialog.reject()
        assert changes[-1] == initial
    finally:
        dialog.close()
        app.processEvents()
