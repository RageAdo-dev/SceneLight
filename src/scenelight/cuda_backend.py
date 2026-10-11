"""Optional CUDA acceleration for SceneLight's background transport analyzer.

The production decisions remain in :mod:`scenelight.engine`. CUDA evaluates
the dense, placement-dependent reductions as a batch and returns compact
measurements to that shared logic. Machines without CuPy or a usable NVIDIA
device never import this module from the normal CPU path.
"""

from __future__ import annotations

import gc
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing import shared_memory
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .engine import (
    DetectedLight,
    EnvironmentProbe,
    Placement,
    PreparedScene,
    SceneAnalysis,
    ScenePlacementMeasurements,
    _detect_source_components,
    _display_chromaticity,
    _environment_probe_specs,
    _luminance,
    _prepare_creative_color_fields,
    analyze_scene,
    prepare_scene,
)


@dataclass(slots=True)
class CudaTransportGeometry:
    shape: tuple[int, int]
    grid_size: tuple[int, int]
    coordinates: tuple[tuple[int, int], ...]
    placements: tuple[Placement, ...]
    local_weights_gpu: Any
    local_weights_cpu: np.ndarray
    local_totals_gpu: Any
    local_totals_cpu: np.ndarray
    upper_weights_gpu: Any
    upper_totals_gpu: Any
    probe_specs: tuple[tuple[tuple[float, float, int], ...], ...]
    probe_x_weights_gpu: Any
    probe_y_weights_gpu: Any
    probe_totals_gpu: Any


@dataclass(frozen=True, slots=True)
class CudaTransportResult:
    coordinates: tuple[tuple[int, int], ...]
    analyses: tuple[SceneAnalysis, ...]
    prepare_seconds: float
    gpu_seconds: float
    component_seconds: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class TransportAnalysisBundle:
    """Exact components plus the scene arrays CUDA still needs.

    The component worker already decodes and prepares the source. Returning a
    compact subset prevents the parent from repeating that expensive work.
    Arrays used only by CPU classification are discarded before
    IPC; all radiometric arrays consumed by CUDA remain full-resolution
    float32 data.
    """

    components: tuple[tuple[DetectedLight, ...], ...]
    prepared: PreparedScene | SharedPreparedSceneInfo


@dataclass(frozen=True, slots=True)
class SharedPreparedBufferSpec:
    """Pickle-safe description of a parent-owned prepared-scene buffer."""

    name: str
    shape: tuple[int, int]
    character_height: float


@dataclass(frozen=True, slots=True)
class SharedPreparedSceneInfo:
    """Small scalar half of a prepared scene stored in shared memory."""

    buffer: SharedPreparedBufferSpec
    global_mean: float
    global_contrast: float
    separation: float
    grain: float
    sharpness: float


@dataclass(slots=True)
class SharedPreparedBuffer:
    """Parent-owned zero-copy IPC allocation for one prepared background."""

    memory: shared_memory.SharedMemory
    spec: SharedPreparedBufferSpec

    def close(self) -> None:
        self.memory.close()
        # On Windows the mapping disappears when the final handle closes and
        # ``unlink`` is a no-op. POSIX needs an explicit unlink.
        if os.name != "nt":
            self.memory.unlink()


_GEOMETRY_LOCK = Lock()
_GEOMETRY_KEY: tuple[tuple[int, int], tuple[int, int], float, float] | None = None
_GEOMETRY_VALUE: CudaTransportGeometry | None = None
_COMPONENT_EXECUTOR: ThreadPoolExecutor | None = None
_COMPONENT_THREAD_COUNT = 1


def _cupy():
    import cupy as cp

    return cp


def cuda_available() -> bool:
    """Return whether the optional CuPy backend can execute on a CUDA GPU."""

    try:
        cp = _cupy()
        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:  # noqa: BLE001 - optional backend probe must be safe.
        return False


