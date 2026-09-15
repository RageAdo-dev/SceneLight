"""Render live and prepared animations through the production sprite shader."""

import os
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw


@pytest.fixture(scope="module")
def renderer(tmp_path_factory):
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    GL = pytest.importorskip("OpenGL.GL")
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from scenelight.preview.artifacts import ArtifactCache
    from scenelight.preview.gpu_view import SceneLightGPUView

    application = QApplication.instance() or QApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        pytest.skip("No OpenGL context available")
    if (context.format().majorVersion(), context.format().minorVersion()) < (3, 3):
        pytest.skip("OpenGL 3.3 is unavailable")

    class View(SceneLightGPUView):
        def makeCurrent(self):
            assert context.makeCurrent(surface)

        def doneCurrent(self):
            context.doneCurrent()

        def context(self):
            return context

        def defaultFramebufferObject(self):
            return 0

        def update(self, *args):
            pass

    root = tmp_path_factory.mktemp("gpu-lighting")
    sprite = Image.new("RGBA", (160, 240))
    draw = ImageDraw.Draw(sprite)
    draw.ellipse((38, 8, 122, 94), fill=(225, 185, 155, 255))
    draw.rounded_rectangle((28, 83, 132, 238), radius=22, fill=(115, 125, 155, 255))
    path = root / "sprite.png"
    sprite.save(path)
    cache = ArtifactCache(root / "cache")
    cache._cuda_available = False
    view = View()
    view.initializeGL()
    view.set_sprite(path, cache.form(path))
    view.set_placement(0.65, 1.0, 0.92)
    yield view
    view.makeCurrent()
    GL.glUseProgram(0)
    GL.glBindVertexArray(0)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
    for unit in range(int(GL.glGetIntegerv(GL.GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS))):
        GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    view.close()
    cache.shutdown()
    application.processEvents()
    context.doneCurrent()
    surface.destroy()


def _lamps(amount):
    y, x = np.mgrid[:144, :256]
    pixels = np.zeros((144, 256, 4), np.uint8)
    rgb = np.full((144, 256, 3), 14.0)
    for cx, color, strength in ((55, (235, 60, 20), 1.0), (205, (20, 85, 235), amount)):
        glow = np.exp(-(((x - cx) / 36) ** 2 + ((y - 45) / 38) ** 2))
        rgb += glow[..., None] * np.asarray(color) * strength
    pixels[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    pixels[..., 3] = 255
    return pixels


def test_video_flag_does_not_remeter_complete_frame_fields(renderer):
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(_lamps(0.6))
    renderer.set_live_background(False)
    still = renderer.render_rgba((640, 360))
    renderer.set_live_background(True)
    video = renderer.render_rgba((640, 360))
    np.testing.assert_array_equal(video, still)


def test_prepared_replay_matches_live_and_preserves_flashes_and_cuts(renderer, tmp_path):
    from scenelight.prepared import FramePreparer, Writer
    from scenelight.runtime.prepared import Reader

    low, full = _lamps(0.15), _lamps(1.0)
    flash = np.full_like(full, 255)
    cut = full.copy()
    cut[..., :3] = cut[..., 2::-1]
    frames = [low, low, _lamps(0.35), _lamps(0.65), full, full, flash, full, cut, cut]
    renderer.set_live_analysis_enabled(True)
    renderer.set_live_background(True)
    expected = []
    for frame in frames:
        renderer.set_background_frame(frame)
        expected.append(renderer.render_rgba((640, 360)))
    for a, b in ((0, 1), (4, 5), (4, 7), (8, 9)):
        np.testing.assert_array_equal(expected[a], expected[b])
    # The interior of the synthetic sprite must respond, not just the video
    # around it. Genuine flashes and cuts reach it on the presented frame.
    for a, b in ((0, 4), (5, 6), (7, 8)):
        delta = abs(
            expected[a][110:250, 385:435, :3].astype(int)
            - expected[b][110:250, 385:435, :3].astype(int)
        )
        assert delta.mean() > 2.0

    renderer.makeCurrent()
    preparer = FramePreparer(preview=True)
    path = tmp_path / "lighting.slframes"
    writer = Writer(path, {"frame_count": len(frames), "preview": True})
    try:
        for frame in frames:
            writer.append(preparer.frame(frame))
        writer.finish()
    finally:
        writer.close()
        preparer.close()
    reader = Reader(str(path))
    try:
        for index, frame in enumerate(frames):
            renderer.set_background_frame(frame)
            renderer.set_prepared_fields(reader.frame(index))
            np.testing.assert_array_equal(renderer.render_rgba((640, 360)), expected[index])
            assert len(reader.frames) <= 2
    finally:
        reader.close()
