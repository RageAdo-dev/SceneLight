"""Compare two resolved capture caches by semantic form and decoded pixels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypeAlias

from PIL import Image

PixelSignature: TypeAlias = tuple[tuple[int, int], str]
VisualSignature: TypeAlias = tuple[object, ...]


def _pixel_signature(path: Path, cache: dict[Path, PixelSignature]) -> PixelSignature:
    path = path.resolve()
    cached = cache.get(path)
    if cached is not None:
        return cached
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
        signature = (image.size, hashlib.sha256(image.tobytes()).hexdigest())
    cache[path] = signature
    return signature


def _semantic_form(name: str) -> tuple[str, tuple[str, ...]]:
    parts = name.lower().split()
    return parts[0], tuple(sorted(set(parts[1:])))


def _sprite_signatures(
    root: Path,
    payload: dict[str, object],
) -> tuple[dict[tuple[str, tuple[str, ...]], VisualSignature], list[str]]:
    raw_sprites = payload.get("sprites")
    raw_composites = payload.get("composite_captures", {})
    if not isinstance(raw_sprites, dict) or not isinstance(raw_composites, dict):
        raise ValueError("Invalid SceneLight capture result")
    pixels: dict[Path, PixelSignature] = {}
    signatures: dict[tuple[str, tuple[str, ...]], VisualSignature] = {}
    conflicts: list[str] = []
    for raw_name, raw_path in raw_sprites.items():
        name = str(raw_name)
        relative = str(raw_path).replace("\\", "/")
        manifest = raw_composites.get(relative)
        if isinstance(manifest, dict):
            raw_size = manifest.get("size")
            raw_layers = manifest.get("layers")
            if not isinstance(raw_size, list) or not isinstance(raw_layers, list):
                raise ValueError(f"Invalid composite manifest: {relative}")
            layers = []
            for raw_layer in raw_layers:
                if not isinstance(raw_layer, dict):
                    raise ValueError(f"Invalid composite layer: {relative}")
                source = root / str(raw_layer.get("source"))
                position = raw_layer.get("position")
                if not isinstance(position, list):
                    raise ValueError(f"Invalid composite position: {relative}")
                layers.append((_pixel_signature(source, pixels), tuple(position)))
            signature: VisualSignature = ("composite", tuple(raw_size), tuple(layers))
        else:
            signature = ("surface", _pixel_signature(root / relative, pixels))
        key = _semantic_form(name)
        existing = signatures.get(key)
        if existing is not None and existing != signature:
            conflicts.append(name)
        signatures[key] = signature
    return signatures, conflicts


def _scene_signatures(root: Path, payload: dict[str, object]) -> dict[str, PixelSignature]:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, dict):
        raise ValueError("Invalid SceneLight scene capture result")
    pixels: dict[Path, PixelSignature] = {}
    return {
        str(name): _pixel_signature(root / str(relative), pixels)
        for name, relative in raw_scenes.items()
    }


def _compare_maps(
    reference: dict[object, object],
    candidate: dict[object, object],
    *,
    ignored: set[object] | None = None,
) -> dict[str, object]:
    ignored = ignored or set()
    reference_names = set(reference) - ignored
    candidate_names = set(candidate) - ignored
    missing = sorted(reference_names - candidate_names, key=str)
    added = sorted(candidate_names - reference_names, key=str)
    changed = sorted(
        (name for name in reference_names & candidate_names if reference[name] != candidate[name]),
        key=str,
    )
    return {
        "reference": len(reference_names),
        "candidate": len(candidate_names),
        "missing": len(missing),
        "added": len(added),
        "changed": len(changed),
        "first_missing": [str(value) for value in missing[:10]],
        "first_added": [str(value) for value in added[:10]],
        "first_changed": [str(value) for value in changed[:10]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--ignore-scene",
        action="append",
        default=[],
        help="Ignore an intentionally time-varying scene name (repeatable).",
    )
    args = parser.parse_args()
    roots = [args.reference.resolve(), args.candidate.resolve()]
    payloads = [
        json.loads((root / ".scenelight_cache/capture_result.json").read_text()) for root in roots
    ]
    sprite_results = [
        _sprite_signatures(root, payload) for root, payload in zip(roots, payloads, strict=True)
    ]
    scenes = [
        _scene_signatures(root, payload) for root, payload in zip(roots, payloads, strict=True)
    ]
    result = {
        "sprites": _compare_maps(sprite_results[0][0], sprite_results[1][0]),
        "sprite_conflicts": {
            "reference": len(sprite_results[0][1]),
            "candidate": len(sprite_results[1][1]),
        },
        "scenes": _compare_maps(
            scenes[0],
            scenes[1],
            ignored=set(args.ignore_scene),
        ),
        "ignored_scenes": sorted(set(args.ignore_scene)),
    }
    print(json.dumps(result, indent=2))
    failures = (
        result["sprites"]["missing"]
        + result["sprites"]["added"]
        + result["sprites"]["changed"]
        + result["sprite_conflicts"]["reference"]
        + result["sprite_conflicts"]["candidate"]
        + result["scenes"]["missing"]
        + result["scenes"]["added"]
        + result["scenes"]["changed"]
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
