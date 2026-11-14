"""Installation progress and status updates during file operations."""

from __future__ import annotations

import os
import shutil
import stat
import threading
import time
from pathlib import Path

from .file_verification import bounded_file_work, verified_digest

STAGE_LABELS = {
    "worker-checkpoints": "Checking saved worker batches",
    "capture-save": "Saving verified captures",
    "background-cache": "Checking saved background lighting",
    "capture-inputs": "Checking game files for changes",
    "capture-reuse": "Checking saved sprite and background captures",
    "background-fields": "Preparing background lighting",
    "cache-restore": "Restoring verified analysis files",
    "form-cache": "Preparing existing sprite maps for the update",
    "form-workers": "Finishing sprite-map workers",
    "form-index": "Saving the sprite-map index",
    "analysis-report": "Saving the analysis report",
    "movie-prepare": "Preparing background videos",
    "cache-save": "Saving reusable analysis files",
    "cache-commit": "Finalizing the reusable cache",
    "cache-cleanup": "Removing the previous cache",
    "runtime-setup": "Preparing the game runtime",
    "runtime-copy": "Transferring SceneLight files into the game",
    "runtime-apply": "Applying updated lighting files",
    "runtime-hashes": "Verifying SceneLight files",
    "source-index": "Recording the game's source files",
    "install-record": "Saving installation details",
    "install-verify": "Verifying the prepared runtime",
    "runtime-cleanup": "Removing the previous runtime",
    "workspace-cleanup": "Cleaning up the temporary workspace",
}


class ProgressStage:
    """Report completed items; repeat the last count while an operation is running."""

    def __init__(self, phase: str, *, total: int = 0, item: str = "", interval: float = 1.0):
        if phase not in STAGE_LABELS:
            raise ValueError(f"Unknown progress stage: {phase}")
        if interval <= 0:
            raise ValueError("Progress heartbeat interval must be positive")
        self.phase = phase
        self.total = max(0, total)
        self.current = 0
        self.item = item
        self.interval = interval
        self._guard = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last_output = float("-inf")

    def _emit(self, *, force: bool = False) -> None:
        with self._guard:
            now = time.monotonic()
            if not force and now - self._last_output < 0.25:
                return
            self._last_output = now
            item = " ".join(str(self.item).split())[:240]
            try:
                print(
                    f"SceneLight stage {self.phase} {self.current}/{self.total}: {item}", flush=True
                )
            except (OSError, ValueError):
                pass  # Closing a progress pipe must not change filesystem results.

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.interval):
            self._emit(force=True)

    def __enter__(self):
        self._emit(force=True)
        self._thread = threading.Thread(
            target=self._heartbeat, name="SceneLight-progress", daemon=True
        )
        self._thread.start()
        return self

    def set_total(self, total: int) -> None:
        with self._guard:
            self.total, self.current = max(0, total), 0
            self._emit(force=True)

    def set_item(self, item: str) -> None:
        with self._guard:
            self.item = item
            self._emit()

    def advance(self) -> None:
        with self._guard:
            self.current += 1
            if self.total:
                self.total = max(self.total, self.current)
            self._emit()

    def __exit__(self, kind, error, trace):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._guard:
            if kind is None:
                # Reaching this point means the operation itself returned.
                if self.total == 0:
                    self.total = self.current
                self.item = "Complete"
            else:
                self.item = f"Stopped: {kind.__name__}: {error}"
            self._emit(force=True)
        return False


def copytree_with_progress(source: Path, destination: Path, phase: str, *, ignore=None) -> None:
    """Retain copytree/copy2 semantics and publish completed file counts."""
    with ProgressStage(phase, item="Counting files") as progress:
        count = 0
        has_links = False
        for directory, dirs, files in os.walk(source):
            ignored = set(ignore(directory, dirs + files)) if ignore is not None else set()
            dirs[:] = [name for name in dirs if name not in ignored]
            names = [name for name in files if name not in ignored]
            has_links |= any((Path(directory) / name).is_symlink() for name in dirs)
            count += len(names)
            progress.set_item(f"Counting files: {count:,} found")
        # copytree follows directory links by default. Avoid a misleading total
        # if a tree contains links that os.walk intentionally did not traverse.
        progress.set_total(0 if has_links else count)

        def copy_file(src, dst):
            progress.set_item(Path(src).name)
            result = shutil.copy2(src, dst)
            progress.advance()
            return result

        shutil.copytree(source, destination, ignore=ignore, copy_function=copy_file)


def copy_cache_tree(source: Path, destination: Path, phase: str, *, verified=None) -> None:
    """Copy independent files into a fresh cache tree, including their timestamps."""
    if os.name != "nt":
        copytree_with_progress(source, destination, phase)
        return

    with ProgressStage(phase, item="Counting cache files") as progress:
        directories = [Path(".")]
        files = []
        for relative in directories:
            with os.scandir(source / relative) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or not (
                        stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
                    ):
                        # Use copytree's link and special-file handling before creating the target.
                        shutil.copytree(source, destination)
                        return
                    path = relative / entry.name
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(path)
                    else:
                        files.append(path)
        for relative in directories:
            (destination / relative).mkdir()
        progress.set_total(len(files))

        def copy(relative):
            # Both captures and maps are read again during this update. Buffered
            # writes keep their bytes available without another disk seek.
            original = source / relative
            target = destination / relative
            with original.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=128 * 1024)
            shutil.copystat(original, target)
            if verified is not None:
                digest, stamp, _ = verified_digest(target)
                return relative, digest, stamp
            return relative, None, None

        for relative, digest, stamp in bounded_file_work(copy, files, workers=8):
            if stamp is not None:
                verified[relative] = (digest, stamp)
            progress.set_item(relative.name)
            progress.advance()
        for relative in reversed(directories):
            shutil.copystat(source / relative, destination / relative)
