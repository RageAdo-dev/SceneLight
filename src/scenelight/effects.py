"""Validated, shareable SceneLight GPU effect packs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .vfx_presets import VFX_PRESETS

EFFECT_PACK_FORMAT = "scenelight-effect-pack"
EFFECT_PACK_VERSION = 1
EFFECT_MANIFEST_VERSION = 1
EFFECT_FRAGMENT_PRIORITY = 600
MAX_PACK_BYTES = 256 * 1024
MAX_EFFECTS_PER_PACK = 16
MAX_PARAMETERS_PER_EFFECT = 16
MAX_FRAGMENT_CHARACTERS = 8192
MAX_SOURCE_TEXTURE_READS = 8

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_LOCAL_UNIFORM = re.compile(r"\bu__([A-Za-z][A-Za-z0-9_]*)\b")
_FORBIDDEN_FRAGMENT = (
    (re.compile(r"#"), "preprocessor directives"),
    (re.compile(r"\b(?:for|while|do)\b"), "loops"),
    (re.compile(r"\b(?:uniform|attribute|varying|sampler\w*)\b"), "variable declarations"),
    (re.compile(r"\b(?:gl_Position|gl_FragCoord)\b"), "geometry/framebuffer access"),
    (re.compile(r"\b(?:u_sc_|v_sc_|scenelight_|tex[1-9]\d*)\w*\b"), "SceneLight internals"),
    (re.compile(r"\breturn\b"), "return statements"),
)
_TEXTURE_CALL = re.compile(r"\b(?:texture|texture2D|texelFetch)\s*\(")
_SOURCE_TEXTURE_CALL = re.compile(r"\btexture2D\s*\(\s*tex0\s*,")
_PARAMETER_TYPES = {"float": 1, "vec2": 2, "vec3": 3, "vec4": 4}


class EffectPackError(ValueError):
    """Raised when an effect pack cannot be admitted safely."""


@dataclass(frozen=True, slots=True)
class EffectPackBuild:
    manifest: dict[str, object]
    warnings: tuple[str, ...]

    @property
    def effect_count(self) -> int:
        effects = self.manifest.get("effects", {})
        return len(effects) if isinstance(effects, dict) else 0


def _identifier(value: object, field: str) -> str:
    normalized = str(value).strip().lower().replace("-", "_")
    if not _IDENTIFIER.fullmatch(normalized):
        raise EffectPackError(f"{field} must use lowercase letters, numbers, and underscores")
    return normalized


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise EffectPackError(f"{field} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise EffectPackError(f"{field} must be a number") from error
    if not math.isfinite(result) or abs(result) > 65535.0:
        raise EffectPackError(f"{field} must be finite and within portable GLSL limits")
    return result


def _parameter_spec(name: str, raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise EffectPackError(f"parameter {name} must be an object")
    kind = str(raw.get("type", "float")).strip().lower()
    width = _PARAMETER_TYPES.get(kind)
    if width is None:
        raise EffectPackError(f"parameter {name} has unsupported type {kind!r}")
    minimum = _finite_number(raw.get("min", 0.0), f"parameter {name} minimum")
    maximum = _finite_number(raw.get("max", 1.0), f"parameter {name} maximum")
    if maximum < minimum:
        raise EffectPackError(f"parameter {name} maximum is below its minimum")
    default_raw = raw.get("default", 0.0 if width == 1 else [0.0] * width)
    if width == 1:
        default: float | list[float] = _finite_number(default_raw, f"parameter {name} default")
        values = [default]
    else:
        if not isinstance(default_raw, (list, tuple)) or len(default_raw) != width:
            raise EffectPackError(f"parameter {name} default must contain {width} numbers")
        values = [_finite_number(value, f"parameter {name} default") for value in default_raw]
        default = values
    if any(value < minimum or value > maximum for value in values):
        raise EffectPackError(f"parameter {name} default is outside its allowed range")
    return {
        "type": kind,
        "default": default,
        "min": minimum,
        "max": maximum,
        "label": str(raw.get("label", name.replace("_", " ").title())).strip()[:80],
    }


def _fragment_source(
    value: object,
    parameter_names: set[str],
    *,
    source_texture: bool,
) -> str:
    if not isinstance(value, str):
        raise EffectPackError("fragment must be GLSL text")
    source = value.strip()
    if not source or len(source) > MAX_FRAGMENT_CHARACTERS:
        raise EffectPackError(f"fragment must contain 1 to {MAX_FRAGMENT_CHARACTERS} characters")
    if source.count("(") != source.count(")") or source.count("{") != source.count("}"):
        raise EffectPackError("fragment has unbalanced parentheses or braces")
    for pattern, label in _FORBIDDEN_FRAGMENT:
        if pattern.search(source):
            raise EffectPackError(f"fragment may not use {label}")
    texture_calls = list(_TEXTURE_CALL.finditer(source))
    source_calls = list(_SOURCE_TEXTURE_CALL.finditer(source))
    if texture_calls and not source_texture:
        raise EffectPackError("fragment must declare source_texture to sample character art")
    if len(texture_calls) != len(source_calls):
        raise EffectPackError("fragment may only sample the character through texture2D(tex0, uv)")
    if len(source_calls) > MAX_SOURCE_TEXTURE_READS:
        raise EffectPackError(
            f"fragment exceeds {MAX_SOURCE_TEXTURE_READS} character texture reads"
        )
    if "gl_FragColor" not in source:
        raise EffectPackError("fragment must modify gl_FragColor")
    unknown = sorted(set(_LOCAL_UNIFORM.findall(source)) - parameter_names)
    if unknown:
        raise EffectPackError(f"fragment references unknown parameter u__{unknown[0]}")
    return source


def _compile_effect(pack_id: str, raw: object) -> tuple[str, dict[str, object]]:
    if not isinstance(raw, dict):
        raise EffectPackError("each effect must be an object")
    effect_id = _identifier(raw.get("id", ""), "effect id")
    public_name = f"{pack_id}.{effect_id}"
    preset_name: str | None = None
    preset = raw.get("preset")
    fragment_functions = ""
    if preset is not None:
        preset_name = _identifier(preset, f"effect {public_name} preset")
        definition = VFX_PRESETS.get(preset_name)
        if definition is None:
            raise EffectPackError(f"effect {public_name} uses unknown VFX preset {preset_name!r}")
        if any(field in raw for field in ("fragment", "parameters", "source_texture")):
            raise EffectPackError(
                f"effect {public_name} cannot replace a trusted VFX preset's shader contract"
            )
        raw_parameters = definition["parameters"]
        raw_defaults = raw.get("defaults", {})
        if not isinstance(raw_defaults, dict):
            raise EffectPackError(f"effect {public_name} defaults must be an object")
        unknown_defaults = sorted(set(raw_defaults) - set(raw_parameters))
        if unknown_defaults:
            raise EffectPackError(
                f"effect {public_name} has unknown preset default {unknown_defaults[0]!r}"
            )
        raw_parameters = {
            name: {**spec, **({"default": raw_defaults[name]} if name in raw_defaults else {})}
            for name, spec in raw_parameters.items()
        }
        source_texture = True
        fragment = str(definition["fragment"]).strip()
        fragment_functions = str(definition.get("functions", "")).strip()
    else:
        raw_parameters = raw.get("parameters", {})
        source_texture = raw.get("source_texture", False)
        if not isinstance(source_texture, bool):
            raise EffectPackError(f"effect {public_name} source_texture must be true or false")
    if not isinstance(raw_parameters, dict) or not raw_parameters:
        raise EffectPackError(f"effect {public_name} must declare parameters")
    if len(raw_parameters) > MAX_PARAMETERS_PER_EFFECT:
        raise EffectPackError(
            f"effect {public_name} exceeds {MAX_PARAMETERS_PER_EFFECT} parameters"
        )
    parameters: dict[str, dict[str, object]] = {}
    for raw_name, raw_spec in raw_parameters.items():
        name = _identifier(raw_name, f"effect {public_name} parameter")
        parameters[name] = _parameter_spec(name, raw_spec)
    intensity = parameters.get("intensity")
    if intensity is None or intensity["type"] != "float" or intensity["default"] != 0.0:
        raise EffectPackError(
            f"effect {public_name} requires a float intensity parameter with default 0"
        )
    if preset_name is None:
        fragment = _fragment_source(
            raw.get("fragment"),
            set(parameters),
            source_texture=source_texture,
        )
    shader = f"scenelight.fx.{pack_id}.{effect_id}"
    if preset_name is not None:
        # Ren'Py rewrites ``l__`` references inside numbered fragment parts,
        # but helper definitions supplied through fragment_functions are not
        # rewritten by every supported renderer. Give both sources one
        # explicit per-effect namespace before they reach Ren'Py.
        local_prefix = f"slfx_{pack_id}_{effect_id}_"
        fragment = fragment.replace("l__", local_prefix)
        fragment_functions = fragment_functions.replace("l__", local_prefix)
    uniform_prefix = "u_" + shader.replace(".", "_") + "_"
    variables = ["uniform float u_time;", "varying vec2 v_tex_coord;"]
    for name, spec in sorted(parameters.items()):
        variables.append(f"uniform {spec['type']} u__{name};")
        spec["uniform"] = uniform_prefix + name
    return public_name, {
        "name": str(raw.get("name", effect_id.replace("_", " ").title())).strip()[:100],
        "description": str(raw.get("description", "")).strip()[:500],
        "shader": shader,
        "animated": "u_time" in fragment,
        "preset": preset_name,
        "source_texture": source_texture,
        "parameters": parameters,
        "variables": "\n".join(variables),
        "fragment_priority": EFFECT_FRAGMENT_PRIORITY,
        "fragment": fragment,
        "fragment_functions": fragment_functions,
    }


def _compile_pack(path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    if path.stat().st_size > MAX_PACK_BYTES:
        raise EffectPackError(f"pack exceeds {MAX_PACK_BYTES // 1024} KiB")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectPackError(f"invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EffectPackError("pack root must be an object")
    if payload.get("format") != EFFECT_PACK_FORMAT or payload.get("version") != 1:
        raise EffectPackError(f"pack must use {EFFECT_PACK_FORMAT} version 1")
    pack_id = _identifier(payload.get("id", ""), "pack id")
    raw_effects = payload.get("effects")
    if not isinstance(raw_effects, list) or not raw_effects:
        raise EffectPackError("pack must contain at least one effect")
    if len(raw_effects) > MAX_EFFECTS_PER_PACK:
        raise EffectPackError(f"pack exceeds {MAX_EFFECTS_PER_PACK} effects")
    effects: dict[str, dict[str, object]] = {}
    for raw_effect in raw_effects:
        public_name, effect = _compile_effect(pack_id, raw_effect)
        if public_name in effects:
            raise EffectPackError(f"duplicate effect {public_name}")
        effects[public_name] = effect
    pack = {
        "id": pack_id,
        "name": str(payload.get("name", pack_id.replace("_", " ").title())).strip()[:100],
        "author": str(payload.get("author", "")).strip()[:100],
        "license": str(payload.get("license", "")).strip()[:100],
        "source": path.name,
        "effects": sorted(effects),
    }
    return pack, effects


def compile_effect_packs(game_root: Path) -> EffectPackBuild:
    """Compile valid authored packs and report invalid packs without aborting a game."""

    pack_root = game_root / "scenelight_effects"
    packs: list[dict[str, object]] = []
    effects: dict[str, dict[str, object]] = {}
    warnings: list[str] = []
    if pack_root.is_dir():
        for path in sorted(pack_root.glob("*.json"), key=lambda item: item.name.lower()):
            try:
                pack, compiled = _compile_pack(path)
                collision = sorted(set(effects) & set(compiled))
                if collision:
                    raise EffectPackError(f"effect name already exists: {collision[0]}")
                packs.append(pack)
                effects.update(compiled)
            except (EffectPackError, OSError) as error:
                warnings.append(f"{path.name}: {error}")
    return EffectPackBuild(
        manifest={
            "version": EFFECT_MANIFEST_VERSION,
            "packs": packs,
            "effects": dict(sorted(effects.items())),
        },
        warnings=tuple(warnings),
    )
