"""Render SceneLight Setup states without injecting mouse or keyboard input."""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from pathlib import Path

if hasattr(ctypes, "windll"):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass

from tkinter import Misc  # noqa: E402

from PIL import ImageGrab

from scenelight.setup_gui import SceneLightSetup, parse_component_progress


def capture(window: Misc, destination: Path) -> None:
    top = window.winfo_toplevel()
    top.geometry("+0+0")
    top.lift()
    top.update()
    x = window.winfo_rootx()
    y = window.winfo_rooty()
    width = window.winfo_width()
    height = window.winfo_height()
    destination.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).save(destination)


def wait_for_inspection(app: SceneLightSetup, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while app._project_checking and time.monotonic() < deadline:
        app.update()
        time.sleep(0.025)
    if app._project_checking:
        raise TimeoutError("SceneLight project inspection did not finish")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()

    app = SceneLightSetup()
    app.update()
    started = time.perf_counter()
    app.project_var.set(str(arguments.project.resolve()))
    callback_seconds = time.perf_counter() - started
    app.update()
    capture(app, arguments.output / "01-project-inspection.png")

    wait_for_inspection(app)
    app.update()
    capture(app, arguments.output / "02-existing-install.png")

    app._show_options(tab="advanced")
    app.update()
    assert app._options_window is not None
    capture(app._options_window, arguments.output / "03-requirements.png")
    if app.requirements_canvas is not None:
        app.requirements_canvas.yview_moveto(1.0)
        app.update()
        capture(app._options_window, arguments.output / "04-requirements-bottom.png")
    inspection = app._project_inspection
    payload = {
        "selection_callback_seconds": callback_seconds,
        "project_checking": app._project_checking,
        "direct_install_ready": bool(inspection and inspection.direct_install_ready),
        "managed_install_ready": bool(inspection and inspection.managed_install_ready),
        "primary_button": str(app.primary_button.cget("text")),
        "installation_status": app.installation_var.get(),
        "requirements": (
            len(app._dependency_state.required) if app._dependency_state is not None else 0
        ),
    }
    app._options_window.withdraw()
    app._running = True
    app._active_operation = "components"
    app.progress_frame.grid()
    app._refresh_project_state()
    component_update = parse_component_progress(
        "Downloading pyside6_addons-6.9.2-cp39-abi3-win_amd64.whl (160.2 MB)"
    )
    assert component_update is not None
    app._apply_component_progress(component_update)
    transfer_update = parse_component_progress(
        "━━━━━━━━ 72.6/160.2 MB 17.0 MB/s 0:00:04",
        component_update.active_download,
    )
    assert transfer_update is not None
    app._apply_component_progress(transfer_update)
    app.update()
    capture(app, arguments.output / "05-live-component-progress.png")
    app.destroy()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
