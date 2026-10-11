"""Entry point for the Windows application and its bundled interpreter."""

from __future__ import annotations

import json
import sys
from multiprocessing import freeze_support
from pathlib import Path


def bundled_python() -> Path | None:
    root = Path(sys.executable).resolve().parent
    if (root / "scenelight-runtime.json").is_file() and (root / "python.exe").is_file():
        return root / "python.exe"
    return None


def main() -> int:
    arguments = sys.argv[1:]
    if len(arguments) == 2 and arguments[0] == "--diagnostics":
        import importlib
        import tkinter

        from . import __version__
        from .setup_gui import dependency_state, preferred_runtime_python

        modules = (
            "numpy",
            "cv2",
            "PIL",
            "psutil",
            "PySide6.QtWidgets",
            "OpenGL.GL",
            "imageio_ffmpeg",
        )
        for module in modules:
            importlib.import_module(module)
        window = tkinter.Tk()
        window.withdraw()
        window.destroy()
        dependencies = dependency_state(include_preview=True)
        if not dependencies.ready:
            raise RuntimeError("Missing bundled components: " + ", ".join(dependencies.missing))
        Path(arguments[1]).write_text(
            json.dumps(
                {
                    "version": __version__,
                    "python": sys.version,
                    "bundled": bundled_python() is not None,
                    "modules": list(modules),
                    "tk": "passed",
                    "dependencies_ready": dependencies.ready,
                    "worker_python": str(preferred_runtime_python()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0
    if arguments[:1] == ["--cli"]:
        from .cli import main as cli_main

        return cli_main(arguments[1:])
    if arguments[:1] == ["--preview"]:
        from .preview.__main__ import main as preview_main

        sys.argv = [sys.argv[0], *arguments[1:]]
        return preview_main()
    from .setup_gui import developer_mode_from_arguments, initial_project_from_arguments, main

    return main(
        initial_project_from_arguments(arguments),
        developer_mode=developer_mode_from_arguments(arguments),
    )


if __name__ == "__main__":
    freeze_support()
    try:
        raise SystemExit(main())
    except Exception as error:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(error), "SceneLight could not start", 0x10)
        raise SystemExit(1) from error
