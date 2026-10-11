"""Check the icon Windows actually receives, not just the source artwork."""

import ctypes
import sys
from ctypes import wintypes

import pytest

from scenelight.branding import ICON_PATH
from scenelight.setup_gui import SceneLightSetup

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows icon handoff")


class IconInfo(ctypes.Structure):
    _fields_ = [
        ("is_icon", wintypes.BOOL),
        ("x_hotspot", wintypes.DWORD),
        ("y_hotspot", wintypes.DWORD),
        ("mask", wintypes.HBITMAP),
        ("color", wintypes.HBITMAP),
    ]


class Bitmap(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.LONG),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("width_bytes", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bits_pixel", wintypes.WORD),
        ("bits", ctypes.c_void_p),
    ]


def test_setup_passes_the_correct_icon_pixels_to_windows():
    import tkinter as tk

    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user.LoadImageW.restype = wintypes.HANDLE
    user.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(IconInfo)]
    user.DestroyIcon.argtypes = [wintypes.HICON]
    gdi.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi.GetBitmapBits.argtypes = [wintypes.HBITMAP, wintypes.LONG, ctypes.c_void_p]
    gdi.GetBitmapBits.restype = wintypes.LONG
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]

    def read_icon(handle):
        info = IconInfo()
        assert user.GetIconInfo(handle, ctypes.byref(info))
        try:
            bitmap = Bitmap()
            assert gdi.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
            length = bitmap.width_bytes * bitmap.height
            pixels = ctypes.create_string_buffer(length)
            assert gdi.GetBitmapBits(info.color, length, pixels) == length
            return (bitmap.width, bitmap.height, bitmap.bits_pixel, pixels.raw)
        finally:
            gdi.DeleteObject(info.color)
            gdi.DeleteObject(info.mask)

    root = tk.Tk()
    root.withdraw()
    try:
        SceneLightSetup._apply_window_icon(root, root)
        dialog = tk.Toplevel(root)
        SceneLightSetup._apply_window_icon(root, dialog)
        dialog.withdraw()
        root.update_idletasks()
        # Both the main window and options/review dialogs must retain the actual
        # small and large frames, rather than scaling up the smallest frame.
        for window in (root, dialog):
            hwnd = user.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
            for kind, size in ((0, 16), (1, 32)):  # ICON_SMALL / ICON_BIG
                handle = user.SendMessageW(hwnd, 0x007F, kind, 0)  # WM_GETICON
                assert handle
                expected = user.LoadImageW(None, str(ICON_PATH), 1, size, size, 0x10)
                assert expected
                try:
                    actual = read_icon(handle)
                    assert actual[:2] == (size, size)
                    assert actual == read_icon(expected)
                finally:
                    user.DestroyIcon(expected)
    finally:
        root.destroy()
