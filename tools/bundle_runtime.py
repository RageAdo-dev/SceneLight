"""Build a private Windows Python runtime from the release builder's interpreter."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from windows_payload import copy_payload, filesystem_path, keep


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
            ignore=lambda directory, names: [
                child
                for child in names
                if child == "site-packages"
                or not keep((Path(directory) / child).relative_to(base), "desktop")
            ],
        )
    # Isolate module lookup from global Python installs, PATH and PYTHONPATH.
    (destination / "python311._pth").write_text(
        ".\nDLLs\nLib\nLib/site-packages\n../src\nimport site\n", encoding="utf-8"
    )
    # Use extended Windows paths for extraction and cleanup as well as copy;
    # Qt ships generated asset names longer than MAX_PATH under a user Temp.
    with tempfile.TemporaryDirectory(
        prefix="scenelight-runtime-deps-", dir=filesystem_path(Path(tempfile.gettempdir()))
    ) as temporary:
        dependencies = filesystem_path(Path(temporary) / "site-packages")
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
                str(dependencies),
                "-r",
                str(requirements),
            ],
            check=True,
        )
        copy_payload(
            dependencies, destination / "Lib/site-packages", "desktop", Path("Lib/site-packages")
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
