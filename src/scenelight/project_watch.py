"""Cheap idle change detection; installation still verifies source bytes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .file_verification import verified_digest
from .runtime.live_edit import signal_path
from .script_cache import source_candidates
from .source_types import VISUAL_SOURCE_SUFFIXES


def source_metadata(project: Path, *, include_paired_scripts=False) -> dict[str, tuple[int, int]]:
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
            if not include_paired_scripts and any(
                source.is_file() for source in source_candidates(path)
            ):
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


class LiveSources:
    """Remember verified file identities between polls of the selected developer project."""

    def __init__(self):
        self.files = {}
        self.watch = ProjectWatch({})

    def snapshot(self, project):
        current = {}
        for name in source_metadata(project, include_paired_scripts=True):
            expected, stamp = self.files.get(name, (None, None))
            digest, stamp, _ = verified_digest(project / name, expected, stamp)
            current[name] = (digest, stamp)
        self.files = current
        return {name: pair[0] for name, pair in current.items()}


def live_updates_enabled(project: Path) -> bool:
    return not Path(signal_path(str(project))).with_suffix(".off").exists()


def save_live_updates_enabled(project: Path, enabled: bool) -> None:
    opt_out = Path(signal_path(str(project))).with_suffix(".off")
    if enabled:
        opt_out.unlink(missing_ok=True)
    else:
        opt_out.parent.mkdir(parents=True, exist_ok=True)
        opt_out.touch()


def notify_playtest(project):
    path = Path(signal_path(str(project)))
    path.parent.mkdir(exist_ok=True, parents=True)
    revision = uuid.uuid4().hex
    temporary = path.with_suffix("." + revision)
    try:
        temporary.write_bytes(revision.encode("ascii"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
