"""Bounded file verification with OS change identities, not mtime-only caching."""

from __future__ import annotations

import hashlib
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation", ctypes.c_longlong),
            ("access", ctypes.c_longlong),
            ("write", ctypes.c_longlong),
            ("change", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetVolumeInformationByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    _kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    _cacheable_volumes: dict[int, bool] = {}


def _open(path: Path):
    if os.name != "nt":
        return path.open("rb", buffering=0)
    # Deny concurrent writers while observing the identity or reading bytes.
    # FILE_READ_ATTRIBUTES alone does not enforce sharing against data writers:
    # NTFS can defer ChangeTime until their handle closes, making reuse unsafe.
    name = os.path.abspath(path)
    if not name.startswith("\\\\?\\"):
        name = "\\\\?\\UNC\\" + name[2:] if name.startswith("\\\\") else "\\\\?\\" + name
    handle = _kernel.CreateFileW(
        name,
        0x80000000,
        0x1 | 0x4,
        None,
        3,
        0x80,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        error.filename = str(path)
        raise error
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _kernel.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb", buffering=0)


def _identity(stream):
    info = os.fstat(stream.fileno())
    ordinary = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    change = info.st_ctime_ns
    if os.name == "nt":
        basic = _FileBasicInfo()
        handle = msvcrt.get_osfhandle(stream.fileno())
        if info.st_dev not in _cacheable_volumes:
            name = ctypes.create_unicode_buffer(64)
            ok = _kernel.GetVolumeInformationByHandleW(
                handle, None, 0, None, None, None, name, len(name)
            )
            _cacheable_volumes[info.st_dev] = bool(ok and name.value.upper() in {"NTFS", "REFS"})
        if not _kernel.GetFileInformationByHandleEx(
            handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)
        ):
            # Older/unsupported filesystems still get full content verification.
            return ordinary, None
        change = basic.change
        if not _cacheable_volumes[info.st_dev]:
            return (*ordinary, change), None
    identity = (*ordinary, change)
    return identity, identity if info.st_ino and change else None


def _token(identity, digest: str) -> str | None:
    if identity is None:
        return None
    payload = "sc-file-v1|" + digest + "|" + "|".join(str(value) for value in identity)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def verified_digest(path: Path, expected: str | None = None, stamp: str | None = None):
    """Return (SHA-256, verification stamp, reused) for these exact file bytes.

    Windows creation time is insufficient: use the kernel ChangeTime, file ID,
    volume, size and write time. Restoring a file's mtime cannot hide an edit.
    POSIX uses its inode change time. Missing stamps force a complete read.
    """
    if expected and stamp:
        with _open(path) as stream:
            _, identity = _identity(stream)
            if stamp == _token(identity, expected):
                return expected, stamp, True
    with _open(path) as stream:
        before, _ = _identity(stream)
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after, identity = _identity(stream)
        if before != after:
            raise RuntimeError(f"File changed during verification: {path}")
        value = digest.hexdigest()
        return value, _token(identity, value), False


def bounded_file_work(function, items, *, workers: int | None = None):
    """Keep at most eight file jobs queued, including on very large mods."""
    count = min(4, max(1, os.cpu_count() or 1)) if workers is None else max(1, workers)
    iterator = iter(items)
    with ThreadPoolExecutor(max_workers=count, thread_name_prefix="SceneLight-files") as pool:
        pending = deque()
        for _ in range(count * 2):
            item = next(iterator, None)
            if item is None:
                break
            pending.append(pool.submit(function, item))
        while pending:
            yield pending.popleft().result()
            item = next(iterator, None)
            if item is not None:
                pending.append(pool.submit(function, item))
