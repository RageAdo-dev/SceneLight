"""Export one video through the production Preview path and report exact results."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QProgressDialog

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
    parser.add_argument("sprite", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--cancel-after-ms", type=int)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prepared", action="store_true")
    args = parser.parse_args()
    video = args.video.resolve(strict=True)
    sprite = args.sprite.resolve(strict=True)
    destination = args.destination.resolve()
    source_capture = cv2.VideoCapture(str(video))
    try:
        source_declared_frames = int(source_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        source_capture.release()

    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    surface_format.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(surface_format)

    _app = QApplication.instance() or QApplication([sys.argv[0]])
    selections = iter(((str(video), ""), (str(sprite), "")))
    ui.QFileDialog.getOpenFileName = lambda *_args, **_kwargs: next(selections)
    window = _SmokeWindow()
    window._prepare_animated = args.prepared
    args.live = args.live or args.prepared
    window.resize(960, 600)
    window.show()
    QApplication.processEvents()
    if args.live:
        if not window._view.live_analysis_supported:
            raise RuntimeError("Live analysis is unavailable in the test context")

        def forbidden(*args, **kwargs):
            raise AssertionError("Live export must not prepare cached scene fields")

        window._cache.scene = window._cache.temporal_scene = forbidden
    else:
        window._view._live_analysis_supported = False
    window.open_background()
    window.open_sprite()
    started = time.perf_counter()
    verified_frames = 0
    try:
        while (
            not window._view._using_live_analysis if args.live else window._scene_artifacts is None
        ) or not window._form_artifacts_by_frame:
            QApplication.processEvents()
            if window.smoke_errors:
                raise RuntimeError("; ".join(window.smoke_errors))
            if time.perf_counter() - started > args.timeout:
                raise TimeoutError("Preview did not finish initial scene/form analysis")
            time.sleep(0.01)
        assert window._background_media is not None
        if args.prepared:
            assert window._prepared_reader is not None
        verified_frames = window._background_media.frame_count
        cancelled = False
        if args.cancel_after_ms is not None:

            def cancel_export() -> None:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QProgressDialog):
                    modal.cancel()
                else:
                    QTimer.singleShot(10, cancel_export)

            QTimer.singleShot(max(0, args.cancel_after_ms), cancel_export)
        try:
            window._export_animation(destination)
        except InterruptedError:
            cancelled = True
        if args.cancel_after_ms is not None:
            result = {
                "passed": cancelled and not destination.exists(),
                "cancelled": cancelled,
                "partial_output_removed": not destination.exists(),
                "seconds": round(time.perf_counter() - started, 3),
                "errors": window.smoke_errors,
            }
            print(json.dumps(result))
            return 0 if result["passed"] else 2
        if window.smoke_errors:
            raise RuntimeError("; ".join(window.smoke_errors))
    finally:
        window.close()
        QApplication.processEvents()

    capture = cv2.VideoCapture(str(destination))
    try:
        if not capture.isOpened():
            raise RuntimeError("Exported MP4 could not be opened")
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_count - 1))
        final_ok, final_frame = capture.read()
    finally:
        capture.release()
    result = {
        "passed": bool(final_ok and final_frame is not None),
        "source_declared_frames": source_declared_frames,
        "source_verified_frames": verified_frames,
        "exported_frames": frame_count,
        "fps": fps,
        "prepared_playback": args.prepared,
        "seconds": round(time.perf_counter() - started, 3),
        "destination": str(destination),
        "errors": window.smoke_errors,
    }
    print(json.dumps(result))
    return 0 if result["passed"] and frame_count == verified_frames else 2


if __name__ == "__main__":
    raise SystemExit(main())
