"""Reuse verified analysis for compatible code-only updates.

Only changed SceneLight-owned code files are replaced. Derived maps stay in
place. A small journal lets the next update restore interrupted replacements.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .developer import (
    EMBED_ROOT,
    MANIFEST_NAME,
    _atomic_json,
    _config_record,
    _plain_project_path,
    _sha256,
    _tracked_source_state,
    developer_status,
)
from .file_verification import bounded_file_work, verified_digest
from .progress import ProgressStage
from .release import release_record
from .script_cache import restore_playback_bytecode
from .sidecar import managed_project_root, storage_root
from .update_settings import analysis_config_sha256, selection_settings, settings_manifest

MODULES = (
    "live_gpu",
    "live_renpy",
    "live_opencl",
    "prepared",
    "prepared_renpy",
    "shader_stages",
    "shader_renpy",
    "inspector",
)
CONTRACTS = (
    "runtime_api_version",
    "runtime_manifest_version",
    "transport_algorithm",
    "sprite_form_version",
    "capture_version",
    "capture_plan_version",
    "capture_pixel_version",
)
JOURNAL = ".scenelight_runtime_update.json"


@contextmanager
def operation_lock(project: Path):
    key = hashlib.sha256(os.path.normcase(str(project.resolve())).encode("utf-8")).hexdigest()
    directory = storage_root().parent / "update-locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (key + ".lock")).open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(
                "Another SceneLight update is already using this project."
            ) from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def runtime_payload(*, embedded: bool, inspector: bool = True) -> dict[str, Path]:
    source = Path(__file__).with_name("runtime")
    prefix = "game/scenelight_runtime/"
    result = {
        prefix + name + ".txt": source / (name + ".py")
        for name in MODULES
        if inspector or name != "inspector"
    }
    if inspector:
        result[prefix + "inspector.rpy"] = source / "inspector.rpy"
    result[prefix + "bootstrap.rpy" if embedded else "game/scenelight_runtime.rpy"] = (
        source / "scenelight_runtime.rpy"
    )
    return result


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def same_sources(old: object, current: dict) -> bool:
    # Ignore a timestamp-only touch, but always hash bytes. Editors may preserve
    # both size and mtime when replacing artwork.
    if not isinstance(old, dict) or set(old) != set(current):
        return False
    return all(
        isinstance(old[name], list)
        and len(old[name]) == 3
        and old[name][0] == row[0]
        and old[name][2] == row[2]
        for name, row in current.items()
    )


def runtime_hashes(root: Path, *, expected=None, stamps=None, verified_out=None) -> dict[str, str]:
    known, identities = expected or {}, stamps or {}

    def check(path):
        relative = path.relative_to(root).as_posix()
        digest, stamp, _ = verified_digest(path, known.get(relative), identities.get(relative))
        return relative, digest, stamp

    result = {}
    with ProgressStage("runtime-hashes", item="Counting prepared runtime files") as progress:
        paths = [
            path
            for path in (root / EMBED_ROOT).rglob("*")
            if path.is_file() and path.suffix != ".rpyc"
        ]
        script = root / "game/scenelight_runtime.rpy"
        if script.is_file():
            paths.append(script)
        progress.set_total(len(paths))
        # Full reads stay sequential: parallel streams cause seek contention on
        # hard drives. Cached identity checks can safely use bounded concurrency.
        for relative, digest, stamp in bounded_file_work(
            check, paths, workers=None if identities else 1
        ):
            result[relative] = digest
            if stamp and verified_out is not None:
                verified_out[relative] = stamp
            progress.set_item(relative)
            progress.advance()
    return result


def _record_plan(mode: str, reason: str, **details) -> None:
    from .diagnostics import current_session

    print("SceneLight update: " + reason, flush=True)
    session = current_session()
    if session is not None:
        session.event("update.plan", reason, mode=mode, **details)


def recover_update(root: Path) -> None:
    journal = _plain_project_path(root, Path(JOURNAL))
    if not journal.exists():
        return
    record = read_json(journal)
    token = record.get("transaction")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{16}", token):
        raise RuntimeError("SceneLight update journal is invalid; retain it for a support report.")
    stage = _plain_project_path(root, Path("game") / (".sl-u-" + token))
    data = _plain_project_path(root, EMBED_ROOT)
    backup = stage / "previous"
    embedded = record.get("embedded") is True
    manifest = _plain_project_path(
        root, Path(MANIFEST_NAME if embedded else ".scenelight_install.json")
    )
    checked = set()
    for path in stage.rglob("*"):
        _plain_project_path(root, path.relative_to(root), checked=checked)
    if record.get("mode") == "files":
        entries = record.get("entries")
        allowed = set(runtime_payload(embedded=embedded)) | {
            "game/scenelight_runtime/inspector.rpyc",
            "game/scenelight_runtime/manifest.json",
        }
        if not isinstance(entries, dict) or not entries or set(entries) - allowed:
            raise RuntimeError("SceneLight update journal contains unexpected file paths.")
        committed = manifest.is_file() and _sha256(manifest) == record.get("committed_sha256")
        for relative, entry in entries.items():
            if not isinstance(entry, dict):
                raise RuntimeError("Invalid runtime update entry.")
            target = _plain_project_path(root, Path(relative))
            actual = _sha256(target) if target.is_file() else None
            acceptable = {entry.get("new_sha256"), entry.get("old_sha256")}
            if actual not in acceptable or (committed and actual != entry.get("new_sha256")):
                raise RuntimeError(
                    "Runtime changed after interruption; retained recovery files for review: "
                    + relative
                )
            if (
                not committed
                and entry.get("old_sha256") is not None
                and actual != entry["old_sha256"]
            ):
                saved = stage / "previous" / relative
                if not saved.is_file() or _sha256(saved) != entry["old_sha256"]:
                    raise RuntimeError("Runtime recovery backup is incomplete: " + relative)
        if not committed:
            saved_record = stage / "previous-record.json"
            if not saved_record.is_file() or _sha256(saved_record) != record.get(
                "previous_record_sha256"
            ):
                raise RuntimeError("Runtime recovery ownership record is incomplete.")
            if not manifest.is_file() or _sha256(manifest) != record["previous_record_sha256"]:
                raise RuntimeError(
                    "Installation record changed during update; retained recovery files."
                )
            for relative, entry in entries.items():
                target = root / relative
                if entry.get("old_sha256") is not None:
                    if not target.is_file() or _sha256(target) != entry["old_sha256"]:
                        os.replace(stage / "previous" / relative, target)
                else:
                    target.unlink(missing_ok=True)
            _record_plan("recovered", "Restored previous code after an interrupted update.")
        journal.unlink()
        shutil.rmtree(stage, ignore_errors=True)
        return
    if manifest.is_file() and _sha256(manifest) == record.get("committed_sha256"):
        # Commit completed; only old links remain to be removed.
        shutil.rmtree(stage, ignore_errors=True)
        journal.unlink()
        return
    if backup.is_dir():
        # Preserve any unexpected post-interruption edits instead of discarding
        # them. The next successful update can proceed from the restored tree.
        if data.exists():
            preserved = stage / "uncommitted"
            if preserved.exists():
                raise RuntimeError("Update recovery needs review: uncommitted files already exist.")
            os.replace(data, preserved)
        os.replace(backup, data)
    if not embedded and (stage / "previous-bootstrap").is_file():
        os.replace(stage / "previous-bootstrap", root / "game/scenelight_runtime.rpy")
    if (stage / "previous-record.json").is_file():
        os.replace(stage / "previous-record.json", manifest)
    journal.unlink()
    if not (stage / "uncommitted").exists():
        shutil.rmtree(stage, ignore_errors=True)
    _record_plan("recovered", "Restored the previous runtime after an interrupted update.")


def _publish(
    root: Path,
    new: dict,
    payload: dict[str, Path | bytes | None],
    embedded: bool,
    previous_files: dict,
) -> dict:
    token = uuid.uuid4().hex[:16]
    for relative in payload:
        _plain_project_path(root, Path(relative))
    _plain_project_path(root, Path(JOURNAL))
    stage = _plain_project_path(root, Path("game") / (".sl-u-" + token))
    stage.mkdir()
    manifest = _plain_project_path(
        root, Path(MANIFEST_NAME if embedded else ".scenelight_install.json")
    )
    entries = {}
    try:
        with ProgressStage("runtime-copy", item="Staging changed code only; maps stay in place"):
            for relative, source in payload.items():
                target = root / relative
                saved = stage / "previous" / relative
                replacement = stage / "next" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                replacement.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    shutil.copy2(target, saved)
                if isinstance(source, bytes):
                    replacement.write_bytes(source)
                elif source is not None:
                    shutil.copy2(source, replacement)
                entries[relative] = {
                    "old_sha256": _sha256(saved) if saved.exists() else None,
                    "new_sha256": _sha256(replacement) if source is not None else None,
                }
                if entries[relative]["old_sha256"] != previous_files.get(relative):
                    raise RuntimeError("Runtime was edited while staging: " + relative)
                expected_new = new["files" if embedded else "runtime_files"].get(relative)
                if entries[relative]["new_sha256"] != expected_new:
                    raise RuntimeError("SceneLight package changed while staging an update.")
            shutil.copy2(manifest, stage / "previous-record.json")
            _atomic_json(stage / "next-record.json", new)
            journal = {
                "transaction": token,
                "embedded": embedded,
                "mode": "files",
                "entries": entries,
                "previous_record_sha256": _sha256(stage / "previous-record.json"),
                "committed_sha256": _sha256(stage / "next-record.json"),
            }
            _atomic_json(root / JOURNAL, journal)
        with ProgressStage(
            "runtime-setup", item="Publishing compatible runtime; analysis retained"
        ):
            for relative in payload:
                target = root / relative
                actual = _sha256(target) if target.is_file() else None
                if actual != entries[relative]["old_sha256"]:
                    raise RuntimeError("Runtime was edited while updating: " + relative)
                if payload[relative] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage / "next" / relative, target)
            os.replace(stage / "next-record.json", manifest)
        recover_update(root)
    except BaseException:
        if (root / JOURNAL).exists():
            recover_update(root)
        else:
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "code_files_replaced": sum(path is not None for path in payload.values()),
        "code_files_removed": sum(path is None for path in payload.values()),
        "derived_files_copied": 0,
    }


def try_runtime_update(
    project: Path, *, config: Path | None, grid: tuple[int, int], embedded: bool
) -> dict | None:
    from .project import _load_config

    started = time.monotonic()
    root = project if embedded else managed_project_root(project)
    recover_update(root)
    restore_playback_bytecode(root / "game")
    manifest_path = root / (MANIFEST_NAME if embedded else ".scenelight_install.json")
    old = read_json(manifest_path)
    current_release = release_record()
    previous_release = old.get("release", {})
    if not old or (embedded and old.get("version") != 3):
        _record_plan(
            "analysis",
            "This installation needs a one-time analysis upgrade.",
            reason_code="legacy_installation",
        )
        return None
    if any(previous_release.get(key) != current_release[key] for key in CONTRACTS):
        _record_plan(
            "analysis",
            "The analysis format changed; checking reusable asset caches.",
            reason_code="analysis_format_changed",
            changed_contracts=[
                key for key in CONTRACTS if previous_release.get(key) != current_release[key]
            ],
        )
        return None
    config_hash = _sha256(config) if config is not None and config.is_file() else None
    configuration = _load_config(project, config)
    analysis_hash = analysis_config_sha256(configuration)
    runtime = read_json(root / EMBED_ROOT / "manifest.json")
    if tuple(runtime.get("transport_atlas", {}).get("grid_size", ())) != tuple(grid):
        _record_plan(
            "analysis",
            "Lighting-map resolution changed; checking asset caches.",
            reason_code="grid_changed",
        )
        return None
    with ProgressStage("source-index", item="Checking authored bytes for changes") as progress:
        sources = _tracked_source_state(project, progress=progress)
    old_sources = old.get("source_state")
    profile_changed = config_hash != old.get("config_sha256") or (
        isinstance(old_sources, dict)
        and old_sources.get("scenelight.json") != sources.get("scenelight.json")
    )
    updated_runtime = None
    if profile_changed:
        previous_analysis = old.get("analysis_config_sha256")
        previous_selection = old.get("selection_settings")
        if (
            previous_analysis is None
            and old.get("config_sha256") is None
            and isinstance(old_sources, dict)
            and "scenelight.json" not in old_sources
        ):
            previous_analysis = analysis_config_sha256({})
            previous_selection = selection_settings({})
        if previous_analysis != analysis_hash:
            _record_plan(
                "analysis",
                "Asset-discovery settings changed, or their earlier values are unavailable; checking asset caches.",
                reason_code="discovery_settings_changed",
            )
            return None
        updated_runtime = settings_manifest(
            runtime,
            read_json(root / EMBED_ROOT / "sprite_form_manifest.json"),
            configuration,
            previous_selection,
        )
        if updated_runtime is None:
            _record_plan(
                "analysis",
                "Character choices need additional asset preparation; checking asset caches.",
                reason_code="character_coverage_changed",
            )
            return None

    def without_config(state):
        return (
            {key: value for key, value in state.items() if key != "scenelight.json"}
            if isinstance(state, dict)
            else state
        )

    if not same_sources(without_config(old_sources), without_config(sources)):
        prior = old_sources if isinstance(old_sources, dict) else {}
        _record_plan(
            "analysis",
            "Authored inputs changed; refreshing inventory and reusing unchanged maps.",
            reason_code="source_files_changed",
            changed_files=[
                name
                for name in sorted(set(prior) | set(sources))
                if prior.get(name) != sources.get(name)
            ][:20],
        )
        return None
    verified_states = {}
    with ProgressStage("install-verify", item="Verifying existing runtime and maps"):
        if embedded:
            status = developer_status(project, check_sources=False, verified_out=verified_states)
            if not status.clean:
                raise RuntimeError(
                    "Runtime update refused: owned files are missing, modified, or unowned."
                )
            expected = dict(old["files"])
        else:
            expected = old.get("runtime_files")
            if (
                not isinstance(expected, dict)
                or runtime_hashes(
                    root,
                    expected=expected,
                    stamps=old.get("runtime_file_stamps"),
                    verified_out=verified_states,
                )
                != expected
            ):
                _record_plan("analysis", "Managed runtime needs repair; checking asset caches.")
                return None
            expected = dict(expected)
    payload = runtime_payload(embedded=embedded, inspector=old.get("inspector_enabled", True))
    previous_files = dict(expected)
    changed = {name: path for name, path in payload.items() if expected.get(name) != _sha256(path)}
    new = dict(old, scenelight_version=__version__, release=current_release, source_state=sources)
    new["file_stamps" if embedded else "runtime_file_stamps"] = verified_states
    new["analysis_config_sha256"] = analysis_hash
    new["selection_settings"] = selection_settings(configuration)
    new["config"] = (
        _config_record(project, {"config": str(config) if config else None})
        if embedded
        else (str(config) if config else None)
    )
    new["config_sha256"] = config_hash
    for name, path in payload.items():
        expected[name] = _sha256(path)
    if updated_runtime is not None:
        name = "game/scenelight_runtime/manifest.json"
        content = json.dumps(updated_runtime, indent=2).encode("utf-8")
        if expected.get(name) != hashlib.sha256(content).hexdigest():
            changed[name] = content
            expected[name] = hashlib.sha256(content).hexdigest()
    new["files" if embedded else "runtime_files"] = expected
    mode = (
        "settings-only"
        if profile_changed
        else "runtime-only"
        if changed or previous_release != current_release
        else "unchanged"
    )
    new["last_update"] = {
        "mode": mode,
        "runtime_files_changed": len(changed),
        "backgrounds_reanalyzed": 0,
        "sprites_reanalyzed": 0,
    }
    _record_plan(
        mode,
        "Updating lighting settings and character choices; existing asset maps are kept."
        if mode == "settings-only"
        else "Updating runtime only; no sprite capture or background analysis."
        if mode == "runtime-only"
        else "Already current; no asset analysis needed.",
        runtime_files_changed=len(changed),
    )
    if configuration != _load_config(project, config) or config_hash != (
        _sha256(config) if config is not None and config.is_file() else None
    ):
        raise RuntimeError("Settings changed during the update. Try again with the saved settings.")
    counts = _publish(root, new, changed, embedded, previous_files) if changed else {}
    if not changed:
        _atomic_json(manifest_path, new)
    report = read_json(root / EMBED_ROOT / "install_report.json")
    result = {
        "ok": True,
        "project": str(project),
        "update_mode": mode,
        "runtime_files_changed": len(changed),
        "backgrounds_reanalyzed": 0,
        "sprites_reanalyzed": 0,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "scene_count": report.get("scene_count", len(runtime.get("scenes", {}))),
        "sprite_count": report.get("sprite_count"),
        "source_untouched": True,
        "installation": "in-place" if embedded else "managed",
        "developer_embedded": embedded,
        "developer_refreshed": embedded,
        "managed_project": None if embedded else str(root),
        **counts,
    }
    _record_plan(mode, "Update complete; existing analysis preserved.", **result)
    return result
