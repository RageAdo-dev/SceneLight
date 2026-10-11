"""Render a controlled production-shader comparison for creative light color."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneLightGPUView


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("background", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--horizontal", type=float, default=0.69)
    parser.add_argument("--baseline", type=float, default=1.06)
    parser.add_argument("--height", type=float, default=0.92)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    cache = ArtifactCache()
    scene = cache.scene(args.background)
    form = cache.form(args.sprite)

    app = QApplication.instance() or QApplication(sys.argv)
    view = SceneLightGPUView()
    view.resize(1280, 720)
    view.show()
    app.processEvents()
    view.set_scene(args.background, scene)
    view.set_sprite(args.sprite, form)
    view.set_placement(args.horizontal, args.baseline, args.height)
    app.processEvents()

    base = Calibration()
    cases = (
        ("aggregate", replace(base, adaptive_light_colors=0.0)),
        ("adaptive", base),
        ("forced", replace(base, individual_light_colors=1.0)),
    )
    frames: list[np.ndarray] = []
    for name, calibration in cases:
        view.set_calibration(calibration)
        app.processEvents()
        frame = view.render_rgba((1280, 720))
        frames.append(frame)
        Image.fromarray(frame, "RGBA").save(args.output / f"{name}.png")

    labeled: list[Image.Image] = []
    for (name, _calibration), frame in zip(cases, frames, strict=True):
        image = Image.fromarray(frame, "RGBA").resize((640, 360), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 152, 28), fill=(0, 0, 0, 205))
        draw.text((10, 8), name, fill="white")
        labeled.append(image)
    comparison = Image.new("RGBA", (1920, 360), "black")
    for index, image in enumerate(labeled):
        comparison.alpha_composite(image, (index * 640, 0))
    comparison.save(args.output / "comparison.png")

    metrics: dict[str, object] = {
        "background": str(args.background.resolve()),
        "sprite": str(args.sprite.resolve()),
        "scene_cached": scene.cached,
        "scene_build_seconds": scene.build_seconds,
        "scene_metadata": scene.metadata,
        "comparisons": {},
    }
    reference = frames[0][..., :3].astype(np.int16)
    for (name, _calibration), frame in zip(cases[1:], frames[1:], strict=True):
        delta = np.abs(frame[..., :3].astype(np.int16) - reference)
        changed = np.any(delta > 0, axis=2)
        metrics["comparisons"][name] = {
            "mean_abs_rgb_full_frame": float(delta.mean()),
            "mean_abs_rgb_changed_pixels": float(delta[changed].mean()) if changed.any() else 0.0,
            "changed_pixel_fraction": float(changed.mean()),
            "max_channel_delta": int(delta.max()),
        }
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    view.close()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_OPENGL", "desktop")
    raise SystemExit(main())
