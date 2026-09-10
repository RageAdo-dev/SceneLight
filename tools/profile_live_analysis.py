"""Measure complete CPU analysis and GPU draw/dispatch costs on identical pixels."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from OpenGL import GL
from PIL import Image
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scenelight.builder import _scene_maps, _transport_maps, _wrap_map  # noqa: E402
from scenelight.engine import prepare_scene  # noqa: E402
from scenelight.runtime.live_gpu import RGBA8, Analysis, State  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--frames", type=int, default=5)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.source.suffix.lower() in (".mp4", ".webm"):
        reader = cv2.VideoCapture(str(args.source))
        ok, frame = reader.read()
        reader.release()
        if not ok:
            raise ValueError("Could not decode benchmark frame")
        source = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA))
    else:
        source = Image.open(args.source).convert("RGBA")
    pixels = np.asarray(source).copy()
    frame_path = args.output.with_suffix(".png")
    source.save(frame_path)
    report = {"size": source.size}
    if args.cpu:
        report["cpu_ms"] = {}
        for name, operation in (
            ("prepare", lambda: prepare_scene(source)),
            ("scene_maps", lambda: _scene_maps(frame_path)),
            (
                "transport",
                lambda: _transport_maps("benchmark", str(frame_path), scene_fixed_components=True),
            ),
            ("wrap", lambda: _wrap_map(frame_path)),
        ):
            started = time.perf_counter()
            operation()
            report["cpu_ms"][name] = (time.perf_counter() - started) * 1000
            print(name, report["cpu_ms"][name], flush=True)
    app = QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    context = QOpenGLContext()
    context.setFormat(fmt)
    assert context.create()
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    assert context.makeCurrent(surface)
    analysis = Analysis()
    device, gl = analysis.device, analysis.device.gl
    report["renderer"] = GL.glGetString(GL.GL_RENDERER).decode()
    queries, program_names = [], {}
    current = ["unknown"]
    with State(gl):
        source_texture = device.target("input", *source.size, RGBA8)
        gl.BindTexture(0x0DE1, source_texture)
        gl.TexSubImage2D(
            0x0DE1, 0, 0, 0, *source.size, 0x1908, 0x1401, ctypes.c_void_p(pixels.ctypes.data)
        )
        for _ in range(5):
            analysis.evaluate(source_texture, source.size, preview=args.preview)
        gl.Finish()
        durations = []
        for _ in range(20):
            started = time.perf_counter()
            analysis.evaluate(source_texture, source.size, preview=args.preview)
            gl.Finish()
            durations.append((time.perf_counter() - started) * 1000)
        report["complete_ms"] = durations
        report["compute_supported_after"] = gl.compute_supported
        report["opencl_active"] = device.opencl is not None
        report["opencl_error"] = device.opencl_error
        original_draw = device.draw

        def draw(program, target, *args, **kwargs):
            current[0] = next(
                (name for name, entry in device.targets.items() if entry[0] == target), "draw"
            )
            return original_draw(program, target, *args, **kwargs)

        device.draw = draw
        original_program = device.compute_program

        def compute_program(name, code):
            program = original_program(name, code)
            program_names[program] = name
            return program

        device.compute_program = compute_program
        original_use = gl.UseProgram

        def use(program):
            if program in program_names:
                current[0] = program_names[program]
            return original_use(program)

        gl.UseProgram = use

        def timed(original):
            def call(*args):
                query = gl.generate("Queries")
                GL.glBeginQuery(GL.GL_TIME_ELAPSED, query)
                original(*args)
                GL.glEndQuery(GL.GL_TIME_ELAPSED)
                queries.append((current[0], query))

            return call

        gl.DrawArrays = timed(gl.DrawArrays)
        if hasattr(gl, "DispatchCompute"):
            gl.DispatchCompute = timed(gl.DispatchCompute)
        for _ in range(args.frames):
            analysis.evaluate(source_texture, source.size, preview=args.preview)
        gl.Finish()
        costs, counts = defaultdict(float), defaultdict(int)
        for name, query in queries:
            nanoseconds = ctypes.c_uint()
            gl.GetQueryObjectuiv(query, GL.GL_QUERY_RESULT, ctypes.byref(nanoseconds))
            costs[name] += nanoseconds.value / 1e6 / args.frames
            counts[name] += 1
            GL.glDeleteQueries(1, [query])
        report["gpu_pass_ms"] = dict(sorted(costs.items(), key=lambda row: -row[1]))
        report["passes_per_frame"] = len(queries) / args.frames
        report["draw_dispatch_ms"] = sum(costs.values())
        report["texture_mib"] = (
            sum(
                w * h * (8 if storage == 0x8230 else 4 if storage in (RGBA8, 0x822E) else 16)
                for _, w, h, storage, _ in device.targets.values()
            )
            / 1048576
        )
        assert gl.GetError() == 0
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("complete_ms", "gpu_pass_ms")}))
    print(json.dumps(dict(list(report["gpu_pass_ms"].items())[:20]), indent=2))
    device.close()
    context.doneCurrent()
    app.quit()


if __name__ == "__main__":
    main()
