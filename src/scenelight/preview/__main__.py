from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview and calibrate SceneLight")
    parser.add_argument("--project", type=Path, help="Ren'Py project associated with this profile")
    args, qt_args = parser.parse_known_args()
    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    surface_format.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("SceneLight Preview & Calibrator")
    window = MainWindow(args.project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
