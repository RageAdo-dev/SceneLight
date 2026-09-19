import json
import os
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import scenelight.capture as capture
from scenelight.project import ProjectDiscovery


def discovery_at(root):
    (root / "game").mkdir(parents=True, exist_ok=True)
    return ProjectDiscovery(
        project_root=root, game_root=root / "game", scenes={}, sprites={}, character_tags=[]
    )


def test_shared_sdk_launcher_can_capture_with_single_instance_guard(tmp_path, monkeypatch):
    """Exercise real child processes and locks, not a mocked success response."""
    script = tmp_path / "shared-sdk.py"
    script.write_text(
        textwrap.dedent("""
            import hashlib, json, os, sys, tempfile, time
            from pathlib import Path
            class SingleInstanceException(Exception):
                pass
            project = Path(sys.argv[1])
            request = json.loads(Path(os.environ['SCENELIGHT_CAPTURE_REQUEST']).read_text())
            # Same launcher identity, separate game directories: the reported failure.
            name = hashlib.sha256(os.path.abspath(sys.argv[0]).encode()).hexdigest() + '.lock'
            lock = Path(tempfile.gettempdir()) / name
            (project.parent / (project.name + '.attempt')).touch()
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except OSError:
                (project / 'log.txt').write_text(
                    'Another instance is already running, quitting.\\nsingleton.SingleInstanceException\\n'
                )
                raise SingleInstanceException()
            try:
                deadline = time.monotonic() + 10
                while len(list(project.parent.glob('*.attempt'))) < 2:
                    if time.monotonic() > deadline:
                        raise RuntimeError('second worker did not start')
                    time.sleep(0.01)
                time.sleep(0.1)
                Path(request['result']).write_text(json.dumps({'temp': tempfile.gettempdir()}))
            finally:
                os.close(fd)
                lock.unlink()
        """),
        encoding="utf-8",
    )
    common_temp = tmp_path / "shared-temp"
    common_temp.mkdir()
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(common_temp))
    monkeypatch.setattr(
        capture,
        "_capture_command",
        lambda _executable, project, **_kw: [sys.executable, str(script), str(project)],
    )
    monkeypatch.setattr(capture, "_capture_exit_grace_seconds", lambda *_args: 0)
    parent_environment = dict(os.environ)

    def run(index):
        discovery = discovery_at(tmp_path / f"worker-{index}")
        result = discovery.project_root / "result.json"
        request = discovery.project_root / "request.json"
        request.write_text(json.dumps({"result": str(result)}))
        capture._run_capture_request(
            discovery,
            Path(sys.executable),
            request_path=request,
            result_path=result,
            native_runtime=False,
            timeout_seconds=15,
            purpose="test single-instance capture",
            isolated_parallel=True,
        )
        return json.loads(result.read_text())["temp"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (1, 2)))
    assert len(set(results)) == 2
    assert all(not Path(path).exists() for path in results)
    assert dict(os.environ) == parent_environment


@pytest.mark.parametrize("persistent", [False, True])
def test_parallel_lock_fallback_keeps_successes_and_resumes_failed_shard(
    tmp_path, monkeypatch, capsys, persistent
):
    discovery = discovery_at(tmp_path / "game-copy")
    cache = discovery.project_root / ".scenelight_cache"
    cache.mkdir()
    calls = {"w1": [], "w2": []}
    barrier = threading.Barrier(2)
    finished = threading.Event()
    monkeypatch.setattr(capture, "_capture_form_worker_count", lambda _count: 2)
    monkeypatch.setattr(capture, "_capture_worker_renderers", lambda *_args: ["angle2", "gl2"])
    cleaned = []
    monkeypatch.setattr(capture, "_schedule_capture_worker_cleanup", cleaned.append)

    def run_worker(
        item, _executable, *, request_path, result_path, capture_root, renderer, **kwargs
    ):
        name = item.project_root.name
        calls[name].append((item.project_root, capture_root, renderer))
        first = len(calls[name]) == 1
        marker = capture_root / "saved-checkpoint"
        if first:
            marker.write_text("keep this")
            barrier.wait(timeout=5)
        else:
            assert finished.is_set(), "Sequential fallback overlapped a healthy worker"
            assert marker.read_text() == "keep this"
            assert calls[name][0] == calls[name][-1]
        if name == "w2" and (first or persistent):
            raise capture.CaptureInstanceConflict("singleton.SingleInstanceException")
        request = json.loads(request_path.read_text())
        result_path.write_text(json.dumps({"sprites": {}, "forms": request["explicit_forms"]}))
        if name == "w1":
            finished.set()

    monkeypatch.setattr(capture, "_run_capture_request_resumable", run_worker)

    def run():
        return capture._run_parallel_capture_workers(
            discovery,
            tmp_path / "sdk/renpy.exe",
            cache_root=cache,
            capture_root=cache / "captured",
            planned_forms=["hero a", "hero b"],
            master_payload={},
            native_runtime=False,
            timeout_seconds=15,
            renderer=None,
        )

    if persistent:
        with pytest.raises(capture.CaptureInstanceConflict):
            run()
    else:
        assert [payload["forms"] for payload in run()] == [["hero a"], ["hero b"]]
    assert len(calls["w1"]) == 1
    assert len(calls["w2"]) == 2
    assert len(cleaned) == 1
    output = capsys.readouterr().out
    assert "one at a time" in output
    assert "retrying with the gl2 renderer" not in output


