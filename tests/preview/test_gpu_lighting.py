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


def test_side_light_illuminates_facing_surface_and_swaps_with_direction(renderer):
    from scenelight.calibration import Calibration
    from scenelight.engine import _srgb_to_linear

    y, x = np.mgrid[:144, :256]
    renderer.set_placement(0.5, 1.0, 0.92)
    renderer.set_calibration(Calibration(specular_strength=0, rim_strength=0, wrap_strength=0))
    renderer.set_live_analysis_enabled(True)
    halves = []
    try:
        for cx in (0.12, 0.88):
            glow = np.exp(-(((x / 256 - cx) / 0.055) ** 2 + ((y / 144 - 0.24) / 0.08) ** 2))
            pixels = np.full((144, 256, 4), 255, np.uint8)
            pixels[..., :3] = (8 + 247 * glow[..., None]).astype(np.uint8)
            renderer.set_background_frame(pixels)
            frame = _srgb_to_linear(renderer.render_rgba((640, 360))[..., :3] / 255.0)
            halves.append((frame[65:100, 270:290].mean(), frame[65:100, 350:370].mean()))
        # A uniform tint cannot pass: the brighter surface must swap sides.
        assert halves[0][0] > halves[0][1] * 1.5, halves
        assert halves[1][1] > halves[1][0] * 1.5, halves
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_placement(0.65, 1.0, 0.92)


def test_video_flag_does_not_remeter_complete_frame_fields(renderer):
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(_lamps(0.6))
    renderer.set_live_background(False)
    still = renderer.render_rgba((640, 360))
    renderer.set_live_background(True)
    video = renderer.render_rgba((640, 360))
    np.testing.assert_array_equal(video, still)


def test_dark_scene_has_no_constant_fill_and_a_flash_reaches_the_sprite(renderer):
    renderer.set_live_analysis_enabled(True)
    black = np.zeros((144, 256, 4), np.uint8)
    black[..., 3] = 255
    levels = []
    for value in (0, 4, 8, 16, 255, 0):
        pixels = black.copy()
        pixels[..., :3] = value
        renderer.set_background_frame(pixels)
        frame = renderer.render_rgba((640, 360))
        levels.append(float(frame[110:200, 395:425, :3].mean()))
    assert levels[0] < 5, levels
    assert all(a < b for a, b in zip(levels[:4], levels[1:5])), levels
    assert levels[-1] == levels[0], levels


def test_broad_environment_color_is_retained_without_inventing_a_second_lamp(renderer):
    from scenelight.calibration import Calibration

    renderer.set_live_analysis_enabled(True)
    renderer.set_placement(0.5, 1.0, 0.92)
    pixels = np.full((144, 256, 4), 255, np.uint8)
    pixels[..., :3] = (52, 145, 70)
    try:
        renderer.set_calibration(Calibration())
        renderer.set_background_frame(pixels)
        automatic = renderer.render_rgba((640, 360))
        renderer.set_calibration(Calibration(adaptive_light_colors=0.0))
        ambient = renderer.render_rgba((640, 360))
        subject = automatic[65:110, 285:355, :3].mean(axis=(0, 1))
        # Compare the same painted material under equal-luminance neutral
        # surroundings; warm material need not become literally green-dominant.
        from scenelight.engine import _linear_to_srgb, _luminance, _srgb_to_linear

        neutral = round(
            float(
                _linear_to_srgb(
                    _luminance(_srgb_to_linear(np.array([52, 145, 70], dtype=np.float32) / 255.0))
                )
            )
            * 255
        )
        pixels[..., :3] = neutral
        renderer.set_background_frame(pixels)
        gray = renderer.render_rgba((640, 360))[65:110, 285:355, :3].mean(axis=(0, 1))
        # Green reflected light increases green relative to BOTH opponent
        # channels. G/R alone misses the blue reduction on this orange paint.
        green_share = subject[1] / (subject[0] + subject[2])
        neutral_share = gray[1] / (gray[0] + gray[2])
        assert green_share > neutral_share * 1.08, (subject, gray)
        np.testing.assert_array_equal(automatic, ambient)
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_placement(0.65, 1.0, 0.92)


def test_compact_colored_lamps_keep_distinct_directional_colors(renderer):
    from scenelight.calibration import Calibration

    renderer.set_live_analysis_enabled(True)
    renderer.set_placement(0.5, 1.0, 0.92)
    try:
        renderer.set_calibration(Calibration())
        renderer.set_background_frame(_lamps(1.0))
        frame = renderer.render_rgba((640, 360))
        left = frame[65:105, 280:305, :3].mean(axis=(0, 1))
        right = frame[65:105, 335:360, :3].mean(axis=(0, 1))
        assert left[0] / max(left[2], 1) > right[0] / max(right[2], 1) * 1.2, (left, right)
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_placement(0.65, 1.0, 0.92)


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
