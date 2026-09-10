"""Numerical parity on a real GL context; skipped when no renderer is available."""

import ctypes
import os
import sys

import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="module")
def analyzer():
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

    from scenelight.runtime.live_gpu import Analysis

    application = QGuiApplication.instance() or QGuiApplication([])
    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    context = QOpenGLContext()
    context.setFormat(surface_format)
    if not context.create():
        pytest.skip("No OpenGL context available")
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    if not context.makeCurrent(surface):
        pytest.skip("Cannot make the offscreen GL context current")
    try:
        analysis = Analysis()
    except RuntimeError as error:
        message = str(error)
        if any(
            marker in message
            for marker in (
                "graphics context lacks",
                "requires full-precision",
                "requires exact floating-point",
                "framebuffer is incomplete",
            )
        ):
            pytest.skip("Renderer lacks required float analysis support: " + message)
        raise
    yield analysis
    analysis.device.close()
    context.doneCurrent()
    surface.destroy()
    # Keep the application alive until every GL object has been released.
    assert application is not None


def _scene(kind):
    y, x = np.mgrid[:144, :256]
    pixels = np.full((144, 256, 4), 255, np.uint8)
    if kind == "dark":
        pixels[..., :3] = 0
    elif kind == "near_black":
        pixels[..., :3] = (1, 2, 1)
    elif kind == "uniform":
        pixels[..., :3] = (160, 160, 160)
    elif kind == "diffuse":
        value = 35 + x * 0.31 + y * 0.2
        pixels[..., :3] = np.stack((value, value * 0.92, value * 0.8), axis=-1)
    elif kind == "colored_sources":
        pixels[..., :3] = 18
        for cx, cy, color in (
            (48, 30, (255, 55, 24)),
            (128, 19, (28, 255, 90)),
            (208, 42, (35, 78, 255)),
        ):
            mask = ((x - cx) / 17) ** 2 + ((y - cy) / 8) ** 2 < 1
            pixels[mask, :3] = color
    else:
        random = np.random.default_rng(83)
        pixels[..., :3] = random.integers(20, 80, (144, 256, 3), dtype=np.uint8)
        pixels[20:100, 40:190, :3] = (235, 223, 196)
        pixels[34:90, 54:176, :3] = (40, 44, 46)
        pixels[102:111, 180:224, :3] = (220, 246, 255)
    return np.ascontiguousarray(pixels.transpose(1, 0, 2)) if kind == "portrait" else pixels


def _evaluate(analysis, pixels, previous=None):
    from scenelight.runtime.live_gpu import RGBA8, State

    device = analysis.device
    gl = device.gl
    height, width = pixels.shape[:2]
    with State(gl):
        source = device.target("test_source", width, height, RGBA8)
        gl.BindTexture(0x0DE1, source)
        gl.TexSubImage2D(
            0x0DE1, 0, 0, 0, width, height, 0x1908, 0x1401, ctypes.c_void_p(pixels.ctypes.data)
        )
        fields = analysis.evaluate(source, (width, height), preview=True, previous=previous)
        result = {}
        for name, texture in fields.items():
            if name.startswith("_"):
                continue
            shape = (10, 416, 4) if name == "transport" else (90, 160, 4)
            values = np.empty(shape, np.uint8)
            device.bind_targets((texture,))
            gl.ReadPixels(
                0, 0, shape[1], shape[0], 0x1908, 0x1401, ctypes.c_void_p(values.ctypes.data)
            )
            result[name] = values
        assert gl.GetError() == 0
        return result


@pytest.mark.parametrize(
    "kind",
    ["dark", "near_black", "uniform", "diffuse", "colored_sources", "ring_and_texture", "portrait"],
)
def test_live_fields_preserve_reference_model(analyzer, tmp_path, kind):
    from scenelight.preview.artifacts import ArtifactCache
    from scenelight.preview.media import environment_wrap

    pixels = _scene(kind)
    source = tmp_path / (kind + ".png")
    Image.fromarray(pixels).save(source)
    cache = ArtifactCache(tmp_path / "cache")
    cache._cuda_available = False
    try:
        expected = cache.temporal_scene(source, "reference:" + kind)
    finally:
        cache.shutdown()
    actual = _evaluate(analyzer, pixels)
    packed = actual["transport"][9, :2, :3].astype(float)
    metadata = packed @ np.array([65536.0, 256.0, 1.0]) / 16777215.0
    np.testing.assert_allclose(
        metadata, [expected.metadata["grain"], expected.metadata["sharpness"]], atol=3e-6, rtol=0
    )
    comparisons = (
        (actual["transport"][:9], expected.transport),
        (actual["irradiance"], expected.irradiance),
        (actual["emitter"], expected.emitter),
        (actual["wrap"][..., :3], environment_wrap(pixels)[..., :3]),
    )
    for generated, reference in comparisons:
        delta = np.abs(generated.astype(int) - reference.astype(int))
        assert delta.max() <= 1, (kind, generated.shape, delta.max(), delta.mean())


