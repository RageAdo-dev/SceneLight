from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize("phase", ["starting", "running", "cancelled"])
def test_setup_exit_finishes_child_cleanup(tmp_path: Path, phase: str) -> None:
    script = tmp_path / "close_setup.py"
    script.write_text(
        textwrap.dedent("""\
            import os
            import queue
            import subprocess
            import sys
            import threading
            import time
            from pathlib import Path
            from types import SimpleNamespace
            from scenelight import setup_gui

            root = Path(sys.argv[1])
            phase = sys.argv[2]
            entered = threading.Event()
            spawn = subprocess.Popen
            terminate = setup_gui.terminate_process_tree

            def delayed_spawn(*args, **kwargs):
                entered.set()
                if phase == "starting":
                    time.sleep(0.5)
                child = spawn(*args, **kwargs)
                (root / "child.pid").write_text(str(child.pid))
                return child

            def delayed_terminate(child):
                time.sleep(0.5)
                terminate(child)
                child.wait(timeout=5)
                (root / "stopped").write_text("yes")

            def noop(*args, **kwargs):
                pass

            widget = SimpleNamespace(set=noop, configure=noop, grid=noop, start=noop, stop=noop)
            app = SimpleNamespace(
                _running=False, _process=None, _cancel_requested=threading.Event(),
                _refresh_project_state=noop, operation_var=widget, progress_frame=widget,
                progress=widget, cancel_operation_button=widget, _append_log=noop,
                _events=queue.Queue(), project_var=SimpleNamespace(get=lambda: str(root)),
                _close_character_review_window=noop, destroy=noop,
            )
            setup_gui.subprocess.Popen = delayed_spawn
            setup_gui.terminate_process_tree = delayed_terminate
            setup_gui.messagebox.askyesno = lambda *a, **kw: True
            second = "from pathlib import Path; Path(%r).touch()" % str(root / "second")
            setup_gui.SceneLightSetup._start_operation(app, "scan", [
                [sys.executable, "-c", "import time; time.sleep(30)"],
                [sys.executable, "-c", second],
            ])
            assert entered.wait(5)
            if phase != "starting":
                deadline = time.monotonic() + 5
                while app._process is None:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
            if phase == "cancelled":
                setup_gui.SceneLightSetup._cancel_operation(app)
            setup_gui.SceneLightSetup._close(app)
            setup_gui.SceneLightSetup._close(app)
            # Let the interpreter shut down naturally, without joining test-owned threads.
        """),
        encoding="utf-8",
    )
    environment = {**os.environ, "SCENELIGHT_MANAGED_ROOT": str(tmp_path / "managed")}
    try:
        result = subprocess.run(
            [sys.executable, str(script), str(tmp_path), phase],
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "stopped").read_text() == "yes"
        assert not (tmp_path / "second").exists()
    finally:
        pid_file = tmp_path / "child.pid"
        if pid_file.exists():
            import psutil

            try:
                child = psutil.Process(int(pid_file.read_text()))
                child.kill()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX shared-memory resource tracker")
@pytest.mark.parametrize("method", ["spawn", "fork"])
@pytest.mark.parametrize("abrupt_exit", [False, True])
def test_shared_prepared_buffer_owner_cleanup(
    tmp_path: Path, method: str, abrupt_exit: bool
) -> None:
    from multiprocessing import get_all_start_methods, shared_memory

    if method not in get_all_start_methods():
        pytest.skip(f"{method} is unavailable")
    script = tmp_path / "shared_worker.py"
    script.write_text(
        textwrap.dedent("""\
            import multiprocessing as mp
            import os
            import sys
            from pathlib import Path
            from PIL import Image
            from scenelight.cuda_backend import allocate_shared_prepared_buffer, _write_shared_prepared_scene
            from scenelight.engine import prepare_scene

            def fill(spec):
                prepared = prepare_scene(Image.new("RGB", (32, 24), (100, 150, 200)), (0.92,))
                _write_shared_prepared_scene(prepared, spec)

            if __name__ == "__main__":
                prepared = prepare_scene(Image.new("RGB", (32, 24), (100, 150, 200)), (0.92,))
                allocation = allocate_shared_prepared_buffer(prepared.luma.shape, 0.92)
                Path(sys.argv[1]).write_text(allocation.spec.name)
                worker = mp.get_context(sys.argv[2]).Process(target=fill, args=(allocation.spec,))
                worker.start()
                worker.join(15)
                assert worker.exitcode == 0
                if sys.argv[3] == "True":
                    os._exit(23)
                allocation.close()
        """),
        encoding="utf-8",
    )
    name_path = tmp_path / "memory-name"
    result = subprocess.run(
        [sys.executable, str(script), str(name_path), method, str(abrupt_exit)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (23 if abrupt_exit else 0), result.stderr
    assert "KeyError" not in result.stderr
    if not abrupt_exit:
        assert "resource_tracker" not in result.stderr
    name = name_path.read_text()
    try:
        leaked = shared_memory.SharedMemory(name=name)
    except FileNotFoundError:
        pass
    else:
        leaked.close()
        leaked.unlink()
        pytest.fail("The owner's allocation survived process exit")
