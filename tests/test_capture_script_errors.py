import pytest

from scenelight import capture, cli
from scenelight.project import ProjectDiscovery
from scenelight.setup_gui import describe_operation_failure

PARSE_ERROR = """I'm sorry, but errors were detected in your script.

File "game/story.rpy", line 44: expected a statement.
    malformed scene
"""


def test_new_parse_error_aborts_live_helper_without_waiting_for_stall(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, [])

    class Process:
        pid = 12345
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return 0

    process = Process()

    def spawn(*_args, **_kwargs):
        (tmp_path / "errors.txt").write_text(PARSE_ERROR)
        return process

    monkeypatch.setattr(capture.subprocess, "Popen", spawn)
    monkeypatch.setattr(capture, "_managed_runtime_pids", lambda _: set())
    monkeypatch.setattr(capture, "_descendant_pids", lambda _: set())
    monkeypatch.setattr(
        capture.time, "sleep", lambda _: pytest.fail("Syntax errors must not wait for timeout")
    )
    with pytest.raises(capture.CaptureScriptError, match="story.rpy") as error:
        capture._run_capture_request(
            discovery,
            tmp_path / "renpy.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=False,
            timeout_seconds=180,
            purpose="run a preflight",
        )
    assert "line 44" in str(error.value)
    assert process.stopped


def test_stale_and_unrelated_error_files_do_not_abort(tmp_path):
    path = tmp_path / "errors.txt"
    path.write_text(PARSE_ERROR)
    before = capture._runtime_log_state(tmp_path)
    assert not capture._fresh_script_error(tmp_path, before)
    path.write_text("Unrelated third-party diagnostics")
    assert not capture._fresh_script_error(tmp_path, before)
    path.write_text(PARSE_ERROR.replace("44", "123"))
    assert capture._fresh_script_error(tmp_path, before)
    assert "line 123" in capture._runtime_diagnostic(tmp_path, before=before)


@pytest.mark.parametrize("compatible_second", [False, True])
def test_script_failure_skips_backends_but_allows_another_engine(
    tmp_path, monkeypatch, compatible_second
):
    project = tmp_path / "source"
    (project / "game").mkdir(parents=True)
    (project / "game/script.rpy").write_text("label start:\n    return\n")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    first = tmp_path / "old-runtime.exe"
    second = tmp_path / "compatible-runtime.exe"
    first.touch()
    second.touch()
    monkeypatch.setattr(cli, "_resolve_renpy_executable", lambda *args: second)
    monkeypatch.setattr(
        cli,
        "_runtime_capture_launchers",
        lambda *args: [(first, False, "older engine"), (second, False, "compatible engine")],
    )
    calls = []

    def preflight(discovery, executable, **kwargs):
        calls.append((executable, kwargs["renderer"]))
        if executable == first or not compatible_second:
            raise capture.CaptureScriptError(
                "Ren'Py could not compile the game scripts. " + PARSE_ERROR
            )
        return None

    monkeypatch.setattr(cli, "preflight_runtime", preflight)
    monkeypatch.setattr(
        cli,
        "capture_runtime_review",
        lambda *args, **kwargs: capture.CaptureResult({}, {}, [], True, 0, [], [], False),
    )
    if compatible_second:
        result = cli._scan_runtime_review(project, config=None, renpy_sdk=second)
        assert result["runtime_preflight"]
    else:
        with pytest.raises(capture.CaptureScriptError) as error:
            cli._scan_runtime_review(project, config=None, renpy_sdk=second)
        title, detail = describe_operation_failure(str(error.value))
        assert "scripts" in title and "file and line" in detail
    assert calls == [(first, None), (second, None)]
