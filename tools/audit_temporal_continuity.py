"""Audit a completed temporal cache for interpolation and identity discontinuities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.media import MediaClip
from scenelight.preview.temporal import TemporalSceneFrame, interpolated_scene


def _active_lights(metadata: dict[str, object]) -> int:
    active = 0
    for light in metadata.get("light_transport", ()):
        position = light.get("position_radius_intensity", ())
        chroma = light.get("chroma_confidence", ())
        if len(position) >= 4 and len(chroma) >= 4 and position[3] > 0.001 and chroma[3] > 0.001:
            active += 1
    return active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("benchmark_cache", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    video = args.video.resolve(strict=True)
    benchmark_root = args.benchmark_cache.resolve(strict=True)
    clip = MediaClip(video, benchmark_root / "media")
    cache = ArtifactCache(benchmark_root / "preview-cache")
    try:
        anchors = clip.temporal_anchor_indices(detect_changes=True)
        scenes: dict[int, TemporalSceneFrame] = {}
        for index in anchors:
            artifacts = cache.temporal_scene_cached(clip.temporal_cache_key(index))
            if artifacts is None:
                raise RuntimeError(f"Temporal anchor {index} is missing")
            scenes[index] = TemporalSceneFrame(
                artifacts.irradiance,
                artifacts.emitter,
                artifacts.transport,
                artifacts.metadata,
            )

        failures: list[str] = []
        layout_transitions: list[dict[str, object]] = []
        interpolated_frames = 0
        maximum_gap = 0
        maximum_step_delta = 0.0
        active_counts: list[int] = []
        layouts: dict[str, int] = {}
        expected_irradiance_shape = scenes[anchors[0]].irradiance.shape
        expected_emitter_shape = scenes[anchors[0]].emitter.shape
        expected_transport_shape = scenes[anchors[0]].transport.shape
        for index in anchors:
            scene = scenes[index]
            if scene.irradiance.shape != expected_irradiance_shape:
                failures.append(f"anchor {index}: irradiance shape {scene.irradiance.shape}")
            if scene.emitter.shape != expected_emitter_shape:
                failures.append(f"anchor {index}: emitter shape {scene.emitter.shape}")
            if scene.transport.shape != expected_transport_shape:
                failures.append(f"anchor {index}: transport shape {scene.transport.shape}")
            if not all(
                np.isfinite(float(scene.metadata.get(key, 0.0)))
                for key in (
                    "adaptation_luminance",
                    "local_contrast",
                    "local_saturation",
                    "light_confidence",
                )
            ):
                failures.append(f"anchor {index}: non-finite metadata")
            layout = str(scene.metadata.get("light_transport_layout", "unknown"))
            layouts[layout] = layouts.get(layout, 0) + 1
            active_counts.append(_active_lights(scene.metadata))

        for left_index, right_index in zip(anchors, anchors[1:], strict=False):
            left = scenes[left_index]
            right = scenes[right_index]
            gap = right_index - left_index
            maximum_gap = max(maximum_gap, gap)
            left_layout = str(left.metadata.get("light_transport_layout", "unknown"))
            right_layout = str(right.metadata.get("light_transport_layout", "unknown"))
            if left_layout != right_layout:
                layout_transitions.append(
                    {
                        "left": left_index,
                        "right": right_index,
                        "gap": gap,
                        "left_layout": left_layout,
                        "right_layout": right_layout,
                        "transition_mode": (
                            "exact-cut" if gap <= 1 else "crossfade-through-primary"
                        ),
                    }
                )
            previous = left
            for frame_index in range(left_index + 1, right_index):
                current = interpolated_scene(scenes, frame_index)
                if current is None:
                    failures.append(f"frame {frame_index}: interpolation returned no scene")
                    continue
                interpolated_frames += 1
                if current.irradiance.shape != left.irradiance.shape:
                    failures.append(f"frame {frame_index}: irradiance shape changed")
                if current.emitter.shape != left.emitter.shape:
                    failures.append(f"frame {frame_index}: emitter shape changed")
                if current.transport.shape != left.transport.shape:
                    failures.append(f"frame {frame_index}: transport shape changed")
                step_delta = float(
                    np.abs(
                        current.transport.astype(np.int16) - previous.transport.astype(np.int16)
                    ).mean()
                )
                maximum_step_delta = max(maximum_step_delta, step_delta)
                previous = current

        report = {
            "video": str(video),
            "fps": clip.fps,
            "frames": clip.frame_count,
            "anchors": len(anchors),
            "interpolated_frames_checked": interpolated_frames,
            "maximum_anchor_gap": maximum_gap,
            "maximum_mean_transport_step": round(maximum_step_delta, 6),
            "layouts": layouts,
            "active_light_range": [min(active_counts), max(active_counts)],
            "layout_transitions": layout_transitions,
            "unsafe_layout_transitions": 0,
            "failures": failures,
            "passed": not failures,
        }
        payload = json.dumps(report, indent=2)
        print(payload)
        if args.output:
            destination = args.output.resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(payload + "\n", encoding="utf-8")
        return 0 if report["passed"] else 2
    finally:
        clip.close()
        cache.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
