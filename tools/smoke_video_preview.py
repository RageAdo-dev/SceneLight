"""Open one video in the production preview and prove that playback advances."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from scenelight.preview import ui


class _SmokeWindow(ui.MainWindow):
    def __init__(self) -> None:
        self.smoke_errors: list[str] = []
        super().__init__()

    def _on_failed(self, title: str, message: str) -> None:
        self.smoke_errors.append(f"{title}: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--target-frame", type=int, default=10)
    args = parser.parse_args()
    video = args.video.expanduser().resolve(strict=True)

    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    surface_format.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication.instance() or QApplication([sys.argv[0]])
    ui.QFileDialog.getOpenFileName = lambda *_args, **_kwargs: (str(video), "")
    window = _SmokeWindow()
    window.resize(960, 600)
    window.show()
    window.open_background()
    started = time.perf_counter()
    result: dict[str, object] = {"video": video.name}

    def finish(passed: bool) -> None:
        result.update(
            {
                "passed": passed,
                "elapsed_s": round(time.perf_counter() - started, 2),
                "playback_started": window._temporal_playback_started,
                "current_frame": window._current_background_index,
                "known_through": window._temporal_plan_known_through,
                "ready_through": window._temporal_ready_through,
                "status": window.statusBar().currentMessage(),
                "errors": window.smoke_errors,
                "hardware_plan": {
                    "cuda": window._cache.hardware_plan.profile.cuda,
                    "process_workers": window._cache.hardware_plan.process_workers,
                    "lookahead_seconds": (window._cache.hardware_plan.nominal_lookahead_seconds),
                },
            }
        )
        print(json.dumps(result), flush=True)
        window.close()
        app.quit()

    def poll() -> None:
        if window.smoke_errors:
            finish(False)
        elif (
            window._temporal_playback_started
            and window._current_background_index >= args.target_frame
        ):
            finish(True)
        elif time.perf_counter() - started > args.timeout:
            finish(False)

    watch = QTimer()
    watch.timeout.connect(poll)
    watch.start(100)
    app.exec()
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
