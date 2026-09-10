"""Compare the live GPU preparation stages against the unchanged CPU reference."""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from pathlib import Path

import cv2
import numpy as np
from OpenGL import GL
from PIL import Image
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat

from scenelight.builder import _wrap_map
from scenelight.cuda_backend import _transport_layout
from scenelight.engine import (
    Placement,
    _detect_source_components,
    _gradient_field,
    _placement_region,
    prepare_scene,
)
from scenelight.preview.artifacts import ArtifactCache
from scenelight.runtime.live_gpu import RGBA8, Analysis, State


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--components", action="store_true")
    parser.add_argument("--physical", action="store_true")
    parser.add_argument("--meters", action="store_true")
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--images", action="store_true")
    args = parser.parse_args()
    source = Image.open(args.source).convert("RGBA")
    pixels = np.asarray(source).copy()
    reference = prepare_scene(source)
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
    analysis = Analysis()
    device, gl = analysis.device, analysis.device.gl
    report = {"renderer": GL.glGetString(GL.GL_RENDERER).decode(), "fields": {}}
    with State(gl):
        texture = device.target("input", *source.size, storage=RGBA8)
        gl.BindTexture(0x0DE1, texture)
        gl.TexSubImage2D(
            0x0DE1, 0, 0, 0, *source.size, 0x1908, 0x1401, ctypes.c_void_p(pixels.ctypes.data)
        )
        first = time.perf_counter()
        fields = analysis.prepare(texture, source.size)
        gl.Finish()
        report["cold_seconds"] = time.perf_counter() - first
        times = []
        for _ in range(5):
            start = time.perf_counter()
            analysis.prepare(texture, source.size)
            gl.Finish()
            times.append((time.perf_counter() - start) * 1000)
        report["warm_complete_ms"] = times
        for name, expected in (
            ("linear", reference.linear),
            ("clipped", reference.clipped_luma),
            ("source_weights", reference.base_source_weights),
            ("texture_residual", reference.texture_residual),
        ):
            device.bind_targets((fields[name],))
            actual = np.empty((analysis.height, analysis.width, 4), np.float32)
            gl.ReadPixels(
                0,
                0,
                analysis.width,
                analysis.height,
                0x1908,
                0x1406,
                ctypes.c_void_p(actual.ctypes.data),
            )
            actual = actual[..., :3] if expected.ndim == 3 else actual[..., 0]
            delta = np.abs(actual - expected)
            report["fields"][name] = {
                "mean": float(delta.mean()),
                "max": float(delta.max()),
                "reference_max": float(expected.max()),
            }
        device.bind_targets((fields["quantiles"],))
        q = np.empty((1, 4, 4), np.float32)
        gl.ReadPixels(0, 0, 4, 1, 0x1908, 0x1406, ctypes.c_void_p(q.ctypes.data))
        report["quantiles"] = {
            "gpu": q[0, :, 0].tolist(),
            "cpu": np.quantile(reference.luma, (0.995, 0.86, 0.97, 0.55)).tolist(),
        }
        report["gl_error"] = gl.GetError()
        if args.components:
            start = time.perf_counter()
            labels = analysis.component_labels("global", fields["source_weights"])
            statistics, candidates, total = analysis.component_statistics(
                "global",
                labels,
                fields["source_weights"],
                fields["linear"],
                fields["texture_residual"],
            )
            selected, remaining = analysis.candidate_batch("global", candidates)
            gl.Finish()
            report["components_cold_ms"] = (time.perf_counter() - start) * 1000
            report["label_iterations"] = analysis.fields["global_iterations"]
            device.bind_targets((labels,))
            actual = np.empty((analysis.height, analysis.width, 4), np.float32)
            gl.ReadPixels(
                0,
                0,
                analysis.width,
                analysis.height,
                0x1908,
                0x1406,
                ctypes.c_void_p(actual.ctypes.data),
            )
            weights = reference.base_source_weights
            positive = weights[weights > 1e-6]
            cutoff = max(float(positive.max()) * 0.035, float(np.quantile(positive, 0.16)))
            mask = cv2.morphologyEx(
                (weights >= cutoff).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
            )
            count, cpu_labels = cv2.connectedComponents(mask, connectivity=8)
            roots = np.full(count, weights.size + 1, dtype=np.int64)
            np.minimum.at(roots, cpu_labels.ravel(), np.arange(weights.size) + 1)
            roots[0] = 0
            expected = roots[cpu_labels]
            report["label_mismatches"] = int(np.count_nonzero(actual[..., 0] != expected))
            device.bind_targets((selected,))
            top = np.empty((1, 8, 4), np.float32)
            gl.ReadPixels(0, 0, 8, 1, 0x1908, 0x1406, ctypes.c_void_p(top.ctypes.data))
            report["top_raw_components"] = top[0].tolist()
            report["components_gl_error"] = gl.GetError()
        if args.physical:
            start = time.perf_counter()
            lights, total = analysis.physical_components(
                "physical", fields["source_weights"], fields["linear"], fields["texture_residual"]
            )
            gl.Finish()
            report["physical_cold_ms"] = (time.perf_counter() - start) * 1000
            times = []
            for _ in range(3):
                start = time.perf_counter()
                lights, total = analysis.physical_components(
                    "physical",
                    fields["source_weights"],
                    fields["linear"],
                    fields["texture_residual"],
                )
                gl.Finish()
                times.append((time.perf_counter() - start) * 1000)
            report["physical_warm_ms"] = times
            report["physical_batches"] = analysis.fields["physical_component_batches"]
            cpu_lights = _detect_source_components(
                reference.linear,
                reference.base_source_weights,
                luma=reference.luma,
                texture_residual=reference.texture_residual,
                coordinate_grid=(reference.yy, reference.xx),
                ring_kernel=reference.ring_kernel,
                crop_components=True,
            )
            expected = np.zeros((3, 6, 4), np.float32)
            for i, light in enumerate([v for v in cpu_lights if not v.creative_only]):
                expected[0, i] = (light.x, light.y, light.radius, light.intensity)
                expected[1, i] = (*light.color, light.confidence)
                expected[2, i] = (light.emission_score, 1, 0, 1)
            device.bind_targets((lights,))
            actual = np.empty_like(expected)
            gl.ReadPixels(0, 0, 6, 3, 0x1908, 0x1406, ctypes.c_void_p(actual.ctypes.data))
            report["physical_max_error"] = float(np.abs(actual - expected).max())
            report["physical_gpu"] = actual.tolist()
            report["physical_cpu"] = expected.tolist()
            report["physical_gl_error"] = gl.GetError()
        if args.meters:
            start = time.perf_counter()
            meters = analysis.meters(fields)
            gl.Finish()
            report["meters_cold_ms"] = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            meters = analysis.meters(fields)
            gl.Finish()
            report["meters_warm_ms"] = (time.perf_counter() - start) * 1000
            data = []
            for texture in meters:
                device.bind_targets((texture,))
                actual = np.empty((1, 145, 4), np.float32)
                gl.ReadPixels(0, 0, 145, 1, 0x1908, 0x1406, ctypes.c_void_p(actual.ctypes.data))
                data.append(actual[0])
            placements = (*_transport_layout((16, 9), 0.84, 0.92)[1], Placement(0.5, 0.99, 0.78))
            errors = []
            for index in (0, 7, 15, 64, 128, 143, 144):
                placement = placements[index]
                _, _, weights = _placement_region(
                    reference.luma.shape, placement, (reference.yy, reference.xx)
                )
                total = float(weights.sum())
                gx, gy = _gradient_field(reference.clipped_luma, placement.height)
                upper = np.clip(
                    (
                        np.clip(placement.baseline_y - placement.height * 0.48, 0, 1)
                        - reference.normalized_y
                    )
                    * 2.2
                    + 0.35,
                    0.15,
                    1,
                )
                expected = np.array(
                    [
                        [*((reference.linear * weights[..., None]).sum(axis=(0, 1))), total],
                        [
                            (reference.clipped_luma * weights).sum(),
                            (np.log(reference.clipped_luma + 0.008) * weights).sum(),
                            (reference.clipped_luma**2 * weights).sum(),
                            (reference.saturation * weights).sum(),
                        ],
                        [
                            (gx * weights).sum(),
                            (gy * weights).sum(),
                            (reference.base_source_weights * weights).sum(),
                            0,
                        ],
                        [
                            *((reference.linear * (weights * upper)[..., None]).sum(axis=(0, 1))),
                            (weights * upper).sum(),
                        ],
                    ]
                )
                actual = np.array([v[index] for v in data])
                errors.append(
                    {
                        "placement": index,
                        "mean_absolute_normalized": float(np.abs(actual - expected).mean() / total),
                        "max_absolute_normalized": float(np.abs(actual - expected).max() / total),
                    }
                )
            report["meter_errors"] = errors
            report["meters_gl_error"] = gl.GetError()
        if args.solve:
            start = time.perf_counter()
            solved = analysis.solve(texture, source.size)
            gl.Finish()
            report["solve_cold_ms"] = (time.perf_counter() - start) * 1000
            timings = []
            for _ in range(3):
                start = time.perf_counter()
                solved = analysis.solve(texture, source.size)
                gl.Finish()
                timings.append((time.perf_counter() - start) * 1000)
            report["solve_warm_ms"] = timings
            device.bind_targets((solved["transport"],))
            actual = np.empty((9, 416, 4), np.uint8)
            gl.ReadPixels(0, 0, 416, 9, 0x1908, 0x1401, ctypes.c_void_p(actual.ctypes.data))
            cache = ArtifactCache(args.output.parent / "reference-cache")
            try:
                reference_scene = cache.temporal_scene(
                    args.source, "live-solve:" + str(args.source.resolve())
                )
            finally:
                cache.shutdown()
            expected = reference_scene.transport
            delta = np.abs(actual.astype(float) - expected.astype(float))
            report["transport_error"] = {
                "mean": float(delta.mean()),
                "max": float(delta.max()),
                "channels_over_1": int(np.count_nonzero(delta > 1)),
            }
            report["transport_plane_errors"] = [
                {
                    "plane": i,
                    "max": float(delta[:, i * 16 : (i + 1) * 16].max()),
                    "mean": float(delta[:, i * 16 : (i + 1) * 16].mean()),
                }
                for i in range(26)
            ]
            report["solve_gl_error"] = gl.GetError()
            np.savez_compressed(args.output.with_suffix(".npz"), gpu=actual, cpu=expected)
            if args.images:
                start = time.perf_counter()
                irradiance, emitter = analysis.scene_images(
                    texture, source.size, solved["state"], solved["global_stats"]
                )
                wrap = analysis.wrap(texture, source.size)
                gl.Finish()
                report["images_cold_ms"] = (time.perf_counter() - start) * 1000
                start = time.perf_counter()
                irradiance, emitter = analysis.scene_images(
                    texture, source.size, solved["state"], solved["global_stats"]
                )
                wrap = analysis.wrap(texture, source.size)
                gl.Finish()
                report["images_warm_ms"] = (time.perf_counter() - start) * 1000
                image_errors = {}
                for name, tex, expected in (
                    ("irradiance", irradiance, reference_scene.irradiance),
                    ("emitter", emitter, reference_scene.emitter),
                    ("wrap", wrap, _wrap_map(args.source)),
                ):
                    device.bind_targets((tex,))
                    actual = np.empty((90, 160, 4), np.uint8)
                    gl.ReadPixels(
                        0, 0, 160, 90, 0x1908, 0x1401, ctypes.c_void_p(actual.ctypes.data)
                    )
                    if expected.shape[2] == 3:
                        actual = actual[..., :3]
                    delta = np.abs(actual.astype(float) - expected.astype(float))
                    image_errors[name] = {
                        "mean": float(delta.mean()),
                        "max": float(delta.max()),
                        "channels_over_1": int(np.count_nonzero(delta > 1)),
                    }
                    Image.fromarray(actual).save(
                        args.output.parent / (args.output.stem + "-" + name + "-gpu.png")
                    )
                    Image.fromarray(expected).save(
                        args.output.parent / (args.output.stem + "-" + name + "-cpu.png")
                    )
                report["image_errors"] = image_errors
                report["images_gl_error"] = gl.GetError()
    from scenelight.runtime.live_gpu import RG32F, RGBA32F

    report["resources"] = {
        "texture_mib": sum(
            width * height * {RGBA32F: 16, RG32F: 8}.get(storage, 4)
            for _texture, width, height, storage, _linear in device.targets.values()
        )
        / 2**20,
        "buffer_mib": sum(size for _buffer, size in device.buffers.values()) / 2**20,
        "program_count": len(device.programs),
        "target_count": len(device.targets),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    device.close()
    context.doneCurrent()
    app.quit()


if __name__ == "__main__":
    main()
