from scenelight.setup_progress import OperationProgress


def test_capture_steps_preserve_tasks_through_retry_and_reuse():
    live = OperationProgress("Starting", 0, operation="refresh")
    for n, line in enumerate(
        (
            "SceneLight story inventory 30/100",
            "SceneLight resolver background 2/3",
            "SceneLight parallel forms 9/15: processing",
            "SceneLight worker 2/2: retrying with the gl2 renderer",
            "SceneLight parallel forms 12/15: processing",
        )
    ):
        live.observe(line, n)
    capture = live.stages.snapshot()[1]
    assert capture.state == "active"
    assert [step.state for step in capture.steps] == ["done", "done", "active", "pending"]
    assert capture.steps[2].tasks == ("Retrying worker 2", "Processing sprite forms")
    live.observe("surface deduplication 1/3: collecting pixels", 8)
    live.observe("SceneLight stage capture-save 2/3: saving", 9)
    assert live.stages.snapshot()[1].steps[-1].state == "active"
    assert live.stages.snapshot()[2].state == "pending"
    live.observe("form 1/2: map", 10)
    assert live.stages.snapshot()[1].state == "done"
    assert live.stages.snapshot()[2].steps[1].state == "active"


def test_settings_update_and_repeated_verification_show_the_actual_stage():
    live = OperationProgress("Starting", 0, operation="refresh")
    live.observe("SceneLight stage install-verify 0/4: checking", 1)
    live.observe("SceneLight update plan: settings-only", 2)
    stages = live.stages.snapshot()
    assert stages[0].steps[1].state == "active"
    assert all(step.state == "skipped" for stage in stages[1:3] for step in stage.steps)
    live.observe("SceneLight stage runtime-copy 1/4: transferring", 3)
    live.observe("SceneLight stage install-verify 2/4: checking", 4)
    assert live.stages.snapshot()[-1].steps[1].state == "active"
    assert live.stages.snapshot()[-1].steps[2].state == "done"


def test_scan_breakdown_follows_the_scan_command():
    live = OperationProgress("Starting", 0, operation="scan")
    for i in (1, 2, 3, 4):
        live.observe(f"SceneLight scan {i}/4: scanning", i)
    stages = live.stages.snapshot()
    assert [stage.state for stage in stages] == ["done", "done", "active"]
    assert stages[0].steps[1].tasks == ("Prepare the inspection copy and read its files",)
    assert stages[-1].steps[-1].state == "active"
