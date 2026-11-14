import json
from pathlib import Path

from scenelight.runtime import log_privacy
from scenelight.setup_timing import RunTiming, TimingSample, previous_runs


def test_total_includes_work_after_the_current_batch_and_adapts_to_speed():
    baseline = TimingSample(
        "install", (("start", 0, 0), ("check", 10, 0), ("form", 30, 10), ("apply", 10, 0))
    )

    def bounds(check_duration):
        run = RunTiming("embed", 0)
        run.history = [baseline]
        run.observe("check", 0, 0)
        run.observe("form", 10, check_duration)
        return run.estimate(check_duration + 10, current_left=0)

    low, high = bounds(10)
    slow_low, slow_high = bounds(20)
    assert low < 10 < high and slow_low < 20 < slow_high
    assert slow_low > low


def test_unknown_update_size_reused_maps_and_overrun(monkeypatch):
    from scenelight import setup_timing

    baseline = TimingSample(
        "analysis", (("start", 1, 0), ("check", 4, 0), ("form", 40, 100), ("apply", 6, 0))
    )
    monkeypatch.setattr(setup_timing, "_reference_runs", lambda: (baseline,))
    run = RunTiming("refresh", 0)
    assert run.label(0, None) == "Checking update size…"
    run.mode = "analysis"
    run.observe("check", 0, 1)
    run.sizes["maps"] = 0
    assert run.estimate(2)[1] < 25
    assert "left overall" in run.label(2, None)
    assert "Recalculating" in run.label(50, None)
    run.mode = "unchanged"
    assert run.estimate(51) is None


def test_history_only_from_successful_matching_project_and_operation(tmp_path: Path):
    sample = {"schema": 1, "mode": "analysis", "steps": [["form", 12.1, 9]]}
    project = str(tmp_path / "Project")
    summary = {
        "status": "succeeded",
        "setup_timing": sample,
        "operation": "refresh",
        "project": log_privacy.mask_text(project),
    }
    for i, override in enumerate(
        (
            {},
            {"status": "cancelled"},
            {"status": "failed"},
            {"project": "elsewhere"},
            {"operation": "scan"},
            {"setup_timing": {"schema": 1, "mode": "analysis", "steps": [["form", -1, 1]]}},
        )
    ):
        folder = tmp_path / str(i)
        folder.mkdir()
        (folder / "session.json").write_text(json.dumps(summary | override), encoding="utf8")
    (tmp_path / "incomplete").mkdir()
    (tmp_path / "incomplete/session.json").write_text("{", encoding="utf8")
    assert previous_runs(tmp_path, project, "refresh") == [TimingSample.read(sample)]


def test_first_large_install_waits_for_size_then_uses_full_install_measurements():
    run = RunTiming("embed", 0)
    run.observe("resolver-backgrounds", 1000, 15)
    assert run.estimate(20) is None
    run.observe("resolver-parallel", 18012, 100)
    low, high = run.estimate(150)
    assert low < 1450 - 150 < high and low < 1570 - 150 < high
    run.capture_finished = 480
    run.observe("transport", 1000, 500)
    low, high = run.estimate(540)
    assert low < 1086 - 60 < high


def test_parallel_eta_waits_for_the_slowest_worker():
    from scenelight.setup_progress import OperationProgress

    live = OperationProgress("Starting", 0, operation="refresh")
    live.observe("SceneLight sprite batches: 2", 0)

    def report(first, second, now):
        live.observe(
            f"SceneLight parallel forms {first + second}/200: working | batches {first}/100 {second}/100",
            now,
        )

    report(0, 0, 0)
    report(100, 1, 4)
    assert live.step_seconds_left(4) is None
    report(100, 11, 9)
    assert live.step_seconds_left(9) == 44.5
    assert live.step_seconds_left(25) is None
    live.observe("SceneLight worker 2/2: retrying with the gl2 renderer", 26)
    assert live.step_seconds_left(26) is None
    report(100, 100, 50)
    assert live.step_seconds_left(50) == 0
