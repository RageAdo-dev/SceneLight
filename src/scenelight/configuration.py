"""Resolve project settings for discovery, installation, and Preview."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .calibration import profile_path


@dataclass(frozen=True)
class ProjectSettings:
    values: dict[str, object]
    sources: tuple[Path, ...]


def _merge(base: dict, incoming: dict) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def resolve_project_settings(project_root: Path, explicit: Path | None = None) -> ProjectSettings:
    root = project_root.expanduser().resolve()
    paths = [root / "scenelight.json", profile_path(root)]
    if explicit is not None:
        selected = explicit.expanduser().resolve()
        paths = [path for path in paths if path != selected] + [selected]
    values: dict[str, object] = {}
    sources = []
    for path in paths:
        if not path.is_file():
            continue
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError(f"SceneLight config must contain a JSON object: {path}")
        _merge(values, loaded)
        sources.append(path)
    return ProjectSettings(values, tuple(sources))
