"""Isolated working copies for non-destructive SceneLight integration.

The selected Ren'Py project is always treated as read-only input.  SceneLight
copies it into an isolated managed directory, adds generated files there, and
launches the managed copy with the game's own bundled executable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .source_types import VISUAL_SOURCE_SUFFIXES, is_effect_source, source_digest

STATE_NAME = ".scenelight_sidecar.json"

_EXCLUDED_ROOT_FILES = {
    "launch with scenelight.bat",
    "log.txt",
    "traceback.txt",
}
_EXCLUDED_GAME_NAMES = {
    "cache",
    "saves",
    "scenelight_capture.rpy",
    "scenelight_capture.rpyc",
    "scenelight_runtime.rpy",
    "scenelight_runtime.rpyc",
}


@dataclass(frozen=True)
class SyncResult:
    source: Path
    managed: Path
    copied: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.copied or self.removed)


def storage_root() -> Path:
    override = os.environ.get("SCENELIGHT_MANAGED_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return (Path(local) / "SceneLight" / "projects").resolve()
    return (Path.home() / ".scenelight" / "projects").resolve()


def managed_project_root(project_root: Path) -> Path:
    source = project_root.expanduser().resolve()
    digest = hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("-.") or "renpy-project"
    return storage_root() / f"{slug}-{digest}"


def analysis_cache_root(project_root: Path) -> Path:
    """Keep reusable analysis outside disposable managed/direct installations."""

    source = project_root.expanduser().resolve()
    digest = hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("-.") or "renpy-project"
    return storage_root().parent / "analysis-cache" / f"{slug}-{digest}"


def remove_analysis_cache(project_root: Path) -> bool:
    """Remove only the deterministic cache owned by one selected project."""

    cache = analysis_cache_root(project_root)
    root = (storage_root().parent / "analysis-cache").resolve()
    if cache.parent.resolve() != root or cache == root:
        raise ValueError(f"Refusing to remove an unexpected analysis cache path: {cache}")
    if not cache.exists():
        return False
    if cache.is_symlink() or not cache.is_dir():
        raise ValueError(f"Analysis cache ownership could not be verified: {cache}")
    shutil.rmtree(cache)
    return True


def _relative_key(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_source_file(relative: Path) -> bool:
    parts = tuple(part.lower() for part in relative.parts)
    if not parts:
        return False
    if parts[0] in {".scenelight_backups", ".scenelight_cache"}:
        return False
    if len(parts) == 1 and parts[0] in _EXCLUDED_ROOT_FILES:
        return False
    if parts[0] == "game" and len(parts) >= 2:
        if parts[1] in _EXCLUDED_GAME_NAMES:
            return False
        if parts[1] == "scenelight_runtime":
            return False
    return True


def _is_reserved_managed_file(relative: Path) -> bool:
    parts = tuple(part.lower() for part in relative.parts)
    if relative.as_posix() in {STATE_NAME, ".scenelight_install.json"}:
        return True
    if len(parts) == 1 and parts[0] == "launch with scenelight.bat":
        return True
    if len(parts) == 1 and parts[0] in _EXCLUDED_ROOT_FILES:
        # Ren'Py owns these runtime logs. Older launchers can keep them open
        # for a moment after the capture result has been published, so source
        # synchronization must neither import nor remove them.
        return True
    if parts and parts[0] == ".scenelight_cache":
        return True
    if len(parts) >= 2 and parts[0] == "game":
        # These are created by the managed game's native Ren'Py runtime. They
        # must survive source synchronization, but are never imported from the
        # selected project (see ``_EXCLUDED_GAME_NAMES`` above).
        if parts[1] in {"cache", "saves"}:
            return True
        return parts[1] in {
            "scenelight_runtime",
            "scenelight_runtime.rpy",
            "scenelight_runtime.rpyc",
            "scenelight_capture.rpy",
            "scenelight_capture.rpyc",
        }
    return False


def _metadata(path: Path, *, content: bool = False) -> dict[str, int | str]:
    stat = path.stat()
    result: dict[str, int | str] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if content:
        result["sha256"] = source_digest(path)
    return result


def _load_state(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".scenelight-copy")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def sync_project(
    project_root: Path,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> SyncResult:
    """Synchronize authored project files into SceneLight's managed copy.

    Files are copied rather than hard-linked so an analyzer or a Ren'Py cache
    writer cannot mutate the selected project through a shared inode.
    """

    source = project_root.expanduser().resolve()
    if not (source / "game").is_dir():
        raise FileNotFoundError(f"Ren'Py game folder not found: {source / 'game'}")
    managed = managed_project_root(source)
    managed.mkdir(parents=True, exist_ok=True)
    state_path = managed / STATE_NAME
    old_state = _load_state(state_path)
    old_files = old_state.get("source_files", {})
    if not isinstance(old_files, dict):
        old_files = {}

    source_files = []
    for file_path in source.rglob("*"):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(source)
        if _is_source_file(relative):
            source_files.append((file_path, relative))

    current: dict[str, dict[str, int | str]] = {}
    copied: list[str] = []
    total_files = len(source_files)
    if progress is not None:
        progress(0, total_files, "inventory ready")
    for file_index, (file_path, relative) in enumerate(source_files, start=1):
        key = relative.as_posix()
        content = key.lower() == "scenelight.json" or (
            relative.parts[0].lower() == "game"
            and (file_path.suffix.lower() in VISUAL_SOURCE_SUFFIXES or is_effect_source(relative))
        )
        metadata = _metadata(file_path, content=content)
        current[key] = metadata
        target = managed / relative
        target_matches = target.is_file() and _metadata(target, content=content) == metadata
        if old_files.get(key) != metadata or not target_matches:
            _copy_atomic(file_path, target)
            copied.append(key)
        if progress is not None and (
            file_index == 1 or file_index % 200 == 0 or file_index == total_files
        ):
            progress(file_index, total_files, key)

    removed: list[str] = []
    for key in sorted(set(old_files) - set(current)):
        target = managed / Path(key)
        if target.is_file() and not _is_reserved_managed_file(Path(key)):
            target.unlink()
            removed.append(key)

    # Remove files created by a foreign Ren'Py compiler, while preserving the
    # isolated SceneLight runtime, maps, cache, and launcher.
    for target in managed.rglob("*"):
        if not target.is_file():
            continue
        relative = target.relative_to(managed)
        key = relative.as_posix()
        if key not in current and not _is_reserved_managed_file(relative):
            target.unlink()
            removed.append(key)

    _atomic_json(
        state_path,
        {
            "version": 1,
            "source": str(source),
            "source_files": current,
        },
    )
    return SyncResult(source, managed, tuple(sorted(set(copied))), tuple(sorted(set(removed))))


def find_native_executable(project_root: Path) -> Path | None:
    """Choose the distribution's own Windows launcher, never an external SDK."""

    root = project_root.expanduser().resolve()
    candidates = [
        path
        for path in root.glob("*.exe")
        if path.is_file() and not path.stem.lower().endswith("-32")
    ]
    if not candidates:
        candidates = [path for path in root.glob("*.exe") if path.is_file()]
    if not candidates:
        return None
    expected = re.sub(r"[^a-z0-9]", "", root.name.lower())

    def rank(path: Path) -> tuple[int, int, str]:
        stem = re.sub(r"[^a-z0-9]", "", path.stem.lower())
        return (0 if stem == expected else 1, len(path.name), path.name.lower())

    return min(candidates, key=rank)


