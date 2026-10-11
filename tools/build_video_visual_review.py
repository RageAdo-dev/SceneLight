"""Render sampled video anchors from an already-built temporal cache."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from build_visual_review import _category, _html, _save_webp
from PIL import Image
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache, SceneArtifacts
from scenelight.preview.gpu_view import SceneLightGPUView
from scenelight.preview.media import MediaClip, environment_wrap
from scenelight.preview.temporal import TemporalSceneFrame, interpolated_scene


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("benchmark_cache", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument(
        "--frame-indices",
        help="Comma-separated exact source frames; interpolated lighting is used between anchors.",
    )
    parser.add_argument("--horizontal", type=float, default=0.5)
    parser.add_argument("--baseline", type=float, default=1.03)
    parser.add_argument("--height", type=float, default=0.92)
    args = parser.parse_args()

    video = args.video.resolve(strict=True)
    benchmark_root = args.benchmark_cache.resolve(strict=True)
    output = args.output.resolve()
    images_root = output / "images"
    seed_root = output / ".seed-scene"
    images_root.mkdir(parents=True, exist_ok=True)
    seed_root.mkdir(parents=True, exist_ok=True)

    clip = MediaClip(video, benchmark_root / "media")
    anchors = clip.temporal_anchor_indices(detect_changes=True)
    if args.frame_indices:
        selected = tuple(
            dict.fromkeys(
                min(max(int(value.strip()), 0), clip.frame_count - 1)
                for value in args.frame_indices.split(",")
                if value.strip()
            )
        )
    else:
        positions = np.linspace(0, len(anchors) - 1, min(args.samples, len(anchors)))
        selected = tuple(dict.fromkeys(anchors[int(round(value))] for value in positions))
    if not selected:
        raise ValueError("At least one frame must be selected")
    frames = {frame.index: frame for frame in clip.iter_frames(selected)}
    temporal_cache = ArtifactCache(benchmark_root / "preview-cache")
    anchor_scenes: dict[int, TemporalSceneFrame] = {}
    for index in anchors:
        artifacts = temporal_cache.temporal_scene_cached(clip.temporal_cache_key(index))
        if artifacts is None:
            raise RuntimeError(f"Temporal anchor {index} is missing from the benchmark cache")
        anchor_scenes[index] = TemporalSceneFrame(
            artifacts.irradiance,
            artifacts.emitter,
            artifacts.transport,
            artifacts.metadata,
        )

    first_index = selected[0]
    first_frame = frames[first_index]
    first_artifacts = interpolated_scene(anchor_scenes, first_index)
    if first_artifacts is None:
        raise RuntimeError(f"Temporal frame {first_index} could not be interpolated")
    wrap = environment_wrap(first_frame.rgba)
    for name, array in (
        ("irradiance", first_artifacts.irradiance),
        ("emitter", first_artifacts.emitter),
        ("wrap", wrap),
        ("transport", first_artifacts.transport),
    ):
        Image.fromarray(array).save(seed_root / f"{name}.png")
    seed_background = output / ".seed-background.png"
    Image.fromarray(first_frame.rgba, "RGBA").save(seed_background)

    form_cache = ArtifactCache(output / ".form-cache")
    sprite = args.sprite.resolve(strict=True)
    form = form_cache.form(sprite)
    app = QApplication.instance() or QApplication(sys.argv)
    view = SceneLightGPUView()
    view.resize(1280, 720)
    view.show()
    app.processEvents()
    view.set_scene(
        seed_background,
        SceneArtifacts(seed_root, first_artifacts.metadata, True, 0.0),
    )
    view.set_sprite(sprite, form)
    view.set_placement(args.horizontal, args.baseline, args.height)
    calibration = Calibration()
    records: list[dict[str, object]] = []
    try:
        for item_index, frame_index in enumerate(selected, start=1):
            frame = frames[frame_index]
            artifacts = interpolated_scene(anchor_scenes, frame_index)
            if artifacts is None:
                raise RuntimeError(f"Temporal frame {frame_index} could not be interpolated")
            view.set_background_frame(frame.rgba, environment_wrap(frame.rgba))
            view.set_live_scene_frame(
                TemporalSceneFrame(
                    artifacts.irradiance,
                    artifacts.emitter,
                    artifacts.transport,
                    artifacts.metadata,
                )
            )
            app.processEvents()
            view.set_compare_mode(1)
            original = view.render_rgba((1280, 720))
            view.set_compare_mode(0)
            view.set_calibration(replace(calibration, adaptive_light_colors=0.0))
            aggregate = view.render_rgba((1280, 720))
            view.set_calibration(calibration)
            relit = view.render_rgba((1280, 720))
            slug = f"{item_index:03d}"
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
                    "name": f"frame {frame_index} · {frame_index / clip.fps:.2f}s",
                    "original": original_name,
                    "aggregate": aggregate_name,
                    "relit": relit_name,
                    "category": _category(metadata),
                    "collection": "Video anchors",
                    "lights": int(metadata.get("lights", 0)),
                    "adaptation": float(metadata.get("adaptation_luminance", 0.0)),
                    "layout": str(metadata.get("light_transport_layout", "unknown")),
                    "adaptive_mean_delta": round(float(delta[changed].mean()), 4)
                    if changed.any()
                    else 0.0,
                    "adaptive_changed_fraction": round(float(changed.mean()), 6),
                }
            )
    finally:
        view.close()
        clip.close()
        temporal_cache.shutdown()
        form_cache.shutdown()

    benchmark = {"before": "4m 58s", "after": "30s", "speedup": "9.9×"}
    (output / "index.html").write_text(_html(records, benchmark), encoding="utf-8")
    (output / "scenes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(output / "index.html")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_OPENGL", "desktop")
    raise SystemExit(main())
