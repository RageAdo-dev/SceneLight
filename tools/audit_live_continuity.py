"""Record per-frame live fields to distinguish input motion from lighting jumps."""

import argparse
import ctypes
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scenelight.runtime.live_gpu import RGBA8, Analysis, State


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
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
    gl, device = analysis.device.gl, analysis.device
    video = cv2.VideoCapture(str(args.video))
    fps = video.get(cv2.CAP_PROP_FPS)
    records, states, transports = [], [], []
    prior_pixels = prior_transport = None
    history = () if args.continuous else None
    while True:
        ok, bgr = video.read()
        if not ok:
            break
        pixels = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        height, width = pixels.shape[:2]
        with State(gl):
            texture = device.target("audit_input", width, height, RGBA8)
            gl.BindTexture(0x0DE1, texture)
            gl.TexSubImage2D(
                0x0DE1, 0, 0, 0, width, height, 0x1908, 0x1401, ctypes.c_void_p(pixels.ctypes.data)
            )
            output = analysis.evaluate(texture, (width, height), previous=history)
            if args.continuous:
                history = (output["_history_lights"], output["_history_image"])
            transport = np.empty((10, 416, 4), np.uint8)
            device.bind_targets((output["transport"],))
            gl.ReadPixels(0, 0, 416, 10, 0x1908, 0x1401, ctypes.c_void_p(transport.ctypes.data))
            state = np.empty((26, 145, 4), np.float32)
            device.bind_targets((device.targets["scene_state"][0],))
            gl.ReadPixels(0, 0, 145, 26, 0x1908, 0x1406, ctypes.c_void_p(state.ctypes.data))
        index = len(records)
        record = {
            "frame": index,
            "time": index / fps,
            "layout_votes": int(state[24, :144, 0].sum()),
            "light_count": state[24, :144, 1].tolist(),
        }
        if prior_transport is not None:
            delta = np.abs(transport[:9].astype(float) - prior_transport[:9])
            record.update(
                input_mean_delta=float(np.abs(pixels.astype(float) - prior_pixels).mean()),
                field_mean_delta=float(delta.mean()),
                field_max_delta=float(delta.max()),
            )
            if delta.max() > 60:
                cv2.imwrite(str(args.output / ("jump-%03d.png" % index)), bgr)
        records.append(record)
        states.append(state)
        transports.append(transport)
        prior_pixels, prior_transport = pixels, transport
    video.release()
    np.savez_compressed(args.output / "fields.npz", states=states, transports=transports)
    (args.output / "frames.json").write_text(json.dumps(records, indent=2))
    largest = sorted(records[1:], key=lambda r: r["field_mean_delta"], reverse=True)[:10]
    print(
        json.dumps([{k: v for k, v in r.items() if k != "light_count"} for r in largest], indent=2)
    )
    device.close()
    context.doneCurrent()
    app.quit()


if __name__ == "__main__":
    main()
