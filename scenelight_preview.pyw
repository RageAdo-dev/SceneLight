"""Source and packaged entry point for SceneLight Preview."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from multiprocessing import freeze_support
from pathlib import Path
from tkinter import Tk, messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

REQUIRED_MODULES = {
    "numpy": "NumPy",
    "cv2": "OpenCV",
    "PIL": "Pillow",
    "PySide6": "PySide6",
    "OpenGL": "PyOpenGL",
    "psutil": "psutil",
    "imageio_ffmpeg": "imageio-ffmpeg",
}


def _private_pythonw() -> Path | None:
    override = os.environ.get("SCENELIGHT_COMPONENT_ROOT")
    if override:
        environment = Path(override).expanduser()
    elif os.environ.get("LOCALAPPDATA"):
        environment = Path(os.environ["LOCALAPPDATA"]) / "SceneLight" / "python-env"
    else:
        environment = Path.home() / ".scenelight" / "python-env"
    name = "pythonw.exe" if os.name == "nt" else "python"
    candidate = environment / ("Scripts" if os.name == "nt" else "bin") / name
    try:
        active = Path(sys.executable).resolve()
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() and resolved != active else None


def _show_error(message: str) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror("SceneLight Preview", message, parent=root)
    root.destroy()


def run() -> int:
    if sys.version_info < (3, 10):
        _show_error("SceneLight Preview needs Python 3.10 or newer.")
        return 1
    private_python = _private_pythonw()
    if private_python is not None:
        try:
            subprocess.Popen([str(private_python), str(Path(__file__).resolve()), *sys.argv[1:]])
        except OSError as error:
            _show_error(f"The SceneLight runtime could not start:\n\n{error}")
            return 1
        return 0
    missing = [
        label
        for module, label in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        _show_error(
            "Preview components are not installed:\n\n"
            + "\n".join(missing)
            + "\n\nOpen SceneLight and click "
            "Open Preview & Calibrator to install them with confirmation."
        )
        return 1
    from scenelight.preview.__main__ import main

    return main()


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(run())