def cuda_device_name() -> str | None:
    if not cuda_available():
        return None
    cp = _cupy()
    value = cp.cuda.runtime.getDeviceProperties(0)["name"]
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def initialize_component_worker(threads: int = 1) -> None:
    """Initialize one bounded exact-classification worker process.

    The production batch path uses one thread in each of four processes;
    wider nested pools increase memory contention on the target 7800X3D.
    Interactive callers may explicitly request two threads for one-scene
    latency. OpenCV itself remains single-threaded in either configuration.
    """

    global _COMPONENT_EXECUTOR, _COMPONENT_THREAD_COUNT
    cv2.setNumThreads(1)
    threads = max(1, int(threads))
    if threads == _COMPONENT_THREAD_COUNT:
        return
    if _COMPONENT_EXECUTOR is not None:
        _COMPONENT_EXECUTOR.shutdown()
    _COMPONENT_EXECUTOR = (
        ThreadPoolExecutor(max_workers=threads, thread_name_prefix="scenelight-components")
        if threads > 1
        else None
    )
    _COMPONENT_THREAD_COUNT = threads


def _transport_layout(
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
) -> tuple[tuple[tuple[int, int], ...], tuple[Placement, ...]]:
    grid_width, grid_height = grid_size
    coordinates = tuple((row, column) for row in range(grid_height) for column in range(grid_width))
    placements: list[Placement] = []
    for row, column in coordinates:
        subject_y = subject_y_max * row / max(grid_height - 1, 1)
        placement = Placement(
            column / max(grid_width - 1, 1),
            subject_y + character_height * 0.48,
            character_height,
        ).clamped()
        placements.append(placement)
    return coordinates, tuple(placements)


