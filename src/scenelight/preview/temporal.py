"""Temporal interpolation for complete SceneLight scene states."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Any

import numpy as np

_TRANSPORT_PLANES = 26
_TRANSPORT_LIGHT_BASE = 3
_TRANSPORT_LIGHT_STRIDE = 3


@dataclass(frozen=True, slots=True)
class TemporalSceneFrame:
    """All background-dependent inputs consumed by the live GPU shader."""

    irradiance: np.ndarray
    emitter: np.ndarray
    transport: np.ndarray
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class TemporalSceneBlend:
    """Retained endpoint textures plus the current GPU interpolation phase."""

    left: TemporalSceneFrame
    right: TemporalSceneFrame
    amount: float
    layout_change: bool
    metadata: dict[str, object]


def scene_blend(
    anchors: dict[int, TemporalSceneFrame], frame_index: float
) -> TemporalSceneBlend | None:
    if not anchors:
        return None
    indices = sorted(anchors)
    insertion = bisect.bisect_right(indices, frame_index)
    lower = indices[max(0, insertion - 1)]
    upper = indices[min(insertion, len(indices) - 1)]
    left, right = anchors[lower], anchors[upper]
    amount = min(max((frame_index - lower) / max(upper - lower, 1), 0.0), 1.0)
    if lower == upper:
        return TemporalSceneBlend(left, left, 0.0, False, left.metadata)
    if amount <= 0.0:
        return TemporalSceneBlend(left, right, 0.0, False, left.metadata)
    changed = bool(
        left.metadata.get("light_transport_layout")
        and right.metadata.get("light_transport_layout")
        and left.metadata["light_transport_layout"] != right.metadata["light_transport_layout"]
    )
    metadata = (
        _mismatched_layout_metadata(left.metadata, right.metadata, amount)
        if changed
        else interpolate_metadata(left.metadata, right.metadata, amount)
    )
    return TemporalSceneBlend(left, right, amount, changed, metadata)


def _lerp_array(left: np.ndarray, right: np.ndarray, amount: float) -> np.ndarray:
    left_float = np.asarray(left, dtype=np.float32)
    right_float = np.asarray(right, dtype=np.float32)
    return np.clip(np.rint(left_float + (right_float - left_float) * amount), 0, 255).astype(
        np.uint8
    )


def _lerp_value(left: Any, right: Any, amount: float) -> Any:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) + (float(right) - float(left)) * amount
    if (
        isinstance(left, (tuple, list))
        and isinstance(right, (tuple, list))
        and len(left) == len(right)
        and all(isinstance(value, (int, float)) for value in (*left, *right))
    ):
        return [float(a) + (float(b) - float(a)) * amount for a, b in zip(left, right, strict=True)]
    return left if amount < 0.5 else right


def _disabled_light(light: dict[str, object]) -> dict[str, object]:
    position = list(light.get("position_radius_intensity", (0.5, 0.2, 1.0, 0.0)))
    chroma = list(light.get("chroma_confidence", (1.0, 1.0, 1.0, 0.0)))
    extra = list(light.get("emission_enabled", (0.0, 0.0)))
    position[3] = 0.0
    chroma[3] = 0.0
    extra[0] = 0.0
    extra[1] = 0.0
    return {
        "position_radius_intensity": position,
        "chroma_confidence": chroma,
        "emission_enabled": extra,
    }


def _light_distance(left: dict[str, object], right: dict[str, object]) -> float:
    left_position = np.asarray(left["position_radius_intensity"][:2], dtype=np.float32)
    right_position = np.asarray(right["position_radius_intensity"][:2], dtype=np.float32)
    left_chroma = np.asarray(left["chroma_confidence"][:3], dtype=np.float32)
    right_chroma = np.asarray(right["chroma_confidence"][:3], dtype=np.float32)
    return float(np.linalg.norm(left_position - right_position)) + 0.08 * float(
        np.linalg.norm(left_chroma - right_chroma)
    )


def _paired_lights(
    left_lights: list[dict[str, object]],
    right_lights: list[dict[str, object]],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Track emitters across anchors so changing detector order cannot make them jump."""

    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    remaining = set(range(len(right_lights)))
    for left in left_lights:
        if not remaining:
            pairs.append((left, _disabled_light(left)))
            continue
        closest = min(remaining, key=lambda index: _light_distance(left, right_lights[index]))
        remaining.remove(closest)
        pairs.append((left, right_lights[closest]))
    for index in sorted(remaining):
        right = right_lights[index]
        pairs.append((_disabled_light(right), right))
    return pairs[:4]


