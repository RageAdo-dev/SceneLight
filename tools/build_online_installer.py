"""Build a small online entry point pinned to one tested offline release ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def build(offline: Path, release_tag: str, destination: Path) -> Path:
    if not release_tag or release_tag in {".", ".."}:
        raise ValueError("An explicit release tag is required")
    match = re.fullmatch(r"SceneLight-v([0-9][A-Za-z0-9._-]*)-Windows\.zip", offline.name)
    if match is None:
        raise ValueError("Expected the complete SceneLight Windows ZIP")
    version = match[1]
    package = "SceneLight-" + version
    with zipfile.ZipFile(offline) as archive:
        for name in (
            "SceneLight.exe",
            "_scenelight/python/pythonw.exe",
            "_scenelight/python/scenelight-runtime.json",
        ):
            if package + "/" + name not in archive.namelist():
                raise ValueError("Offline release is missing " + name)
        # Use the exact launcher tested in the offline payload, including its signature.
        launcher = archive.read(package + "/SceneLight.exe")
    checksum = hashlib.sha256()
    with offline.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    digest = checksum.hexdigest()
    record = {
        "version": version,
        "url": "https://github.com/RageAdo-dev/SceneLight/releases/download/"
        + quote(release_tag, safe="")
        + "/"
        + quote(offline.name),
        "archive": offline.name,
        "package_root": package,
        "sha256": digest,
        "bytes": offline.stat().st_size,
    }
    destination.mkdir(parents=True, exist_ok=True)
    result = destination / f"SceneLight-v{version}-Windows-online.zip"
    online_root = package + "-Online/"
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(online_root + "SceneLight.exe", launcher)
        archive.writestr(online_root + "online-release.json", json.dumps(record, indent=2) + "\n")
        archive.write(
            ROOT / "tools/bootstrap_release.ps1", online_root + "tools/bootstrap_release.ps1"
        )
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            archive.write(ROOT / name, online_root + name)
        archive.writestr(
            online_root + "README.txt",
            "SceneLight online setup\n\n"
            "Extract this entire ZIP, then open SceneLight.exe.\n"
            f"The first launch downloads and verifies {record['bytes'] / 1_000_000:.1f} MB.\n"
            "Later launches reuse that installation under LocalAppData/SceneLight/installed.\n"
            "No administrator access or system Python changes are needed.\n"
            "Closing the download window cancels setup; reopen the installer to retry.\n\n"
            "For offline setup, extract the full Windows ZIP and run its SceneLight.exe.\n"
            "Optional CUDA acceleration can still require an additional download.\n",
        )
    result.with_suffix(".zip.sha256").write_text(
        hashlib.sha256(result.read_bytes()).hexdigest() + "  " + result.name + "\n",
        encoding="ascii",
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offline", type=Path)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(args.offline, args.release_tag, args.destination))
