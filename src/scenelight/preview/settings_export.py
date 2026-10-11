"""Review a lighting settings write before changing any file."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calibration import Calibration, CalibrationProfile
from .calibration_dialog import _ADVANCED, _BASIC, _EMITTED_LIGHT, _GLOW


class SettingsChangedError(ValueError):
    pass


def _read_existing(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class SettingsWrite:
    destination: Path
    previous: bytes | None
    content: bytes

    def write(self) -> None:
        """Write exactly the reviewed bytes; refuse a stale destination."""
        if _read_existing(self.destination) != self.previous:
            raise SettingsChangedError(
                "The file changed outside Preview. Refresh the review before saving."
            )
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.destination.parent,
                prefix=".scenelight-settings-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(self.content)
                stream.flush()
                os.fsync(stream.fileno())
            if _read_existing(self.destination) != self.previous:
                raise SettingsChangedError(
                    "The file changed outside Preview. Refresh the review before saving."
                )
            os.replace(temporary, self.destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def prepare_settings_write(destination: Path, profile: CalibrationProfile) -> SettingsWrite:
    destination = destination.expanduser().resolve()
    previous = _read_existing(destination)
    payload = {} if previous is None else json.loads(previous.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("The destination must contain a JSON object.")
    incoming = profile.to_payload()
    # This page edits global defaults. Keep target-specific rules and asset
    # discovery exactly as authored, including any scene calibration overrides.
    scenes = payload.get("scene_calibration", incoming["scene_calibration"])
    payload.update(incoming)
    payload["scene_calibration"] = scenes
    content = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    return SettingsWrite(destination, previous, content)


class SettingsExportPage(QWidget):
    saved = Signal(str, str)
    editRequested = Signal()

    def __init__(
        self,
        profile: CalibrationProfile,
        profile_path: Path | None,
        config_path: Path | None,
        parent=None,
    ):
        super().__init__(parent)
        self._profile = profile
        self._destinations = [profile_path, config_path]
        self._plan: SettingsWrite | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        contents = QWidget()
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(10, 10, 10, 10)
        scroll.setWidget(contents)
        outer.addWidget(scroll, 1)
        self.mode = QComboBox()
        self.mode.addItems(("Save Preview profile", "Export project config"))
        layout.addWidget(self.mode)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        self.scope.setObjectName("subtitle")
        layout.addWidget(self.scope)
        self.destination = QLineEdit()
        self.destination.setReadOnly(True)
        self.destination.setPlaceholderText("Choose where to save…")
        self.destination.setAccessibleName("Settings destination")
        layout.addWidget(self.destination)
        actions = QHBoxLayout()
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self._choose_destination)
        actions.addWidget(choose)
        refresh = QPushButton("Refresh review")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self.review = QTabWidget()
        self.values = QTreeWidget()
        self.values.setHeaderLabels(("Setting", "Value"))
        self.values.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.values.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.values.setMinimumHeight(180)
        self.values.setAlternatingRowColors(True)
        self.review.addTab(self.values, "Current values")
        self.file_preview = QPlainTextEdit()
        self.file_preview.setReadOnly(True)
        self.file_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.file_preview.setMinimumHeight(180)
        self.review.addTab(self.file_preview, "File preview")
        layout.addWidget(self.review, 1)
        edit = QPushButton("Edit lighting values")
        edit.clicked.connect(self.editRequested.emit)
        layout.addWidget(edit)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("subtitle")
        outer.addWidget(self.message)
        self.write_button = QPushButton()
        self.write_button.setObjectName("primaryAction")
        self.write_button.clicked.connect(self._write)
        outer.addWidget(self.write_button)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def set_profile(self, profile: CalibrationProfile) -> None:
        if profile == self._profile:
            return
        self._profile = profile
        self._plan = None
        self.write_button.setEnabled(False)
        # Large project configs should not be read/formatted on every lighting
        # keystroke while the review page is hidden.
        if self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def select_mode(self, index: int) -> None:
        self.mode.setCurrentIndex(index)
        self.refresh()

    def _mode_changed(self) -> None:
        is_profile = self.mode.currentIndex() == 0
        self.scope.setText(
            "Save the current defaults for Preview and future SceneLight builds. "
            "Changes stay in this Preview until you save."
            if is_profile
            else "Export global lighting defaults to scenelight.json. Existing background, "
            "sprite and discovery rules are kept. Update SceneLight in the project to apply them."
        )
        self.write_button.setText(
            "Save reviewed profile" if is_profile else "Write reviewed config"
        )
        self.refresh()

    def set_destination(self, path: Path) -> None:
        self._destinations[self.mode.currentIndex()] = path.expanduser().resolve()
        self.refresh()

    def _choose_destination(self) -> None:
        default = self._destinations[self.mode.currentIndex()]
        name = "scenelight-profile.json" if self.mode.currentIndex() == 0 else "scenelight.json"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Choose settings destination",
            str(default or name),
            "JSON (*.json)",
            options=QFileDialog.DontConfirmOverwrite,
        )
        if selected:
            self.set_destination(Path(selected))

    def refresh(self) -> None:
        self._show_values()
        destination = self._destinations[self.mode.currentIndex()]
        self._plan = None
        self.write_button.setEnabled(False)
        self.destination.setText(str(destination or ""))
        self.destination.setToolTip(str(destination or ""))
        self.destination.setCursorPosition(0)
        if destination is None:
            self.file_preview.setPlainText(json.dumps(self._profile.to_payload(), indent=2))
            self.message.setText(
                "Choose a destination to review the file. Nothing has been written."
            )
            return
        try:
            self._plan = prepare_settings_write(destination, self._profile)
        except (OSError, ValueError, UnicodeError) as error:
            self.file_preview.clear()
            self.message.setText(f"Cannot prepare this file: {error}")
            return
        self.file_preview.setPlainText(self._plan.content.decode("utf-8"))
        self.message.setText(
            "This will replace the file’s global lighting defaults. Target-specific rules are kept."
            if self._plan.previous is not None
            else "This will create a new file with the reviewed settings."
        )
        self.write_button.setEnabled(True)

    def _write(self) -> None:
        if self._plan is None:
            return
        plan = self._plan
        try:
            plan.write()
        except (OSError, ValueError) as error:
            self.message.setText(f"Not saved: {error}")
            self.write_button.setEnabled(False)
            self._plan = None
            return
        self.refresh()
        self.message.setText("Saved. The file contains exactly the settings shown in File preview.")
        self.saved.emit(
            str(plan.destination), "profile" if self.mode.currentIndex() == 0 else "config"
        )

    def _show_values(self) -> None:
        self.values.clear()
        strength = self._profile.normalized_strength()
        QTreeWidgetItem(self.values, ["Lighting strength", f"{strength:g} ({strength * 100:g}%)"])
        labels = {
            name: label for name, label, *_rest in (*_BASIC, *_ADVANCED, *_GLOW, *_EMITTED_LIGHT)
        }
        defaults = Calibration().as_dict()
        for key, value in self._profile.calibration.as_dict().items():
            label = labels.get(key, key.replace("_", " ").capitalize())
            if key == "glow_rules":
                parent = QTreeWidgetItem(self.values, ["Color glow rules", str(len(value))])
                for rule in value:
                    node = QTreeWidgetItem(
                        parent, [rule["name"], "On" if rule["enabled"] else "Off"]
                    )
                    for name, setting in rule.items():
                        QTreeWidgetItem(node, [name.replace("_", " ").capitalize(), str(setting)])
                continue
            item = QTreeWidgetItem(self.values, [label, str(value)])
            item.setToolTip(0, key)
            item.setToolTip(1, f"Default: {defaults[key]}")
            if value != defaults[key]:
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)
