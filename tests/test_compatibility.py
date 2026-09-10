from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from scenelight import compatibility
from scenelight.compatibility import (
    _add_windows_root_certificates,
    _download_https,
    _install_from_archive,
    _safe_extract,
)


def _runtime_archive(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as bundle:
        for name in (
            "renpy-sdk/renpy.exe",
            "renpy-sdk/renpy/__init__.py",
            "renpy-sdk/lib/placeholder",
            "renpy-sdk/module/placeholder",
            "renpy-sdk/LICENSE.txt",
        ):
            bundle.writestr(name, b"test")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_compatibility_runtime_installs_under_exact_destination(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.zip"
    digest = _runtime_archive(archive)
    destination = tmp_path / "private" / "renpy-7"

    executable = _install_from_archive(archive, destination, digest)

    assert executable == destination / "renpy.exe"
    assert executable.is_file()
    assert (destination / "LICENSE.txt").is_file()


def test_compatibility_runtime_rejects_hash_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.zip"
    _runtime_archive(archive)

    with pytest.raises(ValueError, match="SHA-256"):
        _install_from_archive(archive, tmp_path / "runtime", "0" * 64)


def test_compatibility_runtime_rejects_zip_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", b"unsafe")

    with pytest.raises(ValueError, match="Unsafe path"):
        _safe_extract(archive, tmp_path / "extract")
    assert not (tmp_path / "outside.txt").exists()


def test_windows_root_certificates_are_added_to_context(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    class Context:
        def load_verify_locations(self, *, cadata: str) -> None:
            loaded.append(cadata)

    def enum_certificates(store: str) -> list[tuple[bytes, str, bool]]:
        assert store == "ROOT"
        return [
            (b"trusted", "x509_asn", True),
            (b"ignored", "pkcs_7_asn", True),
        ]

    monkeypatch.setattr(
        compatibility.ssl,
        "DER_cert_to_PEM_cert",
        lambda certificate: f"PEM:{certificate.decode('ascii')}",
    )

    _add_windows_root_certificates(Context(), enum_certificates)  # type: ignore[arg-type]

    assert loaded == ["PEM:trusted"]


def test_https_download_streams_with_explicit_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = b"verified payload"
    expected_context = object()

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def urlopen(
        request: object,
        *,
        context: object,
        timeout: int,
    ) -> Response:
        assert context is expected_context
        assert timeout == 60
        return Response(payload)

    monkeypatch.setattr(compatibility, "_https_context", lambda: expected_context)
    monkeypatch.setattr(compatibility.urllib.request, "urlopen", urlopen)
    destination = tmp_path / "runtime.zip.download"

    _download_https("https://example.invalid/runtime.zip", destination)

    assert destination.read_bytes() == payload
    assert f"compatibility download {len(payload)}/{len(payload)}" in capsys.readouterr().out


def test_compatibility_download_rejects_non_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _download_https("http://example.invalid/runtime.zip", tmp_path / "runtime.zip")
