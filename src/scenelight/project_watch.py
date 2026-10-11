"""Cheap idle change detection; installation still verifies source bytes."""

from __future__ import annotations

import os
from pathlib import Path

from .script_cache import source_candidates
from .source_types import VISUAL_SOURCE_SUFFIXES


def source_metadata(project: Path) -> dict[str, tuple[int, int]]:
    """Read file names, sizes and mtimes without opening artwork or archives."""
    result = {}
    config = project / "scenelight.json"
    if config.is_file():
        info = config.stat()
        result[config.name] = (info.st_size, info.st_mtime_ns)
    game = project / "game"

    def failed(error):
        raise error

    for directory, names, filenames in os.walk(game, onerror=failed):
        current = Path(directory)
        names[:] = [
            name
            for name in names
            if not name.startswith((".scenelight-developer-", ".sl-"))
            and not (current == game and name.lower() in {"cache", "saves", "scenelight_runtime"})
            and not (current / name).is_symlink()
        ]
        for name in filenames:
            path = current / name
            if path.suffix.lower() not in VISUAL_SOURCE_SUFFIXES:
                continue
            if any(source.is_file() for source in source_candidates(path)):
                continue
            info = path.stat()
            result[path.relative_to(project).as_posix()] = (info.st_size, info.st_mtime_ns)
    return result


class ProjectWatch:
    """Require two identical polls before presenting an edited project."""

    def __init__(self, baseline=None):
        self.baseline = baseline
        self.pending = None

    def observe(self, snapshot):
        if self.baseline is None:
            self.baseline = snapshot
        if snapshot == self.baseline:
            self.pending = None
            return False
        if snapshot != self.pending:
            self.pending = snapshot
            return False
        self.baseline = snapshot
        self.pending = None
        return True
