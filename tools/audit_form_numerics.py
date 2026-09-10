"""Capture original synthetic form maps and CPU dispatch details for exact comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


def capture(output: Path) -> None:
    import cv2
    import numpy as np

    from scenelight import form_maps

    root = Path(__file__).resolve().parents[1]
    fixture = runpy.run_path(str(root / "tests/test_effects.py"))["_pre_effect_fixture"]
    observed = {}
    original = form_maps._pseudo_surface

    def surface(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.update(zip(("height", "nx", "ny", "nz"), result))
        return result

    form_maps._pseudo_surface = surface
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "python": sys.version,
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "cpu": cv2.getCPUFeaturesLine(),
        "ipp": cv2.ipp.getIppVersion(),
        "opencv_build": cv2.getBuildInformation(),
        "fixtures": {},
    }
    for mode in ("opaque", "sprite"):
        maps = form_maps.build_sprite_form_maps(fixture(mode))
        normal = np.asarray(maps.normal_noise.convert("RGB"))
        auxiliary = np.asarray(maps.height_ao_edge.convert("RGB"))
        logical = {
            "normal_noise": np.dstack((normal[..., :2], auxiliary[..., 2])),
            "height_ao_edge": np.dstack((auxiliary[..., :2], normal[..., 2])),
            "response": np.asarray(maps.response.convert("RGB")),
        }
        np.savez_compressed(output / (mode + ".npz"), **logical, **observed)
        report["fixtures"][mode] = {
            name: hashlib.sha256(array.tobytes()).hexdigest() for name, array in logical.items()
        }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "hashes": report["fixtures"]}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        capture(args.output)
        return
    variants = {
        "default": {},
        "ipp-avx2": {"OPENCV_IPP": "avx2"},
        "ipp-sse42": {"OPENCV_IPP": "sse42"},
        "opencv-no-avx2": {"OPENCV_CPU_DISABLE": "AVX2"},
        "numpy-no-avx512": {"NPY_DISABLE_CPU_FEATURES": "AVX512F"},
    }
    for name, changes in variants.items():
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(args.output / name), "--child"],
            env=dict(os.environ, **changes),
            check=True,
        )


if __name__ == "__main__":
    main()
