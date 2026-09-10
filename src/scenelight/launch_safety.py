"""Native launcher routing and save snapshots for installed SceneLight games."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

LAUNCHER_CONFIG = Path("game/scenelight_runtime/native-launcher.txt")
ORIGINAL_LAUNCHER_DIR = Path("game/scenelight_runtime/original-launcher")
_SAVE_DIRECTORY_RE = re.compile(
    r"(?m)^\s*(?:(?:define|default)\s+)?(?:renpy\.)?config\.save_directory\s*=\s*"
    r"(['\"])(?P<name>[^'\"]+)\1"
)


def launcher_asset() -> Path:
    return Path(__file__).resolve().parent / "assets" / "scenelight-launcher.exe"


def detect_save_directory(project_root: Path) -> str | None:
    game_root = project_root.expanduser().resolve() / "game"
    candidates = sorted(game_root.rglob("*.rpy")) if game_root.is_dir() else []
    for path in candidates:
        if "scenelight_runtime" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _SAVE_DIRECTORY_RE.search(text)
        if match:
            name = match.group("name").strip()
            if name and not any(part in name for part in ("/", "\\", "..")):
                return name
    return None


def _save_backup_root(project_root: Path) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".scenelight"
    digest = hashlib.sha256(
        os.path.normcase(str(project_root.resolve())).encode("utf-8")
    ).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return base / "SceneLight" / "save-backups" / digest / stamp


def _save_sources(
    project_root: Path,
    save_directory: str | None,
) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = [("project-saves", project_root / "game" / "saves")]
    appdata = os.environ.get("APPDATA")
    if appdata and save_directory:
        sources.append(("renpy-saves", Path(appdata) / "RenPy" / save_directory))
    return sources


def newer_runtime_save_files(
    project_root: Path,
    *,
    save_directory: str | None = None,
    baseline_major: int = 6,
) -> tuple[Path, ...]:
    """Return saves written by a newer Ren'Py major without unpickling them."""

    root = project_root.expanduser().resolve()
    save_directory = save_directory or detect_save_directory(root)
    if save_directory and any(part in save_directory for part in ("/", "\\", "..")):
        raise ValueError("Unsafe Ren'Py save-directory identifier")
    newer: list[Path] = []
    for _label, source in _save_sources(root, save_directory):
        if not source.is_dir():
            continue
        for path in source.rglob("*.save"):
            try:
                with zipfile.ZipFile(path) as archive:
                    version = archive.read("renpy_version").decode(
                        "utf-8",
                        errors="replace",
                    )
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
                continue
            match = re.search(r"Ren'Py\s+(\d+)(?:\.|\s|$)", version)
            if match and int(match.group(1)) > baseline_major:
                newer.append(path.resolve())
    return tuple(sorted(set(newer), key=lambda item: os.path.normcase(str(item))))


def snapshot_saves(
    project_root: Path,
    *,
    save_directory: str | None = None,
) -> dict[str, object]:
    """Copy every known save location before changing an installed launch path."""

    root = project_root.expanduser().resolve()
    save_directory = save_directory or detect_save_directory(root)
    if save_directory and any(part in save_directory for part in ("/", "\\", "..")):
        raise ValueError("Unsafe Ren'Py save-directory identifier")
    sources = _save_sources(root, save_directory)
    existing = [(label, path) for label, path in sources if path.is_dir()]
    if not existing:
        return {
            "created": False,
            "path": None,
            "save_directory": save_directory,
            "sources": [],
        }

    destination = _save_backup_root(root)
    destination.mkdir(parents=True, exist_ok=False)
    copied: list[dict[str, str]] = []
    for label, source in existing:
        target = destination / label
        shutil.copytree(source, target)
        copied.append({"source": str(source), "backup": str(target)})
    (destination / "README.txt").write_text(
        "SceneLight created this safety snapshot before changing the game's launch path.\n"
        "It is not restored automatically because doing so could overwrite newer progress.\n",
        encoding="utf-8",
    )
    return {
        "created": True,
        "path": str(destination),
        "save_directory": save_directory,
        "sources": copied,
    }


def install_native_launcher(
    project_root: Path,
    playback_executable: Path,
) -> dict[str, object]:
    """Route the distribution's ordinary EXE through SceneLight's compatible runtime."""

    from .sidecar import find_native_executable

    root = project_root.expanduser().resolve()
    runtime = playback_executable.expanduser().resolve()
    if not runtime.is_file():
        raise FileNotFoundError(f"SceneLight playback runtime not found: {runtime}")
    executable = find_native_executable(root)
    if executable is None:
        raise FileNotFoundError("This Ren'Py distribution has no Windows game executable.")
    asset = launcher_asset()
    if not asset.is_file():
        raise FileNotFoundError("SceneLight's native launcher component is missing.")

    backup = root / ORIGINAL_LAUNCHER_DIR / executable.name
    config = root / LAUNCHER_CONFIG
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.is_file():
        temporary_backup = backup.with_name(backup.name + ".tmp")
        shutil.copy2(executable, temporary_backup)
        os.replace(temporary_backup, backup)

    temporary_config = config.with_name(f".{config.name}-{uuid.uuid4().hex}.tmp")
    temporary_config.write_text(str(runtime) + "\n", encoding="utf-8")
    os.replace(temporary_config, config)
    temporary_executable = executable.with_name(f".{executable.name}-{uuid.uuid4().hex}.tmp")
    shutil.copy2(asset, temporary_executable)
    os.replace(temporary_executable, executable)
    return {
        "executable": str(executable),
        "original_backup": str(backup),
        "config": str(config),
        "runtime": str(runtime),
    }


def restore_native_launcher(project_root: Path, metadata: dict[str, object]) -> Path:
    root = project_root.expanduser().resolve()
    executable_value = Path(str(metadata["executable"]))
    backup_value = Path(str(metadata["original_backup"]))
    executable = (
        executable_value if executable_value.is_absolute() else root / executable_value
    ).resolve()
    backup = (backup_value if backup_value.is_absolute() else root / backup_value).resolve()
    if root not in executable.parents or root not in backup.parents:
        raise RuntimeError("SceneLight launcher metadata escapes the selected project.")
    if not backup.is_file():
        raise FileNotFoundError("The original game executable backup is missing.")
    temporary = executable.with_name(f".{executable.name}-{uuid.uuid4().hex}.tmp")
    shutil.copy2(backup, temporary)
    os.replace(temporary, executable)
    return executable
