"""Render a visual review directly from the current analyzer and GPU shader."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from build_visual_review import _category, _html, _save_webp
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneLightGPUView


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_result", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scene-names")
    parser.add_argument("--reference-source", action="append", type=Path, default=[])
    parser.add_argument("--horizontal", type=float, default=0.5)
    parser.add_argument("--baseline", type=float, default=1.03)
    parser.add_argument("--height", type=float, default=0.92)
    args = parser.parse_args()

    capture_path = args.capture_result.resolve(strict=True)
    project_root = capture_path.parents[1]
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    captured = capture["scenes"]
    selected_names = None
    if args.scene_names:
        selected_names = {item.strip() for item in args.scene_names.split(",") if item.strip()}
        missing = selected_names - captured.keys()
        if missing:
            raise ValueError(f"Unknown captured scenes: {', '.join(sorted(missing))}")
    scenes = [
        (name, (project_root / relative).resolve(strict=True), "Interaction")
        for name, relative in sorted(captured.items())
        if selected_names is None or name in selected_names
    ]
    scenes.extend(
        (path.stem.replace("_", " "), path.resolve(strict=True), "Reference backgrounds")
        for path in args.reference_source
    )
    if not scenes:
        raise ValueError("No scenes were selected")

    output = args.output.resolve()
    images_root = output / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    sprite = args.sprite.resolve(strict=True)
    cache = ArtifactCache(output / ".preview-cache")
    form = cache.form(sprite)
    app = QApplication.instance() or QApplication(sys.argv)
    view = SceneLightGPUView()
    view.resize(1280, 720)
    view.show()
    app.processEvents()
    view.set_sprite(sprite, form)
    view.set_placement(args.horizontal, args.baseline, args.height)
    calibration = Calibration()
    view.set_calibration(calibration)

    records: list[dict[str, object]] = []
    try:
        for index, (scene_name, background, collection) in enumerate(scenes, start=1):
            artifacts = cache.scene(background)
            view.set_scene(background, artifacts)
            app.processEvents()
            view.set_compare_mode(1)
            original = view.render_rgba((1280, 720))
            view.set_compare_mode(0)
            view.set_calibration(replace(calibration, adaptive_light_colors=0.0))
            aggregate = view.render_rgba((1280, 720))
            view.set_calibration(calibration)
            relit = view.render_rgba((1280, 720))
            slug = f"{index:03d}"
            original_name = f"images/{slug}-original.webp"
            aggregate_name = f"images/{slug}-aggregate.webp"
            relit_name = f"images/{slug}-relit.webp"
            _save_webp(original, output / original_name)
            _save_webp(aggregate, output / aggregate_name)
            _save_webp(relit, output / relit_name)
            delta = np.abs(relit[..., :3].astype(np.int16) - aggregate[..., :3].astype(np.int16))
            changed = np.any(delta > 0, axis=2)
            metadata = artifacts.metadata
            records.append(
                {
                    "name": scene_name,
                    "original": original_name,
                    "aggregate": aggregate_name,
                    "relit": relit_name,
                    "category": _category(metadata),
                    "collection": collection,
                    "lights": int(metadata.get("lights", 0)),
                    "adaptation": float(metadata.get("adaptation_luminance", 0.0)),
                    "layout": str(metadata.get("light_transport_layout", "unknown")),
                    "analysis_seconds": round(float(artifacts.build_seconds), 3),
                    "adaptive_mean_delta": round(float(delta[changed].mean()), 4)
                    if changed.any()
                    else 0.0,
                    "adaptive_changed_fraction": round(float(changed.mean()), 6),
                }
            )
            print(
                f"rendered {index}/{len(scenes)}: {collection} / {scene_name} "
                f"({artifacts.build_seconds:.2f}s)",
                flush=True,
            )
    finally:
        view.close()
        cache.shutdown()

    benchmark = {"before": "4m 58s", "after": "30s", "speedup": "9.9×"}
    (output / "index.html").write_text(_html(records, benchmark), encoding="utf-8")
    (output / "scenes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(output / "index.html")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_OPENGL", "desktop")
    raise SystemExit(main())
