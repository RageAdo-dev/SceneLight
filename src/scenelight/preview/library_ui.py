"""Saved assets and editable sprite-layer recipes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .library import Actor, Layer, Library, compose_layers


class LayerDialog(QDialog):
    def __init__(self, library: Library, parent=None, entry: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Assemble a layered sprite")
        self.resize(920, 620)
        self.library = library
        self._initial_entry = entry
        self.result_entry = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Add body, clothes, eyes, and other pieces. Rows draw from back to front. Offsets use source pixels."
            )
        )
        name_row = QHBoxLayout()
        self.name = QLineEdit(entry["name"] if entry else "Layered character")
        name_row.addWidget(QLabel("Name"))
        name_row.addWidget(self.name)
        self._canvas_width = QSpinBox()
        self._canvas_height = QSpinBox()
        for control in (self._canvas_width, self._canvas_height):
            control.setRange(0, 8192)
            control.setSpecialValueText("Auto")
        if entry and entry.get("canvas"):
            self._canvas_width.setValue(entry["canvas"][0])
            self._canvas_height.setValue(entry["canvas"][1])
        name_row.addWidget(QLabel("Canvas"))
        name_row.addWidget(self._canvas_width)
        name_row.addWidget(self._canvas_height)
        layout.addLayout(name_row)
        body = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Piece", "X", "Y", "Opacity %", "Show"))
        self.table.setColumnWidth(0, 240)
        for index in range(1, 5):
            self.table.setColumnWidth(index, 70)
        body.addWidget(self.table, 3)
        self.preview = QLabel("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(230, 300)
        self.preview.setStyleSheet("background:#253446;border:1px solid #49617a")
        body.addWidget(self.preview, 2)
        layout.addLayout(body, 1)
        controls = QHBoxLayout()
        for title, callback in (
            ("Add pieces…", self.add_pieces),
            ("Move back", lambda: self.move(-1)),
            ("Move front", lambda: self.move(1)),
            ("Remove", self.remove),
            ("Update preview", self.render_preview),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        if entry:
            for layer in entry.get("layers", []):
                self.add_row(Layer(**dict(layer, path=str(library.path(layer["path"])))))
            self.render_preview()

    def add_row(self, layer: Layer):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(layer.name or Path(layer.path).name)
        item.setData(Qt.UserRole, layer.path)
        item.setToolTip(layer.path)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, item)
        for column, value in ((1, layer.x), (2, layer.y), (3, round(layer.opacity * 100))):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))
        visible = QTableWidgetItem()
        visible.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
        self.table.setItem(row, 4, visible)

    def layers(self) -> list[Layer]:
        return [
            Layer(
                self.table.item(row, 0).data(Qt.UserRole),
                int(self.table.item(row, 1).text()),
                int(self.table.item(row, 2).text()),
                float(self.table.item(row, 3).text()) / 100,
                self.table.item(row, 4).checkState() == Qt.Checked,
                self.table.item(row, 0).text(),
            )
            for row in range(self.table.rowCount())
        ]

    def canvas_size(self):
        width, height = self._canvas_width.value(), self._canvas_height.value()
        if bool(width) != bool(height):
            raise ValueError("Set both canvas dimensions, or leave both on Auto.")
        return (width, height) if width else None

    def add_pieces(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add sprite pieces", "", "Still images (*.png *.webp *.jpg *.jpeg *.bmp)"
        )
        for path in paths:
            self.add_row(Layer(path))
        if paths:
            self.render_preview()

    def move(self, offset):
        row = self.table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        for column in range(5):
            first, second = self.table.takeItem(row, column), self.table.takeItem(target, column)
            self.table.setItem(target, column, first)
            self.table.setItem(row, column, second)
        self.table.selectRow(target)
        self.render_preview()

    def remove(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            if self.table.rowCount():
                self.render_preview()

    def render_preview(self):
        try:
            image = compose_layers(self.layers(), self.canvas_size())
            image.thumbnail((400, 450))
            data = image.tobytes()
            qimage = QImage(
                data, image.width, image.height, image.width * 4, QImage.Format_RGBA8888
            ).copy()
            self.preview.setPixmap(
                QPixmap.fromImage(qimage).scaled(
                    self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Layer preview", str(error))

    def save(self):
        try:
            layers, size = self.layers(), self.canvas_size()
            image = compose_layers(layers, size)
            folder = self.library.root / "composites"
            folder.mkdir(exist_ok=True)
            import uuid

            path = folder / (uuid.uuid4().hex + ".png")
            image.save(path)
            try:
                self.result_entry = self.library.add(
                    "sprite",
                    path,
                    name=self.name.text().strip() or "Layered character",
                    layers=layers,
                    canvas=size,
                    actor=Actor.from_payload(self._initial_entry["actor"])
                    if self._initial_entry and self._initial_entry.get("actor")
                    else None,
                )
            finally:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Save layered sprite", str(error))
            return
        self.accept()


class LibraryDialog(QDialog):
    def __init__(self, library: Library, parent=None):
        super().__init__(parent)
        self.library = library
        self.chosen = None
        self.setWindowTitle("SceneLight asset library")
        self.resize(780, 550)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Your saved sprites, layered recipes, and backgrounds. Media is copied locally so it survives moving the original."
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search saved assets…")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.items = QListWidget()
        self.items.setIconSize(QSize(72, 72))
        self.items.itemDoubleClicked.connect(self.use)
        layout.addWidget(self.items, 1)
        buttons = QHBoxLayout()
        for label, callback in (
            ("Import sprite…", lambda: self.add("sprite")),
            ("Import background…", lambda: self.add("background")),
            ("Build layered sprite…", self.layers),
            ("Edit layers…", lambda: self.layers(edit=True)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        buttons = QHBoxLayout()
        remove = QPushButton("Remove from library")
        remove.clicked.connect(self.remove)
        buttons.addWidget(remove)
        buttons.addStretch()
        use = QPushButton("Add to preview")
        use.clicked.connect(self.use)
        buttons.addWidget(use)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.items.clear()
        try:
            entries = self.library.entries()
            for entry in entries:
                if self.search.text().casefold() not in (entry["name"] + entry["kind"]).casefold():
                    continue
                item = QListWidgetItem(
                    f"{entry['name']}   ·   {entry['kind']}"
                    + (" · layered" if entry.get("layers") else "")
                )
                item.setData(Qt.UserRole, entry)
                if entry.get("thumbnail"):
                    try:
                        item.setIcon(QIcon(str(self.library.path(entry["thumbnail"]))))
                    except ValueError:
                        pass
                self.items.addItem(item)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Library", str(error))

    def add(self, kind):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Save assets in library",
            "",
            "Media (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.apng *.mp4 *.webm *.mov)",
        )
        try:
            for path in paths:
                self.library.add(kind, Path(path))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Library import", str(error))
        self.refresh()

    def layers(self, _checked=False, *, edit=False):
        item = self.items.currentItem()
        entry = item.data(Qt.UserRole) if edit and item else None
        if edit and (entry is None or not entry.get("layers")):
            QMessageBox.information(
                self, "Layer recipe", "Select a layered sprite to edit its pieces."
            )
            return
        dialog = LayerDialog(self.library, self, entry)
        if dialog.exec():
            self.refresh()

    def remove(self):
        item = self.items.currentItem()
        if item:
            self.library.remove(item.data(Qt.UserRole)["id"])
            self.refresh()

    def use(self, _item=None):
        item = self.items.currentItem()
        if item:
            self.chosen = item.data(Qt.UserRole)
            self.accept()
