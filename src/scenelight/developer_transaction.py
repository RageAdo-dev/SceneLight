"""Recoverable publication of an embedded runtime and its ownership record."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from . import developer as dev

JOURNAL = ".scenelight_developer_transaction.json"


def _tree_files(root: Path, record: dict | None) -> dict[str, str]:
    if record is None:
        return {}
    owned = dev._owned_paths(root, record)
    prefix = dev.EMBED_ROOT.as_posix() + "/"
    result = {key[len(prefix) :]: record["files"][key] for key in owned if key.startswith(prefix)}
    for path in (root / dev.EMBED_ROOT).rglob("*.rpyc"):
        relative = path.relative_to(root).as_posix()
        if dev._recognized_compiler_output(relative, set(owned)):
            result[path.relative_to(root / dev.EMBED_ROOT).as_posix()] = dev._sha256(path)
    return result


def _verify_tree(root: Path, tree: Path, expected: dict, *, partial=False, hash_files=True):
    dev._plain_project_path(root, tree.relative_to(root))
    found = set()
    checked = set()
    if tree.exists():
        for path in tree.rglob("*"):
            dev._plain_project_path(root, path.relative_to(root), checked=checked)
            if path.is_dir():
                continue
            key = path.relative_to(tree).as_posix()
            if key not in expected or (hash_files and dev._sha256(path) != expected[key]):
                raise RuntimeError(f"Recovery files changed; retained for review: {path}")
            found.add(key)
    if not partial and found != set(expected):
        raise RuntimeError(f"Recovery files are incomplete; retained for review: {tree}")


def _cleanup(root: Path, stage: Path, record: dict, *, hash_files=True):
    _verify_tree(root, stage, record["stage_files"], partial=True, hash_files=hash_files)
    if stage.exists():
        shutil.rmtree(stage)
    (root / JOURNAL).unlink()


def recover(root: Path, *, on_rollback=None) -> str | None:
    """Finish cleanup or restore the previous installation before another mutation."""
    journal = dev._plain_project_path(root, Path(JOURNAL))
    if not journal.exists():
        return None
    record = json.loads(journal.read_text(encoding="utf-8"))
    token = record.get("stage")
    if not isinstance(token, str) or not re.fullmatch(r"\.sl-[0-9a-f]{8}", token):
        raise RuntimeError("Invalid SceneLight recovery record; retain it for review.")
    for key in ("old_tree", "new_tree", "stage_files"):
        values = record.get(key)
        if not isinstance(values, dict):
            raise RuntimeError("Invalid SceneLight recovery file inventory.")
        for relative, digest in values.items():
            path = Path(relative)
            if (
                path.is_absolute()
                or path.drive
                or ".." in path.parts
                or not path.parts
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise RuntimeError("Invalid path or checksum in SceneLight recovery inventory.")
    if not isinstance(record.get("external"), list):
        raise RuntimeError("Invalid SceneLight launcher recovery inventory.")
    for entry in record["external"]:
        if (
            not isinstance(entry, dict)
            or not re.fullmatch(r"old-launcher-[0-9]+", str(entry.get("saved")))
            or not re.fullmatch(r"new-launcher-[0-9]+", str(entry.get("prepared")))
        ):
            raise RuntimeError("Invalid SceneLight launcher recovery copy.")
    stage = dev._plain_project_path(root, Path("game") / token)
    data = dev._plain_project_path(root, dev.EMBED_ROOT)
    manifest = dev._plain_project_path(root, Path(dev.MANIFEST_NAME))
    previous = stage / "previous"
    next_data = stage / "runtime"
    actual = dev._sha256(manifest) if manifest.is_file() else None
    old_sha, new_sha = record["old_manifest"], record["new_manifest"]
    # Removing the ownership record is the uninstall commit point. Its saved
    # copy distinguishes a committed removal from a deleted or missing record.
    removed_record = stage / "removed-record.json"
    committed = (
        record.get("state") == "committed"
        or (new_sha is not None and actual == new_sha)
        or (
            new_sha is None
            and actual is None
            and removed_record.is_file()
            and dev._sha256(removed_record) == old_sha
        )
    )
    if committed:
        if actual != new_sha:
            raise RuntimeError("Installation record changed after commit; recovery was retained.")
        record["state"] = "committed"
        dev._atomic_json(journal, record)
        _cleanup(root, stage, record)
        return "committed"
    if actual != old_sha:
        raise RuntimeError(
            "Installation record changed during interruption; recovery was retained."
        )
    if record.get("state") == "rolled_back":
        _cleanup(root, stage, record)
        return "rolled_back"

    _verify_tree(root, stage, record["stage_files"], partial=True)
    old_tree, new_tree = record["old_tree"], record["new_tree"]
    if previous.exists():
        _verify_tree(root, previous, old_tree)
        if data.exists():
            _verify_tree(root, data, new_tree)
            if next_data.exists():
                raise RuntimeError("Conflicting staged runtime; recovery was retained.")
    elif old_sha is not None:
        _verify_tree(root, data, old_tree)
    elif data.exists():
        _verify_tree(root, data, new_tree)
        if next_data.exists():
            raise RuntimeError("Conflicting staged runtime; recovery was retained.")

    # Check every external file and rollback copy before restoring any of them.
    for entry in record["external"]:
        relative = Path(entry["path"])
        if len(relative.parts) != 1 or (
            relative.suffix.lower() != ".exe" and relative != Path(dev.LEGACY_LAUNCHER_NAME)
        ):
            raise RuntimeError("Invalid launcher path in recovery record.")
        path = dev._plain_project_path(root, relative)
        digest = dev._sha256(path) if path.is_file() else None
        if digest not in (entry["old"], entry["new"]):
            raise RuntimeError(f"Launcher changed during interruption: {relative}")
        if digest != entry["old"]:
            saved = stage / entry["saved"]
            if not saved.is_file() or dev._sha256(saved) != entry["old"]:
                raise RuntimeError(f"Launcher recovery copy is incomplete: {relative}")

    if previous.exists():
        if data.exists():
            os.replace(data, next_data)
        os.replace(previous, data)
    elif old_sha is None and data.exists():
        os.replace(data, next_data)
    for entry in record["external"]:
        path = root / entry["path"]
        if not path.is_file() or dev._sha256(path) != entry["old"]:
            os.replace(stage / entry["saved"], path)
    record["state"] = "rolled_back"
    dev._atomic_json(journal, record)
    if on_rollback is not None:
        on_rollback()
    _cleanup(root, stage, record)
    return "rolled_back"


def publish(
    root: Path,
    stage: Path,
    old_record: dict | None,
    new_record: dict | None,
    *,
    external: dict[str, Path | None] | None = None,
    on_rollback=None,
) -> str | None:
    """Commit a prepared runtime; return a warning if only cleanup remains."""
    journal = dev._plain_project_path(root, Path(JOURNAL))
    if journal.exists():
        raise RuntimeError("An earlier SceneLight transaction still needs recovery.")
    data = root / dev.EMBED_ROOT
    manifest = root / dev.MANIFEST_NAME
    next_record = stage / "next-record.json"
    if new_record is not None:
        dev._save_install_manifest(next_record, new_record)
    old_tree = _tree_files(root, old_record)
    new_tree = {
        key[len(dev.EMBED_ROOT.as_posix()) + 1 :]: value
        for key, value in (new_record or {}).get("files", {}).items()
        if key.startswith(dev.EMBED_ROOT.as_posix() + "/")
    }
    entries = []
    for index, (relative, replacement) in enumerate((external or {}).items()):
        path = dev._plain_project_path(root, Path(relative))
        saved, prepared = f"old-launcher-{index}", f"new-launcher-{index}"
        shutil.copy2(path, stage / saved)
        if replacement is not None:
            shutil.copy2(replacement, stage / prepared)
        entries.append(
            {
                "path": relative,
                "old": dev._sha256(stage / saved),
                "new": dev._sha256(stage / prepared) if replacement is not None else None,
                "saved": saved,
                "prepared": prepared,
            }
        )
    record = {
        "stage": stage.name,
        "state": "prepared",
        "old_manifest": dev._sha256(manifest) if old_record is not None else None,
        "new_manifest": dev._sha256(next_record) if new_record is not None else None,
        "old_tree": old_tree,
        "new_tree": new_tree,
        "external": entries,
        "stage_files": {
            **{f"runtime/{key}": value for key, value in new_tree.items()},
            **{f"previous/{key}": value for key, value in old_tree.items()},
        },
    }
    for path in stage.iterdir():
        if path.is_file():
            record["stage_files"][path.name] = dev._sha256(path)
    if record["old_manifest"] is not None:
        record["stage_files"]["removed-record.json"] = record["old_manifest"]
    dev._atomic_json(journal, record)
    try:
        if old_record is not None:
            os.replace(data, stage / "previous")
        if new_record is not None:
            os.replace(stage / "runtime", data)
        for entry in entries:
            path = root / entry["path"]
            if entry["new"] is None:
                os.replace(path, stage / entry["saved"])
            else:
                os.replace(stage / entry["prepared"], path)
        if new_record is None:
            os.replace(manifest, stage / "removed-record.json")
        else:
            os.replace(next_record, manifest)
    except BaseException:
        recover(root, on_rollback=on_rollback)
        raise
    record["state"] = "committed"
    try:
        dev._atomic_json(journal, record)
        _cleanup(root, stage, record, hash_files=False)
    except OSError as error:
        return f"The change is complete. Cleanup will be retried: {error}"
    return None