@pytest.mark.parametrize("kind", ["empty", "ties", "mixed"])
def test_parallel_quantiles_match_raster_exactly(analyzer, kind):
    from scenelight.runtime.live_gpu import RGBA32F, State

    gl, device = analyzer.device.gl, analyzer.device
    if not gl.compute_supported:
        pytest.skip("This test compares compute and raster implementations")
    values = np.zeros((29, 37, 4), dtype=np.float32)
    if kind == "ties":
        values[:] = np.random.default_rng(6).choice(
            np.array([0.0, 1e-6, 0.5, 0.500001, 1.0], np.float32), values.shape
        )
    elif kind == "mixed":
        values[:] = np.random.default_rng(7).uniform(-0.1, 7.0, values.shape)
    with State(gl):
        source = device.target("quantile_comparison_input", 37, 29, RGBA32F)
        gl.BindTexture(0x0DE1, source)
        gl.TexSubImage2D(
            0x0DE1, 0, 0, 0, 37, 29, 0x1908, 0x1406, ctypes.c_void_p(values.ctypes.data)
        )
        outputs = []
        for compute in (True, False):
            gl.compute_active = compute
            target = analyzer.quantiles(
                "quantile_comparison", source, (37, 29), 2, (0.0, 0.2, 0.5, 1.0), positive=True
            )
            device.bind_targets((target,))
            result = np.empty((1, 4, 4), dtype=np.float32)
            gl.ReadPixels(0, 0, 4, 1, 0x1908, 0x1406, ctypes.c_void_p(result.ctypes.data))
            outputs.append(result)
        np.testing.assert_array_equal(*outputs)
        assert gl.GetError() == 0


@pytest.mark.parametrize(
    "kind", ["dark", "uniform", "colored_sources", "ring_and_texture", "portrait"]
)
def test_geometry_membership_preserves_complete_fields(analyzer, kind):
    gl = analyzer.device.gl
    if gl.es or not gl.compute_supported:
        pytest.skip("Requires desktop compute and geometry paths for comparison")
    pixels = _scene(kind)
    reference = _evaluate(analyzer, pixels)
    try:
        gl.compute_supported = False
        actual = _evaluate(analyzer, pixels)
    finally:
        gl.compute_supported = True
    for name in reference:
        np.testing.assert_array_equal(actual[name], reference[name], err_msg=name)


@pytest.mark.parametrize("kind", ["colored_sources", "ring_and_texture", "portrait"])
def test_opencl_preserves_reference_fields(analyzer, kind):
    if sys.platform != "win32":
        pytest.skip("This interop backend uses WGL")
    from scenelight.runtime.live_opencl import Backend

    try:
        sharing = Backend(analyzer.device)
    except OSError:
        pytest.skip("OpenCL runtime is not installed")
    except RuntimeError as error:
        if "No OpenCL device shares" in str(error):
            pytest.skip(str(error))
        raise
    pixels = _scene(kind)
    reference = _evaluate(analyzer, pixels)
    analyzer.device.opencl = sharing
    try:
        actual = _evaluate(analyzer, pixels)
        for name in reference:
            delta = np.abs(actual[name].astype(int) - reference[name].astype(int))
            assert delta.max() <= 1, (name, delta.max())
    finally:
        sharing.close()
        analyzer.device.opencl = None


def test_scalar_targets_preserve_all_sampler_channels(analyzer):
    from scenelight.runtime.live_gpu import COMMON, R32F, State

    gl, device = analyzer.device.gl, analyzer.device
    values = np.array([[0.0000123, 0.25], [1.125, -0.25]], dtype=np.float32)
    with State(gl):
        source = device.target("scalar_storage_test", 2, 2, R32F)
        gl.BindTexture(0x0DE1, source)
        gl.TexSubImage2D(0x0DE1, 0, 0, 0, 2, 2, 0x1903, 0x1406, ctypes.c_void_p(values.ctypes.data))
        sampled = analyzer.run(
            "scalar_sampling_test",
            COMMON + "void main(){color=texelFetch(t0,ivec2(gl_FragCoord.xy),0);}",
            2,
            2,
            (source,),
        )
        device.bind_targets((sampled,))
        result = np.empty((2, 2, 4), dtype=np.float32)
        gl.ReadPixels(0, 0, 2, 2, 0x1908, 0x1406, ctypes.c_void_p(result.ctypes.data))
        np.testing.assert_array_equal(result, np.repeat(values[..., None], 4, axis=-1))
        assert gl.GetError() == 0


