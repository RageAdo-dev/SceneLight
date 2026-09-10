"""Measure exact sprite-map throughput across worker counts on a target PC."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from scenelight.form_maps import build_sprite_form_maps


def _initialize_worker() -> None:
    import cv2

    cv2.setNumThreads(1)


def _render(job: tuple[str, str]) -> None:
    source_text, output_text = job
    with Image.open(source_text) as opened:
        sprite = opened.convert("RGBA")
        sprite.load()
    maps = build_sprite_form_maps(sprite)
    output = Path(output_text)
    maps.normal_noise.save(output.with_suffix(".normal.png"), compress_level=1)
    maps.height_ao_edge.save(output.with_suffix(".surface.png"), compress_level=1)
    maps.response.save(output.with_suffix(".response.png"), compress_level=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--forms", type=int, default=48)
    parser.add_argument("--workers", default="1,2,3,4")
    args = parser.parse_args()
    project = args.project.resolve()
    capture = json.loads((project / ".scenelight_cache/capture_result.json").read_text())
    sources = [project / value for _, value in sorted(capture["sprites"].items())[: args.forms]]
    # Each process owns one core. Prevent OpenCV/OpenBLAS inside every process
    # from each creating another full-machine pool and oversubscribing laptops.
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    results: list[dict[str, float | int]] = []
    with tempfile.TemporaryDirectory(prefix="scenelight-worker-benchmark-") as temporary:
        root = Path(temporary)
        for workers in [int(value) for value in args.workers.split(",")]:
            output = root / str(workers)
            output.mkdir()
            jobs = [
                (str(source), str(output / f"form-{index}")) for index, source in enumerate(sources)
            ]
            started = time.perf_counter()
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_initialize_worker,
            ) as executor:
                list(executor.map(_render, jobs, chunksize=1))
            elapsed = time.perf_counter() - started
            results.append(
                {
                    "workers": workers,
                    "forms": len(jobs),
                    "seconds": elapsed,
                    "forms_per_second": len(jobs) / elapsed,
                }
            )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
