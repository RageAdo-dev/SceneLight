import os
import sys

import pytest

from scenelight.calibration import Calibration, ColorGlowRule


def test_color_rules_edit_independently_and_cancel_restores_all_settings(monkeypatch):
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from scenelight.preview.calibration_dialog import CalibrationDialog
    from scenelight.preview.color_glow_ui import QColorDialog

    app = QApplication.instance() or QApplication([])
    initial = Calibration(exposure_bias=-0.4, glow_strength=0.3, glow_color_mix=0.25)
    changes = []
    dialog = CalibrationDialog(initial, changes.append)
    try:
        editor = dialog._color_glow
        assert not editor.rules
        assert not editor.remove_button.isEnabled()
        editor.add_button.click()
        editor.sliders["tolerance"].setValue(28)
        editor.values["strength"].setValue(1.25)
        editor.values["radius"].setValue(0.5)
        editor.values["softness"].setValue(0.2)
        editor.enabled.setChecked(False)
        first = dialog.calibration.glow_rules[0]
        assert first.tolerance == 0.28
        assert first.strength == 1.25 and first.radius == 0.5
        assert first.softness == 0.2 and not first.enabled
        editor.copy_button.click()
        editor.enabled.setChecked(True)
        monkeypatch.setattr(QColorDialog, "getColor", lambda *a: QColor("#2244ff"))
        editor.color.click()
        second = dialog.calibration.glow_rules[1]
        assert second.enabled and second.color[2] == 1.0
        assert second.color[0] == pytest.approx(34 / 255, abs=0.00002)
        assert dialog.calibration.glow_rules[0] == first
        assert changes[-1].glow_rules[1] == second
        assert changes[-1].exposure_bias == -0.4
        assert changes[-1].glow_strength == 0.3
        assert changes[-1].glow_color_mix == 0.25
        editor.remove_button.click()
        assert dialog.calibration.glow_rules == (first,)
        editor.remove_button.click()
        assert dialog.calibration == initial
        editor.add_button.click()
        dialog.reject()
        assert changes[-1] == initial
    finally:
        dialog.close()
        app.processEvents()


def test_loading_rules_is_silent_and_switching_keeps_each_value():
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from scenelight.preview.color_glow_ui import ColorGlowEditor

    app = QApplication.instance() or QApplication([])
    editor = ColorGlowEditor()
    try:
        rules = tuple(ColorGlowRule(name=f"Rule {i}", strength=i / 10) for i in range(17))
        changes = []
        editor.changed.connect(lambda: changes.append(editor.rules))
        editor.set_rules(rules)
        assert not changes
        for i in (16, 0, 5, 9):
            editor.rule_list.setCurrentRow(i)
            assert editor.values["strength"].value() == i / 10
        assert editor.rules == rules and not changes
    finally:
        editor.close()
        app.processEvents()
