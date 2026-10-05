"""Live, bounded controls for the production shader."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..calibration import Calibration
from .color_glow_ui import ColorGlowEditor
from .controls import ScrollSlider, ScrollSpinBox

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
    ("glow_strength", "Sprite glow", 0.0, 10.0, 0.05),
    ("glow_radius", "Halo spread", 0.0, 2.0, 0.05),
)

_EMITTED_LIGHT = (
    ("emission_strength", "Light cast onto characters", 0.0, 2.0, 0.05),
    ("emission_radius", "Light reach (screen heights)", 0.0, 2.0, 0.05),
    ("emission_red", "Cast-light color · red", 0.0, 2.0, 0.05),
    ("emission_green", "Cast-light color · green", 0.0, 2.0, 0.05),
    ("emission_blue", "Cast-light color · blue", 0.0, 2.0, 0.05),
)


class CalibrationEditor(QWidget):
    """Embedded live controls; persistence is handled by the separate review page."""

    def __init__(
        self,
        calibration: Calibration,
        on_change: Callable[[Calibration], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._initial = calibration.normalized()
        self._on_change = on_change
        self._controls: dict[str, QDoubleSpinBox] = {}
        self._sliders: dict[str, QSlider] = {}
        self._glow_color = QColor("#ffffff")
        self._glow_color_rgb = (1.0, 1.0, 1.0)
        self._glow_color_mix = 0.0
        self._light_color = QColor("#4080ff")
        self._light_color_rgb = (0.25, 0.50, 1.0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        navigation = QGridLayout()
        navigation.setSpacing(5)
        self._categories = QButtonGroup(self)
        self.category_buttons = {}
        for position, (index, name, hint) in enumerate(
            (
                (0, "Lighting", "Automatic matching, exposure, contrast and saturation"),
                (3, "Sprite glow", "Glow strength, halo spread, glow color and tint"),
                (4, "Color glow", "Make selected colors in the artwork glow"),
                (2, "Light color", "Adjust a color in the background light"),
                (1, "Advanced", "Shadows, bounce, rim light and other lighting controls"),
                (
                    5,
                    "Cast light",
                    "Configure light this sprite casts onto other characters in-game",
                ),
            )
        ):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setObjectName("calibrationCategory")
            button.setToolTip(hint)
            self._categories.addButton(button, index)
            self.category_buttons[name] = button
            navigation.addWidget(button, position // 3, position % 3)
            navigation.setColumnStretch(position % 3, 1)
        self._categories.idClicked.connect(self._show_page)
        layout.addLayout(navigation)
        self._page_title = QLabel()
        self._page_title.setObjectName("sectionTitle")
        layout.addWidget(self._page_title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumHeight(100)
        contents = QWidget()
        pages_layout = QVBoxLayout(contents)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        self._color_glow = ColorGlowEditor()
        self._color_glow.changed.connect(self._changed)
        self._pages = [
            self._page(_BASIC),
            self._page(_ADVANCED),
            self._light_color_page(),
            self._glow_page(),
            self._color_glow,
            self._cast_light_page(),
        ]
        for index, page in enumerate(self._pages):
            pages_layout.addWidget(page)
            page.setVisible(index == 0)
        pages_layout.addStretch(1)
        self.scroll.setWidget(contents)
        layout.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        reset = QPushButton("Restore defaults")
        reset.setObjectName("compactAction")
        reset.setToolTip("Restore all calibration and glow settings to their defaults.")
        reset.clicked.connect(lambda: self._set_calibration(Calibration()))
        buttons.addWidget(reset)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.select_category(0)
        self._set_calibration(self._initial, notify=False)

    def select_category(self, index: int) -> None:
        button = self._categories.button(index)
        if button is not None:
            button.setChecked(True)
            self._show_page(index)

    def _show_page(self, index: int) -> None:
        for number, page in enumerate(self._pages):
            page.setVisible(number == index)
        self._page_title.setText(
            (
                "Basic lighting",
                "Advanced lighting",
                "Background light color",
                "Sprite glow",
                "Color glow",
                "Cast light · in-game",
            )[index]
        )
        self.scroll.verticalScrollBar().setValue(0)

    def _page(self, fields) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(6, 6, 6, 6)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for name, label, minimum, maximum, step in fields:
            control = ScrollSpinBox()
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
                    "This light affects other visible characters in-game. Preview shows one sprite, so check cast light in your mod. It does not recolor this sprite’s own glow."
                )
            control.valueChanged.connect(lambda value, key=name: self._value_changed(key, value))
            self._controls[name] = control
            if name in {"glow_strength", "glow_radius"}:
                slider = ScrollSlider(Qt.Horizontal)
                slider.setRange(round(minimum * 100), round(maximum * 100))
                slider.setSingleStep(round(step * 100))
                slider.setPageStep(round(step * 1000))
                slider.setAccessibleName(label)
                slider.setToolTip(
                    "0–10 · 0 turns glow off"
                    if name == "glow_strength"
                    else "0–2 · controls the halo’s spread"
                )
                slider.valueChanged.connect(
                    lambda value, field=control: field.setValue(value / 100)
                )
                self._sliders[name] = slider
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(slider, 1)
                row_layout.addWidget(control)
                control.setMaximumWidth(80)
                form.addRow(label, row)
            else:
                form.addRow(label, control)
        return page

    def _value_changed(self, name: str, value: float) -> None:
        self._values[name] = value
        if name in self._sliders:
            slider = self._sliders[name]
            slider.blockSignals(True)
            slider.setValue(round(value * 100))
            slider.blockSignals(False)
        self._changed()

    def _glow_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._page(_GLOW))
        color_row = QHBoxLayout()
        self._custom_glow = QCheckBox("Custom glow color")
        self._custom_glow.toggled.connect(self._toggle_glow_color)
        self._color_button = QPushButton("Choose color…")
        self._color_button.clicked.connect(self._choose_glow_color)
        color_row.addWidget(self._custom_glow)
        color_row.addWidget(self._color_button)
        layout.addLayout(color_row)
        mix_row = QHBoxLayout()
        mix_row.addWidget(QLabel("Artwork"))
        self._glow_mix_slider = ScrollSlider(Qt.Horizontal)
        self._glow_mix_slider.setRange(0, 100)
        self._glow_mix_slider.setToolTip(
            "0% preserves artwork colors; 100% replaces them with the chosen glow color. Values between apply a tint."
        )
        self._glow_mix_slider.valueChanged.connect(self._glow_mix_changed)
        mix_row.addWidget(self._glow_mix_slider, 1)
        self._glow_mix_value = QLabel("0% color")
        mix_row.addWidget(self._glow_mix_value)
        layout.addLayout(mix_row)
        self._glow_hint = QLabel()
        self._glow_hint.setObjectName("subtitle")
        self._glow_hint.setWordWrap(True)
        layout.addWidget(self._glow_hint)
        layout.addStretch(1)
        return page

    def _cast_light_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Let this sprite light nearby characters in your mod. Preview shows one sprite; check cast light in-game."
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self._page(_EMITTED_LIGHT))
        layout.addStretch(1)
        return page

    def _light_color_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Reduce or increase a selected color in the background light reaching the sprite. "
            "Negative values reduce the color cast; positive values increase it. "
            "0 leaves the lighting unchanged. The background image and artwork are preserved."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self._light_color_button = QPushButton()
        self._light_color_button.clicked.connect(self._choose_light_color)
        layout.addWidget(self._light_color_button)
        layout.addWidget(
            self._page(
                (
                    ("light_color_amount", "Color influence", -1.0, 1.0, 0.05),
                    ("light_color_tolerance", "Similar colors", 0.0, 1.0, 0.05),
                )
            )
        )
        layout.addStretch(1)
        return page

    def _choose_light_color(self) -> None:
        selected = QColorDialog.getColor(self._light_color, self, "Background light color")
        if selected.isValid():
            self._light_color = selected
            self._light_color_rgb = (selected.redF(), selected.greenF(), selected.blueF())
            self._light_color_button.setText("Color: " + selected.name().upper())
            self._changed()

    def _toggle_glow_color(self, checked: bool) -> None:
        self._glow_color_mix = 1.0 if checked else 0.0
        self._changed()

    def _glow_mix_changed(self, value: int) -> None:
        self._glow_color_mix = value / 100.0
        self._custom_glow.blockSignals(True)
        self._custom_glow.setChecked(value > 0)
        self._custom_glow.blockSignals(False)
        self._changed()

    def _choose_glow_color(self) -> None:
        selected = QColorDialog.getColor(self._glow_color, self, "Sprite glow color")
        if not selected.isValid():
            return
        self._glow_color = selected
        self._glow_color_rgb = (selected.redF(), selected.greenF(), selected.blueF())
        self._glow_color_mix = 1.0
        self._custom_glow.blockSignals(True)
        self._custom_glow.setChecked(True)
        self._custom_glow.blockSignals(False)
        self._changed()

    def _refresh_glow_controls(self) -> None:
        self._glow_mix_slider.blockSignals(True)
        self._glow_mix_slider.setValue(round(self._glow_color_mix * 100))
        self._glow_mix_slider.blockSignals(False)
        self._glow_mix_value.setText(f"{self._glow_color_mix:.0%} color")
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
        # Preserve loaded precision in untouched fields instead of reading the
        # rounded spinbox display back into every unrelated setting.
        values = dict(self._values)
        values.update(
            light_color_red=self._light_color_rgb[0],
            light_color_green=self._light_color_rgb[1],
            light_color_blue=self._light_color_rgb[2],
            glow_red=self._glow_color_rgb[0],
            glow_green=self._glow_color_rgb[1],
            glow_blue=self._glow_color_rgb[2],
            glow_color_mix=self._glow_color_mix,
            glow_rules=[rule.as_dict() for rule in self._color_glow.rules],
        )
        return Calibration.from_mapping(values)

    def _set_calibration(self, calibration: Calibration, *, notify: bool = True) -> None:
        values = calibration.as_dict()
        self._values = values
        self._light_color_rgb = tuple(
            values["light_color_" + channel] for channel in ("red", "green", "blue")
        )
        self._light_color = QColor.fromRgbF(
            values["light_color_red"], values["light_color_green"], values["light_color_blue"]
        )
        self._light_color_button.setText("Color: " + self._light_color.name().upper())
        self._color_glow.set_rules(calibration.glow_rules)
        self._glow_color = QColor.fromRgbF(
            values["glow_red"], values["glow_green"], values["glow_blue"]
        )
        self._glow_color_rgb = tuple(
            values["glow_" + channel] for channel in ("red", "green", "blue")
        )
        self._glow_color_mix = values["glow_color_mix"]
        self._custom_glow.blockSignals(True)
        self._custom_glow.setChecked(self._glow_color_mix > 0)
        self._custom_glow.blockSignals(False)
        for name, control in self._controls.items():
            control.blockSignals(True)
            control.setValue(values[name])
            control.blockSignals(False)
        for name, slider in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(values[name] * 100))
            slider.blockSignals(False)
        self._refresh_glow_controls()
        if notify:
            self._on_change(self.calibration)

    def _changed(self, _value: float | None = None) -> None:
        self._refresh_glow_controls()
        self._on_change(self.calibration)