def renpy_runtime_major(runtime: Path | None) -> int | None:
    """Return the bundled Ren'Py major version without executing the game.

    Ren'Py 6/7 distributions expose a literal ``version_tuple`` while newer
    Ren'Py 8 distributions keep the version in ``renpy/vc_version.py``.  The
    library directory names are a final, deliberately conservative fallback
    for distributions that removed those source files.
    """

    if runtime is None:
        return None
    candidate = runtime.expanduser().resolve()
    root = candidate.parent if candidate.is_file() else candidate

    version_file = root / "renpy" / "vc_version.py"
    try:
        version_text = version_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        version_text = ""
    match = re.search(r"(?m)^\s*version\s*=\s*[uU]?['\"](\d+)(?:\.|['\"])", version_text)
    if match:
        return int(match.group(1))

    init_file = root / "renpy" / "__init__.py"
    try:
        init_text = init_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        init_text = ""
    match = re.search(r"version_tuple\s*=\s*\(\s*(\d+)\s*,", init_text)
    if match:
        return int(match.group(1))

    library = root / "lib"
    try:
        names = {path.name.lower() for path in library.iterdir() if path.is_dir()}
    except OSError:
        names = set()
    if any(name.startswith("py3-") for name in names):
        return 8
    if any(name.startswith("py2-") for name in names):
        return 7
    if any(name.startswith("windows-") for name in names):
        return 6
    return None


def renpy_sdk_prefix(runtime: Path) -> tuple[Path, ...]:
    """Return the supported command prefix for an unpacked Ren'Py SDK."""

    return (runtime.expanduser().resolve(),)


def renpy_runtime_command(
    runtime: Path,
    project_root: Path,
    *,
    native_runtime: bool,
    command: str = "run",
) -> list[str]:
    """Build a tracked command for a native distribution or external SDK."""

    executable = runtime.expanduser().resolve()
    if native_runtime:
        return [str(executable)]
    return [
        *(str(part) for part in renpy_sdk_prefix(executable)),
        str(project_root.expanduser().resolve()),
        command,
    ]


def remove_managed_project(project_root: Path) -> bool:
    """Remove only SceneLight's managed copy after validating its ownership."""

    source = project_root.expanduser().resolve()
    managed = managed_project_root(source)
    root = storage_root()
    if not managed.exists():
        return False
    if managed.parent.resolve() != root.resolve() or managed == root:
        raise ValueError(f"Refusing to remove an unexpected managed path: {managed}")
    state = _load_state(managed / STATE_NAME)
    recorded = state.get("source")
    if not recorded or Path(str(recorded)).resolve() != source:
        raise ValueError(f"Managed copy ownership could not be verified: {managed}")
    # Ren'Py can keep its process/current-directory handle alive briefly after
    # the last game window disappears.  Windows reports that race as WinError
    # 32 at the final directory removal even though every managed file has
    # already been deleted.  Keep the already-validated ownership decision and
    # retry only this managed path; never broaden the target to its parent.
    deadline = time.monotonic() + 15.0
    delay = 0.05
    while True:
        try:
            shutil.rmtree(managed)
            break
        except FileNotFoundError:
            break
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32}:
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "SceneLight's managed copy is still in use. Close the "
                    "SceneLight-launched game, wait a moment, and choose Remove again. "
                    "The selected game/mod was not changed."
                ) from error
            time.sleep(delay)
            delay = min(delay * 1.6, 0.75)
    return True


def visual_sources_changed(result: SyncResult) -> bool:
    return any(
        Path(path).name.lower() == "scenelight.json"
        or Path(path).suffix.lower() in VISUAL_SOURCE_SUFFIXES
        or is_effect_source(Path(path))
        for path in (*result.copied, *result.removed)
    )
