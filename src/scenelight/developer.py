"""Transactional, ownership-safe SceneLight embedding for mod authors.

This module provides the reversible in-place workflow: it adds one previously
unused namespace, records every added file by hash, and refuses to remove
anything after it has been changed or mixed with unowned content.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat as stat_mode
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .calibration import profile_path
from .file_verification import bounded_file_work, verified_digest
from .launch_safety import (
    LAUNCHER_CONFIG,
    ORIGINAL_LAUNCHER_DIR,
    install_native_launcher,
    newer_runtime_save_files,
    restore_native_launcher,
    snapshot_saves,
)
from .progress import ProgressStage, copytree_with_progress
from .release import (
    release_content_sha256_from_manifest,
    release_record,
    release_version_from_manifest,
)
from .script_cache import source_candidates
from .sidecar import find_native_executable, remove_analysis_cache, renpy_sdk_prefix
from .source_types import VISUAL_SOURCE_SUFFIXES, is_effect_source

MANIFEST_NAME = ".scenelight_developer_install.json"
EMBED_ROOT = Path("game/scenelight_runtime")
BOOTSTRAP_NAME = "bootstrap.rpy"
RECOVERY_NAME = "REMOVE-SCENELIGHT.txt"
LEGACY_LAUNCHER_NAME = "Launch with SceneLight.bat"
SAVE_COMPAT_PATH = Path("game/scenelight_save_compat.rpy")
SAVE_COMPAT_MANIFEST_NAME = ".scenelight_save_compat.json"


@dataclass(frozen=True, slots=True)
class DeveloperStatus:
    installed: bool
    clean: bool
    files: tuple[str, ...]
    missing: tuple[str, ...]
    modified: tuple[str, ...]
    unowned: tuple[str, ...]
    refresh_required: bool = False
    changed_sources: tuple[str, ...] = ()
    installed_version: str | None = None
    installed_content_sha256: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_source_state(
    project_root: Path, *, progress: ProgressStage | None = None
) -> dict[str, list[int | str]]:
    """Track authored bytes, including timestamp-preserving asset replacements."""

    state: dict[str, list[int | str]] = {}
    root_config = project_root / "scenelight.json"
    if root_config.is_file():
        stat = root_config.stat()
        if progress is not None:
            progress.set_item(root_config.name)
        state[root_config.name] = [stat.st_size, stat.st_mtime_ns, _sha256(root_config)]
        if progress is not None:
            progress.advance()

    game_root = project_root / "game"
    if not game_root.is_dir():
        return state
    for directory, names, filenames in os.walk(game_root, topdown=True):
        current = Path(directory)
        if current == game_root:
            names[:] = [
                name
                for name in names
                if name.lower() not in {"cache", "saves", "scenelight_runtime"}
                and not name.lower().startswith((".scenelight-developer-", ".sl-"))
            ]
        else:
            names[:] = [
                name
                for name in names
                if not name.lower().startswith((".scenelight-developer-", ".sl-"))
            ]
        for filename in filenames:
            path = current / filename
            suffix = path.suffix.lower()
            relative = path.relative_to(project_root)
            if suffix not in VISUAL_SOURCE_SUFFIXES and not is_effect_source(relative):
                continue
            if any(source.is_file() for source in source_candidates(path)):
                # A source-backed compiler cache is not a new authored input. Keep
                # compiled-only games/mods trackable when no source twin exists.
                continue
            stat = path.stat()
            if progress is not None:
                progress.set_item(relative.as_posix())
            state[relative.as_posix()] = [stat.st_size, stat.st_mtime_ns, _sha256(path)]
            if progress is not None:
                progress.advance()
    return dict(sorted(state.items()))


def _installation_source_state(project_root: Path) -> dict[str, list[int | str]]:
    with ProgressStage("source-index", item="Reading source file fingerprints") as progress:
        return _tracked_source_state(project_root, progress=progress)


def _runtime_file_hashes(
    project_root: Path, destination_root: Path, *, expected=None, stamps=None, verified_out=None
) -> dict[str, str]:
    with ProgressStage("runtime-hashes", item="Counting prepared files") as progress:
        paths = []
        for path in destination_root.rglob("*"):
            if path.is_file():
                paths.append(path)
                progress.set_item(f"Counting prepared files: {len(paths):,} found")
        progress.set_total(len(paths))
        known = expected or {}
        identities = stamps or {}
        relative_paths = {path.relative_to(project_root).as_posix(): path for path in paths}
        missing = set(known) - set(relative_paths)
        if missing:
            raise RuntimeError(
                "Prepared runtime files disappeared: " + ", ".join(sorted(missing)[:5])
            )

        def check(item):
            relative, path = item
            digest, stamp, reused = verified_digest(
                path, known.get(relative), identities.get(relative)
            )
            if relative in known and digest != known[relative]:
                raise RuntimeError(f"Prepared runtime changed after verification: {relative}")
            return relative, digest, stamp, reused

        files = {}
        reused_count = 0
        for relative, digest, stamp, reused in bounded_file_work(
            check, relative_paths.items(), workers=None if identities else 1
        ):
            progress.set_item(relative)
            files[relative] = digest
            if stamp and verified_out is not None:
                verified_out[relative] = stamp
            reused_count += reused
            progress.advance()
        print(
            f"SceneLight files: {reused_count:,} verified checksums reused; {len(files) - reused_count:,} files read",
            flush=True,
        )
        return files


def _prepared_integrity(install):
    """Map the verified managed payload to its embedded names."""
    hashes = install.get("runtime_files", {})
    stamps = install.get("runtime_file_stamps", {})
    if not isinstance(hashes, dict) or not isinstance(stamps, dict):
        return {}, {}
    excluded = {
        (EMBED_ROOT / BOOTSTRAP_NAME).as_posix(),
        (EMBED_ROOT / RECOVERY_NAME).as_posix(),
        LAUNCHER_CONFIG.as_posix(),
    }
    prefix = EMBED_ROOT.as_posix() + "/"
    result = {
        key: value
        for key, value in hashes.items()
        if key.startswith(prefix)
        and key not in excluded
        and not key.startswith(ORIGINAL_LAUNCHER_DIR.as_posix() + "/")
    }
    script = "game/scenelight_runtime.rpy"
    if script in hashes:
        result[(EMBED_ROOT / BOOTSTRAP_NAME).as_posix()] = hashes[script]
    return result, stamps


def _analyzed_sources(project_root, install):
    # Keep the analyzed snapshot, so edits made during publication are still
    # discovered by the next update instead of being marked already prepared.
    source = install.get("source")
    snapshot = install.get("source_state")
    if (
        isinstance(source, str)
        and Path(source).resolve() == project_root
        and isinstance(snapshot, dict)
    ):
        return snapshot
    return _installation_source_state(project_root)


def _save_install_manifest(path: Path, payload: dict) -> None:
    with ProgressStage("install-record", item="Writing installation ownership details"):
        _atomic_json(path, payload)


def _changed_source_paths(previous: object, current: dict[str, list[int | str]]) -> tuple[str, ...]:
    if not isinstance(previous, dict):
        return ()
    names = set(previous) | set(current)
    return tuple(sorted(name for name in names if previous.get(name) != current.get(name)))


def _config_record(project_root: Path, install: dict[str, object]) -> str | None:
    raw = install.get("config")
    if not raw:
        return None
    resolved = Path(str(raw)).expanduser().resolve()
    if resolved == profile_path(project_root):
        return "$profile"
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        # Never leak an arbitrary local path into a manifest the mod author may
        # commit. Advanced external configs must be supplied again when a
        # checkout is refreshed on another computer.
        return "$external"


def _recorded_config_path(project_root: Path, record: object) -> Path | None:
    if record == "$profile":
        return profile_path(project_root)
    if not isinstance(record, str) or not record or record == "$external":
        return None
    relative = Path(record)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    resolved = (project_root / relative).resolve()
    return resolved if project_root in resolved.parents else None


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".scenelight-manifest-{uuid.uuid4().hex}.tmp")
    created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(json.dumps(payload, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if created and temporary.is_file():
            temporary.unlink()


def _save_compat_asset() -> Path:
    return Path(__file__).resolve().parent / "assets" / "scenelight-save-compat.rpy"


def _save_compat_manifest(project_root: Path) -> dict[str, object] | None:
    path = project_root / SAVE_COMPAT_MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(
            f"SceneLight save-compatibility manifest is unreadable: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise RuntimeError("SceneLight save-compatibility manifest is invalid.")
    if payload.get("file") != SAVE_COMPAT_PATH.as_posix():
        raise RuntimeError("SceneLight save-compatibility manifest has an unsafe path.")
    return payload


def _preflight_save_compat_bridge(project_root: Path) -> tuple[Path, Path, str]:
    asset = _save_compat_asset()
    if not asset.is_file():
        raise FileNotFoundError("SceneLight's save-compatibility component is missing.")
    expected_hash = _sha256(asset)
    destination = (project_root / SAVE_COMPAT_PATH).resolve()
    if project_root not in destination.parents:
        raise RuntimeError("SceneLight save-compatibility path escapes the project.")
    if destination.exists() and (
        not destination.is_file() or _sha256(destination) != expected_hash
    ):
        raise RuntimeError(
            "Removal stopped before changing the game because "
            f"{SAVE_COMPAT_PATH.as_posix()} already exists and is not SceneLight's "
            "verified save-compatibility file."
        )
    previous = _save_compat_manifest(project_root)
    if previous is not None and previous.get("sha256") != expected_hash:
        raise RuntimeError(
            "Removal stopped because SceneLight's save-compatibility ownership record "
            "does not match this release."
        )
    return asset, destination, expected_hash


def _install_save_compat_bridge(
    project_root: Path,
    *,
    save_backup: dict[str, object],
    newer_save_count: int,
) -> Path:
    asset, destination, expected_hash = _preflight_save_compat_bridge(project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        temporary = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(asset, temporary)
            os.replace(temporary, destination)
        finally:
            if temporary.is_file():
                temporary.unlink()
    _atomic_json(
        project_root / SAVE_COMPAT_MANIFEST_NAME,
        {
            "version": 1,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "file": SAVE_COMPAT_PATH.as_posix(),
            "sha256": expected_hash,
            "reason": "Preserves saves written by SceneLight's newer compatibility runtime.",
            "newer_save_count": newer_save_count,
            "save_directory": save_backup.get("save_directory"),
            "save_backup": save_backup,
        },
    )
    return destination


def _manifest(project_root: Path) -> dict[str, object] | None:
    path = project_root / MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(
            f"SceneLight developer ownership manifest is unreadable: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("SceneLight developer ownership manifest is not a JSON object.")
    return payload


def _owned_paths(project_root: Path, manifest: dict[str, object]) -> dict[str, Path]:
    version = manifest.get("version")
    if version not in {1, 2, 3}:
        raise RuntimeError("Unsupported SceneLight developer ownership manifest version.")
    if manifest.get("namespace") != EMBED_ROOT.as_posix():
        raise RuntimeError("SceneLight developer ownership manifest has an invalid namespace.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("SceneLight developer ownership manifest has no files.")

    result: dict[str, Path] = {}
    resolved_parents: dict[Path, Path] = {}
    for key, expected_hash in files.items():
        if not isinstance(key, str) or not isinstance(expected_hash, str):
            raise RuntimeError("SceneLight developer ownership manifest contains invalid entries.")
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe path in SceneLight developer manifest: {key}")
        parent = resolved_parents.get(relative.parent)
        if parent is None:
            parent = (project_root / relative.parent).resolve()
            resolved_parents[relative.parent] = parent
        destination = parent / relative.name
        if destination.is_symlink():
            destination = destination.resolve()
        if project_root not in destination.parents:
            raise RuntimeError(f"Path escapes the selected project: {key}")
        in_namespace = relative.parts[: len(EMBED_ROOT.parts)] == EMBED_ROOT.parts
        legacy_launcher = version == 2 and relative == Path(LEGACY_LAUNCHER_NAME)
        native_launcher = manifest.get("native_launcher") if version == 3 else None
        native_executable = isinstance(
            native_launcher, dict
        ) and relative.as_posix() == native_launcher.get("executable")
        if not in_namespace and not legacy_launcher and not native_executable:
            raise RuntimeError(f"Path is outside SceneLight's reserved namespace: {key}")
        result[key] = destination
    return result


def _recognized_compiler_output(relative: str, owned: set[str]) -> bool:
    path = Path(relative)
    if path.suffix.lower() != ".rpyc":
        return False
    return path.with_suffix(".rpy").as_posix() in owned


def developer_status(
    project: Path, *, check_sources: bool = True, verified_out=None
) -> DeveloperStatus:
    project_root = project.expanduser().resolve()
    manifest = _manifest(project_root)
    if manifest is None:
        return DeveloperStatus(False, True, (), (), (), ())
    owned_paths = _owned_paths(project_root, manifest)
    expected = manifest["files"]
    assert isinstance(expected, dict)
    missing: list[str] = []
    modified: list[str] = []
    stamps = manifest.get("file_stamps", {})
    if not isinstance(stamps, dict):
        stamps = {}

    def check(item):
        key, path = item
        if not path.is_file():
            return key, None, None
        digest, stamp, _ = verified_digest(path, expected[key], stamps.get(key))
        return key, digest, stamp

    for key, digest, stamp in bounded_file_work(
        check, owned_paths.items(), workers=None if stamps else 1
    ):
        if digest is None:
            missing.append(key)
        elif digest != expected[key]:
            modified.append(key)
        elif stamp and verified_out is not None:
            verified_out[key] = stamp

    owned = set(owned_paths)
    unowned: list[str] = []
    embed_root = project_root / EMBED_ROOT
    if embed_root.is_dir():
        for path in embed_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(project_root).as_posix()
            if relative not in owned and not _recognized_compiler_output(relative, owned):
                unowned.append(relative)
    elif embed_root.exists():
        modified.append(EMBED_ROOT.as_posix())

    previous_source_state = manifest.get("source_state")
    changed_sources = (
        (
            _changed_source_paths(previous_source_state, _tracked_source_state(project_root))
            if isinstance(previous_source_state, dict)
            else ("SceneLight source inventory upgrade",)
        )
        if check_sources
        else ()
    )
    recorded_config = manifest.get("config")
    recorded_config_hash = manifest.get("config_sha256")
    config_path = _recorded_config_path(project_root, recorded_config)
    if recorded_config is None:
        new_profile = profile_path(project_root)
        if new_profile.is_file():
            config_path = new_profile
    if config_path is not None:
        current_config_hash = _sha256(config_path) if config_path.is_file() else None
        if current_config_hash != recorded_config_hash:
            changed_sources = tuple(sorted({*changed_sources, "SceneLight profile"}))

    return DeveloperStatus(
        True,
        not missing and not modified and not unowned,
        tuple(sorted(owned)),
        tuple(sorted(missing)),
        tuple(sorted(modified)),
        tuple(sorted(unowned)),
        bool(changed_sources),
        changed_sources,
        release_version_from_manifest(manifest),
        release_content_sha256_from_manifest(manifest),
    )


def _recovery_text(*, native_launcher: bool) -> str:
    launcher_line = (
        "  the game's normal executable (the original is backed up below)\n"
        if native_launcher
        else ""
    )
    return f"""SceneLight developer integration recovery

