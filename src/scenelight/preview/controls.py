"""Sidebar inputs that let the mouse wheel scroll without changing settings."""

from PySide6.QtWidgets import QDoubleSpinBox, QSlider


class ScrollSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class ScrollSlider(QSlider):
    def wheelEvent(self, event) -> None:
        event.ignore()