def _build_cuda_geometry(
    shape: tuple[int, int],
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
) -> CudaTransportGeometry:
    cp = _cupy()
    height, width = shape
    coordinates, placements = _transport_layout(grid_size, subject_y_max, character_height)
    all_probe_specs = tuple(
        _environment_probe_specs(
            shape,
            float(np.clip(placement.center_x, 0.0, 1.0)),
            float(
                np.clip(
                    placement.baseline_y - placement.height * 0.48,
                    0.0,
                    1.0,
                )
            ),
            placement,
        )
        for placement in placements
    )

    char_heights = np.asarray(
        [max(4, int(height * placement.height)) for placement in placements],
        dtype=np.float64,
    )
    # Match ``int(char_h * 0.54)`` exactly rather than integer arithmetic.
    char_widths = np.asarray(
        [max(4, int(value * 0.54)) for value in char_heights], dtype=np.float64
    )
    centers_x = np.asarray(
        [int(placement.center_x * width) for placement in placements], dtype=np.float64
    )
    bottoms = np.asarray(
        [int(placement.baseline_y * height) for placement in placements], dtype=np.float64
    )
    radius_x = np.maximum(char_widths * 0.86, 1.0)
    radius_y = np.maximum(char_heights * 0.66, 1.0)
    if not (np.all(char_heights == char_heights[0]) and np.all(char_widths == char_widths[0])):
        raise ValueError("Transport geometry requires one fixed character height")

    # Every placement uses the same radii and only translates by integral
    # screen pixels. Evaluate the expensive FP64 exponential once over the
    # complete translation domain, then take exact HxW slices for all 144
    # positions. This replaces 144 repeated exponentials with one canonical
    # field while retaining the canonical FP32 weights consumed downstream.
    minimum_x = -int(np.max(centers_x))
    maximum_x = width - 1 - int(np.min(centers_x))
    minimum_bottom_delta = -int(np.max(bottoms))
    maximum_bottom_delta = height - 1 - int(np.min(bottoms))
    delta_x = cp.arange(minimum_x, maximum_x + 1, dtype=cp.float64)
    delta_bottom = cp.arange(
        minimum_bottom_delta,
        maximum_bottom_delta + 1,
        dtype=cp.float64,
    )
    canonical_distance = (delta_x[None, :] / radius_x[0]) ** 2 + (
        (delta_bottom[:, None] + char_heights[0] * 0.48) / radius_y[0]
    ) ** 2
    canonical_weights = cp.exp(-cp.maximum(canonical_distance - 0.5, 0.0) * 1.8)
    canonical_weights *= cp.where(canonical_distance < 0.28, 0.18, 1.0)
    canonical_weights = canonical_weights.astype(cp.float32)
    local_weights_gpu = cp.stack(
        tuple(
            canonical_weights[
                -int(bottom) - minimum_bottom_delta : -int(bottom) - minimum_bottom_delta + height,
                -int(center_x) - minimum_x : -int(center_x) - minimum_x + width,
            ]
            for center_x, bottom in zip(centers_x, bottoms, strict=True)
        )
    )
    del canonical_distance, canonical_weights
    local_totals_gpu = cp.sum(local_weights_gpu, axis=(1, 2))
    local_weights_cpu = cp.asnumpy(local_weights_gpu)
    local_totals_cpu = cp.asnumpy(local_totals_gpu)

    normalized_y = cp.arange(height, dtype=cp.float64) / max(height - 1, 1)
    subject_y = cp.asarray(
        [
            float(
                np.clip(
                    placement.baseline_y - placement.height * 0.48,
                    0.0,
                    1.0,
                )
            )
            for placement in placements
        ],
        dtype=cp.float64,
    )
    upper_factor = cp.clip(
        (subject_y[:, None] - normalized_y[None, :]) * 2.2 + 0.35,
        0.15,
        1.0,
    )
    # Inputs are FP32. FP64 multiplication cannot recover their lost precision
    # and is much slower on consumer GPUs. Keep the reduction in FP32; the
    # encoded LUT is checked against the reference implementation.
    upper_weights_gpu = local_weights_gpu * upper_factor[:, :, None].astype(cp.float32)
    upper_totals_gpu = cp.sum(upper_weights_gpu, axis=(1, 2))

    unique_probe_keys = tuple(
        dict.fromkeys(
            key
            for placement_specs in all_probe_specs
            for _direction_x, _direction_y, key in placement_specs
        )
    )
    key_indices = {key: index for index, key in enumerate(unique_probe_keys)}
    probe_specs = tuple(
        tuple(
            (direction_x, direction_y, key_indices[key])
            for direction_x, direction_y, key in placement_specs
        )
        for placement_specs in all_probe_specs
    )
    keys = np.asarray(unique_probe_keys, dtype=np.float64)
    # A 2D Gaussian is exactly separable. Keeping one horizontal and vertical
    # vector per probe avoids materializing an ~900 MB tensor for every aspect
    # ratio while retaining the same full-resolution integration domain.
    probe_x_weights_gpu = cp.exp(
        -0.5
        * (
            (cp.arange(width, dtype=cp.float64)[None, :] - cp.asarray(keys[:, 0])[:, None])
            / cp.asarray(keys[:, 2])[:, None]
        )
        ** 2
    ).astype(cp.float32)
    probe_y_weights_gpu = cp.exp(
        -0.5
        * (
            (cp.arange(height, dtype=cp.float64)[None, :] - cp.asarray(keys[:, 1])[:, None])
            / cp.asarray(keys[:, 3])[:, None]
        )
        ** 2
    ).astype(cp.float32)
    probe_totals_gpu = cp.sum(probe_x_weights_gpu, axis=1) * cp.sum(
        probe_y_weights_gpu,
        axis=1,
    )
    cp.cuda.Stream.null.synchronize()
    return CudaTransportGeometry(
        shape=shape,
        grid_size=grid_size,
        coordinates=coordinates,
        placements=placements,
        local_weights_gpu=local_weights_gpu,
        local_weights_cpu=local_weights_cpu,
        local_totals_gpu=local_totals_gpu,
        local_totals_cpu=local_totals_cpu,
        upper_weights_gpu=upper_weights_gpu,
        upper_totals_gpu=upper_totals_gpu,
        probe_specs=probe_specs,
        probe_x_weights_gpu=probe_x_weights_gpu,
        probe_y_weights_gpu=probe_y_weights_gpu,
        probe_totals_gpu=probe_totals_gpu,
    )


