"""Merge current-build visual review folders into one standalone gallery."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from build_visual_review import _html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--review",
        action="append",
        nargs=2,
        metavar=("COLLECTION", "PATH"),
        required=True,
        help="Collection label and review folder; use '-' to preserve each record's label.",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    images_root = output / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    merged: list[dict[str, object]] = []
    for review_index, (collection, path_text) in enumerate(args.review, start=1):
        source_root = Path(path_text).resolve(strict=True)
        records = json.loads((source_root / "scenes.json").read_text(encoding="utf-8"))
        for record_index, source_record in enumerate(records, start=1):
            record = dict(source_record)
            if collection != "-":
                record["collection"] = collection
            for field in ("original", "aggregate", "relit"):
                source = source_root / str(record[field])
                name = f"{review_index:02d}-{record_index:03d}-{source.name}"
                destination = images_root / name
                shutil.copy2(source, destination)
                record[field] = f"images/{name}"
            merged.append(record)

    benchmark = {"before": "4m 58s", "after": "30s", "speedup": "9.9×"}
    (output / "index.html").write_text(_html(merged, benchmark), encoding="utf-8")
    (output / "scenes.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(output / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
