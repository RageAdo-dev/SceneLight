import hashlib
import importlib.util
import json
import os
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/bootstrap_release.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows installer uses PowerShell")


def release(tmp_path, *, unsafe=False):
    archive = tmp_path / "SceneLight-v1.0.0-Windows.zip"
    with zipfile.ZipFile(archive, "w") as zip:
        for name in (
            "SceneLight.exe",
            "_scenelight/python/pythonw.exe",
            "_scenelight/python/scenelight-runtime.json",
        ):
            zip.writestr("SceneLight-1.0.0/" + name, b"test payload")
        if unsafe:
            zip.writestr("SceneLight-1.0.0/../../escaped.txt", b"no")
    record = {
        "url": "https://example.invalid/release.zip",
        "archive": archive.name,
        "package_root": "SceneLight-1.0.0",
        "bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    manifest = tmp_path / "online-release.json"
    manifest.write_text(json.dumps(record))
    return archive, manifest, record


def install(tmp_path, manifest):
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-ManifestPath",
            str(manifest),
            "-CacheRoot",
            str(tmp_path / "cache"),
            "-Headless",
            "-InstallOnly",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_verified_offline_payload_is_cached_and_reused_without_download(tmp_path):
    archive, manifest, record = release(tmp_path)
    first = install(tmp_path, manifest)
    assert first.returncode == 0, first.stderr
    app = tmp_path / "cache" / record["sha256"] / record["package_root"]
    assert (app / "SceneLight.exe").read_bytes() == b"test payload"
    archive.unlink()
    second = install(tmp_path, manifest)
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert not list((tmp_path / "cache").glob("pending-*"))


def test_verified_zip_cannot_write_outside_its_install_tree(tmp_path):
    _, manifest, record = release(tmp_path, unsafe=True)
    result = install(tmp_path, manifest)
    assert result.returncode != 0
    assert "Unsafe path" in result.stderr
    assert not (tmp_path / "cache" / "escaped.txt").exists()
    assert not (tmp_path / "cache" / record["sha256"]).exists()
    assert not list((tmp_path / "cache").glob("pending-*"))


def test_failed_download_verification_leaves_no_install_and_can_retry(tmp_path):
    archive, manifest, record = release(tmp_path)
    valid = archive.read_bytes()
    responses = [b"corrupt download", valid]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = responses.pop(0)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        record["url"] = f"http://127.0.0.1:{server.server_port}/release.zip"
        manifest.write_text(json.dumps(record))
        archive.unlink()
        first = install(tmp_path, manifest)
        assert first.returncode != 0
        assert "checksum verification failed" in first.stderr
        assert not (tmp_path / "cache" / record["sha256"]).exists()
        assert not list((tmp_path / "cache").glob("pending-*"))
        second = install(tmp_path, manifest)
        assert second.returncode == 0, second.stderr
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_builder_pins_exact_payload_and_preserves_signed_launcher(tmp_path):
    archive, _, record = release(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "online_builder", ROOT / "tools/build_online_installer.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    online = module.build(archive, "v1.0.0-beta.2", tmp_path / "dist")
    with zipfile.ZipFile(online) as zip:
        root = "SceneLight-1.0.0-Online/"
        manifest = json.loads(zip.read(root + "online-release.json"))
        assert manifest["sha256"] == record["sha256"]
        assert manifest["bytes"] == archive.stat().st_size
        assert "/v1.0.0-beta.2/" in manifest["url"]
        assert zip.read(root + "SceneLight.exe") == b"test payload"
        assert not any("pythonw.exe" in name for name in zip.namelist())
        notices = zip.read(root + "THIRD_PARTY_NOTICES.md").decode("utf-8")
        assert "](docs/" not in notices
        assert "/blob/v1.0.0-beta.2/docs/licenses/LGPL-3.0-only.txt" in notices
    assert (
        online.with_suffix(".zip.sha256")
        .read_text()
        .startswith(hashlib.sha256(online.read_bytes()).hexdigest())
    )
