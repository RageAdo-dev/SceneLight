"""Profile one captured sprite form without modifying its project."""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
from pathlib import Path

import psutil
from PIL import Image

from scenelight.form_maps import build_sprite_form_maps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--form", default="monika 1")
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    capture = json.loads((project / ".scenelight_cache/capture_result.json").read_text())
    sprite = project / capture["sprites"][args.form]
    if args.warmup:
        build_sprite_form_maps(Image.open(sprite))

    profile = cProfile.Profile()
    profile.enable()
    build_sprite_form_maps(Image.open(sprite))
    profile.disable()
    output = io.StringIO()
    pstats.Stats(profile, stream=output).sort_stats("cumtime").print_stats(14)
    print(output.getvalue())
    print(f"rss_bytes={psutil.Process(os.getpid()).memory_info().rss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