SceneLight did not edit an existing story or authored game file. It added only:

  game/scenelight_runtime/
{launcher_line}  .scenelight_developer_install.json

Normal removal should be done from SceneLight so hashes are verified and
the original game executable is restored before SceneLight files are removed.
If SceneLight itself is unavailable, close the game and delete exactly the
folder and manifest listed above. Do not delete the game's `game` folder.
"""


def _legacy_launcher_text(executable: Path) -> str:
    values = [str(part.resolve()) for part in renpy_sdk_prefix(executable)]
    working_directory = str(executable.resolve().parent)
    if any(
        '"' in value or any(ord(character) < 32 for character in value)
        for value in [*values, working_directory]
    ):
        raise ValueError("The compatibility-runtime path contains an unsupported character.")
    quoted = " ".join('"' + value.replace("%", "%%") + '"' for value in values)
    quoted_directory = '"' + working_directory.replace("%", "%%") + '"'
    return "\r\n".join(
        (
            "@echo off",
            "setlocal",
            f"pushd {quoted_directory}",
            f'{quoted} "%~dp0" run',
            'set "scenelight_exit=%errorlevel%"',
            "popd",
            'if not "%scenelight_exit%"=="0" pause',
            "endlocal & exit /b %scenelight_exit%",
            "",
        )
    )


def _managed_runtime_sources(managed_root: Path) -> tuple[Path, Path, dict[str, object]]:
    source_script = managed_root / "game" / "scenelight_runtime.rpy"
    source_data = managed_root / "game" / "scenelight_runtime"
    if not source_script.is_file() or not source_data.is_dir():
        raise FileNotFoundError(
            "The managed SceneLight runtime is incomplete; install and verify it first."
        )
    install_path = managed_root / ".scenelight_install.json"
    try:
        install = json.loads(install_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        install = {}
    return source_script, source_data, install if isinstance(install, dict) else {}


def _plain_runtime_tree(root: Path) -> bool:
    """Only move private regular files, never links into another workspace."""
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                info = os.stat(entry.path, follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                    return False
                if stat_mode.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif not stat_mode.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return False
    return True


def _stage_runtime(
    project_root: Path,
    source_script: Path,
    source_data: Path,
    *,
    native_launcher: bool,
    consume_managed: bool = False,
) -> tuple[Path, Path, bool]:
    game_root = project_root / "game"
    if not game_root.is_dir():
        raise FileNotFoundError(f"Ren'Py game folder not found: {game_root}")
    # Keep this transaction directory deliberately short. Generated sprite-map
    # filenames can be long enough that the previous 61-character staging name
    # crossed Win32's traditional MAX_PATH boundary in otherwise valid games.
    stage = game_root / f".sl-{uuid.uuid4().hex[:8]}"
    staged_data = stage / "runtime"
    consumed = False
    try:
        if consume_managed:
            live = project_root / EMBED_ROOT
            if (
                source_data.resolve() != source_data
                or source_data == live
                or live in source_data.parents
                or source_data in live.parents
            ):
                raise RuntimeError("Prepared runtime must be in a separate, unlinked workspace.")
            with ProgressStage("runtime-copy", item="Checking prepared files for safe transfer"):
                consume_managed = _plain_runtime_tree(source_data)
        if consume_managed:
            stage.mkdir()
            with ProgressStage(
                "runtime-copy", total=1, item="Transferring the prepared runtime"
            ) as progress:
                try:
                    os.replace(source_data, staged_data)
                    consumed = True
                    progress.advance()
                except OSError as error:
                    if error.errno != errno.EXDEV and getattr(error, "winerror", None) != 17:
                        raise
            if not consumed:
                copytree_with_progress(source_data, staged_data, "runtime-copy")
        else:
            copytree_with_progress(source_data, staged_data, "runtime-copy")
        shutil.rmtree(staged_data / ORIGINAL_LAUNCHER_DIR.name, ignore_errors=True)
        staged_config = staged_data / LAUNCHER_CONFIG.name
        if staged_config.is_file():
            staged_config.unlink()
        staged_bootstrap = staged_data / BOOTSTRAP_NAME
        staged_recovery = staged_data / RECOVERY_NAME
        # Generated transaction files must never be written through a reused
        # hard link, even if a malformed managed tree supplied those names.
        staged_bootstrap.unlink(missing_ok=True)
        staged_recovery.unlink(missing_ok=True)
        shutil.copy2(source_script, staged_bootstrap)
        staged_recovery.write_text(
            _recovery_text(native_launcher=native_launcher), encoding="utf-8"
        )
    except Exception:
        _discard_staged_runtime(stage, staged_data, source_data, consumed)
        raise
    return stage, staged_data, consumed


def _discard_staged_runtime(stage, data, source_data, consumed):
    if data.is_dir():
        if consumed:
            if source_data.exists():
                # A different process populated the workspace. Keep both copies.
                stage.mkdir(exist_ok=True)
                recovery = stage / "prepared-recovery"
                os.replace(data, recovery)
                print(f"SceneLight retained prepared files for recovery: {recovery}", flush=True)
            else:
                os.replace(data, source_data)
        else:
            shutil.rmtree(data)
    if stage.is_dir() and not any(stage.iterdir()):
        stage.rmdir()


def preflight_embed_destination(project: Path) -> None:
    """Refuse an occupied in-place namespace before analysis starts."""

    project_root = project.expanduser().resolve()
    if _manifest(project_root) is not None:
        raise FileExistsError(
            "SceneLight is already embedded. Remove the existing clean integration before refreshing it."
        )
    destination_root = project_root / EMBED_ROOT
    manifest_path = project_root / MANIFEST_NAME
    if destination_root.exists() or manifest_path.exists():
        raise FileExistsError(
            "The reserved game/scenelight_runtime namespace already exists. "
            "SceneLight will not overwrite or adopt it."
        )


def preflight_refresh_destination(
    project: Path, *, item: str = "Checking ownership of the existing runtime"
) -> None:
    """Require a current, fully owned direct install before expensive analysis."""

    project_root = project.expanduser().resolve()
    manifest = _manifest(project_root)
    if manifest is None:
        raise FileNotFoundError("SceneLight is not embedded in this project yet.")
    if manifest.get("version") != 3:
        raise RuntimeError(
            "This developer installation predates safe refresh support. Remove it through "
            "SceneLight, then install the current developer API once."
        )
    with ProgressStage("install-verify", item=item):
        status = developer_status(project_root, check_sources=False)
    if not status.clean:
        details = [*(f"missing: {path}" for path in status.missing)]
        details.extend(f"modified: {path}" for path in status.modified)
        details.extend(f"unowned: {path}" for path in status.unowned)
        raise RuntimeError(
            "Refresh refused before analysis because the embedded namespace did not pass "
            "ownership verification: " + "; ".join(details)
        )


def embed_from_managed(
    project: Path, managed_project: Path, *, consume_managed: bool = False
) -> dict[str, object]:
    """Publish a verified sidecar runtime in a new, reserved project namespace."""

    project_root = project.expanduser().resolve()
    managed_root = managed_project.expanduser().resolve()
    preflight_embed_destination(project_root)
    destination_root = project_root / EMBED_ROOT
    manifest_path = project_root / MANIFEST_NAME

    source_script, source_data, install = _managed_runtime_sources(managed_root)
    playback_native = bool(install.get("playback_native", True))
    playback_value = install.get("playback_executable")
    legacy_playback = bool(playback_value) and not playback_native
    playback_executable = (
        Path(str(playback_value)).expanduser().resolve() if playback_value else None
    )
    managed_save_backup = install.get("save_backup")
    managed_save_directory = (
        managed_save_backup.get("save_directory") if isinstance(managed_save_backup, dict) else None
    )
    native_executable = find_native_executable(project_root)
    if legacy_playback and (playback_executable is None or not playback_executable.is_file()):
        raise FileNotFoundError(
            "The Ren'Py 7 compatibility runtime recorded for this legacy game is unavailable."
        )
    stage, staged_data, consumed = _stage_runtime(
        project_root,
        source_script,
        source_data,
        native_launcher=legacy_playback,
        consume_managed=consume_managed,
    )
    created_final = False
    native_launcher: dict[str, object] | None = None
    save_backup: dict[str, object] | None = None
    try:
        os.replace(staged_data, destination_root)
        created_final = True
        stage.rmdir()

        if legacy_playback and native_executable is not None:
            assert playback_executable is not None
            save_backup = snapshot_saves(
                project_root,
                save_directory=(str(managed_save_directory) if managed_save_directory else None),
            )
            installed_launcher = install_native_launcher(project_root, playback_executable)
            native_launcher = {
                "executable": Path(str(installed_launcher["executable"]))
                .relative_to(project_root)
                .as_posix(),
                "original_backup": Path(str(installed_launcher["original_backup"]))
                .relative_to(project_root)
                .as_posix(),
                "config": Path(str(installed_launcher["config"]))
                .relative_to(project_root)
                .as_posix(),
                "runtime": str(installed_launcher["runtime"]),
            }

        expected, stamps = _prepared_integrity(install)
        file_stamps = {}
        files = _runtime_file_hashes(
            project_root,
            destination_root,
            expected=expected,
            stamps=stamps if consumed else {},
            verified_out=file_stamps,
        )
        if native_launcher is not None:
            executable_relative = str(native_launcher["executable"])
            files[executable_relative] = _sha256(project_root / executable_relative)
        _save_install_manifest(
            manifest_path,
            {
                "version": 3,
                "scenelight_version": __version__,
                "release": release_record(),
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "namespace": EMBED_ROOT.as_posix(),
                "files": dict(sorted(files.items())),
                "file_stamps": file_stamps,
                "native_launcher": native_launcher,
                "save_backup": save_backup,
                "source_state": _analyzed_sources(project_root, install),
                "config": _config_record(project_root, install),
                "inspector_enabled": install.get("inspector_enabled", True),
                "config_sha256": install.get("config_sha256"),
                "analysis_config_sha256": install.get("analysis_config_sha256"),
                "selection_settings": install.get("selection_settings"),
            },
        )
    except Exception:
        if native_launcher is not None:
            restore_native_launcher(project_root, native_launcher)
        _discard_staged_runtime(
            stage, destination_root if created_final else staged_data, source_data, consumed
        )
        if manifest_path.is_file():
            manifest_path.unlink()
        raise

    return {
        "ok": True,
        "project": str(project_root),
        "developer_embedded": True,
        "owned_file_count": len(files),
        "manifest": str(manifest_path),
        "namespace": str(destination_root),
        "existing_files_modified": native_launcher is not None,
        "manual_recovery": (
            "Use SceneLight to restore the original executable before removing files."
            if native_launcher is not None
            else f"Delete only {destination_root} and {manifest_path}"
        ),
        "launcher": (
            str(project_root / str(native_launcher["executable"]))
            if native_launcher is not None
            else None
        ),
        "save_backup": save_backup,
        "prepared_runtime_transferred": consumed,
    }


def refresh_embedded_from_managed(
    project: Path,
    managed_project: Path,
    *,
    consume_managed: bool = False,
    preflight_complete: bool = False,
) -> dict[str, object]:
    """Transactionally replace a verified direct runtime with freshly analyzed data."""

    project_root = project.expanduser().resolve()
    managed_root = managed_project.expanduser().resolve()
    if not preflight_complete:
        preflight_refresh_destination(project_root)
    manifest_path = project_root / MANIFEST_NAME
    original_manifest_hash = _sha256(manifest_path)
    original_manifest = _manifest(project_root)
    assert original_manifest is not None
    destination_root = project_root / EMBED_ROOT
    source_script, source_data, install = _managed_runtime_sources(managed_root)
    native_launcher = original_manifest.get("native_launcher")
    launcher_owned = isinstance(native_launcher, dict)
    stage, staged_data, consumed = _stage_runtime(
        project_root,
        source_script,
        source_data,
        native_launcher=launcher_owned,
        consume_managed=consume_managed,
    )
    backup = destination_root.parent / f".sl-backup-{uuid.uuid4().hex[:8]}"
    destination_moved = False
    replacement_installed = False
    manifest_updated = False
    cleanup_warning: str | None = None
    try:
        if launcher_owned:
            owned_paths = _owned_paths(project_root, original_manifest)
            for field in ("original_backup", "config"):
                relative_text = native_launcher.get(field)
                if not isinstance(relative_text, str):
                    raise RuntimeError(
                        "The existing native-launcher ownership record is incomplete."
                    )
                source = owned_paths.get(relative_text)
                relative = Path(relative_text)
                if source is None or not source.is_file() or EMBED_ROOT not in relative.parents:
                    raise RuntimeError(
                        "The existing native-launcher recovery files could not be preserved."
                    )
                target = staged_data / relative.relative_to(EMBED_ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        # Re-verify after potentially long analysis/staging so a concurrent
        # manual edit can never be overwritten by the refresh swap.
        preflight_refresh_destination(
            project_root, item="Rechecking ownership before replacing the runtime"
        )
        if _sha256(manifest_path) != original_manifest_hash:
            raise RuntimeError(
                "Installation ownership changed during refresh; retry after the other operation finishes."
            )
        os.replace(destination_root, backup)
        destination_moved = True
        os.replace(staged_data, destination_root)
        replacement_installed = True
        stage.rmdir()

        expected, stamps = _prepared_integrity(install)
        file_stamps = {}
        files = _runtime_file_hashes(
            project_root,
            destination_root,
            expected=expected,
            stamps=stamps if consumed else {},
            verified_out=file_stamps,
        )
        if launcher_owned:
            executable_relative = native_launcher.get("executable")
            if not isinstance(executable_relative, str):
                raise RuntimeError("The existing native-launcher ownership record is incomplete.")
            executable_path = project_root / executable_relative
            if not executable_path.is_file():
                raise RuntimeError("The existing SceneLight launcher disappeared during refresh.")
            files[executable_relative] = _sha256(executable_path)
        refreshed_manifest = {
            "version": 3,
            "scenelight_version": __version__,
            "release": release_record(),
            "installed_at": original_manifest.get("installed_at"),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "namespace": EMBED_ROOT.as_posix(),
            "files": dict(sorted(files.items())),
            "file_stamps": file_stamps,
            "native_launcher": native_launcher,
            "save_backup": original_manifest.get("save_backup"),
            "source_state": _analyzed_sources(project_root, install),
            "config": _config_record(project_root, install),
            "inspector_enabled": install.get("inspector_enabled", True),
            "config_sha256": install.get("config_sha256"),
            "analysis_config_sha256": install.get("analysis_config_sha256"),
            "selection_settings": install.get("selection_settings"),
        }
        _save_install_manifest(manifest_path, refreshed_manifest)
        manifest_updated = True
        try:
            with ProgressStage("runtime-cleanup", item="Removing the replaced runtime"):
                shutil.rmtree(backup)
        except OSError as error:
            # The refreshed install and ownership record are already complete.
            # Do not risk rolling back from a partially removed backup tree.
            cleanup_warning = f"Old verified runtime backup could not be removed: {error}"
    except Exception:
        _discard_staged_runtime(
            stage, destination_root if replacement_installed else staged_data, source_data, consumed
        )
        if destination_moved and backup.is_dir() and not destination_root.exists():
            os.replace(backup, destination_root)
        if manifest_updated:
            _atomic_json(manifest_path, original_manifest)
        raise

    return {
        "ok": True,
        "project": str(project_root),
        "developer_embedded": True,
        "developer_refreshed": True,
        "owned_file_count": len(files),
        "manifest": str(manifest_path),
        "namespace": str(destination_root),
        "existing_files_modified": False,
        "launcher": (
            str(project_root / str(native_launcher["executable"])) if launcher_owned else None
        ),
        "save_backup": original_manifest.get("save_backup"),
        "cleanup_warning": cleanup_warning,
        "prepared_runtime_transferred": consumed,
    }


def remove_embedded(project: Path) -> dict[str, object]:
    """Remove a clean developer integration, or refuse before deleting anything."""

    project_root = project.expanduser().resolve()
    manifest = _manifest(project_root)
    if manifest is None:
        return {
            "ok": True,
            "project": str(project_root),
            "removed": False,
            "reason": "not installed",
        }
    status = developer_status(project_root)
    if status.missing or status.modified or status.unowned:
        details = [*(f"missing: {path}" for path in status.missing)]
        details.extend(f"modified: {path}" for path in status.modified)
        details.extend(f"unowned: {path}" for path in status.unowned)
        raise RuntimeError(
            "Removal refused before deleting anything because the embedded namespace changed: "
            + "; ".join(details)
        )

    owned_paths = _owned_paths(project_root, manifest)
    native_launcher = manifest.get("native_launcher")
    restored_executable: Path | None = None
    removal_save_backup: dict[str, object] | None = None
    compatibility_bridge: Path | None = None
    newer_saves: tuple[Path, ...] = ()
    if isinstance(native_launcher, dict):
        recorded_backup = manifest.get("save_backup")
        recorded_save_directory = (
            recorded_backup.get("save_directory") if isinstance(recorded_backup, dict) else None
        )
        newer_saves = newer_runtime_save_files(
            project_root,
            save_directory=(str(recorded_save_directory) if recorded_save_directory else None),
            baseline_major=6,
        )
        if newer_saves:
            # Refuse an occupied compatibility path before making even the
            # uninstall-time safety snapshot or restoring the old executable.
            _preflight_save_compat_bridge(project_root)
        removal_save_backup = snapshot_saves(
            project_root,
            save_directory=(str(recorded_save_directory) if recorded_save_directory else None),
        )
        if newer_saves:
            compatibility_bridge = _install_save_compat_bridge(
                project_root,
                save_backup=removal_save_backup,
                newer_save_count=len(newer_saves),
            )
        restored_executable = restore_native_launcher(project_root, native_launcher)
    owned = set(owned_paths)
    embed_root = project_root / EMBED_ROOT
    compiler_outputs = [
        path
        for path in embed_root.rglob("*.rpyc")
        if _recognized_compiler_output(path.relative_to(project_root).as_posix(), owned)
    ]
    for path in compiler_outputs:
        path.unlink()
    for path in sorted(owned_paths.values(), key=lambda item: len(item.parts), reverse=True):
        if restored_executable is not None and path == restored_executable:
            continue
        if path.is_file():
            path.unlink()
    for directory in sorted(
        (path for path in embed_root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.rmdir()
    if embed_root.is_dir():
        embed_root.rmdir()
    (project_root / MANIFEST_NAME).unlink()
    analysis_cache_removed = False
    analysis_cache_warning: str | None = None
    try:
        analysis_cache_removed = remove_analysis_cache(project_root)
    except (OSError, ValueError) as error:
        # The verified game removal is already complete. Report a narrowly
        # scoped cache cleanup problem without pretending the game is modified.
        analysis_cache_warning = str(error)
    return {
        "ok": True,
        "project": str(project_root),
        "removed": True,
        "owned_file_count": len(owned_paths),
        "existing_files_modified": restored_executable is not None,
        "save_backup": removal_save_backup,
        "newer_save_count": len(newer_saves),
        "save_compatibility_bridge": (
            str(compatibility_bridge) if compatibility_bridge is not None else None
        ),
        "analysis_cache_removed": analysis_cache_removed,
        "analysis_cache_warning": analysis_cache_warning,
    }
