import importlib.util
import io
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "release_signatures", ROOT / "tools/verify_release_signatures.py"
)
signatures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signatures)


def packages(tmp_path):
    result = []
    originals = {
        name: (ROOT / "src/scenelight/assets" / name).read_bytes() for name in signatures.NAMES
    }
    for name in (
        "test.whl",
        "test.tar.gz",
        "SceneLight-Windows.zip",
        "SceneLight-Windows-source.zip",
        "SceneLight-Windows-online.zip",
    ):
        members = {"src/scenelight/assets/" + k: v for k, v in originals.items()}
        if "-online" in name:
            members = {"SceneLight/SceneLight.exe": originals["scenelight-desktop.exe"]}
        path = tmp_path / name
        if name.endswith(".tar.gz"):
            with tarfile.open(path, "w:gz") as archive:
                for member, data in members.items():
                    item = tarfile.TarInfo(member)
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
        else:
            with zipfile.ZipFile(path, "w") as archive:
                for member, data in members.items():
                    archive.writestr(member, data)
        result.append(path)
    return result


def test_release_formats_keep_exact_launcher_bytes(tmp_path):
    assert len(signatures.verify(packages(tmp_path), signed=False)) == 9


@pytest.mark.parametrize("missing", [True, False])
def test_modified_or_missing_packaged_launcher_is_rejected(tmp_path, missing):
    archives = packages(tmp_path)
    with zipfile.ZipFile(archives[-1], "w") as archive:
        archive.writestr("ignored.txt" if missing else "SceneLight/SceneLight.exe", b"changed")
    with pytest.raises(ValueError, match="Missing launchers|differs from signing input"):
        signatures.verify(archives, signed=False)


@pytest.mark.skipif(os.name != "nt", reason="Windows Authenticode")
def test_signed_mode_rejects_actual_unsigned_executable(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as error:
        signatures.verify(packages(tmp_path), signed=True)
    assert "Invalid package signature" in error.value.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows signing workflow")
@pytest.mark.parametrize("required", [False, True])
def test_missing_certificate_respects_required_mode(monkeypatch, required):
    monkeypatch.delenv("SCENELIGHT_CERT_PFX", raising=False)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(ROOT / "tools/sign_release.ps1"),
    ]
    if required:
        command += ["-RequireSigning"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert (result.returncode != 0) == required
    assert "Signing is required" in result.stderr if required else "unsigned" in result.stdout


def test_workflow_signs_before_every_package_and_verifies_before_upload():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert workflow.index("sign_release.ps1") < workflow.index("python -m build")
    assert workflow.index("python -m build") < workflow.index("build_release_zip.ps1")
    assert workflow.index("Verify packaged launchers") < workflow.index("Record package checksums")
    assert workflow.index("Record package checksums") < workflow.index(
        "Create draft release for tag"
    )
    assert "TRUSTED_SIGNING_ACCOUNT" not in workflow