def _interpolate_record(
    left: dict[str, object], right: dict[str, object], amount: float
) -> dict[str, object]:
    keys = set(left) | set(right)
    return {
        key: _lerp_value(left.get(key, right.get(key)), right.get(key, left.get(key)), amount)
        for key in keys
    }


def _smoothstep(amount: float) -> float:
    value = float(np.clip(amount, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def _fade_light(light: dict[str, object], amount: float) -> dict[str, object]:
    result = dict(light)
    position = list(light.get("position_radius_intensity", (0.5, 0.2, 1.0, 0.0)))
    chroma = list(light.get("chroma_confidence", (1.0, 1.0, 1.0, 0.0)))
    extra = list(light.get("emission_enabled", (0.0, 0.0)))
    position[3] = float(position[3]) * amount
    chroma[3] = float(chroma[3]) * amount
    extra[0] = float(extra[0]) * amount
    extra[1] = float(extra[1]) * amount
    result["position_radius_intensity"] = position
    result["chroma_confidence"] = chroma
    result["emission_enabled"] = extra
    return result


def _mismatched_layout_metadata(
    left: dict[str, object], right: dict[str, object], amount: float
) -> dict[str, object]:
    """Fade incompatible secondary identities through the shared primary key."""

    result = interpolate_metadata(left, right, amount)
    left_lights = [dict(light) for light in left.get("light_transport", ())]
    right_lights = [dict(light) for light in right.get("light_transport", ())]
    if left_lights and right_lights:
        primary = _interpolate_record(left_lights[0], right_lights[0], amount)
    elif left_lights:
        primary = left_lights[0]
    elif right_lights:
        primary = right_lights[0]
    else:
        primary = _disabled_light({})
    if amount < 0.5:
        side = left
        side_lights = left_lights
        fade = 1.0 - _smoothstep(amount * 2.0)
    else:
        side = right
        side_lights = right_lights
        fade = _smoothstep(amount * 2.0 - 1.0)
    result["light_transport"] = [primary] + [_fade_light(light, fade) for light in side_lights[1:4]]
    result["lights"] = sum(
        float(light["position_radius_intensity"][3]) > 0.001
        or float(light["emission_enabled"][0]) > 0.001
        for light in result["light_transport"]
    )
    result["light_transport_layout"] = side.get("light_transport_layout")
    return result


def _mismatched_layout_transport(left: np.ndarray, right: np.ndarray, amount: float) -> np.ndarray:
    """Crossfade incompatible secondary planes without morphing their identities."""

    if (
        left.ndim != 3
        or right.ndim != 3
        or left.shape != right.shape
        or left.shape[1] % _TRANSPORT_PLANES
    ):
        return left if amount < 0.5 else right
    plane_width = left.shape[1] // _TRANSPORT_PLANES
    left_planes = left.reshape(left.shape[0], _TRANSPORT_PLANES, plane_width, left.shape[2])
    right_planes = right.reshape(right.shape[0], _TRANSPORT_PLANES, plane_width, right.shape[2])
    result = _lerp_array(left, right, amount).reshape(
        left.shape[0], _TRANSPORT_PLANES, plane_width, left.shape[2]
    )
    if amount < 0.5:
        side = left_planes
        fade = 1.0 - _smoothstep(amount * 2.0)
    else:
        side = right_planes
        fade = _smoothstep(amount * 2.0 - 1.0)
    for light_index in range(1, 4):
        plane = _TRANSPORT_LIGHT_BASE + light_index * _TRANSPORT_LIGHT_STRIDE
        result[:, plane : plane + 2] = side[:, plane : plane + 2]
        scalar = side[:, plane + 2].astype(np.float32)
        scalar[..., :3] *= fade
        result[:, plane + 2] = np.clip(np.rint(scalar), 0, 255).astype(np.uint8)
    return result.reshape(left.shape)


def interpolate_metadata(
    left: dict[str, object], right: dict[str, object], amount: float
) -> dict[str, object]:
    """Interpolate every shader-facing scene uniform between exact anchors."""

    result = dict(left if amount < 0.5 else right)
    for key in (
        "adaptation_luminance",
        "broad_diffuse_exposure_guard",
        "target_mid",
        "shadow_chroma",
        "local_contrast",
        "local_saturation",
        "light_confidence",
        "source_size",
        "grain",
        "sharpness",
        "local_luminance",
        "broad_diffuse_chroma_guard",
    ):
        if key in left and key in right:
            result[key] = _lerp_value(left[key], right[key], amount)

    left_lights = [dict(light) for light in left.get("light_transport", ())]
    right_lights = [dict(light) for light in right.get("light_transport", ())]
    canonical_layouts = {
        "physical-rgb-families-v1",
        "continuous-light-slots-v2",
        "spatial-radiance-v3",
    }
    if left.get("light_transport_layout") in canonical_layouts and right.get(
        "light_transport_layout"
    ) == left.get("light_transport_layout"):
        light_count = max(len(left_lights), len(right_lights))
        light_pairs = []
        for index in range(light_count):
            if index < len(left_lights):
                a = left_lights[index]
            else:
                a = _disabled_light(right_lights[index])
            if index < len(right_lights):
                b = right_lights[index]
            else:
                b = _disabled_light(left_lights[index])
            light_pairs.append((a, b))
    else:
        light_pairs = _paired_lights(left_lights, right_lights)
    result["light_transport"] = [_interpolate_record(a, b, amount) for a, b in light_pairs[:4]]
    result["lights"] = len(result["light_transport"])

    left_probes = [dict(probe) for probe in left.get("probe_transport", ())]
    right_probes = [dict(probe) for probe in right.get("probe_transport", ())]
    probe_count = max(len(left_probes), len(right_probes))
    probes: list[dict[str, object]] = []
    disabled_probe = {
        "direction_luminance_enabled": (0.0, -1.0, 0.0, 0.0),
        "chroma": (1.0, 1.0, 1.0),
    }
    for index in range(probe_count):
        a = left_probes[index] if index < len(left_probes) else disabled_probe
        b = right_probes[index] if index < len(right_probes) else disabled_probe
        probes.append(_interpolate_record(a, b, amount))
    result["probe_transport"] = probes[:8]
    result["probes"] = len(result["probe_transport"])
    result.pop("transport_preview", None)
    return result


def interpolated_scene(
    anchors: dict[int, TemporalSceneFrame],
    frame_index: int,
) -> TemporalSceneFrame | None:
    """Interpolate textures and uniforms between complete exact scene anchors."""

    if not anchors:
        return None
    index = int(frame_index)
    exact = anchors.get(index)
    if exact is not None:
        return exact
    indices = sorted(anchors)
    insertion = bisect.bisect_left(indices, index)
    if insertion <= 0:
        return anchors[indices[0]]
    if insertion >= len(indices):
        return anchors[indices[-1]]
    lower = indices[insertion - 1]
    upper = indices[insertion]
    amount = (index - lower) / max(upper - lower, 1)
    left = anchors[lower]
    right = anchors[upper]
    left_layout = left.metadata.get("light_transport_layout")
    right_layout = right.metadata.get("light_transport_layout")
    if left_layout and right_layout and left_layout != right_layout:
        # The secondary planes have different semantic identities on the two
        # sides (physical components versus canonical hue families). Keep the
        # common primary key continuous, fade the old secondaries away, then
        # fade the new identities in. This avoids both invented mixed lights
        # and the visible midpoint pop caused by a hard layout switch.
        return TemporalSceneFrame(
            irradiance=_lerp_array(left.irradiance, right.irradiance, amount),
            emitter=_lerp_array(left.emitter, right.emitter, amount),
            transport=_mismatched_layout_transport(left.transport, right.transport, amount),
            metadata=_mismatched_layout_metadata(left.metadata, right.metadata, amount),
        )
    return TemporalSceneFrame(
        irradiance=_lerp_array(left.irradiance, right.irradiance, amount),
        emitter=_lerp_array(left.emitter, right.emitter, amount),
        transport=_lerp_array(left.transport, right.transport, amount),
        metadata=interpolate_metadata(left.metadata, right.metadata, amount),
    )


def interpolated_transport(
    anchors: dict[int, np.ndarray],
    frame_index: int,
) -> np.ndarray | None:
    """Compatibility helper for callers that only need the encoded transport."""

    frames = {
        index: TemporalSceneFrame(value, value, value, {}) for index, value in anchors.items()
    }
    scene = interpolated_scene(frames, frame_index)
    return None if scene is None else scene.transport
