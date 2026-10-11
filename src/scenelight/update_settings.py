"""Separate live lighting/selection settings from inputs that require analysis."""

from __future__ import annotations

import copy
import hashlib
import json

from .calibration import CalibrationProfile

LIVE_SETTINGS = {
    "calibration_version",
    "calibration",
    "strength",
    "scene_calibration",
    "character_tags",
    "excluded_character_tags",
    "character_selection",
    "auto_include_new_characters",
}


def analysis_config_sha256(config: dict) -> str:
    """Keep only a digest in the distributable install record, not local paths."""
    inputs = {key: value for key, value in config.items() if key not in LIVE_SETTINGS}
    return hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _tags(values):
    return (
        {parts[0] for value in values if (parts := str(value).lower().split())}
        if isinstance(values, list)
        else set()
    )


def selection_settings(config: dict) -> dict:
    """Record only normalized character choices, without asset paths."""
    mode = str(config.get("character_selection", "automatic")).strip().lower()
    if mode not in {"automatic", "manual"}:
        raise ValueError("character_selection must be 'automatic' or 'manual'")
    automatic = config.get("auto_include_new_characters")
    if automatic is not None and not isinstance(automatic, bool):
        raise ValueError("auto_include_new_characters must be true or false")
    automatic = mode == "automatic" if automatic is None else automatic

    excluded = _tags(config.get("excluded_character_tags", []))
    return {
        "automatic": automatic,
        "explicit": sorted(_tags(config.get("character_tags", [])) - excluded),
        "excluded": sorted(excluded),
    }


def settings_manifest(
    runtime: dict, forms: dict, config: dict, previous_selection: dict | None = None
) -> dict | None:
    """Reuse maps only for already prepared families; uncertain coverage rebuilds."""
    if not isinstance(runtime.get("calibration"), dict) or "character_tags" not in runtime:
        return None
    if not isinstance(forms.get("sprites", {}), dict) or not isinstance(
        runtime.get("scenes", {}), dict
    ):
        return None
    if any(not isinstance(scene, dict) for scene in runtime.get("scenes", {}).values()):
        return None
    profile = CalibrationProfile.from_payload(config)
    choices = selection_settings(config)
    automatic = choices["automatic"]

    current = _tags(runtime["character_tags"])
    available = current | {name.split()[0] for name in forms.get("sprites", {}) if name.split()}
    excluded = set(choices["excluded"])
    explicit = set(choices["explicit"])
    if automatic:
        # Switching manual -> automatic may discover unprepared families. Do
        # not infer coverage from whichever sprite happens to be on screen.
        if not runtime.get("auto_include_new_characters", True):
            return None
        # An explicitly added effect family may not be an inferred character.
        # Removing that opt-in needs discovery unless it was explicitly excluded.
        if not isinstance(previous_selection, dict) or (
            _tags(previous_selection.get("explicit", [])) - explicit - excluded
        ):
            return None
        restored = _tags(runtime.get("excluded_character_tags", [])) - excluded
        requested = (current | explicit | restored) - excluded
    else:
        requested = explicit
    if not requested <= available:
        return None
    updated = copy.deepcopy(runtime)
    updated.update(
        character_tags=sorted(requested),
        excluded_character_tags=sorted(excluded),
        auto_include_new_characters=automatic,
        strength=profile.normalized_strength(),
        calibration=profile.calibration.as_dict(),
    )
    for name, scene in updated.get("scenes", {}).items():
        scene["calibration"] = profile.for_scene(name.split("::", 1)[0]).as_dict()
    return updated
