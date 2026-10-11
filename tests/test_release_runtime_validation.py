"""Execute the release builder's runtime gate without packaging an SDK."""

import shutil
import subprocess
from pathlib import Path

import pytest

SHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(SHELL is None, reason="PowerShell is required for the Windows release builder")
@pytest.mark.parametrize(
    "initializer,build_version,accepted",
    [
        ("version_tuple = (7, 7, 1, 0)", "", True),
        ("from renpy.vc_version import version", "version = u'7.7.1.24030407'", True),
        ("version_tuple = (7, 8, 7, 0)", "", False),
        ("from renpy.vc_version import version", 'version = "7.8.7.25031702"', False),
        ("from renpy.vc_version import version", "version = u'8.5.3.26051504'", False),
    ],
)
def test_release_runtime_gate(tmp_path, initializer, build_version, accepted):
    runtime = tmp_path / "runtime with spaces"
    for directory in ("renpy", "lib", "module"):
        (runtime / directory).mkdir(parents=True)
    for name in ("renpy.exe", "LICENSE.txt"):
        (runtime / name).touch()
    (runtime / "renpy/__init__.py").write_text(initializer)
    (runtime / "renpy/vc_version.py").write_text(build_version)
    builder = (Path(__file__).resolve().parents[1] / "tools/build_release_zip.ps1").read_text()
    start = builder.index("if (-not [string]::IsNullOrWhiteSpace($CompatibilityRuntime)) {")
    gate = builder[start : builder.index("\n$staging =", start)]
    script = tmp_path / "validate.ps1"
    script.write_text(
        'param([string]$CompatibilityRuntime)\n$ErrorActionPreference = "Stop"\n' + gate,
        encoding="utf-8",
    )
    result = subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(runtime)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is accepted, result.stderr
    if "7.8.7" in build_version or "7, 8, 7" in initializer:
        assert "disqualified" in result.stderr
