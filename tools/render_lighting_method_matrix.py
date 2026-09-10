"""Render reproducible production-GPU lighting method comparisons.

This tool is deliberately external to the player package. It exercises the
exact Preview/runtime shader and exact cached analysis products against real
backgrounds, then writes contact sheets plus palette-independent measurements.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.engine import _srgb_to_linear
from scenelight.preview.artifacts import ArtifactCache, FormArtifacts
from scenelight.preview.gpu_view import CANVAS_SIZE, SceneLightGPUView

DEFAULT_SCENES = (
    "sunlit_greenhouse.jpg",
    "foggy_park.jpg",
    "neon_alley.jpg",
    "night_station.jpg",
    "warm_bedroom.jpg",
    "blue_corridor.jpg",
    "school_corridor.jpg",
    "snowy_forest.jpg",
    "beach_sunset.jpg",
    "rainy_city.jpg",
    "prison.png",
    "simo-kettunen-hallway-01.jpg",
)


@dataclass(frozen=True, slots=True)
class Method:
    name: str
    strength: float
    calibration: Calibration


def _methods() -> tuple[Method, ...]:
    base = Calibration()
    # ``cinematic`` exactly reproduces the user-discovered state that won the
    # general evaluation: separated sources plus restrained strength, exposure,
    # and adaptation.
    decomposed = replace(
        base,
        auto_strength=0.88 * 0.72,
        exposure_bias=-0.22 * 0.72,
        color_adaptation=0.92,
        key_strength=0.82 * 0.72,
        ray_shadow_strength=0.58 * 0.72,
        ambient_occlusion=0.34 * 0.72,
        probe_strength=0.48 * 0.72,
        bounce_strength=0.32 * 0.72,
        specular_strength=0.24 * 0.72,
        rim_strength=0.64 * 0.72,
        wrap_strength=0.42 * 0.72,
        grain_match=0.52 * 0.72,
        shadow_strength=0.62 * 0.72,
        individual_light_colors=0.72,
    )
    return (
        Method("original", 1.0, base),
        Method("physical", 1.0, base),
        Method("separate_full", 1.0, replace(base, individual_light_colors=1.0)),
        Method(
            "cinematic",
            0.72,
            replace(
                base,
                exposure_bias=-0.22,
                color_adaptation=0.92,
                individual_light_colors=1.0,
            ),
        ),
        Method("decomposed_hybrid", 1.0, decomposed),
        Method(
            "filmic_physical",
            1.0,
            replace(
                base,
                auto_strength=0.68,
                exposure_bias=-0.10,
                color_adaptation=0.86,
                highlight_rolloff=1.28,
                key_strength=0.78,
                ray_shadow_strength=0.50,
                ambient_occlusion=0.28,
                probe_strength=0.52,
                bounce_strength=0.36,
                rim_strength=0.72,
                wrap_strength=0.45,
            ),
        ),
        Method(
            "filmic_hybrid",
            1.0,
            replace(
                base,
                auto_strength=0.68,
                exposure_bias=-0.10,
                color_adaptation=0.86,
                highlight_rolloff=1.28,
                key_strength=0.78,
                ray_shadow_strength=0.50,
                ambient_occlusion=0.28,
                probe_strength=0.52,
                bounce_strength=0.36,
                rim_strength=0.72,
                wrap_strength=0.45,
                individual_light_colors=0.62,
            ),
        ),
        Method(
            "restrained_accents",
            1.0,
            replace(
                base,
                exposure_bias=-0.12,
                color_adaptation=0.72,
                highlight_rolloff=1.32,
                key_strength=0.74,
                probe_strength=0.52,
                rim_strength=0.70,
                individual_light_colors=0.56,
            ),
        ),
    )


def _subject_mask(
    sprite: Image.Image,
    form: FormArtifacts,
    *,
    horizontal: float,
    baseline: float,
    character_height: float,
) -> np.ndarray:
    width, height = CANVAS_SIZE
    sprite_height = round(height * character_height)
    sprite_width = round(sprite_height * sprite.width / max(sprite.height, 1))
    center = form.metadata.get("center", (0.5, 0.5))
    x = round(horizontal * width - float(center[0]) * sprite_width)
    y = round(baseline * height - sprite_height)
    alpha = np.asarray(
        sprite.getchannel("A").resize((sprite_width, sprite_height), Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )
    mask = np.zeros((height, width), dtype=bool)
    target_x0, target_y0 = max(0, x), max(0, y)
    target_x1, target_y1 = min(width, x + sprite_width), min(height, y + sprite_height)
    if target_x0 >= target_x1 or target_y0 >= target_y1:
        return mask
    source_x0, source_y0 = target_x0 - x, target_y0 - y
    source = alpha[
        source_y0 : source_y0 + target_y1 - target_y0,
        source_x0 : source_x0 + target_x1 - target_x0,
    ]
    mask[target_y0:target_y1, target_x0:target_x1] = source > 12
    return mask


def _linear_luma(rgb_u8: np.ndarray) -> np.ndarray:
    linear = _srgb_to_linear(rgb_u8.astype(np.float32) / 255.0)
    return np.sum(linear * np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32), axis=2)


def _detail_correlation(reference: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> float:
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY).astype(np.float32)
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY).astype(np.float32)
    reference_edge = cv2.magnitude(
        cv2.Sobel(reference_gray, cv2.CV_32F, 1, 0),
        cv2.Sobel(reference_gray, cv2.CV_32F, 0, 1),
    )[mask]
    candidate_edge = cv2.magnitude(
        cv2.Sobel(candidate_gray, cv2.CV_32F, 1, 0),
        cv2.Sobel(candidate_gray, cv2.CV_32F, 0, 1),
    )[mask]
    if reference_edge.size < 2 or np.std(reference_edge) < 1e-6 or np.std(candidate_edge) < 1e-6:
        return 1.0
    return float(np.corrcoef(reference_edge, candidate_edge)[0, 1])


def _frame_metrics(
    frame: np.ndarray,
    *,
    original: np.ndarray,
    physical: np.ndarray,
    mask: np.ndarray,
) -> dict[str, float | int]:
    rgb = frame[..., :3]
    subject = rgb[mask]
    luma = _linear_luma(rgb)[mask]
    saturation = (subject.max(axis=1) - subject.min(axis=1)).astype(np.float32) / 255.0
    ys, xs = np.nonzero(mask)
    split = float(np.median(xs)) if xs.size else CANVAS_SIZE[0] * 0.5
    left = mask & (np.indices(mask.shape)[1] < split)
    right = mask & ~left

    def unit_chroma(values: np.ndarray) -> np.ndarray:
        mean = values.astype(np.float32).mean(axis=0) / 255.0
        return mean / max(float(mean.mean()), 1e-6)

    left_chroma = unit_chroma(rgb[left])
    right_chroma = unit_chroma(rgb[right])
    delta_physical = np.abs(rgb.astype(np.int16) - physical[..., :3].astype(np.int16))
    delta_original = np.abs(rgb.astype(np.int16) - original[..., :3].astype(np.int16))
    outside = ~cv2.dilate(mask.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)
    return {
        "subject_pixels": int(mask.sum()),
        "linear_luma_p10": float(np.quantile(luma, 0.10)),
        "linear_luma_median": float(np.quantile(luma, 0.50)),
        "linear_luma_p90": float(np.quantile(luma, 0.90)),
        "near_clip_fraction": float((subject.max(axis=1) >= 252).mean()),
        "near_black_fraction": float((subject.max(axis=1) <= 3).mean()),
        "mean_srgb_saturation": float(saturation.mean()),
        "left_right_chroma_distance": float(np.linalg.norm(left_chroma - right_chroma)),
        "mean_abs_from_physical": float(delta_physical[mask].mean()),
        "mean_abs_from_original": float(delta_original[mask].mean()),
        "outside_subject_max_from_physical": int(delta_physical[outside].max()),
        "detail_correlation_to_original": _detail_correlation(original[..., :3], rgb, mask),
    }


def _labeled(frame: np.ndarray, label: str, size: tuple[int, int]) -> Image.Image:
    image = Image.fromarray(frame, "RGBA").resize(size, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 25), fill=(0, 0, 0, 210))
    draw.text((8, 7), label, fill="white")
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backgrounds", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--scenes", nargs="*")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    if args.all:
        scenes = sorted(
            path
            for path in args.backgrounds.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
    else:
        names = tuple(args.scenes or DEFAULT_SCENES)
        scenes = [args.backgrounds / name for name in names]
    missing = [str(path) for path in scenes if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing lighting matrix scene(s): " + ", ".join(missing))

    methods = _methods()
    cache = ArtifactCache()
    form = cache.form(args.sprite)
    with Image.open(args.sprite) as opened:
        sprite = opened.convert("RGBA")
        sprite.load()
    horizontal, baseline, character_height = 0.50, 1.04, 0.82
    mask = _subject_mask(
        sprite,
        form,
        horizontal=horizontal,
        baseline=baseline,
        character_height=character_height,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    view = SceneLightGPUView()
    view.resize(*CANVAS_SIZE)
    view.move(-10000, -10000)
    view.show()
    app.processEvents()
    view.set_sprite(args.sprite, form)
    view.set_placement(horizontal, baseline, character_height)
    app.processEvents()

    report: dict[str, object] = {
        "backgrounds": str(args.backgrounds.resolve()),
        "sprite": str(args.sprite.resolve()),
        "shader_sha256": view.shader_sha256,
        "methods": [
            {
                "name": method.name,
                "strength": method.strength,
                "calibration": asdict(method.calibration),
            }
            for method in methods
        ],
        "scenes": [],
    }
    overview_rows: list[Image.Image] = []
    for scene_index, scene_path in enumerate(scenes, start=1):
        artifacts = cache.scene(scene_path)
        view.set_scene(scene_path, artifacts)
        app.processEvents()
        frames: dict[str, np.ndarray] = {}
        for method in methods:
            view.set_strength(method.strength)
            view.set_calibration(method.calibration)
            view.set_compare_mode(1 if method.name == "original" else 0)
            app.processEvents()
            frames[method.name] = view.render_rgba(CANVAS_SIZE)

        scene_root = args.output / f"{scene_index:02d}_{scene_path.stem}"
        scene_root.mkdir(parents=True, exist_ok=True)
        for name, frame in frames.items():
            Image.fromarray(frame, "RGBA").save(scene_root / f"{name}.png", compress_level=1)

        cell_size = (384, 216)
        row = Image.new("RGBA", (cell_size[0] * len(methods), cell_size[1]), "black")
        for index, method in enumerate(methods):
            row.alpha_composite(
                _labeled(frames[method.name], method.name, cell_size), (index * cell_size[0], 0)
            )
        row.save(scene_root / "comparison.png", compress_level=1)
        overview_rows.append(
            row.resize(
                (cell_size[0] * len(methods) // 2, cell_size[1] // 2), Image.Resampling.LANCZOS
            )
        )

        original = frames["original"]
        physical = frames["physical"]
        report["scenes"].append(
            {
                "scene": scene_path.name,
                "scene_cached": artifacts.cached,
                "scene_build_seconds": artifacts.build_seconds,
                "analysis": artifacts.metadata,
                "metrics": {
                    name: _frame_metrics(
                        frame,
                        original=original,
                        physical=physical,
                        mask=mask,
                    )
                    for name, frame in frames.items()
                },
            }
        )
        print(f"lighting matrix {scene_index}/{len(scenes)}: {scene_path.name}", flush=True)

    overview_width = max(row.width for row in overview_rows)
    overview = Image.new(
        "RGBA", (overview_width, sum(row.height for row in overview_rows)), "black"
    )
    y = 0
    for row in overview_rows:
        overview.alpha_composite(row, (0, y))
        y += row.height
    overview.save(args.output / "overview.png", compress_level=1)
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    view.close()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_OPENGL", "desktop")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    raise SystemExit(main())
