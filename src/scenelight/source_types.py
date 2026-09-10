"""File types that can change a Ren'Py project's visual output."""

from __future__ import annotations

import hashlib
from pathlib import Path

SCRIPT_SOURCE_SUFFIXES = frozenset({".rpy", ".rpym", ".rpyc", ".rpymc"})
ARCHIVE_SOURCE_SUFFIXES = frozenset({".rpa"})
IMAGE_SOURCE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".apng", ".avif", ".svg"}
)
VIDEO_SOURCE_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".avi", ".webm", ".mkv", ".ogv"})
EFFECT_SOURCE_DIRECTORY = "scenelight_effects"

VISUAL_SOURCE_SUFFIXES = frozenset().union(
    SCRIPT_SOURCE_SUFFIXES,
    ARCHIVE_SOURCE_SUFFIXES,
    IMAGE_SOURCE_SUFFIXES,
    VIDEO_SOURCE_SUFFIXES,
)


def is_effect_source(path) -> bool:
    """Return whether a project-relative path is a SceneLight effect pack."""

    parts = tuple(str(part).lower() for part in path.parts)
    return len(parts) >= 2 and EFFECT_SOURCE_DIRECTORY in parts and path.suffix.lower() == ".json"


def source_digest(path: Path) -> str:
    """Hash authored bytes even when an editor preserves size and timestamps."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
