"""Bounded, isolated detection of optional NVIDIA analysis acceleration."""

from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CudaSupport:
    devices: tuple[str, ...] = ()
    recommended: bool = False
    backend_ready: bool = False
    message: str = "CUDA acceleration is unavailable. CPU analysis remains available."


def driver_devices() -> tuple[int, tuple[str, ...]]:
    """Query the driver for devices compatible with CUDA 12."""
    try:
        if sys.platform == "win32":
            library = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/nvcuda.dll"
            driver = ctypes.WinDLL(str(library))
        else:
            driver = ctypes.CDLL("libcuda.so.1")
        integer = ctypes.c_int
        pointer = ctypes.POINTER(integer)
        signatures = {
            "cuInit": [ctypes.c_uint],
            "cuDriverGetVersion": [pointer],
            "cuDeviceGetCount": [pointer],
            "cuDeviceGet": [pointer, integer],
            "cuDeviceGetName": [ctypes.c_void_p, integer, integer],
            "cuDeviceGetAttribute": [pointer, integer, integer],
        }
        for name, arguments in signatures.items():
            function = getattr(driver, name)
            function.argtypes, function.restype = arguments, integer
        if driver.cuInit(0) != 0:
            return 0, ()
        version, count = integer(), integer()
        if driver.cuDriverGetVersion(ctypes.byref(version)) or driver.cuDeviceGetCount(
            ctypes.byref(count)
        ):
            return 0, ()
        names = []
        for ordinal in range(min(max(count.value, 0), 32)):
            device, major = integer(), integer()
            name = ctypes.create_string_buffer(256)
            if driver.cuDeviceGet(ctypes.byref(device), ordinal):
                continue
            # CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR. CUDA 12 dropped Kepler.
            if driver.cuDeviceGetAttribute(ctypes.byref(major), 75, device) or major.value < 5:
                continue
            if driver.cuDeviceGetName(name, len(name), device) == 0:
                names.append(name.value.decode("utf-8", "replace"))
        return version.value, tuple(names)
    except (OSError, AttributeError):
        return 0, ()


def cuda12_toolkit_detected() -> bool:
    """Check the compiler CuPy would select, including its major version."""
    root = os.environ.get("CUDA_PATH")
    program = (
        str(Path(root) / "bin" / ("nvcc.exe" if os.name == "nt" else "nvcc"))
        if root
        else shutil.which("nvcc")
    )
    if not program:
        return False
    try:
        result = subprocess.run(
            [program, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0 and bool(re.search(r"release\s+12\.", result.stdout))
    except (OSError, subprocess.SubprocessError):
        return False


def probe_support(*, check_backend: bool = True) -> CudaSupport:
    version, devices = driver_devices()
    if not devices:
        return CudaSupport(
            message="No compatible NVIDIA CUDA GPU detected. CPU analysis is selected; live lighting can still use your graphics card."
        )
    label = ", ".join(devices)
    if version < 12000:
        return CudaSupport(
            devices,
            message=f"{label} detected. Its driver does not support CUDA 12; using CPU analysis.",
        )
    if check_backend and importlib.util.find_spec("cupy") is not None:
        try:
            import cupy as cp

            # A tiny real operation verifies the installed runtime/compiler too.
            ready = float(cp.arange(4, dtype=cp.float32).sum().get()) == 6.0
        except Exception:  # Optional packages and driver failures must never stop Setup.
            ready = False
        if ready:
            return CudaSupport(
                devices,
                True,
                True,
                f"{label} detected and CUDA verified. GPU acceleration can speed up first-time analysis.",
            )
        return CudaSupport(
            devices,
            message=f"{label} detected, but CUDA did not pass its runtime check. CPU analysis is available.",
        )
    if cuda12_toolkit_detected():
        return CudaSupport(
            devices,
            True,
            False,
            f"{label} detected. Optional CUDA acceleration can speed up first-time analysis.",
        )
    return CudaSupport(
        devices,
        message=f"{label} detected. CUDA 12 tools are not installed; CPU analysis is available. Live lighting still uses your graphics card.",
    )


def detect_cuda_support(
    python: Path, *, timeout: float = 12.0, check_backend: bool = True
) -> CudaSupport:
    """Contain slow or faulty driver initialization outside the Setup process."""
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    try:
        result = subprocess.run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--probe" if check_backend else "--hardware-only",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            raise ValueError("CUDA probe failed")
        payload = json.loads(result.stdout)
        devices = payload["devices"]
        if not isinstance(devices, list) or not all(isinstance(name, str) for name in devices):
            raise ValueError("Invalid GPU list")
        if (
            type(payload["recommended"]) is not bool
            or type(payload["backend_ready"]) is not bool
            or not isinstance(payload["message"], str)
        ):
            raise ValueError("Invalid CUDA status")
        return CudaSupport(
            tuple(devices), payload["recommended"], payload["backend_ready"], payload["message"]
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return CudaSupport(
            message="CUDA detection could not finish. CPU analysis is available; live lighting can still use your graphics card."
        )


if __name__ == "__main__" and sys.argv[1:] in (["--probe"], ["--hardware-only"]):
    print(json.dumps(asdict(probe_support(check_backend=sys.argv[1] == "--probe"))))
