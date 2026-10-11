import hashlib

import pytest

from scenelight.hashing import sha256_file


@pytest.mark.parametrize(
    "payload", [b"", b"SceneLight", bytes(range(256)) * 8193], ids=["empty", "short", "multi-block"]
)
@pytest.mark.parametrize("python310", [False, True])
def test_file_hash_preserves_all_bytes_across_python_versions(
    tmp_path, monkeypatch, payload, python310
):
    if python310:
        monkeypatch.delattr(hashlib, "file_digest", raising=False)
    path = tmp_path / "source.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == hashlib.sha256(payload).digest()
