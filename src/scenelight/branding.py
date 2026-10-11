"""Shared application identity and packaged icon paths."""

from __future__ import annotations

import sys
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSET_ROOT / "scenelight.ico"
ICON_PNG = ASSET_ROOT / "scenelight.png"


def set_process_identity() -> None:
    """Keep Windows taskbar identity attached to SceneLight's windows."""

    if sys.platform != "win32":
        return
    import ctypes

    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        setter("RageAdo.SceneLight")
    except (AttributeError, OSError):
        pass
