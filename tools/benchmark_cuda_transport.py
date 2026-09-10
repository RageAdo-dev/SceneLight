"""Benchmark SceneLight's production CUDA transport pipeline.

This intentionally exercises the same cross-background CPU/GPU overlap used
by ``build_project``. It does not use provisional transport or reduced grids.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scenelight.builder import (  # noqa: E402
    TRANSPORT_CHARACTER_HEIGHT,
    TRANSPORT_GRID_SIZE,
    TRANSPORT_SUBJECT_Y_MAX,
    _analysis_shape_for_path,
    _transport_maps_cuda,
)
from scenelight.cuda_backend import (  # noqa: E402
    SharedPreparedSceneInfo,
    allocate_shared_prepared_buffer,
    cuda_available,
    cuda_device_name,
    detect_transport_bundle_path,
    initialize_component_worker,
    materialize_shared_prepared_scene,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("backgrounds", type=Path)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    return parser


def _source_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    paths = sorted(path for path in root.iterdir() if path.suffix.lower() in suffixes)
    if not paths:
        raise ValueError(f"No backgrounds found in {root}")
    return paths


def main() -> int:
    args = _parser().parse_args()
    if not cuda_available():
        raise RuntimeError("CUDA/CuPy is not available")
    originals = _source_paths(args.backgrounds.resolve())
    count = args.count or len(originals)
    paths = [originals[index % len(originals)] for index in range(count)]
    grouped: dict[tuple[int, int], list[tuple[int, Path]]] = defaultdict(list)
    for index, path in enumerate(paths):
        grouped[_analysis_shape_for_path(path)].append((index, path))

    started = time.perf_counter()
    completed = 0
    cuda_seconds = 0.0
    process_workers = min(args.workers, count)
    with ProcessPoolExecutor(
        max_workers=process_workers,
        initializer=initialize_component_worker,
    ) as executor:
        ordered_entries = [entry for shape in sorted(grouped) for entry in grouped[shape]]
        window = min(count, process_workers * 3)
        allocations = {}

        def submit_bundle(index: int, path: Path):
            allocation = allocate_shared_prepared_buffer(
                _analysis_shape_for_path(path),
                TRANSPORT_CHARACTER_HEIGHT,
            )
            allocations[index] = allocation
            return executor.submit(
                detect_transport_bundle_path,
                str(path),
                grid_size=TRANSPORT_GRID_SIZE,
                subject_y_max=TRANSPORT_SUBJECT_Y_MAX,
                character_height=TRANSPORT_CHARACTER_HEIGHT,
                crop_components=True,
                prepared_buffer=allocation.spec,
            )

        bundle_futures = {
            index: submit_bundle(index, path) for index, path in ordered_entries[:window]
        }
        submit_index = window
        placeholder = Image.new("RGB", (1, 1))
        for _shape, entries in sorted(grouped.items()):
            print(
                f"shape {_shape[1]}x{_shape[0]}: waiting for {len(entries)} exact "
                "component result(s)",
                flush=True,
            )
            for index, path in entries:
                bundle = bundle_futures.pop(index).result()
                if submit_index < len(ordered_entries):
                    next_id, next_path = ordered_entries[submit_index]
                    submit_index += 1
                    bundle_futures[next_id] = submit_bundle(
                        next_id,
                        next_path,
                    )
                allocation = allocations.pop(index)
                prepared = None
                try:
                    assert isinstance(bundle.prepared, SharedPreparedSceneInfo)
                    prepared = materialize_shared_prepared_scene(
                        bundle.prepared,
                        allocation,
                    )
                    cuda_started = time.perf_counter()
                    _transport_maps_cuda(
                        f"bench_{index}",
                        str(path),
                        source_components=bundle.components,
                        prepared_source=(placeholder, prepared),
                    )
                    cuda_seconds += time.perf_counter() - cuda_started
                finally:
                    if prepared is not None:
                        del prepared
                    allocation.close()
                completed += 1
                if completed % 5 == 0 or completed == count:
                    elapsed = time.perf_counter() - started
                    print(
                        f"{completed}/{count} backgrounds in {elapsed:.2f}s "
                        f"({completed / elapsed:.2f}/s; CUDA path average "
                        f"{cuda_seconds / completed:.3f}s)",
                        flush=True,
                    )
        for allocation in allocations.values():
            allocation.close()

    elapsed = time.perf_counter() - started
    projected_700 = elapsed / count * 700
    print(
        json.dumps(
            {
                "backend": "cuda-exact-components-single-prepare",
                "device": cuda_device_name(),
                "grid": list(TRANSPORT_GRID_SIZE),
                "backgrounds": count,
                "source_variety": len(originals),
                "analysis_shapes": len(grouped),
                "workers": min(args.workers, count),
                "seconds": round(elapsed, 4),
                "cuda_path_seconds": round(cuda_seconds, 4),
                "cuda_path_average_seconds": round(cuda_seconds / count, 5),
                "backgrounds_per_second": round(count / elapsed, 4),
                "projected_700_seconds": round(projected_700, 2),
                "projected_700_minutes": round(projected_700 / 60.0, 3),
                "within_two_minute_goal": projected_700 <= 120.0,
                "within_one_minute_goal": projected_700 <= 60.0,
                "required_rate_for_two_minutes": round(700 / 120, 4),
                "speed_margin_vs_two_minutes": round((count / elapsed) / (700 / 120), 4),
                "estimated_full_batches": math.ceil(700 / max(count, 1)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