def cuda_transport_geometry(
    shape: tuple[int, int],
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
) -> CudaTransportGeometry:
    """Return the single-flight, one-shape CUDA geometry cache."""

    global _GEOMETRY_KEY, _GEOMETRY_VALUE
    key = (tuple(shape), tuple(grid_size), subject_y_max, character_height)
    with _GEOMETRY_LOCK:
        if _GEOMETRY_KEY == key and _GEOMETRY_VALUE is not None:
            return _GEOMETRY_VALUE
        # Release the previous shape before constructing the next one. CuPy's
        # caching allocator otherwise retains several large aspect-ratio
        # geometries and eventually causes multi-gigabyte allocation stalls.
        _GEOMETRY_KEY = None
        _GEOMETRY_VALUE = None
        gc.collect()
        cp = _cupy()
        cp.get_default_memory_pool().free_all_blocks()
        value = _build_cuda_geometry(
            tuple(shape), tuple(grid_size), subject_y_max, character_height
        )
        _GEOMETRY_KEY = key
        _GEOMETRY_VALUE = value
        return value


def _detect_components_for_placements(
    prepared: PreparedScene,
    local_weights,
    *,
    crop_components: bool,
) -> tuple[tuple[DetectedLight, ...], ...]:
    if prepared.creative_fields is None:
        prepared.creative_fields = _prepare_creative_color_fields(prepared.linear)
    creative_fields = prepared.creative_fields

    def detect(weights):
        source_weights = prepared.base_source_weights * (0.58 + 0.42 * weights)
        return _detect_source_components(
            prepared.linear,
            source_weights,
            luma=prepared.luma,
            texture_residual=prepared.texture_residual,
            coordinate_grid=(prepared.yy, prepared.xx),
            ring_kernel=prepared.ring_kernel,
            crop_components=crop_components,
            creative_fields=creative_fields,
        )

    if _COMPONENT_EXECUTOR is None:
        return tuple(map(detect, local_weights))
    return tuple(_COMPONENT_EXECUTOR.map(detect, local_weights))


@lru_cache(maxsize=16)
def _cpu_component_geometry(
    shape: tuple[int, int],
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
) -> tuple[Placement, ...]:
    """Return the small image-independent placement layout for workers."""

    _coordinates, placements = _transport_layout(
        grid_size,
        subject_y_max,
        character_height,
    )
    return placements


