"""Source-tree and release entry point for the SceneLight setup window."""

from __future__ import annotations

import sys
from multiprocessing import freeze_support
from pathlib import Path
from tkinter import Tk, messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def _show_error(message: str) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror("SceneLight", message, parent=root)
    root.destroy()


def run() -> int:
    if sys.version_info < (3, 10):
        _show_error("SceneLight needs Python 3.10 or newer.")
        return 1
    if "--cli" in sys.argv:
        from scenelight.cli import main

        arguments = sys.argv[1:]
        arguments.remove("--cli")
        return main(arguments)

    from scenelight.setup_gui import (
        developer_mode_from_arguments,
        initial_project_from_arguments,
        main,
    )

    arguments = sys.argv[1:]
    return main(
        initial_project_from_arguments(arguments),
        developer_mode=developer_mode_from_arguments(arguments),
    )


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(run())
