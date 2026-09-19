"""Resolve image-like Ren'Py assets into raw cache inputs.

LayeredImage and archive-backed images can only be resolved correctly by the
target game's own Ren'Py runtime.  This module asks Ren'Py to render those raw
displayables once, then feeds the transparent results to the same universal
form-map builder used for ordinary PNG declarations.  Final relit sprites are
never baked; lighting remains a live GPU operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np
import psutil
from PIL import Image

from . import diagnostics
from .hashing import sha256_file
from .project import (
    ProjectDiscovery,
    SpriteSpec,
    _looks_like_foreground_sprite,
)
from .sidecar import STATE_NAME, managed_project_root, renpy_runtime_command
from .source_types import VISUAL_SOURCE_SUFFIXES

CAPTURE_VERSION = 42
CAPTURE_PLAN_VERSION = 3
CAPTURE_PIXEL_VERSION = 2
CAPTURE_PROCESS_RESUME_LIMIT = 32
CAPTURE_PROCESS_BATCH_SIZE = 512
# Parallel workers checkpoint every form and normally stay alive until their
# chunk finishes. If a renderer crashes, the worker resumes from those durable
# checkpoints. A fixed form limit made healthy workers restart in lockstep,
# which caused expensive GPU-initialization stalls on large projects.
CAPTURE_PARALLEL_PROCESS_BATCH_SIZE: int | None = None
CAPTURE_LOW_YIELD_CRASH_LIMIT = 2
CAPTURE_LOW_YIELD_FORM_THRESHOLD = 16
MIB = 1024**2
CAPTURE_PARALLEL_MIN_FORMS = 1500
CAPTURE_FORM_WORKER_RESERVE_BYTES = 2 * 1024 * MIB
CAPTURE_FORM_WORKER_BYTES = 1536 * MIB
CAPTURE_FORM_WORKER_CAP = 6
SURFACE_NORMALIZATION_RESERVE_BYTES = 512 * MIB
SURFACE_NORMALIZATION_WORKER_BYTES = 128 * MIB
# Emergency ceiling only: the selected count also adapts to live memory,
# logical CPUs, pending work, and (for pipelining) Ren'Py's concurrent load.
SURFACE_NORMALIZATION_ABSOLUTE_WORKER_CAP = 16
CompositeJob = tuple[str, tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]]
CAPTURE_IGNORED_NAMES = {
    "scenelight-runtime.jsonl",
    "scenelight-runtime.jsonl.1",
    "scenelight_capture.rpy",
    "scenelight_capture.rpyc",
    "scenelight_runtime.rpy",
    "scenelight_runtime.rpyc",
}


class CaptureInstanceConflict(RuntimeError):
    """The mod rejected another capture instance before rendering could start."""


def _is_instance_conflict(diagnostic: str) -> bool:
    return any(
        line.strip() == "Another instance is already running, quitting."
        or re.fullmatch(r"(?:[\w]+\.)*SingleInstanceException(?::.*)?", line.strip())
        for line in diagnostic.splitlines()
    )


@dataclass(frozen=True, slots=True)
class CaptureResult:
    scenes: dict[str, Path]
    sprites: dict[str, Path]
    character_tags: list[str]
    background_inventory_requested: bool
    scene_requests: int
    resolved_requests: list[str]
    errors: list[str]
    cached: bool
    character_candidates: dict[str, Path | None] = field(default_factory=dict)
    composite_sprites: dict[str, SpriteSpec] = field(default_factory=dict)
    scene_sequences: dict[str, list[tuple[int, Path]]] = field(default_factory=dict)
    scene_frame_sources: dict[str, dict[str, Path]] = field(default_factory=dict)


@dataclass(slots=True)
class _CaptureProgressState:
    """Keep visible renderer progress monotonic across managed process batches."""

    watermarks: dict[tuple[str, int], int] = field(default_factory=dict)
    seen: set[tuple[object, ...]] = field(default_factory=set)


def capture_source() -> Path:
    source = Path(__file__).resolve().parent / "runtime" / "scenelight_capture.rpy"
    if not source.is_file():
        raise FileNotFoundError(f"Bundled Ren'Py capture helper is missing: {source}")
    return source


def needs_runtime_capture(discovery: ProjectDiscovery) -> bool:
    # A successful source parse is not proof that it found the complete image
    # registry. Full installation uses the game's renderer whenever one is
    # available so archives, aliases, and dynamic backgrounds can augment even
    # an otherwise ordinary static project.
    return bool(
        discovery.scenes or discovery.runtime_sprite_names or discovery.requires_runtime_inventory
    )


def _managed_authored_paths(project_root: Path) -> set[str] | None:
    """Read provenance only for a managed copy owned by the current storage root."""
    try:
        state = json.loads((project_root / STATE_NAME).read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("version") != 1:
            return None
        source, files = state.get("source"), state.get("source_files")
        if not isinstance(source, str) or not source or not isinstance(files, dict):
            return None
        if managed_project_root(Path(source)) != project_root.resolve():
            return None
        return set(files) if all(isinstance(key, str) for key in files) else None
    except (OSError, ValueError):
        return None


def _capture_content_signature(discovery: ProjectDiscovery) -> str:
    """Identify pixel-producing logic and visual inputs, not UI/helper wording.

    ``CAPTURE_PIXEL_VERSION`` is bumped only when the bytes SceneLight derives
    from a resolved Ren'Py displayable can change. Protocol, progress, recovery,
    and planning-only edits intentionally keep the expensive raw captures.
    """

    digest = hashlib.sha256()
    digest.update(f"scenelight-capture-pixels-{CAPTURE_PIXEL_VERSION}\0".encode("ascii"))
    authored = _managed_authored_paths(discovery.project_root)
    for path in sorted(discovery.game_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VISUAL_SOURCE_SUFFIXES:
            continue
        if path.name.lower() in CAPTURE_IGNORED_NAMES:
            continue
        try:
            relative = path.relative_to(discovery.game_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0].lower() == "scenelight_runtime":
            continue
        if authored is not None and path.suffix.lower() in {".rpyc", ".rpymc"}:
            key = path.relative_to(discovery.project_root).as_posix()
            source_path = path.with_suffix(path.suffix[:-1])
            source_key = source_path.relative_to(discovery.project_root).as_posix()
            if key not in authored and source_key in authored and source_path.is_file():
                # Preflight can regenerate nondeterministic bytecode. It is not
                # an authored input and sync_project removes it before playback.
                # Keep hashing bytecode shipped by the author, even beside source.
                continue
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _project_signature(discovery: ProjectDiscovery, *, content_signature: str | None = None) -> str:
    """Identify one complete requested inventory over stable visual content."""

    digest = hashlib.sha256()
    if content_signature is None:
        content_signature = _capture_content_signature(discovery)
    digest.update(content_signature.encode("ascii"))
    digest.update(b"\0")
    digest.update(f"protocol={CAPTURE_VERSION}\0plan={CAPTURE_PLAN_VERSION}\0".encode("ascii"))
    digest.update(json.dumps(discovery.runtime_sprite_names, sort_keys=True).encode("utf-8"))
    digest.update(json.dumps(discovery.runtime_sprite_sequences, sort_keys=True).encode("utf-8"))
    digest.update(json.dumps(discovery.explicit_character_tags, sort_keys=True).encode("utf-8"))
    digest.update(discovery.character_selection.encode("ascii"))
    digest.update(discovery.scene_analysis.encode("ascii"))
    digest.update(b"\1" if discovery.requires_runtime_inventory else b"\0")
    return digest.hexdigest()


def _paths_exist(project_root: Path, payload: dict[str, object]) -> bool:
    raw_composites = payload.get("composite_captures", {})
    if not isinstance(raw_composites, dict):
        return False
    composite_destinations = {str(value).replace("\\", "/") for value in raw_composites}
    for group_name in ("scenes", "sprites", "character_candidates"):
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            return False
        for relative in group.values():
            if relative is None:
                continue
            normalized = str(relative).replace("\\", "/")
            if (
                not (project_root / normalized).is_file()
                and normalized not in composite_destinations
            ):
                return False
    raw_sequences = payload.get("scene_sequences", {})
    if not isinstance(raw_sequences, dict):
        return False
    for raw_frames in raw_sequences.values():
        if not isinstance(raw_frames, list):
            return False
        for raw_frame in raw_frames:
            if not isinstance(raw_frame, list) or len(raw_frame) != 2:
                return False
            if not (project_root / str(raw_frame[1]).replace("\\", "/")).is_file():
                return False
    return True


def _merge_composite_capture_jobs(
    project_root: Path,
    job_root: Path,
    payload: dict[str, object],
) -> None:
    """Merge every atomic composite job from resumed batches into one result."""

    raw_composites = payload.setdefault("composite_captures", {})
    if not isinstance(raw_composites, dict):
        raise ValueError("Invalid SceneLight composite capture table")

    def merge_job(raw_job: object) -> None:
        if not isinstance(raw_job, dict):
            raise ValueError("Invalid SceneLight composite pipeline job")
        destination = str(raw_job.get("destination", "")).replace("\\", "/")
        manifest = raw_job.get("manifest")
        _validated_composite_job(project_root, destination, manifest)
        raw_composites[destination] = manifest

    deferred_path = job_root.parent / "composite_manifest.jsonl"
    if deferred_path.is_file():
        with deferred_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    merge_job(json.loads(line))
                except json.JSONDecodeError:
                    # Only a final interrupted append can be incomplete.
                    continue
    if job_root.is_dir():
        for job_path in sorted(job_root.glob("composite_*.json")):
            merge_job(json.loads(job_path.read_text(encoding="utf-8")))


def _materialize_composite_captures(
    project_root: Path,
    payload: dict[str, object],
) -> None:
    """Assemble safe static ``im.Composite`` exports outside old Ren'Py.

    The in-engine resolver exports each unique archive PNG once and records the
    ordinary Composite size/order/positions. Pygame-compatible integer
    composition plus the established renderer-alpha pass is byte-identical for
    this safe structural subset. Anything else remains on Ren'Py's fallback.
    """

    raw_composites = payload.get("composite_captures", {})
    if not isinstance(raw_composites, dict):
        raise ValueError("Invalid SceneLight composite capture table")
    if not raw_composites:
        return

    reported: set[str] = set()
    for group_name in ("scenes", "sprites"):
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            raise ValueError(f"Invalid SceneLight capture group: {group_name}")
        reported.update(str(value).replace("\\", "/") for value in group.values())

    jobs: list[CompositeJob] = []
    for raw_destination, raw_manifest in sorted(raw_composites.items()):
        destination_name = str(raw_destination).replace("\\", "/")
        if destination_name not in reported:
            continue
        job = _validated_composite_job(project_root, destination_name, raw_manifest)
        destination = Path(job[0])
        marker = destination.with_name(destination.name + ".composite-normalized")
        # Both files publish by atomic replace. A destination without its
        # marker can be left by an interrupted worker and is rebuilt safely.
        if not destination.is_file() or not marker.is_file():
            jobs.append(job)

    if jobs:
        worker_count = _surface_normalization_worker_count(len(jobs))
        print(
            f"composite assembly 0/{len(jobs)}: preparing layered sprite captures",
            flush=True,
        )
        if worker_count == 1:
            for index, job in enumerate(jobs, 1):
                _materialize_composite_capture_file(job)
                if index == 1 or index % 10 == 0 or index == len(jobs):
                    print(
                        f"composite assembly {index}/{len(jobs)}: "
                        "preparing layered sprite captures",
                        flush=True,
                    )
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                for index, _ in enumerate(
                    executor.map(_materialize_composite_capture_file, jobs),
                    1,
                ):
                    if index == 1 or index % 10 == 0 or index == len(jobs):
                        print(
                            f"composite assembly {index}/{len(jobs)}: "
                            "preparing layered sprite captures",
                            flush=True,
                        )
    payload["composite_captures"] = {}
    payload["composite_captures_materialized"] = True


def _safe_composite_path(
    project_root: Path,
    raw_path: object,
    *,
    resolved_root: Path | None = None,
) -> Path:
    resolved_root = resolved_root or project_root.resolve()
    path = (resolved_root / str(raw_path).replace("/", os.sep)).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("SceneLight composite capture escaped the project directory") from error
    return path


def _safe_composite_destination(
    project_root: Path,
    raw_path: object,
    *,
    resolved_root: Path | None = None,
    directory_cache: dict[str, Path] | None = None,
) -> Path:
    """Validate an output path without resolving every unique filename."""

    resolved_root = resolved_root or project_root.resolve()
    relative = Path(str(raw_path).replace("/", os.sep))
    if not relative.name or relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("SceneLight composite capture escaped the project directory")
    parent_key = relative.parent.as_posix()
    parent = directory_cache.get(parent_key) if directory_cache is not None else None
    if parent is None:
        parent = (resolved_root / relative.parent).resolve()
        try:
            parent.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(
                "SceneLight composite capture escaped the project directory"
            ) from error
        if directory_cache is not None:
            directory_cache[parent_key] = parent
    return parent / relative.name


def _validated_composite_job(
    project_root: Path,
    raw_destination: object,
    raw_manifest: object,
    *,
    resolved_root: Path | None = None,
    path_cache: dict[str, Path] | None = None,
    file_cache: dict[Path, bool] | None = None,
    directory_cache: dict[str, Path] | None = None,
) -> CompositeJob:
    resolved_root = resolved_root or project_root.resolve()

    def safe_path(raw_path: object) -> Path:
        key = str(raw_path).replace("\\", "/")
        if path_cache is not None and key in path_cache:
            return path_cache[key]
        path = _safe_composite_path(
            project_root,
            key,
            resolved_root=resolved_root,
        )
        if path_cache is not None:
            path_cache[key] = path
        return path

    if not isinstance(raw_manifest, dict):
        raise ValueError("Invalid SceneLight composite capture manifest")
    raw_size = raw_manifest.get("size")
    raw_layers = raw_manifest.get("layers")
    if (
        not isinstance(raw_size, list)
        or len(raw_size) != 2
        or not all(isinstance(value, int) for value in raw_size)
    ):
        raise ValueError("Invalid SceneLight composite capture size")
    width, height = raw_size
    if width < 1 or height < 1 or width > 16384 or height > 16384:
        raise ValueError("Invalid SceneLight composite capture dimensions")
    if not isinstance(raw_layers, list) or not raw_layers or len(raw_layers) > 256:
        raise ValueError("Invalid SceneLight composite capture layers")
    layers: list[tuple[str, tuple[int, int]]] = []
    for raw_layer in raw_layers:
        if not isinstance(raw_layer, dict):
            raise ValueError("Invalid SceneLight composite capture layer")
        raw_position = raw_layer.get("position")
        if (
            not isinstance(raw_position, list)
            or len(raw_position) != 2
            or not all(isinstance(value, int) for value in raw_position)
        ):
            raise ValueError("Invalid SceneLight composite capture position")
        source = safe_path(raw_layer.get("source"))
        if file_cache is not None and source in file_cache:
            source_exists = file_cache[source]
        else:
            source_exists = source.is_file()
            if file_cache is not None:
                file_cache[source] = source_exists
        if not source_exists or source.suffix.lower() != ".png":
            raise FileNotFoundError("SceneLight composite component is missing or unsupported")
        layers.append((str(source), (raw_position[0], raw_position[1])))
    destination = _safe_composite_destination(
        project_root,
        raw_destination,
        resolved_root=resolved_root,
        directory_cache=directory_cache,
    )
    return str(destination), (width, height), tuple(layers)


def _capture_temporary_path(destination: Path, purpose: str) -> Path:
    """Return a short same-directory temporary path for atomic publication."""

    digest = hashlib.sha256(str(destination).encode("utf-8")).hexdigest()[:16]
    return destination.parent / f".sl-{purpose}-{digest}.tmp"


def _materialize_composite_capture_file(
    job: CompositeJob,
) -> None:
    destination_text, size, layers = job
    destination = Path(destination_text)
    normalized_marker = destination.with_name(destination.name + ".composite-normalized")
    canvas = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    for source_text, position in layers:
        with Image.open(source_text) as opened:
            layer = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        _pygame_alpha_blit(canvas, layer, position)
    source = canvas.astype(np.uint16)
    alpha = source[..., 3:4]
    normalized = ((source * alpha) >> 8).astype(np.uint8)
    temporary = _capture_temporary_path(destination, "composite")
    try:
        Image.fromarray(normalized, mode="RGBA").save(
            temporary,
            format="PNG",
            compress_level=1,
        )
        normalized_marker.unlink(missing_ok=True)
        os.replace(temporary, destination)
        marker_temporary = _capture_temporary_path(normalized_marker, "marker")
        try:
            marker_temporary.write_text("normalized\n", encoding="utf-8")
            os.replace(marker_temporary, normalized_marker)
        finally:
            marker_temporary.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def _pygame_alpha_blit(
    destination: np.ndarray,
    source: np.ndarray,
    position: tuple[int, int],
) -> None:
    """Reproduce Pygame 1.9/pygame_sdl2's integer SRCALPHA blit.

    Pillow uses a mathematically cleaner source-over division, but old Ren'Py
    composites use Pygame's documented 8-bit approximation. The explicit
    transparent-destination branch and integer equations below match the game
    engine byte-for-byte, including antialiased overlapping layer edges.
    """

    x, y = position
    source_height, source_width = source.shape[:2]
    destination_height, destination_width = destination.shape[:2]
    target_x0 = max(0, x)
    target_y0 = max(0, y)
    target_x1 = min(destination_width, x + source_width)
    target_y1 = min(destination_height, y + source_height)
    if target_x0 >= target_x1 or target_y0 >= target_y1:
        return
    source_x0 = target_x0 - x
    source_y0 = target_y0 - y
    source_view = source[
        source_y0 : source_y0 + (target_y1 - target_y0),
        source_x0 : source_x0 + (target_x1 - target_x0),
    ]
    destination_view = destination[target_y0:target_y1, target_x0:target_x1]
    source_visible = source_view[..., 3] != 0
    empty_destination = destination_view[..., 3] == 0
    copy_mask = source_visible & empty_destination
    destination_view[copy_mask] = source_view[copy_mask]

    # DDLC-style components are mostly disjoint body/face pieces. Perform the
    # integer blend only on their small antialiased overlap instead of
    # allocating full-frame int32 intermediates for every layer.
    blend_mask = source_visible & ~empty_destination
    if not np.any(blend_mask):
        return
    source_i32 = source_view[blend_mask].astype(np.int32)
    destination_i32 = destination_view[blend_mask].astype(np.int32)
    source_alpha = source_i32[:, 3:4]
    destination_alpha = destination_i32[:, 3:4]
    destination_view[blend_mask, :3] = (
        (
            (destination_i32[:, :3] << 8)
            + (source_i32[:, :3] - destination_i32[:, :3]) * source_alpha
            + source_i32[:, :3]
        )
        >> 8
    ).astype(np.uint8)
    destination_view[blend_mask, 3:4] = (
        source_alpha + destination_alpha - (source_alpha * destination_alpha // 255)
    ).astype(np.uint8)


def _normalize_surface_captures(
    project_root: Path,
    payload: dict[str, object],
) -> None:
    """Match Ren'Py 7's renderer readback for static-surface captures.

    The old renderer screenshot path multiplies every saved RGBA channel by
    the source alpha with an 8-bit right shift. Directly saving an ImageBase
    surface is much faster, but leaves straight-alpha pixels. Normalize only
    the files explicitly marked by the trusted capture helper so the fast path
    keeps the established form-map and scene-analysis input semantics.
    """

    raw_paths = payload.get("surface_captures", [])
    if not isinstance(raw_paths, list):
        raise ValueError("Invalid SceneLight surface capture list")
    if not raw_paths:
        return

    reported: set[str] = set()
    for group_name in ("scenes", "sprites"):
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            raise ValueError(f"Invalid SceneLight capture group: {group_name}")
        reported.update(str(value).replace("\\", "/") for value in group.values())

    resolved_root = project_root.resolve()
    captures_to_normalize: list[Path] = []
    for raw_path in sorted(set(str(value).replace("\\", "/") for value in raw_paths)):
        if raw_path not in reported:
            # Two registered scene names can normalize to the same public scene
            # key (for example ``bedroom`` and ``bg bedroom``). The later value
            # is the only consumed capture; leave the superseded checkpoint
            # untouched instead of failing the otherwise valid renderer pass.
            continue
        path = (resolved_root / raw_path).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError("SceneLight surface capture escaped the project directory") from error

        captures_to_normalize.append(path)

    captures_to_normalize = _deduplicate_surface_capture_paths(
        resolved_root,
        payload,
        captures_to_normalize,
    )

    # A few review thumbnails are cheaper inline. Full archive inventories use
    # disposable workers: Pillow/NumPy's Windows allocators can otherwise keep
    # hundreds of megabytes committed in the long-lived installer process and
    # unnecessarily force the later exact form-map builder down to one worker.
    total = len(captures_to_normalize)
    print(f"surface normalization 0/{total}: preparing captured sprite pixels", flush=True)
    if total <= 8:
        for index, path in enumerate(captures_to_normalize, 1):
            _normalize_surface_capture_file(path)
            print(
                f"surface normalization {index}/{total}: {path.name}",
                flush=True,
            )
    else:
        worker_count = _surface_normalization_worker_count(total)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for index, _ in enumerate(
                executor.map(_normalize_surface_capture_file, captures_to_normalize),
                1,
            ):
                if index == 1 or index % 10 == 0 or index == total:
                    print(
                        f"surface normalization {index}/{total}: preparing sprite pixels",
                        flush=True,
                    )

    # State is written only after this normalized result is persisted. Clearing
    # the list makes a valid cached capture immune to accidental double passes.
    payload["surface_captures"] = []
    payload["surface_captures_normalized"] = True


def _deduplicate_normalized_captures(
    project_root: Path,
    payload: dict[str, object],
) -> None:
    """Share byte-identical renderer-normalized captures without another alpha pass."""

    raw_paths = payload.get("normalized_captures", [])
    if not isinstance(raw_paths, list):
        raise ValueError("Invalid SceneLight normalized capture list")
    if not raw_paths:
        return
    reported: set[str] = set()
    for group_name in ("scenes", "sprites"):
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            raise ValueError(f"Invalid SceneLight capture group: {group_name}")
        reported.update(str(value).replace("\\", "/") for value in group.values())
    resolved_root = project_root.resolve()
    paths: list[Path] = []
    for raw_path in sorted(set(str(value).replace("\\", "/") for value in raw_paths)):
        if raw_path not in reported:
            continue
        path = (resolved_root / raw_path).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(
                "SceneLight normalized capture escaped the project directory"
            ) from error
        if not path.with_name(path.name + ".surface-normalized").is_file():
            raise ValueError(f"SceneLight normalized capture is missing its marker: {raw_path}")
        paths.append(path)
    _deduplicate_surface_capture_paths(resolved_root, payload, paths)
    payload["normalized_captures"] = []
    payload["normalized_captures_deduplicated"] = True


def _surface_capture_digest(path: Path) -> tuple[int, bytes]:
    return path.stat().st_size, sha256_file(path)


def _deduplicate_surface_capture_paths(
    project_root: Path,
    payload: dict[str, object],
    paths: list[Path],
) -> list[Path]:
    """Map byte-identical captures to one source before expensive normalization."""

    unique_paths = sorted(set(paths))
    if len(unique_paths) < 2:
        return unique_paths

    by_size: dict[int, list[Path]] = {}
    for path in unique_paths:
        by_size.setdefault(path.stat().st_size, []).append(path)
    candidates = [path for group in by_size.values() if len(group) > 1 for path in group]
    print(
        f"surface deduplication 0/{len(candidates)}: checking captured sprite identity",
        flush=True,
    )
    fingerprints: dict[Path, tuple[int, bytes]] = {}
    if candidates:
        workers = max(1, min(8, os.cpu_count() or 1, len(candidates)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for index, (path, fingerprint) in enumerate(
                zip(candidates, executor.map(_surface_capture_digest, candidates), strict=True),
                1,
            ):
                fingerprints[path] = fingerprint
                if index == 1 or index % 100 == 0 or index == len(candidates):
                    print(
                        "surface deduplication %d/%d: checking captured sprite identity"
                        % (index, len(candidates)),
                        flush=True,
                    )

    masters: dict[tuple[int, bytes], Path] = {}
    aliases: dict[Path, Path] = {}
    for path in unique_paths:
        fingerprint = fingerprints.get(path)
        if fingerprint is None:
            continue
        master = masters.setdefault(fingerprint, path)
        if master != path:
            aliases[path] = master
    if not aliases:
        return unique_paths

    for group_name in ("scenes", "sprites"):
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for key, raw_value in list(group.items()):
            value = (project_root / str(raw_value)).resolve()
            master = aliases.get(value)
            if master is not None:
                group[key] = master.relative_to(project_root).as_posix()

    for alias in aliases:
        alias.unlink(missing_ok=True)
        alias.with_name(alias.name + ".surface-checkpoint").unlink(missing_ok=True)
        alias.with_name(alias.name + ".surface-normalized").unlink(missing_ok=True)
    print(
        "surface identity reuse: %d duplicate forms share %d unique captures"
        % (len(aliases), len(unique_paths) - len(aliases)),
        flush=True,
    )
    return [path for path in unique_paths if path not in aliases]


def _surface_normalization_worker_count(item_count: int) -> int:
    """Use available cores without retaining unsafe full-frame batches."""

    if item_count <= 0:
        return 1
    available = int(psutil.virtual_memory().available)
    memory_budget = max(0, available - SURFACE_NORMALIZATION_RESERVE_BYTES)
    memory_workers = max(1, memory_budget // SURFACE_NORMALIZATION_WORKER_BYTES)
    return max(
        1,
        min(
            SURFACE_NORMALIZATION_ABSOLUTE_WORKER_CAP,
            os.cpu_count() or 1,
            item_count,
            memory_workers,
        ),
    )


def _composite_pipeline_worker_count(item_count: int) -> int:
    """Adapt live composition to memory, CPUs, and pending work."""

    # Ren'Py's structural exporter is dominated by archive reads while these
    # workers run native NumPy/Pillow code. The same CPU/memory scheduler is a
    # better throughput bound than reserving one full logical CPU.
    return _surface_normalization_worker_count(item_count)


def _normalize_surface_capture_file(path: Path) -> None:
    """Normalize one direct surface in a worker-safe, atomic operation."""

    checkpoint_marker = path.with_name(path.name + ".surface-checkpoint")
    normalized_marker = path.with_name(path.name + ".surface-normalized")
    resumable_dynamic_surface = checkpoint_marker.is_file()

    with path.open("rb") as stream:
        magic = stream.read(16)
        if magic == b"SCENELIGHT_RGBA1":
            header = stream.read(12)
            if len(header) != 12:
                raise ValueError("Invalid SceneLight RGBA checkpoint header")
            width, height, reported_length = struct.unpack("<III", header)
            if width < 1 or height < 1 or width > 16384 or height > 16384:
                raise ValueError("Invalid SceneLight RGBA checkpoint dimensions")
            expected_length = width * height * 4
            if reported_length != expected_length:
                raise ValueError("Invalid SceneLight RGBA checkpoint length")
            decoder = zlib.decompressobj()
            raw = decoder.decompress(stream.read(), expected_length + 1)
            if len(raw) != expected_length or decoder.unconsumed_tail or not decoder.eof:
                raise ValueError("Invalid SceneLight RGBA checkpoint payload")
            source = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4).astype(np.uint16)
        else:
            stream.seek(0)
            with Image.open(stream) as image:
                source = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    alpha = source[..., 3:4]
    normalized = ((source * alpha) >> 8).astype(np.uint8)
    temporary = _capture_temporary_path(path, "surface")
    try:
        Image.fromarray(normalized, mode="RGBA").save(
            temporary,
            format="PNG",
            compress_level=1,
        )
        # Invalidate the raw checkpoint before publishing normalized pixels.
        # If the host stops between these operations, the next renderer pass
        # safely recreates this form instead of normalizing it twice.
        checkpoint_marker.unlink(missing_ok=True)
        normalized_marker.unlink(missing_ok=True)
        os.replace(temporary, path)
        if resumable_dynamic_surface:
            marker_temporary = _capture_temporary_path(normalized_marker, "marker")
            try:
                marker_temporary.write_text("normalized\n", encoding="utf-8")
                os.replace(marker_temporary, normalized_marker)
            finally:
                marker_temporary.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def _write_capture_result(path: Path, payload: dict[str, object]) -> None:
    temporary = _capture_temporary_path(path, "result")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _decode_result(
    discovery: ProjectDiscovery,
    payload: dict[str, object],
    *,
    cached: bool,
) -> CaptureResult:
    resolved_root = discovery.project_root.resolve()
    path_cache: dict[str, Path] = {}
    file_cache: dict[Path, bool] = {}
    directory_cache: dict[str, Path] = {}
    raw_sprites = payload.get("sprites", {})
    raw_composites = payload.get("composite_captures", {})
    if not isinstance(raw_sprites, dict) or not isinstance(raw_composites, dict):
        raise ValueError("Invalid SceneLight composite sprite result")

    def resolved_path(raw_value: object) -> Path:
        key = str(raw_value).replace("\\", "/")
        cached_path = path_cache.get(key)
        if cached_path is not None:
            return cached_path
        if key in raw_composites:
            path = _safe_composite_destination(
                discovery.project_root,
                key,
                resolved_root=resolved_root,
                directory_cache=directory_cache,
            )
        else:
            path = _safe_composite_path(
                discovery.project_root,
                key,
                resolved_root=resolved_root,
            )
        path_cache[key] = path
        return path

    def paths(name: str) -> dict[str, Path]:
        values = payload.get(name, {})
        if not isinstance(values, dict):
            raise ValueError(f"Invalid SceneLight capture group: {name}")
        return {str(key): resolved_path(value) for key, value in values.items()}

    tags = payload.get("character_tags", [])
    raw_candidates = payload.get("character_candidates", {})
    if not isinstance(raw_candidates, dict):
        raise ValueError("Invalid SceneLight character review candidates")
    character_candidates = {
        str(tag): (resolved_path(value) if value is not None else None)
        for tag, value in raw_candidates.items()
    }
    errors = payload.get("errors", [])
    resolved_requests = payload.get("resolved_requests", [])
    composite_sprites: dict[str, SpriteSpec] = {}
    raw_scene_sequences = payload.get("scene_sequences", {})
    if not isinstance(raw_scene_sequences, dict):
        raise ValueError("Invalid SceneLight temporal scene result")
    scene_sequences: dict[str, list[tuple[int, Path]]] = {}
    for raw_name, raw_frames in raw_scene_sequences.items():
        if not isinstance(raw_frames, list):
            raise ValueError("Invalid SceneLight temporal scene frames")
        frames: list[tuple[int, Path]] = []
        for raw_frame in raw_frames:
            if not isinstance(raw_frame, list) or len(raw_frame) != 2:
                raise ValueError("Invalid SceneLight temporal scene frame")
            frames.append((int(raw_frame[0]), resolved_path(raw_frame[1])))
        if frames:
            scene_sequences[str(raw_name)] = frames
    validated_composites: dict[
        str,
        tuple[tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]],
    ] = {}
    for raw_name, raw_relative in raw_sprites.items():
        relative = str(raw_relative).replace("\\", "/")
        manifest = raw_composites.get(relative)
        if manifest is None:
            continue
        validated = validated_composites.get(relative)
        if validated is None:
            _destination, size, layers = _validated_composite_job(
                discovery.project_root,
                relative,
                manifest,
                resolved_root=resolved_root,
                path_cache=path_cache,
                file_cache=file_cache,
                directory_cache=directory_cache,
            )
            validated = size, layers
            validated_composites[relative] = validated
        size, layers = validated
        composite_sprites[str(raw_name)] = SpriteSpec(
            name=str(raw_name),
            layers=tuple(Path(source) for source, _position in layers),
            positions=tuple(position for _source, position in layers),
            canvas_size=size,
            renderer_alpha=True,
        )
    return CaptureResult(
        scenes=paths("scenes"),
        sprites=paths("sprites"),
        character_tags=sorted(str(tag) for tag in tags) if isinstance(tags, list) else [],
        background_inventory_requested=bool(payload.get("background_inventory_requested", False)),
        scene_requests=(
            int(payload.get("scene_requests", 0))
            if isinstance(payload.get("scene_requests", 0), int)
            else 0
        ),
        resolved_requests=(
            sorted(str(name) for name in resolved_requests)
            if isinstance(resolved_requests, list)
            else []
        ),
        errors=[str(error) for error in errors] if isinstance(errors, list) else [],
        cached=cached,
        character_candidates=character_candidates,
        composite_sprites=composite_sprites,
        scene_sequences=scene_sequences,
        scene_frame_sources={
            str(name): {str(source): resolved_path(path) for source, path in sources.items()}
            for name, sources in payload.get("scene_frame_sources", {}).items()
        },
    )


def _validate_result(discovery: ProjectDiscovery, result: CaptureResult) -> CaptureResult:
    """Reject a broken resolver instead of silently installing weak fallbacks."""

    # A runtime inventory may legitimately contain no background declarations
    # (for example, a video-only or UI-only project). Treat that as an empty
    # compatible project, while still rejecting declarations the resolver saw
    # but failed to capture.
    if result.background_inventory_requested and result.scene_requests and not result.scenes:
        examples = "; ".join(error for error in result.errors if error.startswith("scene "))
        if examples:
            examples = examples[:800]
        else:
            examples = "the selected Ren'Py runtime did not report a capture error"
        summary = (
            f"Ren'Py found {result.scene_requests} background image declarations but could "
            "not capture any of them."
        )
        raise RuntimeError(f"{summary} First errors: {examples}")

    requested = {" ".join(name.lower().split()) for name in discovery.runtime_sprite_names}
    if not requested:
        return result
    resolved = {" ".join(name.lower().split()) for name in result.resolved_requests}
    missing = sorted(requested - resolved)
    if len(missing) > max(1, len(requested) // 4):
        examples = ", ".join(missing[:8])
        raise RuntimeError(
            "Ren'Py resolved fewer than 75% of the runtime-only sprite expressions "
            f"({len(requested) - len(missing)}/{len(requested)}). Missing examples: {examples}"
        )
    return result


def _capture_process_options(*, native_runtime: bool) -> tuple[object | None, int]:
    """Keep a normal graphics-capable launch surface for every Ren'Py runtime.

    SDL can silently fall back to Ren'Py's software renderer when either a
    native game or an SDK interpreter is created with ``SW_HIDE`` or
    ``CREATE_NO_WINDOW``. The in-engine capture callback hides the window as
    soon as the GPU renderer exists, so setup must not suppress the initial
    window at the process layer.
    """

    del native_runtime
    return None, 0


def _runtime_log_state(project_root: Path) -> dict[str, tuple[int, int, int]]:
    state = {}
    for name in ("traceback.txt", "log.txt"):
        try:
            stat = (project_root / name).stat()
            state[name] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except OSError:
            pass
    return state


def _runtime_diagnostic(
    project_root: Path, *, before: dict[str, tuple[int, int, int]] | None = None
) -> str:
    """Return a concise diagnosis plus the useful tail of Ren'Py's logs."""

    sections: list[str] = []
    combined: list[str] = []
    current = _runtime_log_state(project_root)
    for name in ("traceback.txt", "log.txt"):
        if before is not None and name in before and current.get(name) == before[name]:
            continue
        path = project_root / name
        if not path.is_file():
            continue
        try:
            tail = path.read_text(encoding="utf-8", errors="replace")[-5000:].strip()
        except OSError:
            continue
        if tail:
            sections.append(f"\n\n--- {name} (tail) ---\n{tail}")
            combined.append(tail.lower())

    evidence = "\n".join(combined)
    if "number of texture units: 0" in evidence or "can't find a workable environment" in evidence:
        diagnosis = (
            "\n\nRen'Py started, but it reported no usable GPU/OpenGL renderer "
            "('Number of texture units: 0'). SceneLight requires the selected game itself "
            "to create a graphics context. This is common in Windows Sandbox or a virtual "
            "machine without 3D acceleration; installing Python packages will not fix it. "
            "Enable virtual 3D acceleration or run the game on the host computer."
        )
    else:
        diagnosis = ""
    return diagnosis + "".join(sections)


def _managed_runtime_pids(project_root: Path) -> set[int]:
    """Return processes executing from this isolated managed game copy."""

    root = os.path.normcase(str(project_root.resolve()))
    result: set[int] = set()
    for process in psutil.process_iter(("pid", "exe")):
        try:
            executable = process.info.get("exe")
            if not executable:
                continue
            candidate = os.path.normcase(str(Path(str(executable)).resolve()))
            if os.path.commonpath((root, candidate)) == root:
                result.add(int(process.info["pid"]))
        except (OSError, ValueError, psutil.Error):
            continue
    return result


def _descendant_pids(parent_pids: set[int]) -> set[int]:
    """Return the complete process tree below launchers SceneLight started.

    Windows Ren'Py SDK launchers can exit after spawning a renderer whose
    executable lives in the SDK rather than the managed game copy. The child's
    recorded parent PID remains usable after that short-lived launcher exits.
    """

    relationships: dict[int, int] = {}
    for process in psutil.process_iter(("pid", "ppid")):
        try:
            relationships[int(process.info["pid"])] = int(process.info["ppid"])
        except (KeyError, TypeError, ValueError, psutil.Error):
            continue

    roots = set(parent_pids)
    known = set(roots)
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in relationships.items():
            if pid not in known and parent_pid in known:
                known.add(pid)
                changed = True
    return known - roots


def _stop_process_pids(pids: set[int]) -> None:
    """Stop only process IDs previously proven to descend from our launcher."""

    processes: list[psutil.Process] = []
    for pid in sorted(pids):
        if pid == os.getpid():
            continue
        try:
            process = psutil.Process(pid)
            process.terminate()
            processes.append(process)
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=3.0)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=3.0)


def _stop_managed_runtime_pids(project_root: Path, pids: set[int]) -> None:
    """Stop only capture processes proven to live under the managed copy."""

    current = _managed_runtime_pids(project_root)
    processes: list[psutil.Process] = []
    for pid in sorted(pids & current):
        try:
            process = psutil.Process(pid)
            process.terminate()
            processes.append(process)
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=3.0)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=3.0)


@contextmanager
def _capture_process(command, *, cwd, environment, startupinfo, creationflags):
    """Keep launcher-based temp locks private until this child tree has stopped."""
    # Mod single-instance guards often key a lock by sys.argv[0], which is the
    # SAME SDK launcher for different cloned games. Set the child's temp paths
    # before Python starts and caches tempfile.gettempdir(). Keep the path short
    # because some guards append the entire launcher path as the lock filename.
    with tempfile.TemporaryDirectory(prefix="slc-", ignore_cleanup_errors=True) as temporary:
        child_environment = environment.copy()
        child_environment.update({name: temporary for name in ("TMP", "TEMP", "TMPDIR")})
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=child_environment,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        owned_runtime_pids: set[int] = set()
        try:
            yield process, owned_runtime_pids
        finally:
            # SDK launchers can exit before their renderer. Its recorded parent
            # PID is still usable even if supervision failed before the first poll.
            owned_runtime_pids.update(_descendant_pids({process.pid} | owned_runtime_pids))
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            _stop_process_pids(owned_runtime_pids)


def _run_capture_request(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    request_path: Path,
    result_path: Path,
    native_runtime: bool,
    timeout_seconds: int,
    purpose: str,
    progress_path: Path | None = None,
    composite_job_root: Path | None = None,
    materialize_composites: bool = True,
    renderer: str | None = None,
    checkpoint_root: Path | None = None,
    checkpoint_limit: int | None = None,
    progress_state: _CaptureProgressState | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    show_progress: bool = True,
    isolated_parallel: bool = False,
) -> bool:
    """Run one isolated native-engine request and require an atomic result."""

    result_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["SCENELIGHT_CAPTURE_REQUEST"] = str(request_path)
    # Ren'Py's image-state resolver contains set/dict traversals. A stable hash
    # seed keeps the canonical form plan identical when a memory-safe batch
    # starts a new interpreter.
    environment["PYTHONHASHSEED"] = "0"
    environment.setdefault("SDL_AUDIODRIVER", "dummy")
    if renderer is None:
        environment.pop("RENPY_RENDERER", None)
    else:
        environment["RENPY_RENDERER"] = renderer

    startupinfo, creationflags = _capture_process_options(native_runtime=native_runtime)
    preexisting_runtime_pids = (
        set() if isolated_parallel else _managed_runtime_pids(discovery.project_root)
    )
    visible_progress = progress_state or _CaptureProgressState()
    previous_forms = [
        (total, current)
        for (stage, total), current in visible_progress.watermarks.items()
        if stage == "form"
    ]
    if previous_forms and show_progress:
        total, current = max(previous_forms, key=lambda value: (value[1], value[0]))
        print(
            f"SceneLight resolver resume {current}/{total}: "
            "starting the next memory-safe capture batch",
            flush=True,
        )
    working_directory = (
        discovery.project_root if native_runtime else renpy_executable.resolve().parent
    )
    diagnostics.event(
        "capture",
        "Starting isolated capture",
        purpose=purpose,
        project=str(discovery.project_root),
        renderer=renderer,
        executable=str(renpy_executable),
        native_runtime=native_runtime,
        timeout_seconds=timeout_seconds,
    )
    logs_before = _runtime_log_state(discovery.project_root)
    with _capture_process(
        _capture_command(
            renpy_executable,
            discovery.project_root,
            native_runtime=native_runtime,
        ),
        cwd=working_directory,
        environment=environment,
        startupinfo=startupinfo,
        creationflags=creationflags,
    ) as (process, owned_runtime_pids):
        capture_started = time.perf_counter()
        diagnostics.event(
            "capture.process",
            "Capture process started",
            engine_pid=process.pid,
            project=str(discovery.project_root),
            renderer=renderer,
            purpose=purpose,
        )
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        last_runtime_progress: tuple[object, ...] | None = None
        exit_grace_deadline: float | None = None
        composite_executor: ProcessPoolExecutor | None = None
        composite_futures = []
        seen_composite_jobs: set[Path] = set()
        seen_composite_destinations: set[Path] = set()
        planned_form_total: int | None = None
        reported_work = -1
        batch_yielded = False
        checkpoint_baseline = (
            _durable_form_checkpoint_count(checkpoint_root) if checkpoint_root is not None else 0
        )
        latest_form_progress: int | None = None
        if composite_job_root is not None and materialize_composites:
            composite_job_root.mkdir(parents=True, exist_ok=True)
            composite_executor = ProcessPoolExecutor(
                max_workers=_composite_pipeline_worker_count(1024)
            )

        def submit_composite_jobs() -> None:
            if composite_job_root is None:
                return
            for job_path in composite_job_root.glob("composite_*.json"):
                if job_path in seen_composite_jobs:
                    continue
                try:
                    raw_job = json.loads(job_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    # Jobs publish by atomic replace. A transient reader failure is
                    # retried on the next 50 ms supervision pass.
                    continue
                if not isinstance(raw_job, dict):
                    raise ValueError("Invalid SceneLight composite pipeline job")
                job = _validated_composite_job(
                    discovery.project_root,
                    raw_job.get("destination"),
                    raw_job.get("manifest"),
                )
                seen_composite_jobs.add(job_path)
                destination = Path(job[0])
                seen_composite_destinations.add(destination)
                marker = destination.with_name(destination.name + ".composite-normalized")
                if composite_executor is not None and (
                    not destination.is_file() or not marker.is_file()
                ):
                    composite_futures.append(
                        composite_executor.submit(_materialize_composite_capture_file, job)
                    )

        while True:
            if not isolated_parallel:
                current_runtime_pids = _managed_runtime_pids(discovery.project_root)
                owned_runtime_pids.update(current_runtime_pids - preexisting_runtime_pids)
            owned_runtime_pids.update(_descendant_pids({process.pid} | owned_runtime_pids))
            active_owned_pids = {pid for pid in owned_runtime_pids if psutil.pid_exists(pid)}
            running = process.poll() is None or bool(active_owned_pids)
            if progress_path is not None and progress_path.is_file():
                try:
                    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    progress_payload = None
                progress_line = _capture_progress_line(progress_payload)
                if progress_line is not None:
                    progress_key, line = progress_line
                    if progress_key != last_runtime_progress:
                        last_runtime_progress = progress_key
                        # ``timeout_seconds`` is a stall limit, not a cap on the
                        # size of a healthy capture. Large mods can legitimately
                        # contain tens of thousands of canonical forms, so a fixed
                        # wall-clock deadline would kill an active renderer and
                        # restart the entire pass with another backend.
                        deadline = max(deadline, time.monotonic() + timeout_seconds)
                    stage = str(progress_payload["stage"])
                    current = int(progress_payload["current"])
                    total = int(progress_payload["total"])
                    if stage == "form":
                        latest_form_progress = current
                    if stage in {"planned", "checkpoint", "restore", "form"}:
                        planned_form_total = total
                    watermark_key = (stage, total)
                    prior = visible_progress.watermarks.get(watermark_key, -1)
                    if current > prior and progress_key not in visible_progress.seen:
                        if progress_callback is not None:
                            progress_callback(stage, current, total)
                        if show_progress:
                            print(line, flush=True)
                        visible_progress.watermarks[watermark_key] = current
                        visible_progress.seen.add(progress_key)
            submit_composite_jobs()
            if planned_form_total and checkpoint_root is not None:
                checkpoint_destinations = {
                    Path(str(marker)[: -len(suffix)])
                    for suffix in (".surface-checkpoint", ".surface-normalized")
                    for marker in checkpoint_root.glob("sprite_*.png" + suffix)
                }
                durable_work = min(
                    planned_form_total,
                    len(seen_composite_destinations | checkpoint_destinations),
                )
                if durable_work > reported_work and (
                    reported_work < 0
                    or durable_work == planned_form_total
                    or durable_work - reported_work >= 10
                ):
                    if show_progress:
                        print(
                            f"SceneLight capture work {durable_work}/{planned_form_total}: "
                            "saved sprite captures",
                            flush=True,
                        )
                    reported_work = durable_work
            if result_path.is_file():
                # The hook publishes only by atomic replace, so existence means the
                # render is complete. SceneLight owns this isolated helper and can
                # stop it without entering mod-defined quit labels or error screens.
                if running:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
                    _stop_process_pids(owned_runtime_pids)
                    if not isolated_parallel:
                        _stop_managed_runtime_pids(discovery.project_root, owned_runtime_pids)
                break
            if (
                checkpoint_root is not None
                and checkpoint_limit is not None
                and checkpoint_limit > 0
                and latest_form_progress is not None
                and latest_form_progress - checkpoint_baseline >= checkpoint_limit
            ):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                _stop_process_pids(owned_runtime_pids)
                if not isolated_parallel:
                    _stop_managed_runtime_pids(discovery.project_root, owned_runtime_pids)
                batch_yielded = True
                break
            now = time.monotonic()
            if not running:
                # Older Windows Ren'Py launchers can report exit just before their
                # renderer callback's atomic result becomes visible to the parent
                # process.  A short bounded grace period avoids misreporting that
                # successful request as an exit-0 failure.
                if exit_grace_deadline is None:
                    grace_seconds = _capture_exit_grace_seconds(
                        checkpoint_root,
                        checkpoint_baseline,
                    )
                    exit_grace_deadline = min(deadline, now + grace_seconds)
                if now >= exit_grace_deadline:
                    break
            elif now >= deadline:
                timed_out = True
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                _stop_process_pids(owned_runtime_pids)
                if not isolated_parallel:
                    _stop_managed_runtime_pids(discovery.project_root, owned_runtime_pids)
                break
            time.sleep(0.05)

        returncode = process.wait()
        if composite_executor is not None:
            if result_path.is_file():
                submit_composite_jobs()
                pending_count = len(composite_futures)
                if pending_count:
                    print(
                        f"composite assembly 0/{pending_count}: finishing layered sprite captures",
                        flush=True,
                    )
                for index, future in enumerate(as_completed(composite_futures), 1):
                    future.result()
                    if index == 1 or index % 10 == 0 or index == pending_count:
                        print(
                            f"composite assembly {index}/{pending_count}: "
                            "finishing layered sprite captures",
                            flush=True,
                        )
                composite_executor.shutdown(wait=True)
            else:
                composite_executor.shutdown(wait=True, cancel_futures=True)
        if result_path.is_file():
            diagnostics.event(
                "capture.result",
                "Capture completed",
                engine_pid=process.pid,
                project=str(discovery.project_root),
                elapsed_seconds=round(time.perf_counter() - capture_started, 3),
            )
            return True
        if batch_yielded:
            return False
        detail = _runtime_diagnostic(discovery.project_root, before=logs_before)
        session = diagnostics.current_session()
        if session is not None:
            session.event(
                "capture",
                "Capture did not complete",
                "error",
                purpose=purpose,
                renderer=renderer,
                exit_code=returncode,
                timed_out=timed_out,
                last_progress=last_runtime_progress,
                project=str(discovery.project_root),
            )
            session.attach_text(discovery.project_root.name + "-engine-failure", detail)
        if _is_instance_conflict(detail):
            raise CaptureInstanceConflict(
                "The mod's single-instance protection blocked SceneLight capture. "
                "Close other copies of this mod or other SceneLight setup sessions and retry. "
                "Completed sprite checkpoints are retained." + detail
            )
        if timed_out and last_runtime_progress is not None:
            reason = f"made no progress for {timeout_seconds} seconds"
        elif timed_out:
            reason = f"timed out after {timeout_seconds} seconds"
        else:
            reason = f"exit {returncode}"
        raise RuntimeError(f"Ren'Py could not {purpose} ({reason}).{detail}")


def _capture_progress_line(
    payload: object,
) -> tuple[tuple[object, ...], str] | None:
    """Convert an atomic in-engine checkpoint into setup-visible progress."""

    if not isinstance(payload, dict):
        return None
    stage = payload.get("stage")
    current = payload.get("current")
    total = payload.get("total")
    if not isinstance(stage, str) or not isinstance(current, int) or not isinstance(total, int):
        return None
    if current < 0 or total <= 0 or current > total:
        return None
    if stage == "scene":
        return (stage, current, total), f"SceneLight resolver background {current}/{total}"
    if stage == "inventory":
        return (stage, current, total), f"SceneLight story inventory {current}/{total}"
    if stage == "families":
        return (stage, current, total), f"SceneLight image families {current}/{total}"
    if stage == "geometry":
        return (stage, current, total), f"SceneLight character geometry {current}/{total}"
    if stage == "catalog":
        return (stage, current, total), f"SceneLight image catalog {current}/{total}"
    if stage == "plan":
        return (stage, current, total), f"SceneLight resolver plan {current}/{total}"
    if stage == "form":
        item = payload.get("item")
        suffix = f": {item}" if isinstance(item, str) and item else ""
        return (stage, current, total, item), (
            f"SceneLight resolver form {current}/{total}{suffix}"
        )
    if stage == "planned":
        requests = payload.get("requests")
        if not isinstance(requests, int) or requests < 0:
            return None
        return (
            (stage, total, requests),
            f"SceneLight resolver planned {total} canonical forms for {requests} requests.",
        )
    if stage == "restore":
        return (
            (stage, current, total),
            f"SceneLight restored {current}/{total} completed sprite forms; "
            f"{total - current} remain.",
        )
    if stage == "checkpoint":
        return (
            (stage, current, total),
            f"SceneLight checkpoint scan {current}/{total}",
        )
    return None


def preflight_runtime(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    native_runtime: bool = False,
    timeout_seconds: int = 90,
    renderer: str | None = None,
) -> str | None:
    """Prove that the selected game initializes before expensive analysis."""

    cache_root = discovery.project_root / ".scenelight_cache"
    output_root = cache_root / "preflight"
    cache_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    request_path = cache_root / "preflight_request.json"
    result_path = cache_root / "preflight_result.json"
    request = {
        "version": CAPTURE_VERSION,
        "output_dir": str(output_root.relative_to(discovery.project_root)).replace("\\", "/"),
        "result": str(result_path.relative_to(discovery.project_root)).replace("\\", "/"),
        "sprite_names": [],
        "sprite_sequences": [],
        "character_tags": discovery.character_tags,
        "explicit_character_tags": discovery.explicit_character_tags,
        "character_selection": discovery.character_selection,
        "inventory_backgrounds": False,
        "inventory_characters": False,
        "probe_texture_cleanup": True,
    }
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    _run_capture_request(
        discovery,
        renpy_executable,
        request_path=request_path,
        result_path=result_path,
        native_runtime=native_runtime,
        timeout_seconds=timeout_seconds,
        purpose="initialize the selected game's renderer for the SceneLight preflight",
        renderer=renderer,
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("version") != CAPTURE_VERSION:
        raise ValueError("Ren'Py wrote an incompatible SceneLight preflight result")
    if payload.get("texture_cleanup_ok") is False:
        version = payload.get("renpy_version", "This Ren'Py runtime")
        raise ValueError(
            f"{version} leaks graphics textures. "
            "SceneLight cannot safely use it for playback. Select a corrected Ren'Py 8 runtime "
            "or SceneLight's verified Ren'Py 7 compatibility runtime for Python 2 games."
        )
    save_directory = payload.get("save_directory")
    if save_directory is None:
        return None
    if not isinstance(save_directory, str):
        raise ValueError("Ren'Py wrote an invalid save-directory identifier")
    save_directory = save_directory.strip()
    if not save_directory or any(part in save_directory for part in ("/", "\\", "..")):
        raise ValueError("Ren'Py wrote an unsafe save-directory identifier")
    return save_directory


def capture_runtime_review(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    native_runtime: bool = False,
    timeout_seconds: int = 300,
    renderer: str | None = None,
) -> CaptureResult:
    """Inventory reviewable image families without capturing every sprite form."""

    review_discovery = replace(
        discovery,
        explicit_character_tags=[],
        character_selection="automatic",
    )
    signature = _project_signature(review_discovery)
    cache_root = discovery.project_root / ".scenelight_cache" / "review" / signature[:16]
    preview_root = cache_root / "previews"
    request_path = cache_root / "request.json"
    result_path = cache_root / "result.json"
    state_path = cache_root / "state.json"
    progress_path = cache_root / "progress.json"
    preview_root.mkdir(parents=True, exist_ok=True)

    if state_path.is_file() and result_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
            payload = {}
        if (
            state.get("version") == CAPTURE_VERSION
            and state.get("signature") == signature
            and payload.get("version") == CAPTURE_VERSION
            and _paths_exist(discovery.project_root, payload)
        ):
            return _decode_result(discovery, payload, cached=True)

    request = {
        "version": CAPTURE_VERSION,
        "output_dir": str(preview_root.relative_to(discovery.project_root)).replace("\\", "/"),
        "result": str(result_path.relative_to(discovery.project_root)).replace("\\", "/"),
        "progress": str(progress_path.relative_to(discovery.project_root)).replace("\\", "/"),
        "sprite_names": [],
        "sprite_sequences": [],
        "character_tags": [],
        "explicit_character_tags": [],
        "character_selection": "automatic",
        "inventory_backgrounds": False,
        "inventory_characters": True,
        "review_only": True,
    }
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    progress_path.unlink(missing_ok=True)
    _run_capture_request(
        discovery,
        renpy_executable,
        request_path=request_path,
        result_path=result_path,
        native_runtime=native_runtime,
        timeout_seconds=timeout_seconds,
        purpose="inventory character families for SceneLight review",
        progress_path=progress_path,
        composite_job_root=preview_root / "composite_jobs",
        renderer=renderer,
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("version") != CAPTURE_VERSION:
        raise ValueError("Ren'Py wrote an incompatible SceneLight review result")
    _merge_composite_capture_jobs(discovery.project_root, preview_root / "composite_jobs", payload)
    _materialize_composite_captures(discovery.project_root, payload)
    if not _paths_exist(discovery.project_root, payload):
        raise FileNotFoundError("Ren'Py did not write every SceneLight review preview")
    _deduplicate_normalized_captures(discovery.project_root, payload)
    _normalize_surface_captures(discovery.project_root, payload)
    _write_capture_result(result_path, payload)
    state_path.write_text(
        json.dumps({"version": CAPTURE_VERSION, "signature": signature}, indent=2) + "\n",
        encoding="utf-8",
    )
    return _decode_result(discovery, payload, cached=False)


def _capture_form_worker_count(form_count: int) -> int:
    """Choose isolated Ren'Py workers from live CPU, memory, and workload."""

    if form_count < CAPTURE_PARALLEL_MIN_FORMS:
        return 1
    available = int(psutil.virtual_memory().available)
    memory_budget = max(0, available - CAPTURE_FORM_WORKER_RESERVE_BYTES)
    memory_workers = max(1, memory_budget // CAPTURE_FORM_WORKER_BYTES)
    cpu_workers = max(1, (os.cpu_count() or 1) // 2)
    workload_workers = max(1, (form_count + 749) // 750)
    return max(
        1,
        min(
            CAPTURE_FORM_WORKER_CAP,
            memory_workers,
            cpu_workers,
            workload_workers,
        ),
    )


def _partition_capture_forms(planned_forms: list[str], worker_count: int) -> list[list[str]]:
    """Split ordered forms evenly while preserving sprite-family locality."""

    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    base_size, larger_chunks = divmod(len(planned_forms), worker_count)
    chunks: list[list[str]] = []
    offset = 0
    for worker_index in range(worker_count):
        chunk_size = base_size + (1 if worker_index < larger_chunks else 0)
        chunks.append(planned_forms[offset : offset + chunk_size])
        offset += chunk_size
    return chunks


def _capture_worker_copy(source: str, destination: str) -> str:
    """Hard-link immutable distribution assets and copy writable runtime files."""

    source_path = Path(source)
    destination_path = Path(destination)
    link_suffixes = {
        ".avi",
        ".dll",
        ".exe",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".otf",
        ".png",
        ".pyd",
        ".rpa",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
    }
    if source_path.suffix.lower() in link_suffixes:
        try:
            os.link(source_path, destination_path)
            return str(destination_path)
        except OSError:
            pass
    return shutil.copy2(source_path, destination_path)


def _clone_capture_runtime(source: Path, destination: Path) -> None:
    source = source.resolve()
    immutable_runtime_roots = {"lib", "renpy"}

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        ignored: set[str] = set()
        if current == source:
            ignored.update(name for name in names if name.startswith(".scenelight_cache"))
        if current == source / "game":
            ignored.update(name for name in names if name in {"cache", "saves"})
        return ignored

    def copy_worker_file(source_name: str, destination_name: str) -> str:
        source_path = Path(source_name).resolve()
        relative = source_path.relative_to(source)
        if relative.parts and relative.parts[0].lower() in immutable_runtime_roots:
            try:
                os.link(source_path, destination_name)
                return destination_name
            except OSError:
                pass
        return _capture_worker_copy(source_name, destination_name)

    shutil.copytree(
        source,
        destination,
        copy_function=copy_worker_file,
        ignore=ignore,
    )


def _schedule_capture_worker_cleanup(worker_group: Path) -> threading.Thread:
    """Release completed worker trees without blocking the next build phase."""

    thread = threading.Thread(
        target=shutil.rmtree,
        args=(worker_group,),
        kwargs={"ignore_errors": True},
        name="scenelight-worker-cleanup",
        daemon=False,
    )
    thread.start()
    return thread


def _relativize_capture_payload(project_root: Path, payload: dict[str, object]) -> None:
    """Make absolute worker outputs portable inside the managed project cache."""

    resolved_root = project_root.resolve()

    def relative(raw: object) -> str:
        path = Path(str(raw))
        resolved = path.resolve() if path.is_absolute() else (resolved_root / path).resolve()
        try:
            return resolved.relative_to(resolved_root).as_posix()
        except ValueError as error:
            raise ValueError("SceneLight worker output escaped the managed project") from error

    for group_name in ("scenes", "sprites", "character_candidates"):
        group = payload.get(group_name)
        if not isinstance(group, dict):
            continue
        for name, raw_path in list(group.items()):
            if raw_path is not None:
                group[name] = relative(raw_path)
    for list_name in ("surface_captures", "normalized_captures"):
        values = payload.get(list_name)
        if isinstance(values, list):
            payload[list_name] = [relative(value) for value in values]
    raw_composites = payload.get("composite_captures")
    if not isinstance(raw_composites, dict):
        return
    composites: dict[str, object] = {}
    for raw_destination, raw_manifest in raw_composites.items():
        if not isinstance(raw_manifest, dict):
            continue
        manifest = dict(raw_manifest)
        raw_layers = manifest.get("layers")
        if isinstance(raw_layers, list):
            layers = []
            for raw_layer in raw_layers:
                if not isinstance(raw_layer, dict):
                    continue
                layer = dict(raw_layer)
                layer["source"] = relative(layer.get("source"))
                layers.append(layer)
            manifest["layers"] = layers
        composites[relative(raw_destination)] = manifest
    payload["composite_captures"] = composites


def _load_runtime_capture_plan(
    path: Path,
    signature: str,
) -> tuple[list[str], dict[str, list[str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != CAPTURE_PLAN_VERSION or payload.get("signature") != signature:
        raise ValueError("Ren'Py wrote an incompatible SceneLight character plan")
    raw_forms = payload.get("planned_forms")
    raw_requests = payload.get("request_forms")
    if not isinstance(raw_forms, list) or not isinstance(raw_requests, dict):
        raise ValueError("Ren'Py wrote an invalid SceneLight character plan")
    forms = [str(value) for value in raw_forms if isinstance(value, str) and value.strip()]
    requests: dict[str, list[str]] = {}
    for raw_name, raw_values in raw_requests.items():
        if not isinstance(raw_name, str) or not isinstance(raw_values, list):
            raise ValueError("Ren'Py wrote an invalid SceneLight character request plan")
        requests[raw_name] = [
            str(value) for value in raw_values if isinstance(value, str) and value.strip()
        ]
    if len(forms) != len(set(forms)) or not forms or not requests:
        raise ValueError("Ren'Py wrote an incomplete SceneLight character plan")
    return forms, requests


def _merge_parallel_capture_payloads(
    master: dict[str, object],
    workers: list[dict[str, object]],
    request_forms: dict[str, list[str]],
) -> dict[str, object]:
    """Merge isolated form workers into the ordinary capture-result contract."""

    merged = dict(master)
    sprites: dict[str, str] = {}
    composites: dict[str, object] = {}
    surface_captures: set[str] = set()
    normalized_captures: set[str] = set()
    errors = [str(value) for value in master.get("errors", [])]
    for payload in workers:
        if payload.get("version") != CAPTURE_VERSION or payload.get("plan_only"):
            raise ValueError("Ren'Py wrote an incompatible SceneLight worker result")
        raw_sprites = payload.get("sprites", {})
        raw_composites = payload.get("composite_captures", {})
        if not isinstance(raw_sprites, dict) or not isinstance(raw_composites, dict):
            raise ValueError("Ren'Py wrote an invalid SceneLight worker result")
        sprites.update((str(name), str(path)) for name, path in raw_sprites.items())
        composites.update((str(path), value) for path, value in raw_composites.items())
        surface_captures.update(str(value) for value in payload.get("surface_captures", []))
        normalized_captures.update(str(value) for value in payload.get("normalized_captures", []))
        errors.extend(str(value) for value in payload.get("errors", []))

    expected_forms = {form for forms in request_forms.values() for form in forms}
    missing_forms = expected_forms - set(sprites)
    if missing_forms:
        raise RuntimeError(
            "SceneLight capture workers did not return %d planned sprite forms."
            % len(missing_forms)
        )

    used_paths = set(sprites.values())
    merged["sprites"] = sprites
    merged["composite_captures"] = {
        path: manifest for path, manifest in composites.items() if path in used_paths
    }
    merged["surface_captures"] = sorted(surface_captures & used_paths)
    merged["normalized_captures"] = sorted(normalized_captures & used_paths)
    merged["resolved_requests"] = sorted(
        requested
        for requested, forms in request_forms.items()
        if any(form in sprites for form in forms)
    )
    merged["errors"] = errors
    merged["plan_only"] = False

    raw_candidates = master.get("character_candidates", {})
    candidates = dict(raw_candidates) if isinstance(raw_candidates, dict) else {}
    candidate_tags = set(candidates)
    candidate_tags.update(str(value) for value in master.get("character_tags", []))
    for tag in sorted(candidate_tags):
        preview = None
        for requested, forms in sorted(request_forms.items()):
            if requested.split()[0] != tag:
                continue
            preview = next((sprites[form] for form in forms if form in sprites), None)
            if preview is not None:
                break
        candidates[tag] = preview
    merged["character_candidates"] = candidates
    return merged


def _capture_worker_renderers(
    renderer: str | None,
    renderer_root: Path,
) -> list[str | None]:
    """Prefer stable ANGLE for isolated Windows software-capture workers."""

    fallbacks = ("angle2", "gl2") if (renderer_root / "gl2").is_dir() else ()
    if renderer is None and os.name == "nt" and fallbacks:
        return list(fallbacks)
    values: list[str | None] = [renderer]
    values.extend(value for value in fallbacks if value not in values)
    return values


def _run_parallel_capture_workers(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    cache_root: Path,
    capture_root: Path,
    planned_forms: list[str],
    master_payload: dict[str, object],
    native_runtime: bool,
    timeout_seconds: int,
    renderer: str | None,
) -> list[dict[str, object]]:
    worker_count = _capture_form_worker_count(len(planned_forms))
    if worker_count <= 1:
        raise ValueError("Parallel SceneLight capture requires at least two workers")
    chunks = _partition_capture_forms(planned_forms, worker_count)

    totals = [len(chunk) for chunk in chunks]
    completed = [0] * worker_count
    total_forms = len(planned_forms)
    progress_lock = threading.Lock()
    last_reported = [-1]
    report_step = max(25, total_forms // 100)
    print(
        f"SceneLight parallel forms 0/{total_forms}: "
        f"starting {worker_count} isolated capture workers",
        flush=True,
    )
    worker_group = Path(
        tempfile.mkdtemp(prefix=".slw-", dir=str(discovery.project_root.resolve().parent))
    )
    worker_projects = [worker_group / f"w{index + 1}" for index in range(worker_count)]
    copies_completed = [0]
    prepared = [False] * worker_count
    capture_mode = [f"{worker_count} isolated capture workers"]

    def report(worker_index: int, stage: str, current: int, total: int) -> None:
        if stage not in {"restore", "form"} or total != totals[worker_index]:
            return
        with progress_lock:
            completed[worker_index] = max(completed[worker_index], current)
            aggregate = min(total_forms, sum(completed))
            if (
                last_reported[0] < 0
                or aggregate == total_forms
                or aggregate - last_reported[0] >= report_step
            ):
                last_reported[0] = aggregate
                print(
                    f"SceneLight parallel forms {aggregate}/{total_forms}: {capture_mode[0]}",
                    flush=True,
                )

    def run_worker(worker_index: int) -> dict[str, object]:
        worker_number = worker_index + 1
        worker_project = worker_projects[worker_index]
        if not prepared[worker_index]:
            _clone_capture_runtime(discovery.project_root, worker_project)
            prepared[worker_index] = True
            with progress_lock:
                copies_completed[0] += 1
                print(
                    f"SceneLight worker copies {copies_completed[0]}/{worker_count}: "
                    "isolated game runtimes ready",
                    flush=True,
                )
        worker_discovery = replace(
            discovery,
            project_root=worker_project,
            game_root=worker_project / "game",
        )
        worker_executable = renpy_executable
        if native_runtime:
            try:
                executable_relative = renpy_executable.resolve().relative_to(
                    discovery.project_root.resolve()
                )
            except ValueError as error:
                raise ValueError(
                    "The native Ren'Py launcher is outside the managed project"
                ) from error
            worker_executable = worker_project / executable_relative
        worker_root = capture_root / "parallel" / f"worker-{worker_number}"
        worker_root.mkdir(parents=True, exist_ok=True)
        request_path = cache_root / f"capture_worker_{worker_number}_request.json"
        result_path = cache_root / f"capture_worker_{worker_number}_result.json"
        progress_path = cache_root / f"capture_worker_{worker_number}_progress.json"
        request = {
            "version": CAPTURE_VERSION,
            "output_dir": str(worker_root.resolve()),
            "result": str(result_path.resolve()),
            "progress": str(progress_path.resolve()),
            "component_dir": str((capture_root / "components").resolve()),
            "defer_composites": True,
            "explicit_forms": chunks[worker_index],
            "sprite_names": [],
            "sprite_sequences": [],
            "character_tags": master_payload.get("character_tags", []),
            "explicit_character_tags": discovery.explicit_character_tags,
            "character_selection": discovery.character_selection,
            "inventory_backgrounds": False,
            "inventory_characters": False,
        }
        request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        progress_path.unlink(missing_ok=True)
        renderer_root = worker_executable.parent / "renpy"
        worker_renderers = _capture_worker_renderers(renderer, renderer_root)
        last_error: RuntimeError | None = None
        for renderer_index, worker_renderer in enumerate(worker_renderers):
            progress_path.unlink(missing_ok=True)
            try:
                _run_capture_request_resumable(
                    worker_discovery,
                    worker_executable,
                    request_path=request_path,
                    result_path=result_path,
                    native_runtime=native_runtime,
                    timeout_seconds=timeout_seconds,
                    purpose=f"capture SceneLight sprite batch {worker_number} of {worker_count}",
                    progress_path=progress_path,
                    composite_job_root=worker_root / "composite_jobs",
                    renderer=worker_renderer,
                    capture_root=worker_root,
                    progress_callback=lambda stage, current, total: report(
                        worker_index, stage, current, total
                    ),
                    show_progress=False,
                    isolated_parallel=True,
                    checkpoint_limit=CAPTURE_PARALLEL_PROCESS_BATCH_SIZE,
                )
                last_error = None
                break
            except CaptureInstanceConflict:
                raise
            except RuntimeError as error:
                last_error = error
                if renderer_index + 1 < len(worker_renderers):
                    next_renderer = worker_renderers[renderer_index + 1]
                    print(
                        f"SceneLight worker {worker_number}/{worker_count}: "
                        f"retrying with the {next_renderer} renderer",
                        flush=True,
                    )
        if last_error is not None:
            raise last_error
        with progress_lock:
            completed[worker_index] = totals[worker_index]
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        _relativize_capture_payload(discovery.project_root, payload)
        return payload

    results: list[dict[str, object] | None] = [None] * worker_count
    try:
        conflicts: list[int] = []
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(run_worker, worker_index): worker_index
                for worker_index in range(worker_count)
            }
            for future in as_completed(futures):
                worker_index = futures[future]
                try:
                    results[worker_index] = future.result()
                except CaptureInstanceConflict:
                    conflicts.append(worker_index)
                except Exception as error:
                    failures.append(error)
        # All children have settled before retrying a guard that uses a global
        # mutex instead of temp files. Preserve healthy shards and reuse the
        # failed shard's exact output directory, plan, and durable checkpoints.
        if failures:
            raise failures[0]
        if conflicts:
            print(
                "SceneLight detected the mod's single-instance protection. "
                "Finishing blocked sprite batches one at a time from saved progress.",
                flush=True,
            )
            capture_mode[0] = "sequential capture (single-instance protection)"
            for worker_index in sorted(conflicts):
                results[worker_index] = run_worker(worker_index)
        report(0, "form", totals[0], totals[0])
        return [payload for payload in results if payload is not None]
    finally:
        print(
            "SceneLight worker cleanup 1/1: releasing isolated game runtimes in the background",
            flush=True,
        )
        _schedule_capture_worker_cleanup(worker_group)


def capture_runtime_assets(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    native_runtime: bool = False,
    timeout_seconds: int = 900,
    renderer: str | None = None,
) -> CaptureResult:
    """Capture unresolved raw assets through the target Ren'Py runtime."""

    cache_root = discovery.project_root / ".scenelight_cache"
    # A signature-specific directory makes per-form checkpoint reuse safe:
    # changed art, script state, or resolver code can never reuse stale pixels.
    # Raw pixels depend on the helper and visual project content, not on which
    # subset happened to request them. A later scan can therefore add a sprite
    # family without moving every unchanged per-form checkpoint to a new cache.
    content_signature = _capture_content_signature(discovery)
    signature = _project_signature(discovery, content_signature=content_signature)
    capture_root = cache_root / "captured" / content_signature[:16]
    cache_root.mkdir(parents=True, exist_ok=True)
    capture_root.mkdir(parents=True, exist_ok=True)
    request_path = cache_root / "capture_request.json"
    result_path = cache_root / "capture_result.json"
    state_path = cache_root / "capture_state.json"
    progress_path = cache_root / "capture_progress.json"

    if state_path.is_file() and result_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
            result_payload = {}
        if (
            state.get("version") == CAPTURE_VERSION
            and state.get("signature") == signature
            and result_payload.get("version") == CAPTURE_VERSION
            and _paths_exist(discovery.project_root, result_payload)
        ):
            return _validate_result(
                discovery,
                _decode_result(discovery, result_payload, cached=True),
            )

    request = {
        "version": CAPTURE_VERSION,
        "output_dir": str(capture_root.relative_to(discovery.project_root)).replace("\\", "/"),
        "result": str(result_path.relative_to(discovery.project_root)).replace("\\", "/"),
        "progress": str(progress_path.relative_to(discovery.project_root)).replace("\\", "/"),
        "plan_signature": signature,
        "defer_composites": True,
        "sprite_names": discovery.runtime_sprite_names,
        "sprite_sequences": discovery.runtime_sprite_sequences,
        "character_tags": discovery.character_tags,
        "explicit_character_tags": discovery.explicit_character_tags,
        "character_selection": discovery.character_selection,
        # Source parsing is intentionally conservative and cannot see every
        # archive image, alias, ATL block, Movie, Composite, LiveTile, or
        # DynamicDisplayable. The loaded game's registry is authoritative, so
        # every full capture inventories registered backgrounds even when the
        # fast parser already found a usable subset.
        "inventory_backgrounds": True,
        "scene_analysis": discovery.scene_analysis,
        "inventory_characters": discovery.requires_runtime_inventory
        or not discovery.character_tags,
    }
    if _capture_form_worker_count(CAPTURE_PARALLEL_MIN_FORMS) > 1:
        request["plan_only_threshold"] = CAPTURE_PARALLEL_MIN_FORMS
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    progress_path.unlink(missing_ok=True)

    result_payload: dict[str, object] | None = None
    resumed_plan: tuple[list[str], dict[str, list[str]]] | None = None
    if result_path.is_file():
        try:
            candidate = json.loads(result_path.read_text(encoding="utf-8"))
            if (
                isinstance(candidate, dict)
                and candidate.get("version") == CAPTURE_VERSION
                and candidate.get("plan_only")
                and _paths_exist(discovery.project_root, candidate)
            ):
                resumed_plan = _load_runtime_capture_plan(
                    capture_root / "capture_plan.json",
                    signature,
                )
                result_payload = candidate
                print(
                    "SceneLight reused the completed character plan after an interrupted "
                    "parallel capture.",
                    flush=True,
                )
        except (OSError, ValueError):
            result_payload = None

    if result_payload is None:
        # A previous runtime can have produced a valid result and then failed in
        # unrelated project shutdown code. The helper publishes a new result only
        # after every requested asset is complete.
        _run_capture_request_resumable(
            discovery,
            renpy_executable,
            request_path=request_path,
            result_path=result_path,
            native_runtime=native_runtime,
            timeout_seconds=timeout_seconds,
            purpose="capture dynamic SceneLight assets",
            progress_path=progress_path,
            composite_job_root=capture_root / "composite_jobs",
            renderer=renderer,
            capture_root=capture_root,
        )
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    if result_payload.get("version") != CAPTURE_VERSION:
        raise ValueError("Ren'Py wrote an incompatible SceneLight capture result")
    if result_payload.get("plan_only"):
        planned_forms, request_forms = resumed_plan or _load_runtime_capture_plan(
            capture_root / "capture_plan.json", signature
        )
        worker_payloads = _run_parallel_capture_workers(
            discovery,
            renpy_executable,
            cache_root=cache_root,
            capture_root=capture_root,
            planned_forms=planned_forms,
            master_payload=result_payload,
            native_runtime=native_runtime,
            timeout_seconds=timeout_seconds,
            renderer=renderer,
        )
        result_payload = _merge_parallel_capture_payloads(
            result_payload,
            worker_payloads,
            request_forms,
        )
    _merge_composite_capture_jobs(
        discovery.project_root,
        capture_root / "composite_jobs",
        result_payload,
    )
    if not _paths_exist(discovery.project_root, result_payload):
        raise FileNotFoundError("Ren'Py did not write every reported SceneLight capture")
    _deduplicate_normalized_captures(discovery.project_root, result_payload)
    _normalize_surface_captures(discovery.project_root, result_payload)
    _write_capture_result(result_path, result_payload)
    validated_result = _validate_result(
        discovery, _decode_result(discovery, result_payload, cached=False)
    )
    # Only successful captures may receive the reusable completion marker.
    state_path.write_text(
        json.dumps(
            {"version": CAPTURE_VERSION, "signature": signature},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return validated_result


def _surface_checkpoint_count(capture_root: Path) -> int:
    """Count atomically completed dynamic-sprite checkpoints."""

    return sum(1 for _ in capture_root.glob("sprite_*.png.surface-checkpoint")) + sum(
        1 for _ in capture_root.glob("sprite_*.png.surface-normalized")
    )


def _capture_exit_grace_seconds(
    checkpoint_root: Path | None,
    checkpoint_baseline: int,
) -> float:
    """Wait briefly after a checkpointed exit, conservatively otherwise."""

    if (
        checkpoint_root is not None
        and _durable_form_checkpoint_count(checkpoint_root) > checkpoint_baseline
    ):
        return 1.0
    return 10.0


def _durable_form_checkpoint_count(capture_root: Path) -> int:
    """Count semantic form checkpoints without confusing aliases or orderings."""

    journal = capture_root / "capture_forms.jsonl"
    keys: set[str] = set()
    if journal.is_file():
        try:
            with journal.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(value, dict):
                        continue
                    key = value.get("key") or value.get("name")
                    if isinstance(key, str) and key:
                        keys.add(key)
        except OSError:
            pass
    return max(len(keys), _surface_checkpoint_count(capture_root))


def _run_capture_request_resumable(
    discovery: ProjectDiscovery,
    renpy_executable: Path,
    *,
    request_path: Path,
    result_path: Path,
    native_runtime: bool,
    timeout_seconds: int,
    purpose: str,
    progress_path: Path,
    composite_job_root: Path,
    renderer: str | None,
    capture_root: Path,
    progress_callback: Callable[[str, int, int], None] | None = None,
    show_progress: bool = True,
    isolated_parallel: bool = False,
    checkpoint_limit: int | None = CAPTURE_PROCESS_BATCH_SIZE,
) -> None:
    """Resume after a native renderer exit when new atomic forms were saved."""

    progress_state = _CaptureProgressState()
    low_yield_crashes = 0
    for resume_index in range(CAPTURE_PROCESS_RESUME_LIMIT + 1):
        before = _durable_form_checkpoint_count(capture_root)
        try:
            completed = _run_capture_request(
                discovery,
                renpy_executable,
                request_path=request_path,
                result_path=result_path,
                native_runtime=native_runtime,
                timeout_seconds=timeout_seconds,
                purpose=purpose,
                progress_path=progress_path,
                composite_job_root=composite_job_root,
                materialize_composites=False,
                renderer=renderer,
                checkpoint_root=capture_root,
                checkpoint_limit=checkpoint_limit,
                progress_state=progress_state,
                progress_callback=progress_callback,
                show_progress=show_progress,
                isolated_parallel=isolated_parallel,
            )
            if completed is not False:
                return
            after = _durable_form_checkpoint_count(capture_root)
            if after <= before:
                raise RuntimeError("Ren'Py ended a capture batch without saving a sprite form.")
            progress_path.unlink(missing_ok=True)
            print(
                "SceneLight memory-safe batch %d complete: %d new sprite forms saved "
                "(%d total). Starting the next batch." % (resume_index + 1, after - before, after),
                flush=True,
            )
        except CaptureInstanceConflict:
            raise
        except RuntimeError as error:
            after = _durable_form_checkpoint_count(capture_root)
            crashed = "(exit " in str(error)
            if not crashed or after <= before or resume_index >= CAPTURE_PROCESS_RESUME_LIMIT:
                raise
            saved = after - before
            if saved < CAPTURE_LOW_YIELD_FORM_THRESHOLD:
                low_yield_crashes += 1
            else:
                low_yield_crashes = 0
            if low_yield_crashes >= CAPTURE_LOW_YIELD_CRASH_LIMIT:
                print(
                    "SceneLight renderer repeatedly stopped after small sprite batches. "
                    "Trying another compatible renderer.",
                    flush=True,
                )
                raise RuntimeError(
                    "Ren'Py repeatedly stopped during small sprite batches; "
                    "another renderer is required."
                ) from error
            progress_path.unlink(missing_ok=True)
            print(
                "SceneLight renderer stopped unexpectedly after saving %d new sprite forms "
                "(%d total). Retrying from saved progress." % (saved, after),
                flush=True,
            )


def _capture_command(
    renpy_executable: Path,
    project_root: Path,
    *,
    native_runtime: bool,
) -> list[str]:
    """Build the launch command for either a game runtime or an SDK.

    A distributed game executable already knows its project directory and must
    be started without SDK arguments.  The SDK launcher needs the project and
    ``run`` command explicitly.
    """

    return renpy_runtime_command(
        renpy_executable,
        project_root,
        native_runtime=native_runtime,
    )


def merge_capture(discovery: ProjectDiscovery, capture: CaptureResult) -> None:
    """Merge resolved raw assets into the normal palette-independent builder."""

    for name, path in capture.scenes.items():
        # The loaded Ren'Py displayable is authoritative over source regexes;
        # it includes archive resolution, aliases, composites, and transforms.
        discovery.scenes[name] = path
    for scene_name, frames in capture.scene_sequences.items():
        if discovery.scene_analysis == "live":
            continue
        timeline: list[tuple[int, str]] = []
        key_by_path: dict[Path, str] = {}
        base_path = capture.scenes.get(scene_name)
        if base_path is not None:
            key_by_path[base_path] = scene_name
        for time_ms, path in frames:
            frame_key = key_by_path.get(path)
            if frame_key is None:
                frame_key = f"{scene_name}::t{time_ms:05d}"
                key_by_path[path] = frame_key
            discovery.scenes[frame_key] = path
            timeline.append((time_ms, frame_key))
        if len({frame_key for _time_ms, frame_key in timeline}) > 1:
            discovery.scene_sequences[scene_name] = timeline
            discovery.scene_frame_sources[scene_name] = {
                source: key_by_path[path]
                for source, path in capture.scene_frame_sources.get(scene_name, {}).items()
                if path in key_by_path
            }

    reference_height = 720
    scene_heights: list[int] = []
    for path in capture.scenes.values():
        try:
            with Image.open(path) as scene:
                scene_heights.append(scene.height)
        except (OSError, ValueError):
            pass
    if scene_heights:
        reference_height = max(scene_heights)

    captured_by_tag: dict[str, list[tuple[str, SpriteSpec]]] = {}
    for name, path in capture.sprites.items():
        parts = name.split()
        if parts:
            spec = capture.composite_sprites.get(name)
            if spec is None:
                spec = SpriteSpec(name=name, layers=(path,))
            captured_by_tag.setdefault(parts[0], []).append((name, spec))

    explicit_tags = set(discovery.explicit_character_tags)
    eligible_tags = set(explicit_tags)
    ignored_tags: list[str] = []
    captured_tags = (
        explicit_tags if discovery.character_selection == "manual" else set(capture.character_tags)
    )
    for tag in captured_tags:
        if tag in explicit_tags or any(
            _looks_like_foreground_sprite(spec, reference_height)
            for _name, spec in captured_by_tag.get(tag, ())
        ):
            eligible_tags.add(tag)
        else:
            ignored_tags.append(tag)

    for tag in sorted(eligible_tags):
        for name, spec in captured_by_tag.get(tag, ()):
            discovery.sprites.setdefault(name, spec)
    discovery.character_tags = (
        sorted(explicit_tags)
        if discovery.character_selection == "manual"
        else sorted(set(discovery.character_tags) | eligible_tags)
    )
    discovery.unsupported.extend(
        "runtime inventory ignored non-character image family: %s" % tag
        for tag in sorted(ignored_tags)
    )
    discovery.unsupported.extend(f"runtime capture: {error}" for error in capture.errors)
    discovery.unsupported = sorted(set(discovery.unsupported))
    for error in capture.errors:
        label, separator, detail = error.partition(": ")
        if not separator or not label.startswith("sprite "):
            continue
        sprite = label.removeprefix("sprite ").strip()
        if not sprite:
            continue
        discovery.skipped_sprites.append(
            {"sprite": sprite, "stage": "runtime-capture", "error": detail}
        )
    discovery.skipped_sprites = [
        dict(zip(("sprite", "stage", "error"), values, strict=True))
        for values in sorted(
            {(item["sprite"], item["stage"], item["error"]) for item in discovery.skipped_sprites}
        )
    ]
    _merge_video_scene_sequences(discovery)


def _merge_video_scene_sequences(discovery: ProjectDiscovery) -> None:
    """Decode authored Movie sources into the same temporal scene contract."""

    if not discovery.scene_media:
        return
    from .preview.media import MediaClip

    cache_root = discovery.project_root / ".scenelight_cache" / "temporal-media"
    for scene_name, source in sorted(discovery.scene_media.items()):
        clip: MediaClip | None = None
        try:
            clip = MediaClip(source, cache_root)
            if discovery.scene_analysis == "live":
                # Only a first-frame compatibility field is installed. The
                # actual displayed render drives lighting at playback time.
                frame_root = cache_root / "scene_video_frames" / clip.identity[:16]
                frame_root.mkdir(parents=True, exist_ok=True)
                frame_path = frame_root / "frame_00000000.bmp"
                if not frame_path.is_file():
                    Image.fromarray(clip.frame_by_index(0).rgba, "RGBA").save(
                        frame_path, format="BMP"
                    )
                discovery.scenes[scene_name] = frame_path
                continue
            if not clip.animated or clip.frame_count < 2:
                continue
            step = max(1, round(clip.fps / 8.0))
            cuts = clip.temporal_cut_indices()
            indices = sorted(
                set(range(0, clip.frame_count, step))
                | {clip.frame_count - 1}
                | {index for cut in cuts for index in (cut - 1, cut)}
            )
            timeline: list[tuple[int, str]] = []
            frame_root = cache_root / "scene_video_frames" / clip.identity[:16]
            frame_root.mkdir(parents=True, exist_ok=True)
            for frame in clip.iter_frames(indices):
                frame_index = frame.index
                frame_key = scene_name if frame_index == 0 else f"{scene_name}::v{frame_index:06d}"
                frame_path = frame_root / f"frame_{frame_index:08d}.bmp"
                if not frame_path.is_file():
                    Image.fromarray(frame.rgba, "RGBA").save(frame_path, format="BMP")
                discovery.scenes[frame_key] = frame_path
                timeline.append((round(frame_index * 1000.0 / clip.fps), frame_key))
            discovery.scene_sequences[scene_name] = timeline
            discovery.scene_sequence_metadata[scene_name] = {
                "mode": "movie-position",
                "duration_ms": clip.duration_ms,
                "source": source.relative_to(discovery.game_root).as_posix(),
                "source_fps": clip.fps,
                "cuts_ms": [round(index * 1000.0 / clip.fps) for index in cuts],
            }
        except (OSError, RuntimeError, ValueError) as error:
            discovery.unsupported.append(
                f"temporal movie {scene_name}: {type(error).__name__}: {error}"
            )
        finally:
            if clip is not None:
                clip.close()
