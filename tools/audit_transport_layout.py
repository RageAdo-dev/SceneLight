"""Find scene caches whose transport planes change semantic layout spatially."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

TRANSPORT_PLANES = 26
LIGHT_BASE = 3
LIGHT_STRIDE = 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cache_root = args.cache_root.resolve(strict=True)

    mixed_records: list[dict[str, object]] = []
    metadata_mismatches: list[dict[str, object]] = []
    metadata_paths = sorted(cache_root.rglob("metadata.json"))
    for metadata_path in metadata_paths:
        transport_path = metadata_path.parent / "transport.png"
        if not transport_path.is_file():
            continue
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        strip = np.asarray(Image.open(transport_path).convert("RGBA"))
        if strip.shape[1] % TRANSPORT_PLANES:
            mixed_records.append(
                {
                    "source": str(payload.get("source", metadata_path.parent)),
                    "error": f"invalid transport width {strip.shape[1]}",
                }
            )
            continue
        planes = strip.reshape(
            strip.shape[0],
            TRANSPORT_PLANES,
            strip.shape[1] // TRANSPORT_PLANES,
            4,
        )
        physical = np.zeros((planes.shape[0], planes.shape[2]), dtype=bool)
        creative = np.zeros_like(physical)
        for light_index in range(1, 4):
            scalar_plane = LIGHT_BASE + light_index * LIGHT_STRIDE + 2
            scalar = planes[:, scalar_plane, :, :3]
            physical |= scalar[..., 0] > 2
            creative |= (scalar[..., 0] <= 2) & (scalar[..., 2] > 2)
        if physical.any() and creative.any():
            mixed_records.append(
                {
                    "source": str(payload.get("source", metadata_path.parent)),
                    "physical_cells": int(physical.sum()),
                    "creative_cells": int(creative.sum()),
                    "metadata_layout": payload.get("scene", {}).get("light_transport_layout"),
                }
            )
        actual_layout = "physical-rgb-families-v1" if creative.any() else "physical-components-v1"
        metadata_layout = payload.get("scene", {}).get("light_transport_layout")
        if metadata_layout != actual_layout:
            metadata_mismatches.append(
                {
                    "source": str(payload.get("source") or payload.get("cache_key")),
                    "actual_layout": actual_layout,
                    "metadata_layout": metadata_layout,
                }
            )

    report = {
        "scene_caches": len(metadata_paths),
        "mixed_layout_scenes": len(mixed_records),
        "metadata_layout_mismatches": len(metadata_mismatches),
        "mixed_records": mixed_records,
        "metadata_mismatches": metadata_mismatches,
        "passed": not mixed_records and not metadata_mismatches,
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
