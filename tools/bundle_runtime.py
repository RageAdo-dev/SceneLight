"""Build a private Windows Python runtime from the release builder's interpreter."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def bundle(destination: Path, requirements: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("The desktop runtime must be built on Windows")
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Build the desktop runtime with Python 3.11")
    if destination.exists():
        raise FileExistsError(destination)
    base = Path(sys.base_prefix)
    if not (base / "tcl").is_dir():
        raise RuntimeError("The build interpreter must include Tcl/Tk")
    destination.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe", "LICENSE.txt"):
        shutil.copy2(base / name, destination / name)
    for pattern in ("python*.dll", "vcruntime*.dll"):
        for path in base.glob(pattern):
            shutil.copy2(path, destination / path.name)
    for name in ("DLLs", "Lib", "tcl"):
        shutil.copytree(
            base / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "test", "tests"),
        )
    # Isolate module lookup from global Python installs, PATH and PYTHONPATH.
    (destination / "python311._pth").write_text(
        ".\nDLLs\nLib\nLib/site-packages\n../src\nimport site\n", encoding="utf-8"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-compile",
            "--target",
            str(destination / "Lib/site-packages"),
            "-r",
            str(requirements),
        ],
        check=True,
    )
    (destination / "scenelight-runtime.json").write_text(
        json.dumps({"python": sys.version, "requirements": requirements.read_text()}, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    bundle(args.destination, Path(__file__).resolve().parents[1] / "requirements-preview.txt")
