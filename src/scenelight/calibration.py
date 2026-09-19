"""Versioned, bounded controls for SceneLight's live GPU renderer."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .sidecar import storage_root

CALIBRATION_VERSION = 1


@dataclass(frozen=True, slots=True)
class Calibration:
    """Creative controls whose defaults reproduce the validated renderer."""

    auto_strength: float = 0.88
    exposure_bias: float = 0.0
    ambient_strength: float = 1.0
    color_adaptation: float = 0.78
    contrast_match: float = 0.72
    saturation_match: float = 0.58
    highlight_rolloff: float = 1.2
    key_strength: float = 0.82
    ray_shadow_strength: float = 0.58
    ambient_occlusion: float = 0.34
    probe_strength: float = 0.48
    bounce_strength: float = 0.32
    specular_strength: float = 0.24
    rim_strength: float = 0.64
    wrap_strength: float = 0.42
    grain_match: float = 0.52
    shadow_strength: float = 0.62
    individual_light_colors: float = 0.0
    adaptive_light_colors: float = 1.0
    glow_strength: float = 0.0
    glow_radius: float = 1.0
    emission_strength: float = 0.0
    emission_radius: float = 0.35
    emission_red: float = 1.0
    emission_green: float = 1.0
    emission_blue: float = 1.0

    def normalized(self) -> "Calibration":
        values = asdict(self)
        for name in values:
            if name == "exposure_bias":
                values[name] = max(-4.0, min(float(values[name]), 4.0))
            else:
                values[name] = max(0.0, min(float(values[name]), 2.0))
        return Calibration(**values)

    def as_dict(self) -> dict[str, float]:
        return asdict(self.normalized())

    def uniform_blocks(self) -> tuple[tuple[float, float, float, float], ...]:
        value = self.normalized()
        return (
            (
                value.auto_strength,
                value.exposure_bias,
                value.ambient_strength,
                value.color_adaptation,
            ),
            (
                value.contrast_match,
                value.saturation_match,
                value.highlight_rolloff,
                value.key_strength,
            ),
            (
                value.ray_shadow_strength,
                value.ambient_occlusion,
                value.probe_strength,
                value.bounce_strength,
            ),
            (
                value.specular_strength,
                value.rim_strength,
                value.wrap_strength,
                value.grain_match,
            ),
            (
                value.shadow_strength,
                value.individual_light_colors,
                value.adaptive_light_colors,
                0.0,
            ),
            (
                value.glow_strength,
                value.glow_radius,
                value.emission_strength,
                value.emission_radius,
            ),
            (value.emission_red, value.emission_green, value.emission_blue, 0.0),
        )

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        base: "Calibration | None" = None,
    ) -> "Calibration":
        if value is None:
            return base or cls()
        if not isinstance(value, dict):
            raise ValueError("SceneLight calibration must be a JSON object")
        names = {field.name for field in fields(cls)}
        unknown = sorted(set(value) - names)
        if unknown:
            raise ValueError("Unknown SceneLight calibration setting(s): " + ", ".join(unknown))
        values = asdict(base or cls())
        for name, raw in value.items():
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"SceneLight calibration {name!r} must be a number")
            values[name] = float(raw)
        return cls(**values).normalized()


def lighting_mode_preset(name: str) -> tuple[float, Calibration]:
    """Return a live-preview strength/calibration pair for a public light mode."""

    mode = str(name).strip().lower().replace("-", "_")
    if mode in {"physical", "combined", "realistic"}:
        return 1.0, Calibration()
    if mode in {"separate", "individual", "creative"}:
        return 1.0, Calibration(individual_light_colors=1.0)
    if mode == "cinematic":
        return 0.72, Calibration(
            exposure_bias=-0.22,
            color_adaptation=0.92,
            individual_light_colors=1.0,
        )
    raise ValueError("SceneLight light mode must be physical, cinematic, or separate")


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    calibration: Calibration = Calibration()
    scenes: dict[str, Calibration] | None = None
    strength: float = 1.0

    def for_scene(self, scene_name: str | None) -> Calibration:
        if not scene_name or not self.scenes:
            return self.calibration
        return self.scenes.get(scene_name.strip().lower(), self.calibration)

    def to_payload(self) -> dict[str, Any]:
        return {
            "calibration_version": CALIBRATION_VERSION,
            "strength": self.normalized_strength(),
            "calibration": self.calibration.as_dict(),
            "scene_calibration": {
                name: value.as_dict() for name, value in sorted((self.scenes or {}).items())
            },
        }

    @classmethod
    def from_payload(cls, payload: object) -> "CalibrationProfile":
        if not isinstance(payload, dict):
            raise ValueError("SceneLight profile must contain a JSON object")
        version = payload.get("calibration_version", CALIBRATION_VERSION)
        if version != CALIBRATION_VERSION:
            raise ValueError(
                f"Unsupported SceneLight calibration version {version!r}; "
                f"expected {CALIBRATION_VERSION}"
            )
        calibration = Calibration.from_mapping(payload.get("calibration"))
        raw_strength = payload.get("strength", 1.0)
        if isinstance(raw_strength, bool) or not isinstance(raw_strength, (int, float)):
            raise ValueError("SceneLight profile strength must be a number")
        strength = max(0.0, min(float(raw_strength), 1.5))
        raw_scenes = payload.get("scene_calibration", {})
        if not isinstance(raw_scenes, dict):
            raise ValueError("scene_calibration must be a JSON object")
        scenes: dict[str, Calibration] = {}
        for raw_name, raw_value in raw_scenes.items():
            name = " ".join(str(raw_name).lower().split())
            if not name:
                raise ValueError("Scene calibration names cannot be empty")
            scenes[name] = Calibration.from_mapping(raw_value, base=calibration)
        return cls(calibration=calibration, scenes=scenes, strength=strength)

    def normalized_strength(self) -> float:
        return max(0.0, min(float(self.strength), 1.5))


def profile_path(project_root: Path) -> Path:
    """Return the external per-project profile path without touching the project."""

    managed = storage_root()
    digest = hashlib.sha256(
        os.path.normcase(str(project_root.expanduser().resolve())).encode("utf-8")
    ).hexdigest()[:12]
    return managed.parent / "profiles" / f"{digest}.json"


def load_profile(path: Path) -> CalibrationProfile:
    if not path.is_file():
        return CalibrationProfile()
    return CalibrationProfile.from_payload(json.loads(path.read_text(encoding="utf-8")))


def save_profile(path: Path, profile: CalibrationProfile) -> None:
    """Atomically save a profile to an explicitly selected local path."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(profile.to_payload(), indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def merge_profile_into_config(path: Path, profile: CalibrationProfile) -> None:
    """Explicitly export calibration while preserving existing discovery settings."""

    payload: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Existing SceneLight config must contain a JSON object")
        payload.update(loaded)
    payload.update(profile.to_payload())
    _save_config_payload(path, payload)


def _save_config_payload(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