def test_continuity_preserves_cold_and_unchanging_scene_fields(analyzer):
    pixels = _scene("colored_sources")
    baseline = _evaluate(analyzer, pixels)
    cold = _evaluate(analyzer, pixels, ())
    previous = tuple(
        analyzer.device.targets[name][0]
        for name in ("history_lights_snapshot", "history_image_snapshot")
    )
    warm = _evaluate(analyzer, pixels, previous)
    for name in baseline:
        np.testing.assert_array_equal(baseline[name], cold[name])
        np.testing.assert_array_equal(baseline[name], warm[name])


@pytest.mark.parametrize("case", ["tie", "stronger", "cut"])
def test_light_identity_continuity_keeps_values_live_and_resets_on_cuts(analyzer, case):
    from scenelight.runtime.live_gpu import RGBA32F, State

    gl, device = analyzer.device.gl, analyzer.device
    old = np.zeros((3, 12, 4), dtype=np.float32)
    for offset in (0, 6):
        old[0, offset] = (0.2, 0.1, 0.2, 1.0)
        old[0, offset + 1] = (0.8, 0.1, 0.2, 0.995)
        old[1, offset : offset + 2] = (0.9, 0.9, 0.9, 0.8)
        old[2, offset : offset + 2] = (0.8, 1.0, 0.0, 1.0)
    current = old.copy()
    for offset in (0, 6):
        current[:, offset : offset + 2] = old[:, [offset + 1, offset]]
        current[0, offset, 3] = 1.0
        current[0, offset + 1, 3] = 0.5 if case == "stronger" else 0.995
        current[1, offset + 1, 3] = 0.6
    image = np.full((18, 32, 4), 0.2, np.float32)
    changed = image.copy()
    if case == "cut":
        changed[..., :3] = (0.8, 0.1, 0.1)
    with State(gl):
        textures = []
        for name, pixels in (
            ("old_lights", old),
            ("current_lights", current),
            ("old_image", image),
            ("new_image", changed),
        ):
            h, w = pixels.shape[:2]
            texture = device.target("continuity_test_" + name, w, h, RGBA32F)
            gl.BindTexture(0x0DE1, texture)
            gl.TexSubImage2D(
                0x0DE1, 0, 0, 0, w, h, 0x1908, 0x1406, ctypes.c_void_p(pixels.ctypes.data)
            )
            textures.append(texture)
        result = analyzer.stabilize_light_order(
            textures[1], textures[3], (textures[0], textures[2])
        )
        device.bind_targets((result,))
        pixels = np.empty_like(current)
        gl.ReadPixels(0, 0, 12, 3, 0x1908, 0x1406, ctypes.c_void_p(pixels.ctypes.data))
        for offset in (0, 6):
            expected_index = offset + 1 if case == "tie" else offset
            np.testing.assert_array_equal(pixels[:, offset], current[:, expected_index])
        assert gl.GetError() == 0


def test_compute_failure_uses_equivalent_raster_solver(analyzer, monkeypatch):
    from scenelight.runtime.live_gpu import ComputeUnavailable

    if not analyzer.device.gl.compute_supported:
        pytest.skip("Compute shaders unavailable; reference tests exercise the raster solver")
    pixels = _scene("colored_sources")
    expected = _evaluate(analyzer, pixels)

    def unavailable(*args):
        raise ComputeUnavailable("Injected optional compute compiler failure")

    monkeypatch.setattr(analyzer.device, "compute_program", unavailable)
    actual = _evaluate(analyzer, pixels)
    assert not analyzer.device.gl.compute_supported
    for name in expected:
        np.testing.assert_array_equal(actual[name], expected[name])


def test_analysis_restores_external_pixel_layout_and_raster_state(analyzer):
    from scenelight.runtime.live_gpu import State

    gl = analyzer.device.gl
    layouts = {0x0D02: 31, 0x0D03: 2, 0x0D04: 3, 0x0CF2: 27, 0x0CF3: 4, 0x0CF4: 5}
    original = {name: gl.integer(name) for name in layouts}
    discard = bool(gl.IsEnabled(0x8C89))
    try:
        for name, value in layouts.items():
            gl.PixelStorei(name, value)
        gl.Enable(0x8C89)
        with State(gl):
            assert all(gl.integer(name) == 0 for name in layouts)
            assert not gl.IsEnabled(0x8C89)
            analyzer.device.validate()
        assert {name: gl.integer(name) for name in layouts} == layouts
        assert gl.IsEnabled(0x8C89)
    finally:
        for name, value in original.items():
            gl.PixelStorei(name, value)
        (gl.Enable if discard else gl.Disable)(0x8C89)
