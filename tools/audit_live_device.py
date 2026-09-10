"""Exercise the shared native GPU device, precision, accumulation, and state restoration."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

import numpy as np
from OpenGL import GL
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

from scenelight.runtime.live_gpu import RGBA32F, Device, State


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    app = QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("No test OpenGL context")
    device = Device()
    gl = device.gl
    GL.glViewport(3, 4, 11, 19)
    GL.glClearColor(0.1, 0.2, 0.3, 0.4)
    GL.glEnable(GL.GL_BLEND)
    GL.glEnable(GL.GL_SCISSOR_TEST)
    GL.glColorMask(True, False, True, False)
    expected = (
        gl.integer(0x0BA2, 4),
        gl.integer(0x0C23, 4),
        bool(gl.IsEnabled(0x0BE2)),
        bool(gl.IsEnabled(0x0C11)),
    )
    with State(gl):
        texture = device.target("precision", 8, 1, RGBA32F)
        shader = device.program(
            "precision",
            """
            in vec2 uv; out vec4 color;
            void main() { color=vec4(0.0000123, 1.125, -0.25, 1.0); }
        """,
        )
        device.draw(shader, texture, 8, 1)
        pixels = np.empty((1, 8, 4), dtype=np.float32)
        gl.ReadPixels(0, 0, 8, 1, 0x1908, 0x1406, ctypes.c_void_p(pixels.ctypes.data))
        assert np.allclose(pixels, (0.0000123, 1.125, -0.25, 1.0), atol=1e-8)
        scatter = device.program(
            "scatter",
            """
            out vec4 color; void main() { color = vec4(1.0); }
        """,
            """
            void main() {
                float x = float(gl_VertexID % 8);
                gl_Position=vec4((x+0.5)/8.0*2.0-1.0, 0.0, 0.0, 1.0);
                gl_PointSize=1.0;
            }
        """,
        )
        device.draw(scatter, texture, 8, 1, points=8000, blend=True)
        gl.ReadPixels(0, 0, 8, 1, 0x1908, 0x1406, ctypes.c_void_p(pixels.ctypes.data))
        assert np.array_equal(pixels, np.full_like(pixels, 1000))
        assert gl.GetError() == 0
    observed = (
        gl.integer(0x0BA2, 4),
        gl.integer(0x0C23, 4),
        bool(gl.IsEnabled(0x0BE2)),
        bool(gl.IsEnabled(0x0C11)),
    )
    assert observed == expected
    report = {
        "renderer": GL.glGetString(GL.GL_RENDERER).decode(),
        "version": gl.version,
        "float_precision": True,
        "float_accumulation": True,
        "host_state_restored": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    device.close()
    context.doneCurrent()
    app.quit()


if __name__ == "__main__":
    main()
