"""Measure the shared live-source prototype against an independent pixel oracle.

This validates texture acquisition and a linear-light reduction primitive. It
does not certify a complete replacement lighting solver.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from OpenGL import GL
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scenelight.engine import _srgb_to_linear  # noqa: E402
from scenelight.preview.gpu_view import SceneLightGPUView, _link_program  # noqa: E402
from scenelight.preview.media import MediaClip  # noqa: E402
from scenelight.preview.shader_source import (  # noqa: E402
    BACKGROUND_VERTEX,
    live_probe_fragment_source,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
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
        raise RuntimeError("Could not create a GL context")
    vertex = BACKGROUND_VERTEX.replace("v_uv", "v_tex_coord").replace(
        "1.0 - in_unit.y * 2.0", "in_unit.y * 2.0 - 1.0"
    )
    program = _link_program(vertex, live_probe_fragment_source())
    vertices = np.array(((0, 0, 0, 0), (1, 0, 1, 0), (0, 1, 0, 1), (1, 1, 1, 1)), np.float32)
    vao, vbo = GL.glGenVertexArrays(1), GL.glGenBuffers(1)
    GL.glBindVertexArray(vao)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)
    for name, offset in (("in_unit", 0), ("in_uv", 8)):
        location = GL.glGetAttribLocation(program, name)
        GL.glEnableVertexAttribArray(location)
        GL.glVertexAttribPointer(location, 2, GL.GL_FLOAT, False, 16, ctypes.c_void_p(offset))
    target, _ = SceneLightGPUView._upload_array(np.zeros((9, 16, 4), np.uint8))
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    GL.glFramebufferTexture2D(
        GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, target, 0
    )
    if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("Prototype framebuffer is incomplete")
    GL.glUseProgram(program)
    GL.glUniform2f(GL.glGetUniformLocation(program, "u_sc_probe_grid"), 16, 9)
    GL.glUniform1i(GL.glGetUniformLocation(program, "tex1"), 1)
    GL.glViewport(0, 0, 16, 9)
    GL.glDisable(GL.GL_BLEND)
    query = int(np.asarray(GL.glGenQueries(1)).reshape(-1)[0])
    clip = MediaClip(args.video, args.output / "media")
    source = 0
    records, signatures = [], set()
    indices = range(min(60, clip.frame_count))
    try:
        for frame in clip.iter_frames(indices):
            GL.glActiveTexture(GL.GL_TEXTURE1)
            if not source:
                source, _ = SceneLightGPUView._upload_array(frame.rgba)
            else:
                GL.glBindTexture(GL.GL_TEXTURE_2D, source)
                GL.glTexSubImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    0,
                    0,
                    frame.rgba.shape[1],
                    frame.rgba.shape[0],
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    frame.rgba,
                )
            GL.glBeginQuery(GL.GL_TIME_ELAPSED, query)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glEndQuery(GL.GL_TIME_ELAPSED)
            gpu_ns = int(GL.glGetQueryObjectuiv(query, GL.GL_QUERY_RESULT))
            pixels = np.frombuffer(
                GL.glReadPixels(0, 0, 16, 9, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE), np.uint8
            )
            actual = pixels.reshape(9, 16, 4)[..., :3]
            h, w = frame.rgba.shape[:2]
            xs = (np.arange(64, dtype=np.float32) + 0.5) * (w / 64) - 0.5
            ys = (np.arange(36, dtype=np.float32) + 0.5) * (h / 36) - 0.5
            xx, yy = np.meshgrid(xs, ys)
            sampled = cv2.remap(
                frame.rgba[..., :3].astype(np.float32) / 255,
                xx,
                yy,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            expected = np.rint(
                _srgb_to_linear(sampled).reshape(9, 4, 16, 4, 3).mean(axis=(1, 3)) * 255
            ).astype(np.uint8)
            error = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
            signatures.add(actual.tobytes())
            records.append(
                {
                    "frame": frame.index,
                    "gpu_ms": gpu_ns / 1e6,
                    "max_channel_error": int(error.max()),
                    "mean_channel_error": float(error.mean()),
                }
            )
    finally:
        clip.close()
        GL.glDeleteQueries(1, [query])
        GL.glDeleteTextures([source, target])
        GL.glDeleteFramebuffers(1, [fbo])
        GL.glDeleteBuffers(1, [vbo])
        GL.glDeleteVertexArrays(1, [vao])
        GL.glDeleteProgram(program)
    result = {
        "scope": "Live texture reduction primitive only; GPU time excludes upload and readback.",
        "frames": len(records),
        "distinct_fields": len(signatures),
        "max_channel_error": max(row["max_channel_error"] for row in records),
        "gpu_ms_p50_p95": [
            float(x) for x in np.percentile([r["gpu_ms"] for r in records[1:]], [50, 95])
        ],
        "records": records,
    }
    (args.output / "live-gpu-source.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "records"}))
    context.doneCurrent()
    app.quit()
    return 0 if result["max_channel_error"] <= 1 and result["distinct_fields"] > 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
