"""Time the exact decode, surface-map, and PNG-write stages for one form."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from PIL import Image

from scenelight.form_maps import build_sprite_form_maps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--form", default="monika 1b")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    project = args.project.resolve()
    capture = json.loads((project / ".scenelight_cache/capture_result.json").read_text())
    source_path = project / capture["sprites"][args.form]
    results: list[dict[str, float]] = []
    with tempfile.TemporaryDirectory(prefix="scenelight-form-profile-") as temporary:
        output = Path(temporary)
        for index in range(max(1, args.runs)):
            started = time.perf_counter()
            with Image.open(source_path) as opened:
                sprite = opened.convert("RGBA")
                sprite.load()
            decoded = time.perf_counter()
            maps = build_sprite_form_maps(sprite)
            generated = time.perf_counter()
            maps.normal_noise.save(output / f"{index}-normal.png", compress_level=1)
            maps.height_ao_edge.save(output / f"{index}-surface.png", compress_level=1)
            maps.response.save(output / f"{index}-response.png", compress_level=1)
            saved = time.perf_counter()
            results.append(
                {
                    "decode_seconds": decoded - started,
                    "map_seconds": generated - decoded,
                    "save_seconds": saved - generated,
                    "total_seconds": saved - started,
                }
            )
    print(json.dumps({"form": args.form, "runs": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
