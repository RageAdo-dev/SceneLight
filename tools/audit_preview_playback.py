"""Measure actual Qt playback with a lit sprite after temporal preparation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scenelight.preview import ui  # noqa: E402
from scenelight.preview.artifacts import ArtifactCache  # noqa: E402
from scenelight.preview.hardware import detect_hardware_profile  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prepared", action="store_true")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--maximized", action="store_true")
    parser.add_argument("--baseline-analysis", type=Path)
    parser.add_argument("--gpu-timing", action="store_true")
    args = parser.parse_args()
    if args.baseline_analysis:
        from scenelight.preview import gpu_view

        spec = importlib.util.spec_from_file_location("baseline_analysis", args.baseline_analysis)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        gpu_view.Analysis = module.Analysis
    args.output.mkdir(parents=True, exist_ok=True)
    ui.ArtifactCache = lambda: ArtifactCache(
        args.output / "cache",
        hardware_profile=detect_hardware_profile(cuda=False) if args.cpu else None,
    )
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    errors = []

    class AuditWindow(ui.MainWindow):
        def _on_failed(self, operation, message):
            errors.append(f"{operation}: {message}")

    window = AuditWindow()
    window.resize(1100, 740)
    gpu_queries, gpu_times = [], []
    if args.gpu_timing:
        from OpenGL import GL

        original_draw = window._view._draw_scene

        def timed_draw():
            now = time.perf_counter()
            while gpu_queries and GL.glGetQueryObjectiv(
                gpu_queries[0][1], GL.GL_QUERY_RESULT_AVAILABLE
            ):
                stamp, query = gpu_queries.pop(0)
                gpu_times.append(
                    (stamp, int(GL.glGetQueryObjectuiv(query, GL.GL_QUERY_RESULT)) / 1e6)
                )
                GL.glDeleteQueries(1, [query])
            query = int(np.asarray(GL.glGenQueries(1)).reshape(-1)[0])
            GL.glBeginQuery(GL.GL_TIME_ELAPSED, query)
            try:
                original_draw()
            finally:
                GL.glEndQuery(GL.GL_TIME_ELAPSED)
                gpu_queries.append((now, query))

        window._view._draw_scene = timed_draw
    window.showMaximized() if args.maximized else window.show()
    app.processEvents()
    window._view.liveAnalysisFailed.connect(
        lambda message: errors.append("Live analysis: " + message)
    )
    window._prepare_animated = args.prepared
    args.live = args.live or args.prepared
    if args.live and not window._view.live_analysis_supported:
        raise RuntimeError("Live analysis is unavailable in the test context")
    if args.live:

        def forbidden(*args, **kwargs):
            raise AssertionError("Live playback must not prepare cached scene fields")

        window._cache.scene = window._cache.temporal_scene = forbidden
    if not args.live:
        window._view._live_analysis_supported = False
    selections = iter((args.video, args.sprite))
    ui.QFileDialog.getOpenFileName = lambda *a, **k: (str(next(selections)), "")
    launched = time.perf_counter()
    window.open_background()
    window.open_sprite()
    started = None
    swaps = []
    finished = False
    process = psutil.Process()
    memory_samples = []

    def swapped():
        if started is None:
            return
        playback = window._background_playback
        if playback is not None:
            swaps.append(
                (time.perf_counter(), playback.presented, window._current_background_index)
            )

    window._view.frameSwapped.connect(swapped)

    def poll():
        nonlocal started, finished
        if finished:
            return
        now = time.perf_counter()
        if not memory_samples or now - memory_samples[-1][0] >= 1:
            memory = process.memory_info()
            cpu = process.cpu_times()
            memory_samples.append(
                (now, getattr(memory, "private", memory.rss) / 1048576.0, cpu.user + cpu.system)
            )
        ready = (
            (window._view._using_live_analysis and window._view._form_artifacts is not None)
            if args.live
            else (
                window._temporal_plan_complete
                and len(window._temporal_scenes) >= len(window._temporal_anchors)
                and window._view._form_artifacts is not None
                and window._view._scene_artifacts is not None
            )
        )
        if started is None and ready:
            started = now
        if (
            not errors
            and now - launched < max(120, args.seconds + 30)
            and (started is None or now - started < args.seconds)
        ):
            return
        finished = True
        distinct = []
        for stamp, absolute, index in swaps:
            if not distinct or distinct[-1][1] != absolute:
                distinct.append((stamp, absolute, index))
        intervals = np.diff([r[0] for r in distinct]) * 1000
        result = {
            "scope": "Qt frameSwapped signals with production relighting active; no capture during measurement.",
            "live_analysis": window._view._live_analysis_enabled,
            "prepared_playback": window._prepared_reader is not None,
            "temporal_worker_started": window._temporal_future is not None,
            "source_fps": window._background_media.fps,
            "cuda_background_analysis": False if args.live else window._cache._cuda_available,
            "preparation_seconds": None if started is None else started - launched,
            "measured_seconds": None if started is None else now - started,
            "distinct_presented_frames": len(distinct),
            "presented_fps": (len(distinct) - 1) / (distinct[-1][0] - distinct[0][0])
            if len(distinct) > 1
            else 0,
            "missed_source_frames": sum(
                max(b[1] - a[1] - 1, 0) for a, b in zip(distinct, distinct[1:])
            ),
            "interval_ms_p50_p95_p99": [float(x) for x in np.percentile(intervals, [50, 95, 99])]
            if len(intervals)
            else [],
            "errors": errors,
            "gpu_draw_ms_p50_p95": [
                float(v)
                for v in np.percentile(
                    [ms for stamp, ms in gpu_times if started is not None and stamp > started + 2],
                    [50, 95],
                )
            ]
            if any(started is not None and stamp > started + 2 for stamp, _ in gpu_times)
            else [],
            "viewport": window._view._canvas_viewport(),
        }
        (args.output / "playback.json").write_text(json.dumps(result, indent=2))
        (args.output / "swaps.json").write_text(json.dumps(swaps))
        (args.output / "memory.json").write_text(json.dumps(memory_samples))
        if not errors and started is not None:
            Image.fromarray(window._view.render_rgba()).save(args.output / "preview.png")
        print(json.dumps(result), flush=True)
        window.close()
        app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(50)
    app.exec()
    return 0 if started is not None and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
