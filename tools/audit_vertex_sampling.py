"""Compare exact pixels and GPU draw time for both shared lighting shaders.

Generate original inputs with examples/synthetic/make_release_lab.py, then pass
its game/scenelight_lab directory and a new output directory. Uses an offscreen
OpenGL context and requires the optional Preview dependencies.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np
from OpenGL import GL
from PIL import Image
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneLightGPUView, _link_program
from scenelight.preview.hardware import detect_hardware_profile
from scenelight.preview.shader_source import (
    fragment_source,
    production_shader_sha256,
    vertex_source,
)


def gpu_times(view, reference, optimized):
    framebuffer, color, query = 0, 0, 0
    try:
        view.makeCurrent()
        framebuffer = GL.glGenFramebuffers(1)
        color = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, color)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, 2160, 1215, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None
        )
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
        GL.glFramebufferTexture2D(
            GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, color, 0
        )
        assert GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE
        GL.glViewport(0, 0, 2160, 1215)
        query = int(np.asarray(GL.glGenQueries(1)).reshape(-1)[0])
        results = []
        # ABBA order reduces the effect of gradual clock/temperature changes.
        for name, program in (
            ("reference", reference),
            ("vertex", optimized),
            ("vertex", optimized),
            ("reference", reference),
        ):
            view._program = program
            for _ in range(5):
                view._draw_scene()
            GL.glFinish()
            samples = []
            for _ in range(40):
                GL.glBeginQuery(GL.GL_TIME_ELAPSED, query)
                view._draw_scene()
                GL.glEndQuery(GL.GL_TIME_ELAPSED)
                GL.glFinish()
                samples.append(int(GL.glGetQueryObjectuiv(query, GL.GL_QUERY_RESULT)) / 1e6)
            results.append(
                {
                    "variant": name,
                    "median_ms": statistics.median(samples),
                    "mean_ms": statistics.mean(samples),
                }
            )
        return results
    finally:
        if query:
            GL.glDeleteQueries(1, [query])
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        if color:
            GL.glDeleteTextures([color])
        if framebuffer:
            GL.glDeleteFramebuffers(1, [framebuffer])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for name in ("warm.png", "cool.png", "nova.png"):
        if not (args.assets / name).is_file():
            parser.error("Missing generated input: " + name)
    args.output.mkdir(parents=True)
    app = QApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("No offscreen OpenGL 3.3 context")

    class View(SceneLightGPUView):
        def makeCurrent(self):
            if not context.makeCurrent(surface):
                raise RuntimeError("Lost the offscreen test context")

        def doneCurrent(self):
            context.doneCurrent()

        def context(self):
            return context

        def defaultFramebufferObject(self):
            return 0

        def update(self, *args):
            pass

    view = View()
    reference, optimized = 0, 0
    try:
        view.initializeGL()
        view.makeCurrent()
        reference = _link_program(vertex_source(), fragment_source())
        optimized = _link_program(
            vertex_source(center_samples=True), fragment_source(center_samples=True)
        )
        GL.glDeleteProgram(view._program)
        view._program = optimized
        for name in ("in_unit", "in_uv"):
            assert GL.glGetAttribLocation(reference, name) == GL.glGetAttribLocation(
                optimized, name
            )
        report = {
            "gpu": GL.glGetString(GL.GL_RENDERER).decode(),
            "shader_sha256": production_shader_sha256(),
            "comparisons": [],
        }
        cache = ArtifactCache(
            args.output / "cache", hardware_profile=detect_hardware_profile(cuda=False)
        )
        view.set_sprite(args.assets / "nova.png", cache.form(args.assets / "nova.png"))
        calibrations = (
            Calibration(),
            Calibration(individual_light_colors=1.0),
            Calibration(auto_strength=1.25, key_strength=1.3, probe_strength=1.0),
        )
        for scene in ("warm", "cool"):
            path = args.assets / (scene + ".png")
            view.set_scene(path, cache.scene(path))
            for placement in ((0.25, 1.04, 0.92), (0.75, 1.04, 1.3), (0.513, 1.12, 0.65)):
                view.set_placement(*placement)
                for index, calibration in enumerate(calibrations):
                    view.set_calibration(calibration)
                    view._program = reference
                    before = view.render_rgba()
                    view._program = optimized
                    after = view.render_rgba()
                    delta = np.abs(before.astype(np.int16) - after.astype(np.int16))
                    record = {
                        "scene": scene,
                        "placement": placement,
                        "calibration": index,
                        "max_difference": int(delta.max()),
                        "different_pixels": int(np.any(delta, axis=2).sum()),
                    }
                    report["comparisons"].append(record)
                    if record["different_pixels"] and not (args.output / "before.png").exists():
                        Image.fromarray(before).save(args.output / "before.png")
                        Image.fromarray(after).save(args.output / "after.png")
        view.set_placement(0.5, 1.04, 0.92)
        view.set_calibration(Calibration())
        report["gpu_times"] = gpu_times(view, reference, optimized)
        report["pixel_identical"] = all(
            record["different_pixels"] == 0 for record in report["comparisons"]
        )
        (args.output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"pixel_identical": report["pixel_identical"], "gpu_times": report["gpu_times"]}
            )
        )
        if not report["pixel_identical"]:
            raise AssertionError("Vertex sampling changed rendered pixels; inspect result.json")
    finally:
        view.makeCurrent()
        if reference:
            GL.glDeleteProgram(reference)
        if optimized:
            view._program = optimized
        view.close()
        app.processEvents()


if __name__ == "__main__":
    main()
