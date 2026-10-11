"""Install or remove the optional in-game inspector without rebuilding assets."""

from __future__ import annotations

import json
from pathlib import Path

from .calibration import profile_path
from .developer import MANIFEST_NAME, _atomic_json, _sha256
from .sidecar import managed_project_root
from .updates import _publish, read_json, recover_update, runtime_payload

INSPECTOR_FILES = ("game/scenelight_runtime/inspector.rpy", "game/scenelight_runtime/inspector.txt")
INSPECTOR_CACHE = "game/scenelight_runtime/inspector.rpyc"


def _preference_path(project: Path) -> Path:
    profile = profile_path(project)
    return profile.with_name(profile.stem + ".inspector.json")


def _installation(project: Path, embedded: bool) -> tuple[Path, Path]:
    root = project.expanduser().resolve() if embedded else managed_project_root(project)
    return root, root / (MANIFEST_NAME if embedded else ".scenelight_install.json")


def inspector_enabled(project: Path, *, embedded: bool) -> bool:
    _root, manifest = _installation(project, embedded)
    record = read_json(manifest)
    if record:
        return record.get("inspector_enabled", True) is not False
    return read_json(_preference_path(project)).get("enabled", True) is not False


def set_inspector_enabled(project: Path, enabled: bool, *, embedded: bool) -> dict:
    """Called under the project operation lock; only inspector code is touched."""
    if not isinstance(enabled, bool):
        raise ValueError("Inspector setting must be on or off.")
    project = project.expanduser().resolve()
    if not (project / "game").is_dir():
        raise ValueError("Choose a Ren'Py project containing a game folder.")
    root, manifest = _installation(project, embedded)
    recover_update(root)
    if not manifest.exists():
        if (root / "game/scenelight_runtime").exists():
            raise RuntimeError(
                "Unowned SceneLight files found. Review the installation before changing the inspector."
            )
        preference = _preference_path(project)
        preference.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(preference, {"enabled": enabled})
        return {
            "ok": True,
            "inspector_enabled": enabled,
            "installed": False,
            "project": str(project),
        }
    old = json.loads(manifest.read_text(encoding="utf-8"))
    key = "files" if embedded else "runtime_files"
    if not isinstance(old, dict) or not isinstance(old.get(key), dict) or not old[key]:
        raise RuntimeError("The installation ownership record is invalid. Update SceneLight first.")
    if (
        embedded and (old.get("version") != 3 or old.get("namespace") != "game/scenelight_runtime")
    ) or (not embedded and old.get("version") != 1):
        raise RuntimeError(
            "Update this older SceneLight installation before changing its inspector."
        )
    full_payload = runtime_payload(embedded=embedded)
    bootstrap = (
        "game/scenelight_runtime/bootstrap.rpy" if embedded else "game/scenelight_runtime.rpy"
    )
    if enabled and (
        not (root / bootstrap).is_file()
        or _sha256(root / bootstrap) != _sha256(full_payload[bootstrap])
    ):
        raise RuntimeError(
            "Update SceneLight before enabling this inspector; the installed runtime is a different build."
        )
    expected = dict(old[key])
    previous = dict(expected)
    changed = {}
    for relative in (*INSPECTOR_FILES, INSPECTOR_CACHE):
        target = root / relative
        if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
            raise RuntimeError("Inspector path escapes its installation: " + relative)
        actual = _sha256(target) if target.is_file() else None
        if relative == INSPECTOR_CACHE and relative not in expected and actual is not None:
            if INSPECTOR_FILES[0] not in previous:
                raise RuntimeError(
                    "Unowned compiled inspector found; review the installation first."
                )
            previous[relative] = actual
        elif actual != expected.get(relative):
            raise RuntimeError(
                "Inspector was edited or is missing; retained it for review: " + relative
            )
        source = full_payload.get(relative) if enabled else None
        digest = _sha256(source) if source is not None else None
        if digest is None:
            expected.pop(relative, None)
        else:
            expected[relative] = digest
        if actual != digest:
            changed[relative] = source
    new = dict(old, inspector_enabled=enabled)
    new[key] = expected
    if changed:
        counts = _publish(root, new, changed, embedded, previous)
    else:
        _atomic_json(manifest, new)
        counts = {"code_files_replaced": 0, "code_files_removed": 0, "derived_files_copied": 0}
    return {
        "ok": True,
        "inspector_enabled": enabled,
        "installed": True,
        "project": str(project),
        "installation": "in-place" if embedded else "managed",
        "backgrounds_reanalyzed": 0,
        "sprites_reanalyzed": 0,
        **counts,
    }
