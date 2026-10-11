"""Setup dependencies helpers shared by the controller and tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEPENDENCIES = {
    "numpy": "NumPy",
    "cv2": "OpenCV",
    "PIL": "Pillow",
}


BASE_REQUIREMENTS = (
    "numpy==2.2.6",
    "opencv-python-headless==5.0.0.93",
    "Pillow==12.3.0",
    "psutil==7.2.2",
    "PySide6-Essentials==6.11.2",
    "imageio-ffmpeg==0.6.0",
)


PACKAGING_REQUIREMENTS = (
    "pip==26.2.1",
    "setuptools==84.0.0",
    "wheel==0.48.0",
)


BASE_DEPENDENCIES = {
    "numpy": BASE_REQUIREMENTS[0],
    "cv2": BASE_REQUIREMENTS[1],
    "PIL": BASE_REQUIREMENTS[2],
    "psutil": BASE_REQUIREMENTS[3],
    "PySide6": BASE_REQUIREMENTS[4],
    "imageio_ffmpeg": BASE_REQUIREMENTS[5],
}


CUDA_REQUIREMENT = "cupy-cuda12x==14.2.0"


PREVIEW_DEPENDENCIES = {
    **BASE_DEPENDENCIES,
    "PySide6.QtOpenGLWidgets": "PySide6-Essentials==6.11.2",
    "OpenGL": "PyOpenGL==3.1.10",
}


def _missing_modules(
    dependencies: dict[str, str], python_executable: Path | None = None
) -> list[str]:
    program = Path(python_executable or sys.executable)
    target = program.resolve()
    active = Path(sys.executable).resolve()
    # Windows' GUI and console executables in the same environment share their
    # packages. Treating pythonw.exe as a different environment spawned a new
    # interpreter (and blocked Tk) whenever Settings refreshed its component list.
    same_environment = target == active or (
        os.name == "nt"
        and target.parent == active.parent
        and {target.name.lower(), active.name.lower()} <= {"python.exe", "pythonw.exe"}
    )
    if same_environment:
        missing: list[str] = []
        for module, requirement in dependencies.items():
            distribution, separator, expected = requirement.partition("==")
            try:
                installed = version(distribution)
            except PackageNotFoundError:
                installed = ""
            try:
                available = importlib.util.find_spec(module) is not None
            except (ModuleNotFoundError, ValueError):
                available = False
            if not available or not separator or installed != expected:
                missing.append(requirement)
        return missing
    if not program.is_file():
        return list(dependencies.values())
    probe = """import importlib.metadata
import importlib.util
import json
import sys

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
missing = []
for module, requirement in pairs:
    distribution, separator, expected = requirement.partition("==")
    try:
        installed = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        installed = ""
    try:
        available = importlib.util.find_spec(module) is not None
    except (ModuleNotFoundError, ValueError):
        available = False
    if not available or not separator or installed != expected:
        missing.append(module)
print(json.dumps(missing))
"""
    arguments = [value for item in dependencies.items() for value in item]
    try:
        result = subprocess.run(
            [str(program), "-c", probe, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        missing_modules = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        missing_modules = None
    if not isinstance(missing_modules, list):
        return list(dependencies.values())
    return [
        requirement for module, requirement in dependencies.items() if module in missing_modules
    ]


DEPENDENCY_LABELS = {
    "numpy": "NumPy",
    "opencv-python-headless": "OpenCV",
    "Pillow": "Pillow",
    "PySide6": "PySide6",
    "PyOpenGL": "PyOpenGL",
    "psutil": "psutil",
    "imageio-ffmpeg": "imageio-ffmpeg",
    "cupy-cuda12x": "CuPy CUDA 12",
    "pip": "pip",
    "setuptools": "setuptools",
    "wheel": "wheel",
}
