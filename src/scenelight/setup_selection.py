"""Setup selection helpers shared by the controller and tests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .calibration import profile_path


def character_review_candidates(payload: dict[str, object]) -> dict[str, str | None]:
    """Decode scan candidates without trusting arbitrary payload types."""

    raw = payload.get("character_candidates", {})
    if not isinstance(raw, dict):
        return {}
    candidates: dict[str, str | None] = {}
    for raw_tag, raw_preview in raw.items():
        parts = str(raw_tag).strip().lower().split()
        if not parts or not re.fullmatch(r"[a-z0-9_]+", parts[0]):
            continue
        tag = parts[0]
        candidates[tag] = str(raw_preview) if isinstance(raw_preview, str) else None
    return dict(sorted(candidates.items()))


def character_review_mode(payload: dict[str, object]) -> str:
    """Keep existing choices; new installations include detected characters."""

    auto_include = payload.get("auto_include_new_characters")
    if isinstance(auto_include, bool):
        return "automatic" if auto_include else "manual"
    mode = payload.get("character_selection")
    if isinstance(mode, str) and mode in {"manual", "automatic"}:
        return mode
    return "automatic" if mode is None else "manual"


def character_review_selected_tags(payload: dict[str, object]) -> set[str]:
    """Use one selection rule for visible checks and persisted update policy."""

    def tags(key: str) -> set[str]:
        values = payload.get(key, [])
        return (
            {str(value).strip().lower() for value in values} if isinstance(values, list) else set()
        )

    chosen = tags("explicit_character_tags")
    if character_review_mode(payload) == "automatic":
        chosen.update(tags("suggested_character_tags") | tags("character_tags"))
    return chosen - tags("excluded_character_tags")


def character_review_required(
    payload: dict[str, object], *, installed: bool, force: bool = False
) -> bool:
    """Require deliberate review for first install or newly suggested families."""

    if force or not installed:
        return True
    if character_review_mode(payload) == "automatic":
        return False
    explicit = payload.get("explicit_character_tags", [])
    suggested = payload.get("suggested_character_tags", payload.get("character_tags", []))
    explicit_tags = (
        {str(tag).strip().lower() for tag in explicit if isinstance(tag, str) and str(tag).strip()}
        if isinstance(explicit, list)
        else set()
    )
    suggested_tags = (
        {str(tag).strip().lower() for tag in suggested if isinstance(tag, str) and str(tag).strip()}
        if isinstance(suggested, list)
        else set()
    )
    excluded = payload.get("excluded_character_tags", [])
    excluded_tags = set(excluded) if isinstance(excluded, list) else set()
    return bool(suggested_tags - explicit_tags - excluded_tags)


def save_character_selection(
    project_root: Path,
    mode: str,
    tags: list[str],
    *,
    candidates: list[str] | None = None,
) -> Path:
    """Save an authoritative per-user selection outside the chosen game."""

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"manual", "automatic"}:
        raise ValueError("Character selection mode must be manual or automatic")
    normalized_tags: list[str] = []
    for raw in tags:
        parts = raw.strip().lower().split()
        if parts and re.fullmatch(r"[a-z0-9_]+", parts[0]):
            normalized_tags.append(parts[0])
    normalized_tags = sorted(set(normalized_tags))
    destination = profile_path(project_root)
    payload: dict[str, object] = {}
    project_config = project_root / "scenelight.json"
    if project_config.is_file():
        configured = json.loads(project_config.read_text(encoding="utf-8"))
        if isinstance(configured, dict) and "excluded_character_tags" in configured:
            payload["excluded_character_tags"] = configured["excluded_character_tags"]
    if destination.is_file():
        loaded = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("The existing SceneLight profile is not a JSON object")
        payload.update(loaded)
    payload["character_selection"] = normalized_mode
    payload["auto_include_new_characters"] = normalized_mode == "automatic"
    payload["character_tags"] = normalized_tags
    prior_exclusions = payload.get("excluded_character_tags", [])
    prior_exclusions = prior_exclusions if isinstance(prior_exclusions, list) else []
    excluded = set()
    for value in [*prior_exclusions, *(candidates or [])]:
        parts = str(value).strip().lower().split()
        if parts and re.fullmatch(r"[a-z0-9_]+", parts[0]):
            excluded.add(parts[0])
    excluded.difference_update(normalized_tags)
    payload["excluded_character_tags"] = sorted(excluded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination
