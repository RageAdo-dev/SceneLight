"""Preserve Ren'Py statement identities while isolated analyzers compile scripts.

Source-backed rpyc files are more than disposable execution caches: Ren'Py uses
their previous AST to retain statement names when a script is edited. Losing
those names can move a loaded save back to an earlier explicit label.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


def source_candidates(compiled: Path) -> tuple[Path, ...]:
    if compiled.suffix.lower() == ".rpyc":
        return compiled.with_suffix(".rpy"), compiled.with_name(compiled.stem + "_ren.py")
    if compiled.suffix.lower() == ".rpymc":
        return (compiled.with_suffix(".rpym"),)
    return ()


def generated_script_cache(relative: Path, source_keys) -> bool:
    """Only retain bytecode with a corresponding current authored source."""
    return any(candidate.as_posix() in source_keys for candidate in source_candidates(relative))


def _bytecode(game_root: Path):
    for directory, names, filenames in os.walk(game_root):
        names[:] = [
            name
            for name in names
            if name not in {"cache", "saves", "scenelight_runtime"} and not name.startswith(".sl-")
        ]
        for name in filenames:
            if name.startswith(("scenelight_runtime.", "scenelight_capture.")):
                continue
            path = Path(directory) / name
            if any(source.is_file() for source in source_candidates(path)):
                yield path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_root(game_root: Path) -> Path:
    return game_root.parent / ".scenelight_cache" / "playback-bytecode"


def _backup_name(relative: str) -> str:
    # Do not duplicate deeply nested game paths beneath the recovery directory.
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24] + ".bin"


def restore_playback_bytecode(game_root: Path) -> None:
    backup = _backup_root(game_root)
    record = backup / "index.json"
    if not record.exists():
        return
    payload = json.loads(record.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in (1, 2)
        or not isinstance(payload.get("files"), dict)
    ):
        raise RuntimeError("The playback script recovery index is invalid; retain it for support.")
    originals = {}
    resolved_game = game_root.resolve()
    for name, expected in payload["files"].items():
        relative = Path(name)
        target = game_root / relative
        if (
            relative.is_absolute()
            or relative.drive
            or ".." in relative.parts
            or not source_candidates(relative)
        ):
            raise RuntimeError("Unsafe path in playback script recovery index.")
        if resolved_game not in target.resolve().parents:
            raise RuntimeError("Playback script recovery path escapes the game.")
        saved = backup / "files" / (_backup_name(name) if payload["version"] == 2 else relative)
        if not saved.is_file() or _digest(saved) != expected:
            raise RuntimeError("Playback script recovery file is missing or changed: " + name)
        originals[name] = (target, saved)
    # Verify all backups before changing anything. Preserve the backups until
    # the entire restore finishes so recovery itself can be interrupted.
    for path in list(_bytecode(game_root)):
        if path.relative_to(game_root).as_posix() not in originals:
            path.unlink()
    for target, saved in originals.values():
        if not any(source.is_file() for source in source_candidates(target)):
            continue  # Never resurrect a deleted source as a compiled-only script.
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".sl-bc-" + uuid.uuid4().hex[:8])
        try:
            shutil.copy2(saved, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    shutil.rmtree(backup)


@contextmanager
def preserve_playback_bytecode(game_root: Path):
    restore_playback_bytecode(game_root)
    backup = _backup_root(game_root)
    backup.parent.mkdir(parents=True, exist_ok=True)
    stage = backup.with_name(".bytecode-" + uuid.uuid4().hex[:8])
    stage.mkdir()
    try:
        files = {}
        for path in _bytecode(game_root):
            relative = path.relative_to(game_root)
            saved = stage / "files" / _backup_name(relative.as_posix())
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
            files[relative.as_posix()] = _digest(saved)
        (stage / "index.json").write_text(
            json.dumps({"version": 2, "files": files}), encoding="utf-8"
        )
        os.replace(stage, backup)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    try:
        yield
    finally:
        restore_playback_bytecode(game_root)
