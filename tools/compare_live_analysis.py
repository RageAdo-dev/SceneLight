"""Alternate old/new engines on identical frames and compare every shader input."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scenelight.runtime import live_gpu  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--game", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("baseline_gpu", args.baseline)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
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
    engines = [baseline.Analysis(), live_gpu.Analysis()]
    reader = cv2.VideoCapture(str(args.video))
    records, index = [], 0
    while True:
        ok, bgr = reader.read()
        if not ok:
            break
        if index % args.stride:
            index += 1
            continue
        pixels = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        h, w = pixels.shape[:2]
        arrays, times = {}, {}
        for which in range(2) if index % (args.stride * 2) == 0 else reversed(range(2)):
            engine = engines[which]
            device, gl = engine.device, engine.device.gl
            with live_gpu.State(gl):
                source = device.target("comparison_input", w, h, live_gpu.RGBA8)
                gl.BindTexture(live_gpu.TEXTURE_2D, source)
                gl.TexSubImage2D(
                    live_gpu.TEXTURE_2D,
                    0,
                    0,
                    0,
                    w,
                    h,
                    live_gpu.RGBA,
                    live_gpu.UNSIGNED_BYTE,
                    ctypes.c_void_p(pixels.ctypes.data),
                )
                gl.Finish()
                start = time.perf_counter()
                fields = engine.evaluate(source, (w, h), preview=not args.game)
                gl.Finish()
                times[which] = (time.perf_counter() - start) * 1000
                arrays[which] = {}
                for name, texture in fields.items():
                    ah, aw = (10, 416) if name == "transport" else (90, 160)
                    result = np.empty((ah, aw, 4), np.uint8)
                    device.bind_targets((texture,))
                    gl.ReadPixels(
                        0,
                        0,
                        aw,
                        ah,
                        live_gpu.RGBA,
                        live_gpu.UNSIGNED_BYTE,
                        ctypes.c_void_p(result.ctypes.data),
                    )
                    arrays[which][name] = result
                assert gl.GetError() == 0
        differences = {}
        for name in arrays[0]:
            delta = np.abs(arrays[0][name].astype(int) - arrays[1][name].astype(int))
            differences[name] = {
                "max": int(delta.max()),
                "changed": int(np.count_nonzero(delta)),
                "mean": float(delta.mean()),
            }
        records.append({"frame": index, "milliseconds": times, "differences": differences})
        index += 1
    reader.release()
    for engine in engines:
        engine.device.close()
    context.doneCurrent()
    app.quit()
    summary = {
        "frames": len(records),
        "warm_median_ms": [
            statistics.median(r["milliseconds"][i] for r in records[2:]) for i in range(2)
        ],
        "maximum_field_delta": {
            name: max(r["differences"][name]["max"] for r in records)
            for name in records[0]["differences"]
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}))


if __name__ == "__main__":
    main()