def _detect_components_for_layout(
    prepared: PreparedScene,
    placements: tuple[Placement, ...],
    *,
    crop_components: bool,
    scene_fixed: bool = False,
) -> tuple[tuple[DetectedLight, ...], ...]:
    """Classify exact sources without materializing 144 dense annuli.

    ``base_source_weights`` is exactly zero outside the saliency support. The
    reference expression multiplies that sparse field by a dense placement
    annulus, so evaluating the annulus only at non-zero coordinates produces
    the identical full ``source_weights`` array while avoiding roughly 140 MB
    of geometry reads and allocations for every analysis shape.
    """

    height, width = prepared.base_source_weights.shape
    if prepared.creative_fields is None:
        prepared.creative_fields = _prepare_creative_color_fields(prepared.linear)
    creative_fields = prepared.creative_fields

    # An emitter belongs to the background, not to the character.  Temporal
    # media therefore classifies the scene-wide saliency field once and keeps
    # those source identities fixed while the transport grid changes the
    # subject's local meter, probes, and source-to-surface directions.  This
    # removes the dominant video-analysis cost and prevents
    # a moving character from making a real lamp change identity.  Static
    # project builds retain the historical placement-weighted classifier so
    # existing authored/cached results remain unchanged.
    if scene_fixed:
        detected = _detect_source_components(
            prepared.linear,
            prepared.base_source_weights,
            luma=prepared.luma,
            texture_residual=prepared.texture_residual,
            coordinate_grid=(prepared.yy, prepared.xx),
            ring_kernel=prepared.ring_kernel,
            crop_components=crop_components,
            creative_fields=creative_fields,
        )
        return (detected,) * len(placements)

    nonzero_y, nonzero_x = np.nonzero(prepared.base_source_weights)
    nonzero_flat = nonzero_y * width + nonzero_x
    base_values = prepared.base_source_weights.reshape(-1)[nonzero_flat]

    def fill_source_weights(
        placement: Placement,
        source_weights: np.ndarray,
    ) -> None:
        clamped = placement.clamped()
        character_height = max(4, int(height * clamped.height))
        character_width = max(4, int(character_height * 0.54))
        center_x = int(clamped.center_x * width)
        bottom = int(clamped.baseline_y * height)
        radius_x = max(character_width * 0.86, 1)
        radius_y = max(character_height * 0.66, 1)
        center_y = bottom - character_height * 0.48
        distance = ((nonzero_x - center_x) / radius_x) ** 2 + (
            (nonzero_y - center_y) / radius_y
        ) ** 2
        annulus = np.exp(-np.maximum(distance - 0.5, 0.0) * 1.8)
        annulus *= np.where(distance < 0.28, 0.18, 1.0)
        local_values = annulus.astype(np.float32)
        source_weights.reshape(-1)[nonzero_flat] = base_values * (0.58 + 0.42 * local_values)

    def classify(source_weights: np.ndarray) -> tuple[DetectedLight, ...]:
        return _detect_source_components(
            prepared.linear,
            source_weights,
            luma=prepared.luma,
            texture_residual=prepared.texture_residual,
            coordinate_grid=(prepared.yy, prepared.xx),
            ring_kernel=prepared.ring_kernel,
            crop_components=crop_components,
            creative_fields=creative_fields,
        )

    # ``Placement.clamped`` makes the bottom transport rows
    # converge at the supported 1.25 baseline. Those rows are byte-identical
    # inputs to the expensive connected-component classifier. Classify each
    # distinct placement once, then expand the immutable result back to the
    # complete grid so the encoded 16x9 transport remains unchanged.
    unique_placements: list[Placement] = []
    unique_indices: list[int] = []
    index_by_placement: dict[tuple[float, float, float], int] = {}
    for placement in placements:
        key = (placement.center_x, placement.baseline_y, placement.height)
        unique_index = index_by_placement.get(key)
        if unique_index is None:
            unique_index = len(unique_placements)
            index_by_placement[key] = unique_index
            unique_placements.append(placement)
        unique_indices.append(unique_index)

    if _COMPONENT_EXECUTOR is not None:

        def detect_one(placement: Placement) -> tuple[DetectedLight, ...]:
            source_weights = np.zeros_like(prepared.base_source_weights)
            fill_source_weights(placement, source_weights)
            return classify(source_weights)

        unique_detected = tuple(_COMPONENT_EXECUTOR.map(detect_one, unique_placements))
    else:
        source_weights = np.zeros_like(prepared.base_source_weights)
        collected: list[tuple[DetectedLight, ...]] = []
        for placement in unique_placements:
            fill_source_weights(placement, source_weights)
            collected.append(classify(source_weights))
        unique_detected = tuple(collected)
    return tuple(unique_detected[index] for index in unique_indices)


def detect_transport_components_path(
    path: str | Path,
    *,
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
    crop_components: bool = True,
) -> tuple[tuple[DetectedLight, ...], ...]:
    """Compute exact component classifications in a process-safe worker."""

    with Image.open(path) as opened:
        source = opened.convert("RGB")
        source.load()
    prepared = prepare_scene(source, (character_height,))
    placements = _cpu_component_geometry(
        prepared.luma.shape,
        grid_size,
        subject_y_max,
        character_height,
    )
    return _detect_components_for_layout(
        prepared,
        placements,
        crop_components=crop_components,
    )


def _compact_cuda_prepared_scene(prepared: PreparedScene) -> PreparedScene:
    empty_float32 = np.empty((0,), dtype=np.float32)
    empty_float64 = np.empty((0,), dtype=np.float64)
    empty_int64 = np.empty((0,), dtype=np.int64)
    return PreparedScene(
        srgb=empty_float32,
        linear=prepared.linear,
        # The CUDA/shared-decision path only reads the luminance array's
        # shape. Reuse clipped_luma so pickle memoization sends one array.
        luma=prepared.clipped_luma,
        clipped_luma=prepared.clipped_luma,
        saturation=prepared.saturation,
        base_source_weights=prepared.base_source_weights,
        texture_residual=empty_float32,
        yy=empty_int64,
        xx=empty_int64,
        normalized_y=empty_float64,
        ring_kernel=np.empty((0, 0), dtype=np.uint8),
        global_mean=prepared.global_mean,
        global_contrast=prepared.global_contrast,
        separation=prepared.separation,
        grain=prepared.grain,
        sharpness=prepared.sharpness,
        gradient_fields=prepared.gradient_fields,
    )


