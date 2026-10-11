"""Release downloads must not depend on the temporary Actions storage quota."""

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release.yml"
SHELLS = list(
    dict.fromkeys(path for name in ("pwsh", "powershell") if (path := shutil.which(name)))
)
SHELL = SHELLS[0] if SHELLS else None


def _step(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split(f"      - name: {name}\n", 1)[1]
    return block.split("\n      - ", 1)[0]


def _script(name: str) -> str:
    return textwrap.dedent(_step(name).split("        run: |\n", 1)[1]).rstrip() + "\n"


def test_tagged_release_does_not_use_temporary_artifact_storage():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    release = _step("Create draft release for tag")
    temporary = _step("Upload temporary download")

    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in release
    assert "gh release create" in release
    assert "if: github.event_name == 'workflow_dispatch' && inputs.upload_artifact" in temporary
    assert "retention-days: 1\n" in temporary
    assert "if-no-files-found: error" in temporary
    assert "continue-on-error" not in workflow
    assert "default: false" in workflow.split("  push:", 1)[0]
    assert workflow.index("Create draft release for tag") < workflow.index(
        "Upload temporary download"
    )


@pytest.mark.skipif(SHELL is None, reason="PowerShell is required for release upload checks")
@pytest.mark.parametrize("shell", SHELLS or [None])
@pytest.mark.parametrize(
    "exists,upload_exit,lookup_exit", [(True, 0, 0), (False, 0, 0), (False, 1, 0), (False, 0, 1)]
)
def test_release_upload_preserves_existing_assets_and_reports_failures(
    tmp_path, monkeypatch, exists, upload_exit, lookup_exit, shell
):
    monkeypatch.setenv("RELEASE_TAG", "v1.0.0")
    monkeypatch.setenv("TEST_GH_CALLS", str(tmp_path / "calls.json"))
    stub = """
$ErrorActionPreference = 'Stop'
$script:Calls = @()
function gh {
    $script:Calls += ,@($args)
    ConvertTo-Json -InputObject $script:Calls -Depth 4 | Set-Content -LiteralPath $env:TEST_GH_CALLS
    if ($args[1] -eq 'list') {
        $global:LASTEXITCODE = LOOKUP_EXIT
        'RELEASE_LIST'
    } else {
        $global:LASTEXITCODE = UPLOAD_EXIT
    }
}
"""
    stub = (
        stub.replace("LOOKUP_EXIT", str(lookup_exit))
        .replace("RELEASE_LIST", '[{"tagName":"v1.0.0"}]' if exists else "[]")
        .replace("UPLOAD_EXIT", str(upload_exit))
    )
    script = tmp_path / "publish.ps1"
    script.write_text(stub + _script("Create draft release for tag"), encoding="utf-8")
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    calls = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8-sig"))
    assert list(map(str, calls[0][:4])) == ["release", "list", "--limit", "1000"]
    if lookup_exit:
        assert result.returncode != 0
        assert "Release lookup failed" in result.stderr
        assert len(calls) == 1
    elif exists:
        assert result.returncode == 0, result.stderr
        assert len(calls) == 1
    else:
        assert calls[1][:3] == ["release", "create", "v1.0.0"]
        assert len([arg for arg in calls[1] if arg.startswith("dist/")]) == 8
        assert {"--draft", "--prerelease", "--verify-tag"}.issubset(calls[1])
        assert "--clobber" not in calls[1]
        assert (result.returncode == 0) == (upload_exit == 0)
        if upload_exit:
            assert "Release upload failed" in result.stderr


@pytest.mark.skipif(SHELL is None, reason="PowerShell is required for release summary checks")
def test_build_only_summary_records_actual_package_hashes(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    payload = b"a build-only package"
    (dist / "SceneLight-test.zip").write_bytes(payload)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    script = tmp_path / "summary.ps1"
    script.write_text(
        _script("Record package checksums") + _script("Explain build-only result"), encoding="utf-8"
    )
    result = subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    text = summary.read_text(encoding="utf-8-sig")
    assert (
        f"| SceneLight-test.zip | {len(payload)} | {hashlib.sha256(payload).hexdigest()} |" in text
    )
    assert "No package was uploaded" in text
