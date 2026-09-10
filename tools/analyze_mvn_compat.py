"""Quantify an external MVN/SceneLight renderer compatibility capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

PAIRS = {
    "scenelight_plain": ("01_plain_scenelight_off", "02_plain_scenelight_on"),
    "mvn_outer_without_scenelight": (
        "01_plain_scenelight_off",
        "03_outer_mvn_scenelight_off",
    ),
    "mvn_outer_with_scenelight": (
        "02_plain_scenelight_on",
        "04_outer_mvn_scenelight_on",
    ),
    "scenelight_through_outer_mvn": (
        "03_outer_mvn_scenelight_off",
        "04_outer_mvn_scenelight_on",
    ),
    "mvn_lighting_without_scenelight": (
        "01_plain_scenelight_off",
        "05_mvn_light_scenelight_off",
    ),
    "mvn_lighting_with_scenelight": (
        "02_plain_scenelight_on",
        "06_mvn_light_scenelight_on",
    ),
    "scenelight_through_inner_mvn": (
        "07_inner_mvn_scenelight_off",
        "08_inner_mvn_scenelight_on",
    ),
    "mvn_animation_advances": ("09_animated_mvn_early", "10_animated_mvn_late"),
    "mvn_and_atl_movement_advance": ("11_mvn_moving_left", "12_mvn_moving_right"),
}


def load_capture(root: Path, name: str) -> np.ndarray:
    return np.asarray(Image.open(root / f"{name}.png").convert("RGB"), dtype=np.int16)


def difference(left: np.ndarray, right: np.ndarray) -> dict[str, float | int]:
    delta = np.abs(left - right)
    changed = np.any(delta > 2, axis=2)
    return {
        "changed_pixels": int(np.count_nonzero(changed)),
        "changed_fraction": round(float(np.mean(changed)), 6),
        "mean_channel_delta": round(float(np.mean(delta)), 6),
        "maximum_channel_delta": int(np.max(delta)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", type=Path)
    arguments = parser.parse_args()
    captures = arguments.captures.resolve()
    images = {name: load_capture(captures, name) for names in PAIRS.values() for name in names}
    dimensions = next(iter(images.values())).shape
    if any(image.shape != dimensions for image in images.values()):
        raise ValueError("MVN compatibility captures do not share one size")

    height, width = dimensions[:2]
    badge_box = (
        slice(max(0, int(height * 0.015)), min(height, int(height * 0.095))),
        slice(max(0, int(width * 0.755)), min(width, int(width * 0.99))),
    )
    badge_reference = images["01_plain_scenelight_off"][badge_box]
    badge_stable = all(
        np.array_equal(badge_reference, image[badge_box]) for image in images.values()
    )
    metrics = {
        label: difference(images[left], images[right]) for label, (left, right) in PAIRS.items()
    }
    minimum_effect_pixels = max(100, int(width * height * 0.0001))
    all_effects_visible = all(
        result["changed_pixels"] >= minimum_effect_pixels for result in metrics.values()
    )
    payload = {
        "size": [width, height],
        "badge_stable": badge_stable,
        "minimum_effect_pixels": minimum_effect_pixels,
        "all_effects_visible": all_effects_visible,
        "comparisons": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0 if badge_stable and all_effects_visible else 1


if __name__ == "__main__":
    raise SystemExit(main())