def allocate_shared_prepared_buffer(
    shape: tuple[int, int],
    character_height: float,
) -> SharedPreparedBuffer:
    """Allocate the exact eight FP32 scene planes returned by one worker."""

    height, width = shape
    value_count = height * width * 8
    memory = shared_memory.SharedMemory(
        create=True,
        size=value_count * np.dtype(np.float32).itemsize,
    )
    return SharedPreparedBuffer(
        memory=memory,
        spec=SharedPreparedBufferSpec(
            name=memory.name,
            shape=tuple(shape),
            character_height=float(character_height),
        ),
    )


def _write_shared_prepared_scene(
    prepared: PreparedScene,
    spec: SharedPreparedBufferSpec,
) -> SharedPreparedSceneInfo:
    if prepared.luma.shape != spec.shape:
        raise ValueError(
            f"Prepared scene shape {prepared.luma.shape} does not match "
            f"shared buffer shape {spec.shape}"
        )
    height, width = spec.shape
    pixels = height * width
    memory = shared_memory.SharedMemory(name=spec.name)
    packed = None
    try:
        packed = np.ndarray((pixels * 8,), dtype=np.float32, buffer=memory.buf)
        packed[: pixels * 3].reshape(height, width, 3)[:] = prepared.linear
        packed[pixels * 3 : pixels * 4].reshape(spec.shape)[:] = prepared.clipped_luma
        packed[pixels * 4 : pixels * 5].reshape(spec.shape)[:] = prepared.saturation
        packed[pixels * 5 : pixels * 6].reshape(spec.shape)[:] = prepared.base_source_weights
        gradient_x, gradient_y = prepared.gradient_fields[spec.character_height]
        packed[pixels * 6 : pixels * 7].reshape(spec.shape)[:] = gradient_x
        packed[pixels * 7 : pixels * 8].reshape(spec.shape)[:] = gradient_y
    finally:
        if packed is not None:
            del packed
        memory.close()
        # Related workers share the parent's tracker; only the owner unlinks.
    return SharedPreparedSceneInfo(
        buffer=spec,
        global_mean=prepared.global_mean,
        global_contrast=prepared.global_contrast,
        separation=prepared.separation,
        grain=prepared.grain,
        sharpness=prepared.sharpness,
    )


def materialize_shared_prepared_scene(
    info: SharedPreparedSceneInfo,
    allocation: SharedPreparedBuffer,
) -> PreparedScene:
    """Create zero-copy NumPy views over a worker-filled parent allocation."""

    if allocation.spec != info.buffer:
        raise ValueError("Shared prepared-scene allocation does not match its bundle")
    height, width = info.buffer.shape
    pixels = height * width
    packed = np.ndarray(
        (pixels * 8,),
        dtype=np.float32,
        buffer=allocation.memory.buf,
    )
    linear = packed[: pixels * 3].reshape(height, width, 3)
    clipped_luma = packed[pixels * 3 : pixels * 4].reshape(info.buffer.shape)
    saturation = packed[pixels * 4 : pixels * 5].reshape(info.buffer.shape)
    base_source_weights = packed[pixels * 5 : pixels * 6].reshape(info.buffer.shape)
    gradient_x = packed[pixels * 6 : pixels * 7].reshape(info.buffer.shape)
    gradient_y = packed[pixels * 7 : pixels * 8].reshape(info.buffer.shape)
    empty_float32 = np.empty((0,), dtype=np.float32)
    empty_float64 = np.empty((0,), dtype=np.float64)
    empty_int64 = np.empty((0,), dtype=np.int64)
    return PreparedScene(
        srgb=empty_float32,
        linear=linear,
        luma=clipped_luma,
        clipped_luma=clipped_luma,
        saturation=saturation,
        base_source_weights=base_source_weights,
        texture_residual=empty_float32,
        yy=empty_int64,
        xx=empty_int64,
        normalized_y=empty_float64,
        ring_kernel=np.empty((0, 0), dtype=np.uint8),
        global_mean=info.global_mean,
        global_contrast=info.global_contrast,
        separation=info.separation,
        grain=info.grain,
        sharpness=info.sharpness,
        gradient_fields={
            info.buffer.character_height: (gradient_x, gradient_y),
        },
    )


