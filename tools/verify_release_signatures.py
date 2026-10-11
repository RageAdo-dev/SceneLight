"""Check the exact launcher bytes and signatures shipped in every release format."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"scenelight-desktop.exe", "scenelight-launcher.exe"}


def launchers(archive: Path) -> dict[str, bytes]:
    def wanted(name):
        return Path(name).name in NAMES | {"SceneLight.exe"}

    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as source:
            return {
                item.name: source.extractfile(item).read()
                for item in source.getmembers()
                if item.isfile() and wanted(item.name)
            }
    with zipfile.ZipFile(archive) as source:
        return {name: source.read(name) for name in source.namelist() if wanted(name)}


def verify(
    archives: list[Path], *, signed: bool, assets: Path = ROOT / "src/scenelight/assets"
) -> list[str]:
    if not archives:
        raise ValueError("No release packages found")
    originals = {name: (assets / name).read_bytes() for name in NAMES}
    records = []
    with tempfile.TemporaryDirectory(prefix="scenelight-signatures-") as temporary:
        paths = []
        for archive in archives:
            found = launchers(archive)
            expected = {"SceneLight.exe"} if archive.name.endswith("-online.zip") else NAMES
            if not expected.issubset({Path(name).name for name in found}):
                raise ValueError(f"Missing launchers in {archive.name}")
            for name, payload in found.items():
                original = (
                    "scenelight-desktop.exe"
                    if Path(name).name == "SceneLight.exe"
                    else Path(name).name
                )
                if payload != originals[original]:
                    raise ValueError(f"Launcher differs from signing input: {archive.name}/{name}")
                target = Path(temporary) / f"{len(paths)}.exe"
                target.write_bytes(payload)
                paths.append(str(target))
                records.append(f"{archive.name}/{name}")
        if signed:
            if os.name != "nt":
                raise RuntimeError("Authenticode verification requires Windows")
            inventory = Path(temporary) / "files.json"
            inventory.write_text(json.dumps(paths), encoding="utf-8")
            script = Path(temporary) / "verify.ps1"
            script.write_text(
                """param([string]$Inventory)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1')
foreach ($file in (Get-Content -LiteralPath $Inventory -Raw | ConvertFrom-Json)) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    if ($signature.Status -ne 'Valid') { throw "Invalid package signature: $file ($($signature.Status))" }
}
""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script),
                    str(inventory),
                ],
                check=True,
                timeout=180,
                capture_output=True,
                text=True,
            )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--signed", action="store_true")
    args = parser.parse_args()
    archives = sorted(
        p for p in args.dist.iterdir() if p.name.endswith((".whl", ".tar.gz", ".zip"))
    )
    for record in verify(archives, signed=args.signed):
        print(
            ("Signature and bytes verified: " if args.signed else "Unsigned bytes verified: ")
            + record
        )


if __name__ == "__main__":
    main()
