"""Exercise full temporal analysis with CUDA imports deliberately unavailable."""

from __future__ import annotations

import argparse
import importlib.abc
import json
import sys
import time
from pathlib import Path

import numpy as np


class NoCuda(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "cupy" or fullname.startswith("cupy."):
            raise ImportError("CUDA intentionally unavailable during CPU compatibility validation")
        return None


sys.meta_path.insert(0, NoCuda())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scenelight.preview.artifacts import ArtifactCache  # noqa: E402
from scenelight.preview.hardware import detect_hardware_profile  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("background", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = ArtifactCache(
        args.output / "cache", hardware_profile=detect_hardware_profile(cuda=False)
    )
    started = time.perf_counter()
    try:
        scene = cache.temporal_scene(args.background, "cpu-validation")
        np.savez_compressed(
            args.output / "cpu-fields.npz",
            irradiance=scene.irradiance,
            emitter=scene.emitter,
            transport=scene.transport,
        )
        result = {
            "cuda_imported": "cupy" in sys.modules,
            "cuda_selected": cache._cuda_available,
            "elapsed_seconds": time.perf_counter() - started,
            "irradiance_shape": scene.irradiance.shape,
            "emitter_shape": scene.emitter.shape,
            "transport_shape": scene.transport.shape,
            "metadata": scene.metadata,
        }
        if result["cuda_imported"] or result["cuda_selected"]:
            raise AssertionError("CPU validation unexpectedly selected CUDA")
        (args.output / "cpu-analysis.json").write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "metadata"}))
    finally:
        cache.shutdown()


if __name__ == "__main__":
    main()
