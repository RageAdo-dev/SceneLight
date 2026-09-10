"""Bounded file hashing on every supported Python version."""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> bytes:
    with path.open("rb") as stream:
        fast_digest = getattr(hashlib, "file_digest", None)
        if fast_digest is not None:
            return fast_digest(stream, "sha256").digest()
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.digest()