def test_non_lock_worker_error_is_not_hidden_by_fallback(tmp_path, monkeypatch, capsys):
    discovery = discovery_at(tmp_path / "project")
    cache = discovery.project_root / ".scenelight_cache"
    cache.mkdir()
    monkeypatch.setattr(capture, "_capture_form_worker_count", lambda _count: 2)
    monkeypatch.setattr(capture, "_capture_worker_renderers", lambda *_args: [None])
    monkeypatch.setattr(capture, "_schedule_capture_worker_cleanup", lambda _path: None)
    calls = []

    def fail(item, *_args, **_kwargs):
        calls.append(item.project_root.name)
        if item.project_root.name == "w1":
            raise capture.CaptureInstanceConflict("single-instance guard")
        raise RuntimeError("invalid sprite data")

    monkeypatch.setattr(capture, "_run_capture_request_resumable", fail)
    with pytest.raises(RuntimeError, match="invalid sprite data"):
        capture._run_parallel_capture_workers(
            discovery,
            tmp_path / "sdk/renpy.exe",
            cache_root=cache,
            capture_root=cache / "captured",
            planned_forms=["hero a", "hero b"],
            master_payload={},
            native_runtime=False,
            timeout_seconds=15,
            renderer=None,
        )
    assert sorted(calls) == ["w1", "w2"]
    assert "one at a time" not in capsys.readouterr().out


def test_known_lock_stops_resumable_renderer_retry_even_with_new_checkpoint(tmp_path, monkeypatch):
    discovery = discovery_at(tmp_path / "project")
    calls = []
    counts = iter((0, 10))
    monkeypatch.setattr(capture, "_durable_form_checkpoint_count", lambda _path: next(counts))

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise capture.CaptureInstanceConflict("blocked (exit 1)")

    monkeypatch.setattr(capture, "_run_capture_request", fail)
    with pytest.raises(capture.CaptureInstanceConflict):
        capture._run_capture_request_resumable(
            discovery,
            tmp_path / "renpy.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=False,
            timeout_seconds=5,
            purpose="capture",
            progress_path=tmp_path / "progress.json",
            composite_job_root=tmp_path / "composites",
            renderer=None,
            capture_root=tmp_path,
        )
    assert len(calls) == 1


def test_stale_singleton_log_is_not_used_as_current_failure(tmp_path):
    (tmp_path / "traceback.txt").write_text("singleton.SingleInstanceException\n")
    before = capture._runtime_log_state(tmp_path)
    (tmp_path / "log.txt").write_text("RuntimeError: shader compilation failed\n")
    detail = capture._runtime_diagnostic(tmp_path, before=before)
    assert "shader compilation failed" in detail
    assert not capture._is_instance_conflict(detail)
    (tmp_path / "log.txt").write_text("Another instance is already running, quitting.\n")
    assert capture._is_instance_conflict(capture._runtime_diagnostic(tmp_path, before=before))


@pytest.mark.parametrize(
    "message",
    [
        "singleton.SingleInstanceException",
        "tendo.singleton.SingleInstanceException: locked",
        "Another instance is already running, quitting.",
    ],
)
def test_lock_classifier_recognizes_specific_guard_failures(message):
    assert capture._is_instance_conflict(message)
    assert not capture._is_instance_conflict("ValueError: not an instance of Sprite")
    assert not capture._is_instance_conflict("RuntimeError: Could not compile shader")


def test_capture_context_cleans_descendant_of_already_exited_launcher(tmp_path, monkeypatch):
    calls = []

    class Launcher:
        pid = 101

        def poll(self):
            return 0

    monkeypatch.setattr(capture.subprocess, "Popen", lambda *args, **kwargs: Launcher())
    monkeypatch.setattr(capture, "_descendant_pids", lambda roots: {202} if 101 in roots else set())
    monkeypatch.setattr(capture, "_stop_process_pids", lambda pids: calls.append(set(pids)))
    with pytest.raises(ValueError, match="supervisor failed"):
        with capture._capture_process(
            ["launcher"], cwd=tmp_path, environment={}, startupinfo=None, creationflags=0
        ):
            raise ValueError("supervisor failed")
    assert calls == [{202}]
