from __future__ import annotations

from scenelight.preview.hardware import (
    GIB,
    HardwareProfile,
    calibrate_temporal_plan,
    derive_hardware_plan,
    recommended_lookahead_seconds,
)


def _profile(
    physical: int,
    logical: int,
    memory_gib: float,
    *,
    cuda: bool = True,
) -> HardwareProfile:
    return HardwareProfile(
        physical_cores=physical,
        logical_cores=logical,
        available_memory_bytes=round(memory_gib * GIB),
        cuda=cuda,
    )


def test_hardware_plan_scales_every_expensive_pool() -> None:
    tiny = derive_hardware_plan(_profile(2, 4, 4, cuda=False))
    common = derive_hardware_plan(_profile(8, 16, 64))
    workstation = derive_hardware_plan(_profile(16, 32, 64))

    assert (tiny.process_workers, tiny.component_threads, tiny.store_workers) == (2, 1, 1)
    assert tiny.form_workers == 1
    assert tiny.temporal_batch_size == 4

    # This preserves the approved 7800X3D scheduling while deriving it from
    # the host instead of naming or assuming that processor.
    assert (common.process_workers, common.component_threads, common.store_workers) == (8, 6, 2)
    assert common.form_workers == 2
    assert common.temporal_batch_size == 16

    assert (workstation.process_workers, workstation.store_workers) == (16, 4)
    assert workstation.form_workers == 4
    assert workstation.temporal_batch_size == 32


def test_memory_budget_prevents_process_overcommit() -> None:
    constrained = derive_hardware_plan(_profile(32, 64, 2))

    assert constrained.process_workers == 2
    assert constrained.component_threads == 2
    assert constrained.form_workers == 2
    assert constrained.temporal_batch_size == 4


def test_exact_lead_expands_and_contracts_with_measured_capacity() -> None:
    assert recommended_lookahead_seconds(1.0) == 4.0
    assert recommended_lookahead_seconds(2.0) == 3.0
    assert recommended_lookahead_seconds(4.0) == 2.0
    assert recommended_lookahead_seconds(8.0) == 2.0
    assert recommended_lookahead_seconds(16.0) == 2.0


def test_calibration_uses_observed_exact_wave_not_cpu_name() -> None:
    plan = derive_hardware_plan(_profile(8, 16, 64))
    calibration = calibrate_temporal_plan(
        plan,
        warm_seconds=2.0,
        completed_tasks=8,
    )

    assert calibration.plan is plan
    assert calibration.anchors_per_second == 4.0
    assert calibration.safe_anchors_per_second == 3.2
    assert calibration.lookahead_seconds == 2.25
