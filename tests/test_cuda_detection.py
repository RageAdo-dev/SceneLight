import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenelight import cuda_detection


def test_tool_markers_without_a_cuda_device_do_not_trigger_installation(monkeypatch):
    monkeypatch.setattr(cuda_detection, "driver_devices", lambda: (0, ()))
    monkeypatch.setattr(cuda_detection, "cuda12_toolkit_detected", lambda: True)
    support = cuda_detection.probe_support()
    assert not support.recommended
    assert "No compatible NVIDIA" in support.message


@pytest.mark.parametrize("toolkit,expected", [(True, True), (False, False)])
def test_detected_gpu_recommends_acceleration_only_with_compatible_tools(
    monkeypatch, toolkit, expected
):
    monkeypatch.setattr(cuda_detection, "driver_devices", lambda: (12080, ("NVIDIA Test GPU",)))
    monkeypatch.setattr(cuda_detection.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(cuda_detection, "cuda12_toolkit_detected", lambda: toolkit)
    result = cuda_detection.probe_support()
    assert result.recommended is expected
    assert "NVIDIA Test GPU" in result.message
    assert not result.backend_ready


def test_old_driver_does_not_recommend_cuda12_wheel(monkeypatch):
    monkeypatch.setattr(cuda_detection, "driver_devices", lambda: (11040, ("Old GPU",)))
    monkeypatch.setattr(cuda_detection, "cuda12_toolkit_detected", lambda: True)
    assert not cuda_detection.probe_support().recommended


@pytest.mark.parametrize("version,expected", [("12.8", True), ("11.8", False), ("13.0", False)])
def test_toolkit_version_is_checked_not_just_the_nvcc_filename(monkeypatch, version, expected):
    monkeypatch.delenv("CUDA_PATH", raising=False)
    monkeypatch.setattr(cuda_detection.shutil, "which", lambda name: "nvcc")
    monkeypatch.setattr(
        cuda_detection.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=f"Cuda compilation tools, release {version}"
        ),
    )
    assert cuda_detection.cuda12_toolkit_detected() is expected


def test_explicit_cuda_path_takes_priority_over_another_compiler_on_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CUDA_PATH", str(tmp_path / "CUDA13"))
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="release 13.0")

    monkeypatch.setattr(cuda_detection.subprocess, "run", run)
    assert not cuda_detection.cuda12_toolkit_detected()
    assert "CUDA13" in calls[0][0]


@pytest.mark.parametrize("works", [True, False])
def test_installed_backend_must_perform_a_real_operation(monkeypatch, works):
    monkeypatch.setattr(cuda_detection, "driver_devices", lambda: (13000, ("NVIDIA Test GPU",)))
    monkeypatch.setattr(cuda_detection.importlib.util, "find_spec", lambda name: object())

    def arange(*args, **kwargs):
        if not works:
            raise RuntimeError("Missing CUDA runtime library")
        return SimpleNamespace(sum=lambda: SimpleNamespace(get=lambda: 6.0))

    monkeypatch.setitem(sys.modules, "cupy", SimpleNamespace(arange=arange, float32="float32"))
    support = cuda_detection.probe_support()
    assert support.backend_ready is works
    assert support.recommended is works


def test_hung_probe_falls_back_to_cpu_with_a_timeout(monkeypatch):
    def hung(args, **kwargs):
        assert kwargs["timeout"] == 0.1
        raise subprocess.TimeoutExpired(args, 0.1)

    monkeypatch.setattr(cuda_detection.subprocess, "run", hung)
    support = cuda_detection.detect_cuda_support(Path("python.exe"), timeout=0.1)
    assert not support.recommended
    assert "could not finish" in support.message


def test_probe_uses_console_interpreter_and_validates_its_response(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        payload = {
            "devices": ["GPU"],
            "recommended": True,
            "backend_ready": False,
            "message": "Detected GPU",
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(cuda_detection.subprocess, "run", run)
    support = cuda_detection.detect_cuda_support(Path("runtime/pythonw.exe"))
    assert calls[0][0].endswith("python.exe")
    assert support.devices == ("GPU",) and support.recommended


def test_new_private_environment_does_not_borrow_hosts_cupy_readiness(monkeypatch):
    monkeypatch.setattr(cuda_detection, "driver_devices", lambda: (13000, ("GPU",)))
    monkeypatch.setattr(cuda_detection, "cuda12_toolkit_detected", lambda: False)

    def forbidden(name):
        pytest.fail("Host packages must not certify a not-yet-created private runtime")

    monkeypatch.setattr(cuda_detection.importlib.util, "find_spec", forbidden)
    assert not cuda_detection.probe_support(check_backend=False).recommended
