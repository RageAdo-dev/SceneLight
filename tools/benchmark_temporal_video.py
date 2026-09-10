"""Benchmark cold exact temporal-light analysis for one video."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.media import MediaClip


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--max-anchors", type=int)
    args = parser.parse_args()

    root = args.cache.expanduser().resolve()
    clip = MediaClip(args.video.expanduser().resolve(strict=True), root / "media")
    cache = ArtifactCache(root=root / "preview-cache")
    cancelled = threading.Event()
    plan = cache.prepare_temporal_backend()
    anchors = clip.temporal_anchor_indices(detect_changes=True)
    if args.max_anchors is not None:
        anchors = anchors[: max(1, args.max_anchors)]
    decode_seconds = 0.0
    analysis_seconds = 0.0
    built = 0
    batches: list[dict[str, float | int]] = []
    started_all = time.perf_counter()
    try:
        for offset in range(0, len(anchors), plan.temporal_batch_size):
            batch = anchors[offset : offset + plan.temporal_batch_size]
            prepared: list[tuple[int, Path, str]] = []
            transient_paths: list[Path] = []
            started = time.perf_counter()
            for frame in clip.iter_frames(batch):
                path, transient = clip.analysis_frame_path(frame)
                prepared.append((frame.index, path, clip.temporal_cache_key(frame.index)))
                if transient:
                    transient_paths.append(path)
            decode_seconds += time.perf_counter() - started
            started = time.perf_counter()
            results = list(cache.temporal_scene_batch(tuple(prepared), cancelled))
            elapsed = time.perf_counter() - started
            analysis_seconds += elapsed
            built += len(results)
            batches.append(
                {
                    "through": batch[-1],
                    "count": len(results),
                    "seconds": round(elapsed, 3),
                }
            )
            for path in transient_paths:
                path.unlink(missing_ok=True)
    finally:
        clip.close()
        cache.shutdown()
    print(
        json.dumps(
            {
                "anchors": len(anchors),
                "built": built,
                "workers": plan.process_workers,
                "batch_size": plan.temporal_batch_size,
                "decode_seconds": round(decode_seconds, 3),
                "analysis_seconds": round(analysis_seconds, 3),
                "total_seconds": round(time.perf_counter() - started_all, 3),
                "batches": batches,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
