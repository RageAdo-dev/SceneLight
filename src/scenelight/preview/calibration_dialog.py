"""Live, bounded controls for the production shader."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
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
    ("individual_light_colors", "Individual light colors (creative)", 0.0, 2.0, 0.01),
    ("adaptive_light_colors", "Adaptive separated light colors", 0.0, 2.0, 0.01),
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

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._page(_BASIC), "Basic")
        tabs.addTab(self._page(_ADVANCED), "Advanced")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        reset = QPushButton("Restore approved defaults")
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
                control.setToolTip(
                    "Automatically separates colors only when multiple strong "
                    "emitters are both spatially and chromatically distinct."
                )
            control.valueChanged.connect(self._changed)
            self._controls[name] = control
            form.addRow(label, control)
        return page

    @property
    def calibration(self) -> Calibration:
        return Calibration.from_mapping(
            {name: control.value() for name, control in self._controls.items()}
        )

    def _set_calibration(self, calibration: Calibration, *, notify: bool = True) -> None:
        values = calibration.as_dict()
        for name, control in self._controls.items():
            control.blockSignals(True)
            control.setValue(values[name])
            control.blockSignals(False)
        if notify:
            self._on_change(self.calibration)

    def _changed(self, _value: float | None = None) -> None:
        self._on_change(self.calibration)

    def reject(self) -> None:
        self._on_change(self._initial)
        super().reject()
