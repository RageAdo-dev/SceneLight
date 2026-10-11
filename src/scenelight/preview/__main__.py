from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from ..branding import ICON_PNG, set_process_identity
from .ui import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview and calibrate SceneLight")
    parser.add_argument("--project", type=Path, help="Ren'Py project associated with this profile")
    args, qt_args = parser.parse_known_args()
    set_process_identity()
    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    surface_format.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("SceneLight Preview & Calibrator")
    app.setWindowIcon(QIcon(str(ICON_PNG)))
    try:
        window = MainWindow(args.project)
    except Exception as error:
        from .. import diagnostics

        session = diagnostics.current_session()
        if session is not None:
            session.exception("preview.startup", error)
            session.update(status="failed", failure=str(error))
        raise
    previous_exception_hook = sys.excepthook

    def record_exception(kind, error, trace):
        from .. import diagnostics

        session = diagnostics.current_session()
        if session is not None:
            session.exception("preview.unhandled", error.with_traceback(trace))
            session.update(status="error", failure=str(error))
        previous_exception_hook(kind, error, trace)

    sys.excepthook = record_exception
    window.show()
    try:
        return app.exec()
    finally:
        sys.excepthook = previous_exception_hook


if __name__ == "__main__":
    raise SystemExit(main())
