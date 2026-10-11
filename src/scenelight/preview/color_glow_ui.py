"""Edit independent color-selective glow rules for the selected sprite."""

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..calibration import ColorGlowRule
from .controls import ScrollSlider, ScrollSpinBox


class ColorGlowEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        self._loading = False
        layout = QVBoxLayout(self)
        note = QLabel("Make colors in the artwork glow. Add a separate rule for each color.")
        note.setWordWrap(True)
        note.setObjectName("subtitle")
        layout.addWidget(note)
        self.rule_list = QListWidget()
        self.rule_list.setMaximumHeight(70)
        self.rule_list.currentRowChanged.connect(self._select)
        layout.addWidget(self.rule_list)
        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Add color")
        self.add_button.clicked.connect(self._add)
        self.copy_button = QPushButton("Duplicate")
        self.copy_button.clicked.connect(self._duplicate)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove)
        actions.addWidget(self.add_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.details = QWidget()
        form = QFormLayout(self.details)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.name = QLineEdit()
        self.name.setPlaceholderText("For example: Red gems")
        self.name.textEdited.connect(self._edit)
        form.addRow("Rule name", self.name)
        self.enabled = QCheckBox("Enable this color glow")
        self.enabled.toggled.connect(self._edit)
        form.addRow("", self.enabled)
        self.color = QPushButton("Choose matching color…")
        self.color.clicked.connect(self._choose_color)
        form.addRow("Artwork color", self.color)
        self.sliders = {}
        self.values = {}
        for key, title, maximum, hint in (
            (
                "tolerance",
                "Color range",
                1.0,
                "Narrow matches only close colors; broad includes more nearby shades.",
            ),
            (
                "softness",
                "Soft edges",
                1.0,
                "Feather the boundary between matching and nonmatching colors.",
            ),
            (
                "strength",
                "Glow strength",
                10.0,
                "Brightness of this color's glow. Zero turns this rule off.",
            ),
            (
                "radius",
                "Halo spread",
                2.0,
                "Spread around matching pixels. Zero keeps glow inside the art.",
            ),
        ):
            row = QHBoxLayout()
            slider = ScrollSlider(Qt.Horizontal)
            slider.setRange(0, round(maximum * 100))
            slider.setAccessibleName(title)
            slider.setToolTip(hint)
            spin = ScrollSpinBox()
            spin.setRange(0, maximum)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setMaximumWidth(80)
            spin.setToolTip(hint)
            slider.valueChanged.connect(lambda value, k=key: self._slide(k, value))
            spin.valueChanged.connect(lambda value, k=key: self._spin(k, value))
            self.sliders[key], self.values[key] = slider, spin
            row.addWidget(slider, 1)
            row.addWidget(spin)
            form.addRow(title, row)
        layout.addWidget(self.details)
        self.hint = QLabel()
        self.hint.setObjectName("subtitle")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch(1)
        self.set_rules(())

    @property
    def rules(self):
        return tuple(self._rules)

    def set_rules(self, rules):
        self._rules = list(rules)
        self._rebuild(0 if rules else -1)

    def _label(self, rule):
        return (rule.name or "Color glow") + (
            " · off" if not rule.enabled or rule.strength == 0 else ""
        )

    def _rebuild(self, index):
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        self.rule_list.addItems([self._label(rule) for rule in self._rules])
        self.rule_list.setCurrentRow(index)
        self.rule_list.blockSignals(False)
        self._select(index)

    def _select(self, index):
        valid = 0 <= index < len(self._rules)
        self.details.setEnabled(valid)
        self.details.setVisible(valid)
        self.rule_list.setVisible(bool(self._rules))
        self.copy_button.setEnabled(valid)
        self.remove_button.setEnabled(valid)
        self.hint.setText(
            "Choose + Add color to start, then pick the artwork color you want to glow."
            if not valid
            else "Match uses the original artwork. Adjust Color range and Soft edges to blend the glow."
        )
        if not valid:
            return
        self._loading = True
        try:
            rule = self._rules[index]
            self.name.setText(rule.name)
            self.enabled.setChecked(rule.enabled)
            color = QColor.fromRgbF(*rule.color)
            swatch = QPixmap(20, 20)
            swatch.fill(color)
            self.color.setIcon(QIcon(swatch))
            self.color.setText("Choose color… " + color.name().upper())
            for key, spin in self.values.items():
                value = getattr(rule, key)
                spin.setValue(value)
                self.sliders[key].setValue(round(value * 100))
        finally:
            self._loading = False

    def _add(self):
        self._rules.append(ColorGlowRule(name=f"Color glow {len(self._rules) + 1}"))
        self._rebuild(len(self._rules) - 1)
        self.changed.emit()

    def _duplicate(self):
        index = self.rule_list.currentRow()
        if index < 0:
            return
        self._rules.insert(
            index + 1, replace(self._rules[index], name=self._rules[index].name + " copy")
        )
        self._rebuild(index + 1)
        self.changed.emit()

    def _remove(self):
        index = self.rule_list.currentRow()
        if index < 0:
            return
        self._rules.pop(index)
        self._rebuild(min(index, len(self._rules) - 1))
        self.changed.emit()

    def _choose_color(self):
        index = self.rule_list.currentRow()
        if index < 0:
            return
        selected = QColorDialog.getColor(
            QColor.fromRgbF(*self._rules[index].color), self, "Match this artwork color"
        )
        if selected.isValid():
            self._rules[index] = replace(
                self._rules[index], color=(selected.redF(), selected.greenF(), selected.blueF())
            )
            self._select(index)
            self.changed.emit()

    def _slide(self, key, value):
        if not self._loading:
            self.values[key].setValue(value / 100)

    def _spin(self, key, value):
        if self._loading:
            return
        self.sliders[key].blockSignals(True)
        self.sliders[key].setValue(round(value * 100))
        self.sliders[key].blockSignals(False)
        index = self.rule_list.currentRow()
        if index >= 0:
            self._rules[index] = replace(self._rules[index], **{key: value})
        self._edit()

    def _edit(self, *_args):
        index = self.rule_list.currentRow()
        if self._loading or index < 0:
            return
        self._rules[index] = replace(
            self._rules[index],
            name=self.name.text(),
            enabled=self.enabled.isChecked(),
        )
        self.rule_list.item(index).setText(self._label(self._rules[index]))
        self.changed.emit()
