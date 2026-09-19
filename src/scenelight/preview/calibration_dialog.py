"""Live, bounded controls for the production shader."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..calibration import Calibration

_BASIC = (
    ("auto_strength", "Automatic match", 0.0, 2.0, 0.01),
    ("exposure_bias", "Exposure bias (stops)", -4.0, 4.0, 0.05),
    ("ambient_strength", "Ambient strength", 0.0, 2.0, 0.01),
    ("color_adaptation", "Color adaptation", 0.0, 2.0, 0.01),
    ("contrast_match", "Contrast match", 0.0, 2.0, 0.01),
    ("saturation_match", "Saturation match", 0.0, 2.0, 0.01),
    ("highlight_rolloff", "Highlight protection", 0.0, 2.0, 0.01),
)

_ADVANCED = (
    ("key_strength", "Key light", 0.0, 2.0, 0.01),
    ("ray_shadow_strength", "Ray shadows", 0.0, 2.0, 0.01),
    ("ambient_occlusion", "Ambient occlusion", 0.0, 2.0, 0.01),
    ("probe_strength", "Environment probes", 0.0, 2.0, 0.01),
    ("bounce_strength", "Ground bounce", 0.0, 2.0, 0.01),
    ("specular_strength", "Specular response", 0.0, 2.0, 0.01),
    ("rim_strength", "Rim light", 0.0, 2.0, 0.01),
    ("wrap_strength", "Edge integration", 0.0, 2.0, 0.01),
    ("grain_match", "Grain match", 0.0, 2.0, 0.01),
    ("shadow_strength", "Shadow strength", 0.0, 2.0, 0.01),
    ("individual_light_colors", "Source color separation", 0.0, 2.0, 0.01),
    ("adaptive_light_colors", "Automatic color separation", 0.0, 2.0, 0.01),
)

_GLOW = (
    ("glow_strength", "Sprite glow", 0.0, 2.0, 0.05),
    ("glow_radius", "Halo spread", 0.0, 2.0, 0.05),
)

_EMITTED_LIGHT = (
    ("emission_strength", "Light cast onto characters", 0.0, 2.0, 0.05),
    ("emission_radius", "Light reach (screen heights)", 0.0, 2.0, 0.05),
    ("emission_red", "Cast-light color · red", 0.0, 2.0, 0.05),
    ("emission_green", "Cast-light color · green", 0.0, 2.0, 0.05),
    ("emission_blue", "Cast-light color · blue", 0.0, 2.0, 0.05),
)


class CalibrationDialog(QDialog):
    def __init__(
        self,
        calibration: Calibration,
        on_change: Callable[[Calibration], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SceneLight calibration")
        self.setMinimumWidth(470)
        self._initial = calibration.normalized()
        self._on_change = on_change
        self._controls: dict[str, QDoubleSpinBox] = {}
        self._glow_color = QColor("#ffffff")
        self._glow_color_mix = 0.0

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._page(_BASIC), "Basic")
        tabs.addTab(self._page(_ADVANCED), "Advanced")
        tabs.addTab(self._glow_page(), "Glow && emitted light")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(lambda: self._set_calibration(Calibration()))
        buttons.addWidget(reset)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        self._set_calibration(self._initial, notify=False)

    def _page(self, fields) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for name, label, minimum, maximum, step in fields:
            control = QDoubleSpinBox()
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setDecimals(2)
            if name == "individual_light_colors":
                control.setToolTip(
                    "Manual override: 0.00 leaves automatic behavior intact; "
                    "1.00 always emphasizes every detected source color."
                )
            if name == "adaptive_light_colors":
                control.setToolTip("Separates strong lights with different colors and positions.")
            if name == "glow_radius":
                control.setToolTip(
                    "1.0 spreads the halo across 4% of the shorter canvas edge. Leave transparent padding around effect art."
                )
            if name.startswith("emission_"):
                control.setToolTip(
                    "Exported for in-game lighting of other selected sprites. The single-sprite Preview shows self glow; there is no second character to receive emitted light."
                )
            control.valueChanged.connect(self._changed)
            self._controls[name] = control
            form.addRow(label, control)
        return page

    def _glow_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        own = QGroupBox("Sprite glow · visible in Preview")
        own_layout = QVBoxLayout(own)
        own_layout.addWidget(self._page(_GLOW))
        color_row = QHBoxLayout()
        self._custom_glow = QCheckBox("Custom glow color")
        self._custom_glow.toggled.connect(self._toggle_glow_color)
        self._color_button = QPushButton("Choose color…")
        self._color_button.clicked.connect(self._choose_glow_color)
        color_row.addWidget(self._custom_glow)
        color_row.addWidget(self._color_button)
        own_layout.addLayout(color_row)
        self._glow_hint = QLabel()
        self._glow_hint.setObjectName("subtitle")
        self._glow_hint.setWordWrap(True)
        own_layout.addWidget(self._glow_hint)
        layout.addWidget(own)

        cast = QGroupBox("Light cast onto other characters")
        cast_layout = QVBoxLayout(cast)
        note = QLabel(
            "These colors affect nearby characters in-game. They do not change this sprite’s glow."
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        cast_layout.addWidget(note)
        cast_layout.addWidget(self._page(_EMITTED_LIGHT))
        layout.addWidget(cast)
        layout.addStretch(1)
        return page

    def _toggle_glow_color(self, checked: bool) -> None:
        self._glow_color_mix = 1.0 if checked else 0.0
        self._changed()

    def _choose_glow_color(self) -> None:
        selected = QColorDialog.getColor(self._glow_color, self, "Sprite glow color")
        if not selected.isValid():
            return
        self._glow_color = selected
        self._glow_color_mix = 1.0
        self._custom_glow.blockSignals(True)
        self._custom_glow.setChecked(True)
        self._custom_glow.blockSignals(False)
        self._changed()

    def _refresh_glow_controls(self) -> None:
        swatch = QPixmap(20, 20)
        swatch.fill(self._glow_color)
        self._color_button.setIcon(QIcon(swatch))
        self._color_button.setText("Choose color… " + self._glow_color.name().upper())
        self._glow_hint.setText(
            "Glow is off. Increase Sprite glow above 0 to see the color and halo."
            if self._controls["glow_strength"].value() == 0
            else "Custom color applies to the glowing sprite and halo."
            if self._glow_color_mix > 0
            else "Glow uses the artwork’s colors. Choose a color to customize it."
        )

    @property
    def calibration(self) -> Calibration:
        values = {name: control.value() for name, control in self._controls.items()}
        values.update(
            glow_red=self._glow_color.redF(),
            glow_green=self._glow_color.greenF(),
            glow_blue=self._glow_color.blueF(),
            glow_color_mix=self._glow_color_mix,
        )
        return Calibration.from_mapping(values)

    def _set_calibration(self, calibration: Calibration, *, notify: bool = True) -> None:
        values = calibration.as_dict()
        self._glow_color = QColor.fromRgbF(
            values["glow_red"], values["glow_green"], values["glow_blue"]
        )
        self._glow_color_mix = values["glow_color_mix"]
        self._custom_glow.blockSignals(True)
        self._custom_glow.setChecked(self._glow_color_mix > 0)
        self._custom_glow.blockSignals(False)
        for name, control in self._controls.items():
            control.blockSignals(True)
            control.setValue(values[name])
            control.blockSignals(False)
        self._refresh_glow_controls()
        if notify:
            self._on_change(self.calibration)

    def _changed(self, _value: float | None = None) -> None:
        self._refresh_glow_controls()
        self._on_change(self.calibration)

    def reject(self) -> None:
        self._on_change(self._initial)
        super().reject()