def detect_transport_bundle_path(
    path: str | Path,
    *,
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
    crop_components: bool = True,
    prepared_buffer: SharedPreparedBufferSpec | None = None,
    scene_fixed_components: bool = False,
) -> TransportAnalysisBundle:
    """Prepare and classify once, then return exact CUDA-ready scene data."""

    with Image.open(path) as opened:
        source = opened.convert("RGB")
        source.load()
    bundle, _prepared = detect_transport_bundle_image(
        source,
        grid_size=grid_size,
        subject_y_max=subject_y_max,
        character_height=character_height,
        crop_components=crop_components,
        prepared_buffer=prepared_buffer,
        scene_fixed_components=scene_fixed_components,
    )
    return bundle


def detect_transport_bundle_image(
    source: Image.Image,
    *,
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
    crop_components: bool = True,
    prepared_buffer: SharedPreparedBufferSpec | None = None,
    scene_fixed_components: bool = False,
) -> tuple[TransportAnalysisBundle, PreparedScene]:
    """Classify an already-decoded image and retain its exact preparation.

    The retained object lets another scene-wide product reuse the radiometric
    reconstruction in the same worker. The returned transport bundle remains
    byte-for-byte identical to :func:`detect_transport_bundle_path`.
    """

    prepared = prepare_scene(source, (character_height,))
    placements = _cpu_component_geometry(
        prepared.luma.shape,
        grid_size,
        subject_y_max,
        character_height,
    )
    components = _detect_components_for_layout(
        prepared,
        placements,
        crop_components=crop_components,
        scene_fixed=scene_fixed_components,
    )
    compact: PreparedScene | SharedPreparedSceneInfo
    if prepared_buffer is None:
        compact = _compact_cuda_prepared_scene(prepared)
    else:
        compact = _write_shared_prepared_scene(prepared, prepared_buffer)
    return TransportAnalysisBundle(components=components, prepared=compact), prepared


