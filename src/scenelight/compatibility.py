"""Verified, per-user Ren'Py 7 runtime for legacy Ren'Py 6 games."""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# The 7.8.7 binaries lose Texture's finalizer and leak every uploaded frame.
# Keep Python 2 compatibility on the last runtime validated by the memory audit.
RENPY_VERSION = "7.7.1"
RENPY_URL = f"https://www.renpy.org/dl/{RENPY_VERSION}/renpy-{RENPY_VERSION}-sdk.zip"
RENPY_SHA256 = "767fb21aed2e689bfba04e2a7db0e30003f0b6825538cca5ab66a1ab4dbb8d2e"


def compatibility_root() -> Path:
    override = os.environ.get("SCENELIGHT_COMPATIBILITY_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return (base / "SceneLight" / "compatibility-runtime" / f"renpy-{RENPY_VERSION}").resolve()


def _valid_runtime(root: Path) -> bool:
    return all(
        path.exists()
        for path in (
            root / "renpy.exe",
            root / "renpy" / "__init__.py",
            root / "lib",
            root / "module",
            root / "LICENSE.txt",
        )
    )


def cached_renpy_executable() -> Path | None:
    root = compatibility_root()
    executable = root / "renpy.exe"
    return executable if _valid_runtime(root) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _add_windows_root_certificates(
    context: ssl.SSLContext,
    enum_certificates: object,
) -> None:
    """Add Windows' trusted roots to an OpenSSL context.

    Some otherwise clean Windows Python installations have no OpenSSL CA file,
    even though Windows networking and browsers have a valid system trust store.
    Importing only the Windows ROOT store preserves TLS verification while making
    the downloader follow the same administrator-managed trust decisions.
    """

    for certificate, encoding, _trust in enum_certificates("ROOT"):  # type: ignore[operator]
        if encoding != "x509_asn":
            continue
        try:
            context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
        except (ssl.SSLError, ValueError):
            # A malformed or unsupported store entry must not prevent the other
            # trusted roots from being loaded.
            continue


def _https_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    enum_certificates = getattr(ssl, "enum_certificates", None)
    if os.name == "nt" and enum_certificates is not None:
        _add_windows_root_certificates(context, enum_certificates)
    return context


def _download_https(url: str, destination: Path) -> None:
    if not url.lower().startswith("https://"):
        raise ValueError("The compatibility runtime must be downloaded over HTTPS.")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SceneLight compatibility downloader"},
    )
    context = _https_context()
    last_reported = -1
    downloaded = 0

    # The caller supplies the fixed Ren'Py HTTPS origin and verifies the pinned
    # SHA-256 digest before installation.
    with (
        urllib.request.urlopen(  # nosec B310
            request,
            context=context,
            timeout=60,
        ) as response,
        destination.open("wb") as stream,
    ):
        total_header = response.headers.get("Content-Length")
        total_size = int(total_header) if total_header else 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            stream.write(block)
            downloaded += len(block)
            if total_size > 0:
                percent = min(downloaded, total_size) * 100 // total_size
                if percent == last_reported:
                    continue
                last_reported = percent
            print(
                f"compatibility download {downloaded}/{total_size}: Ren'Py {RENPY_VERSION}",
                flush=True,
            )

    if total_size > 0 and downloaded != total_size:
        raise OSError("The Ren'Py download ended before the advertised number of bytes arrived.")


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise ValueError(f"Unsafe path in Ren'Py archive: {item.filename}")
        bundle.extractall(destination)


def _install_from_archive(archive: Path, destination: Path, expected_hash: str) -> Path:
    if _sha256(archive) != expected_hash.lower():
        raise ValueError("The Ren'Py download failed its SHA-256 verification.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="renpy-extract-", dir=destination.parent) as temp:
        extraction = Path(temp)
        _safe_extract(archive, extraction)
        candidates = [path.parent for path in extraction.rglob("renpy.exe")]
        source = next((path for path in candidates if _valid_runtime(path)), None)
        if source is None:
            raise ValueError("The verified archive did not contain a complete Ren'Py runtime.")
        if destination.exists():
            if _valid_runtime(destination):
                return destination / "renpy.exe"
            raise ValueError(f"An incomplete compatibility runtime already exists: {destination}")
        shutil.move(str(source), str(destination))
    if not _valid_runtime(destination):
        raise ValueError("The installed Ren'Py compatibility runtime is incomplete.")
    return destination / "renpy.exe"


def install_compatibility_runtime() -> Path:
    existing = cached_renpy_executable()
    if existing is not None:
        print(f"Compatibility runtime already verified: {existing}", flush=True)
        return existing
    root = compatibility_root()
    downloads = root.parent / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / f"renpy-{RENPY_VERSION}-sdk.zip"
    if not archive.is_file() or _sha256(archive) != RENPY_SHA256:
        partial = archive.with_suffix(".zip.download")
        partial.unlink(missing_ok=True)
        print(f"Downloading Ren'Py {RENPY_VERSION} compatibility runtime...", flush=True)
        try:
            _download_https(RENPY_URL, partial)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        if _sha256(partial) != RENPY_SHA256:
            partial.unlink(missing_ok=True)
            raise ValueError("The Ren'Py download failed its SHA-256 verification.")
        partial.replace(archive)
    print("Verifying and installing compatibility runtime...", flush=True)
    executable = _install_from_archive(archive, root, RENPY_SHA256)
    print(f"Compatibility runtime ready: {executable}", flush=True)
    return executable


def main() -> int:
    install_compatibility_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
