"""Hardware-aware scheduling for exact SceneLight analysis.

This module never selects a different renderer or a lower-quality analysis.
It only decides how many independent exact jobs may run concurrently and how
much exact temporal state must exist before first-view playback begins.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import psutil

MIB = 1024**2
GIB = 1024**3
MAX_ANALYSIS_PROCESSES = 16
ESTIMATED_PROCESS_BYTES = 384 * MIB
REFERENCE_TEMPORAL_RATE = 4.0
REFERENCE_LOOKAHEAD_SECONDS = 2.0
MIN_LOOKAHEAD_SECONDS = 2.0
MAX_LOOKAHEAD_SECONDS = 6.0
CALIBRATION_CAPACITY_GUARD = 0.8


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """The host resources that can safely influence scheduling."""

    physical_cores: int
    logical_cores: int
    available_memory_bytes: int
    cuda: bool


@dataclass(frozen=True, slots=True)
class HardwarePlan:
    """Concurrency selected without changing any analysis operation."""

    profile: HardwareProfile
    process_workers: int
    component_threads: int
    store_workers: int
    form_workers: int
    temporal_batch_size: int
    nominal_anchor_rate: float
    nominal_lookahead_seconds: float


@dataclass(frozen=True, slots=True)
class TemporalCalibration:
    """Measured exact-analysis capacity of the live, warmed worker pool."""

    plan: HardwarePlan
    warm_seconds: float
    completed_tasks: int
    anchors_per_second: float
    safe_anchors_per_second: float
    lookahead_seconds: float


def detect_hardware_profile(*, cuda: bool) -> HardwareProfile:
    """Read physical cores and usable memory with cross-platform fallbacks."""

    logical = psutil.cpu_count(logical=True) or os.cpu_count() or 1
    physical = psutil.cpu_count(logical=False) or logical
    try:
        available_memory = int(psutil.virtual_memory().available)
    except (AttributeError, OSError):
        # The fallback remains conservative rather than assuming an unlimited
        # host. Supported desktop installations normally take the psutil path.
        available_memory = 8 * GIB
    return HardwareProfile(
        physical_cores=max(1, int(physical)),
        logical_cores=max(1, int(logical)),
        available_memory_bytes=max(512 * MIB, available_memory),
        cuda=bool(cuda),
    )


def recommended_lookahead_seconds(anchors_per_second: float) -> float:
    """Choose an exact-state lead from measured throughput.

    Four exact states per media second is the normal transport demand. The
    square-root response avoids excessive startup delay on slower machines.
    The two-second floor also keeps the normal four-anchor/second pipeline at
    or above one full eight-worker wave on the validated class of hardware;
    going below it can reduce utilization rather than improve first-view time.
    The later source-specific cold-prefix gate still holds slow
    videos for a complete exact warmup.
    """

    capacity = max(0.25, float(anchors_per_second))
    raw = REFERENCE_LOOKAHEAD_SECONDS * math.sqrt(REFERENCE_TEMPORAL_RATE / capacity)
    bounded = min(MAX_LOOKAHEAD_SECONDS, max(MIN_LOOKAHEAD_SECONDS, raw))
    return math.ceil(bounded * 4.0 - 1e-9) / 4.0


def derive_hardware_plan(profile: HardwareProfile) -> HardwarePlan:
    """Derive bounded concurrency for a supplied (and therefore testable) host."""

    reserve = min(4 * GIB, max(1 * GIB, profile.available_memory_bytes // 4))
    usable = max(ESTIMATED_PROCESS_BYTES, profile.available_memory_bytes - reserve)
    memory_workers = max(1, usable // ESTIMATED_PROCESS_BYTES)
    process_workers = max(
        1,
        min(
            MAX_ANALYSIS_PROCESSES,
            profile.physical_cores,
            profile.logical_cores,
            int(memory_workers),
        ),
    )
    # The process pool is the largest allocation, but static component and
    # animated-form workers also hold full-resolution float work arrays. Cap
    # every expensive pool by the same live-memory budget so a many-core host
    # under memory pressure does not overcommit merely because its CPU is fast.
    component_threads = max(
        1,
        min(6, profile.physical_cores - 1, int(memory_workers)),
    )
    store_workers = max(1, min(4, process_workers // 4))
    form_workers = max(
        1,
        min(4, profile.physical_cores // 4, int(memory_workers)),
    )
    nominal_anchor_rate = max(0.5, process_workers * 0.5)
    nominal_safe_rate = nominal_anchor_rate * CALIBRATION_CAPACITY_GUARD
    return HardwarePlan(
        profile=profile,
        process_workers=process_workers,
        component_threads=component_threads,
        store_workers=store_workers,
        form_workers=form_workers,
        temporal_batch_size=max(4, process_workers * 2),
        nominal_anchor_rate=nominal_anchor_rate,
        nominal_lookahead_seconds=recommended_lookahead_seconds(nominal_safe_rate),
    )


def calibrate_temporal_plan(
    plan: HardwarePlan,
    *,
    warm_seconds: float,
    completed_tasks: int,
) -> TemporalCalibration:
    """Convert an exact warm wave into a source-independent capacity estimate."""

    task_count = max(1, int(completed_tasks))
    elapsed = max(0.001, float(warm_seconds))
    rate = task_count / elapsed
    safe_rate = rate * CALIBRATION_CAPACITY_GUARD
    return TemporalCalibration(
        plan=plan,
        warm_seconds=elapsed,
        completed_tasks=task_count,
        anchors_per_second=rate,
        safe_anchors_per_second=safe_rate,
        lookahead_seconds=recommended_lookahead_seconds(safe_rate),
    )