def analyze_transport_cuda(
    source: Image.Image,
    *,
    grid_size: tuple[int, int],
    subject_y_max: float,
    character_height: float,
    crop_components: bool = True,
    source_components: tuple[tuple[DetectedLight, ...], ...] | None = None,
    prepared: PreparedScene | None = None,
) -> CudaTransportResult:
    """Analyze all transport positions with batched CUDA reductions."""

    cp = _cupy()
    total_started = time.perf_counter()
    prepare_started = time.perf_counter()
    prepared = prepared or prepare_scene(source, (character_height,))
    geometry = cuda_transport_geometry(
        prepared.luma.shape,
        grid_size,
        subject_y_max,
        character_height,
    )
    prepare_seconds = time.perf_counter() - prepare_started

    gpu_started = time.perf_counter()
    weights = geometry.local_weights_gpu.reshape(len(geometry.placements), -1)
    totals = geometry.local_totals_gpu
    linear = cp.asarray(prepared.linear.reshape(-1, 3))
    clipped = cp.asarray(prepared.clipped_luma.reshape(-1))
    features = cp.column_stack(
        (
            linear,
            clipped,
            cp.log(clipped + cp.float32(0.008)),
            clipped * clipped,
            cp.asarray(prepared.saturation.reshape(-1)),
            cp.asarray(prepared.gradient_fields[float(character_height)][0].reshape(-1)),
            cp.asarray(prepared.gradient_fields[float(character_height)][1].reshape(-1)),
            cp.asarray(prepared.base_source_weights.reshape(-1)),
        )
    )
    reduced = weights @ features
    denominators = totals[:, None] + cp.float32(1e-6)
    reduced /= denominators

    upper_linear = (
        geometry.upper_weights_gpu.reshape(
            len(geometry.placements),
            -1,
        )
        @ linear
    )
    upper_linear /= geometry.upper_totals_gpu[:, None] + cp.float32(1e-6)

    probe_vertical = geometry.probe_y_weights_gpu @ linear.reshape(
        prepared.luma.shape[0],
        prepared.luma.shape[1] * 3,
    )
    probe_vertical = probe_vertical.reshape(
        geometry.probe_y_weights_gpu.shape[0],
        prepared.luma.shape[1],
        3,
    )
    probe_samples = cp.sum(
        probe_vertical * geometry.probe_x_weights_gpu[:, :, None],
        axis=1,
    )
    probe_samples /= geometry.probe_totals_gpu[:, None] + cp.float32(1e-6)
    # Work above is asynchronous. Let the CPU's exact connected-component
    # classifier run while the GPU reductions finish.
    component_started = time.perf_counter()
    if source_components is None:
        source_components = _detect_components_for_placements(
            prepared,
            geometry.local_weights_cpu,
            crop_components=crop_components,
        )
    component_seconds = time.perf_counter() - component_started

    reduced_cpu = cp.asnumpy(reduced)
    upper_cpu = cp.asnumpy(upper_linear)
    probe_cpu = cp.asnumpy(probe_samples)
    cp.cuda.Stream.null.synchronize()
    gpu_seconds = time.perf_counter() - gpu_started

    probe_values = tuple(
        (
            _display_chromaticity(sample),
            float(np.clip(_luminance(sample), 0.0, 1.0)),
        )
        for sample in probe_cpu
    )
    analyses: list[SceneAnalysis] = []
    base_source_total = float(np.sum(prepared.base_source_weights))
    for index, placement in enumerate(geometry.placements):
        values = reduced_cpu[index]
        local_mean = float(values[3])
        second_moment = float(values[5])
        measurements = ScenePlacementMeasurements(
            ambient_linear=tuple(float(value) for value in values[:3]),
            local_mean=local_mean,
            adaptation_luminance=float(max(np.exp(values[4]) - 0.008, 0.0)),
            local_variance=float(max(second_moment - local_mean * local_mean, 0.0)),
            local_saturation=float(values[6]),
            source_total=float(
                0.58 * base_source_total
                + 0.42 * float(values[9]) * float(geometry.local_totals_cpu[index])
            ),
            upper_light_linear=tuple(float(value) for value in upper_cpu[index]),
            gradient_x=float(values[7]),
            gradient_y=float(values[8]),
        )
        probes = tuple(
            EnvironmentProbe(direction_x, direction_y, *probe_values[probe_index])
            for direction_x, direction_y, probe_index in geometry.probe_specs[index]
        )
        analyses.append(
            analyze_scene(
                source,
                placement,
                prepared=prepared,
                crop_components=crop_components,
                local_weights=geometry.local_weights_cpu[index],
                local_weight_total=float(geometry.local_totals_cpu[index]),
                environment_probes=probes,
                source_components=source_components[index],
                measurements=measurements,
            )
        )
    return CudaTransportResult(
        coordinates=geometry.coordinates,
        analyses=tuple(analyses),
        prepare_seconds=prepare_seconds,
        gpu_seconds=gpu_seconds,
        component_seconds=component_seconds,
        total_seconds=time.perf_counter() - total_started,
    )


def analyze_transport_cuda_path(
    path: Path,
    **kwargs,
) -> CudaTransportResult:
    with Image.open(path) as opened:
        source = opened.convert("RGB")
        source.load()
    return analyze_transport_cuda(source, **kwargs)


def prepare_transport_source_path(
    path: str | Path,
    character_height: float,
) -> tuple[Image.Image, PreparedScene]:
    """Decode and prepare one background for bounded parent-side prefetch."""

    with Image.open(path) as opened:
        source = opened.convert("RGB")
        source.load()
    return source, prepare_scene(source, (character_height,))
