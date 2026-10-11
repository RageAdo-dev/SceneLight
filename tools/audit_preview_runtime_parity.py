"""Compare independently built Preview artifacts with installed runtime atlas tiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _preview_entry(cache_root: Path, scene_name: str) -> tuple[Path, dict[str, object]]:
    prefix = f"scene_bg_{scene_name}_"
    for metadata_path in cache_root.rglob("metadata.json"):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        source = Path(str(payload.get("source", "")))
        if source.stem.casefold().startswith(prefix.casefold()):
            return metadata_path.parent, payload["scene"]
    raise FileNotFoundError(f"No Preview cache entry found for {scene_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("preview_cache", type=Path)
    parser.add_argument("scene_names", nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve(strict=True)
    preview_cache = args.preview_cache.resolve(strict=True)
    manifest = json.loads((runtime_root / "manifest.json").read_text(encoding="utf-8"))
    atlas = manifest["atlas"]
    transport_atlas = manifest["transport_atlas"]
    tile_width, tile_height = atlas["tile_size"]
    grid_width, grid_height = transport_atlas["grid_size"]
    transport_width = grid_width * transport_atlas["planes"]
    irradiance_atlas = np.asarray(
        Image.open(runtime_root / Path(atlas["irradiance"]).name).convert("RGBA")
    )
    emitter_atlas = np.asarray(
        Image.open(runtime_root / Path(atlas["emitter"]).name).convert("RGBA")
    )
    wrap_atlas = np.asarray(Image.open(runtime_root / Path(atlas["wrap"]).name).convert("RGB"))
    transport_image = np.asarray(
        Image.open(runtime_root / Path(transport_atlas["texture"]).name).convert("RGBA")
    )

    records: list[dict[str, object]] = []
    for scene_name in args.scene_names:
        preview_root, preview_metadata = _preview_entry(preview_cache, scene_name)
        runtime_scene = manifest["scenes"][scene_name]
        column, row = runtime_scene["tile"]
        x0, y0 = column * tile_width, row * tile_height
        tx0, ty0 = column * transport_width, row * grid_height
        comparisons = {
            "irradiance": (
                np.asarray(Image.open(preview_root / "irradiance.png").convert("RGBA")),
                irradiance_atlas[y0 : y0 + tile_height, x0 : x0 + tile_width],
            ),
            "emitter": (
                np.asarray(Image.open(preview_root / "emitter.png").convert("RGBA")),
                emitter_atlas[y0 : y0 + tile_height, x0 : x0 + tile_width],
            ),
            "wrap": (
                np.asarray(Image.open(preview_root / "wrap.png").convert("RGB")),
                wrap_atlas[y0 : y0 + tile_height, x0 : x0 + tile_width],
            ),
            "transport": (
                np.asarray(Image.open(preview_root / "transport.png").convert("RGBA")),
                transport_image[ty0 : ty0 + grid_height, tx0 : tx0 + transport_width],
            ),
        }
        textures = {
            name: {
                "preview_sha256": _digest(left),
                "runtime_sha256": _digest(right),
                "equal": bool(np.array_equal(left, right)),
            }
            for name, (left, right) in comparisons.items()
        }
        metadata_equal = all(
            runtime_scene.get(key) == value for key, value in preview_metadata.items()
        )
        records.append(
            {
                "scene": scene_name,
                "textures": textures,
                "metadata_equal": metadata_equal,
                "passed": metadata_equal and all(item["equal"] for item in textures.values()),
            }
        )

    report = {
        "scenes": records,
        "passed": all(record["passed"] for record in records),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
