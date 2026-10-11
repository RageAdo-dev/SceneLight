"""Compare exact sprite-form analysis throughput across executor strategies."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from scenelight.builder import _render_form_entry
from scenelight.project import SpriteSpec, discover_project


def _source_hash(spec: SpriteSpec) -> str:
    sprite = spec.compose()
    return hashlib.sha256(np.asarray(sprite, dtype=np.uint8).tobytes()).hexdigest()


def _run(
    executor_type: type[ThreadPoolExecutor] | type[ProcessPoolExecutor],
    specs: list[tuple[str, SpriteSpec]],
    root: Path,
    workers: int,
) -> tuple[float, dict[str, str]]:
    output = root / executor_type.__name__
    output.mkdir(parents=True)
    started = time.perf_counter()
    with executor_type(max_workers=workers) as executor:
        futures = []
        for index, (key, spec) in enumerate(specs):
            paths = {
                "normal_noise": output / f"{index:04d}_normal_noise.png",
                "height_ao_edge": output / f"{index:04d}_height_ao_edge.png",
                "response": output / f"{index:04d}_response.png",
            }
            futures.append(
                executor.submit(
                    _render_form_entry,
                    root,
                    key,
                    spec,
                    paths,
                    _source_hash(spec),
                )
            )
        for future in as_completed(futures):
            future.result()
    elapsed = time.perf_counter() - started
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.glob("*.png"))
    }
    return elapsed, hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--count", type=int, default=64)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    discovery = discover_project(args.project)
    specs = sorted(discovery.sprites.items())[: args.count]
    if not specs:
        raise SystemExit("No sprite forms were discovered")
    with tempfile.TemporaryDirectory(prefix="scenelight-form-executor-") as temporary:
        root = Path(temporary)
        thread_seconds, thread_hashes = _run(ThreadPoolExecutor, specs, root, args.workers)
        process_seconds, process_hashes = _run(ProcessPoolExecutor, specs, root, args.workers)
    if thread_hashes != process_hashes:
        raise SystemExit("Executor output hashes differ")
    print(f"forms={len(specs)} workers={args.workers}")
    print(f"thread_seconds={thread_seconds:.4f}")
    print(f"process_seconds={process_seconds:.4f}")
    print(f"speedup={thread_seconds / process_seconds:.3f}x")
    print(f"identical_pngs={len(thread_hashes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
