"""Validated inputs and pixels from the last completed Ren'Py capture."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

from .file_verification import bounded_file_work, verified_digest

_NAME = r"[A-Za-z_]\w*(?: +\w+)*"
_IMAGE = re.compile(rf"""image +{_NAME} *= *["'][\w./ -]+\.(?:png|jpg|jpeg)["']""", re.I)
_LABEL = re.compile(r"label +[A-Za-z_]\w*:")
_SHOW = re.compile(rf"(?:show|scene|hide) +{_NAME}|return")
_LAYERED = re.compile(rf"layeredimage +{_NAME}:")
_LAYER = re.compile(
    r"""group +\w+:|attribute +\w+(?: +default)?:|always:|["'][\w./ -]+\.(?:png|jpg|jpeg)["']"""
    r"|(?:rotate|zoom|xzoom|yzoom|xoffset|yoffset|alpha) +-?\d+(?:\.\d+)?",
    re.I,
)


def rendering_script(source: bytes) -> bytes:
    """Keep executable and ambiguous script changes in the shared cache key."""
    if any(token in source for token in (b'"""', b"'''", b"\\", b"\x00")):
        return source
    try:
        lines = source.decode("utf-8-sig").splitlines()
    except UnicodeError:
        return source
    kept = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or _IMAGE.fullmatch(line):
            continue
        if _LABEL.fullmatch(line) or _LAYERED.fullmatch(line):
            end = i
            while end < len(lines) and (not lines[end].strip() or lines[end][0].isspace()):
                end += 1
            allowed = _LAYER if _LAYERED.fullmatch(line) else _SHOW
            if all(not row.strip() or allowed.fullmatch(row.strip()) for row in lines[i:end]):
                i = end
                continue
        kept.append(line)
    return "\n".join(kept).encode()


def _pixel_reader(root: Path):
    captured = (root / "captured").resolve()
    directories = {}

    def digest(relative: str, expected=None, stamp=None):
        raw = root.parent / relative
        if raw.suffix.lower() != ".png":
            raise ValueError("Outside the capture cache")
        folder = directories.get(raw.parent)
        if folder is None:
            folder = raw.parent.resolve()
            if not folder.is_relative_to(captured):
                raise ValueError("Outside the capture cache")
            directories[raw.parent] = folder
        path = folder / raw.name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Expected a regular capture PNG")
        return verified_digest(path, expected, stamp)[:2]

    return digest


def compiled_source_digest(compiled: Path, sources: tuple[Path, ...]) -> str | None:
    """Ren'Py stores the matching source MD5 in the last 16 bytes of RPC2 files."""
    with compiled.open("rb") as stream:
        if stream.read(10) != b"RENPY RPC2" or compiled.stat().st_size < 56:
            return None
        stream.seek(-16, 2)
        footer = stream.read(16)
    for source in sources:
        if source.is_file():
            raw = source.read_bytes()
            if hashlib.md5(raw, usedforsecurity=False).digest() == footer:
                return hashlib.sha256(raw).hexdigest()
    return None


def verified_pixels(root: Path, scope: str, compiled=None, *, progress=None) -> dict:
    path = root / "capture_pixels.json"
    try:
        index = json.loads(path.read_bytes())
        if index["scope"] != scope:
            return {}
        for name, values in (compiled or {}).items():
            earlier = index.get("compiled", {}).get(name)
            if earlier and earlier[0] == values[0] and earlier[1] != values[1]:
                if len(earlier) < 3 or len(values) < 3 or not values[2] or earlier[2] != values[2]:
                    return {}
        digest = _pixel_reader(root)
        expected = {}
        for kind in ("sprites", "scenes"):
            for _key, relative, checksum in index[kind].values():
                expected[relative] = checksum
        stamps = index.get("stamps", {})

        def check(item):
            relative, checksum = item
            try:
                actual, _ = digest(relative, checksum, stamps.get(relative))
            except (OSError, ValueError):
                actual = None
            return relative, actual

        if progress is not None:
            progress.set_total(len(expected))
        checked = {}
        for relative, actual in bounded_file_work(check, expected.items()):
            checked[relative] = actual
            if progress is not None:
                progress.advance()
        result = {}
        for kind in ("sprites", "scenes"):
            result[kind] = {
                name: [key, relative]
                for name, (key, relative, checksum) in index[kind].items()
                if checked[relative] and checked[relative] == checksum
            }
        return result
    except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        return {}


def record_pixels(root: Path, scope: str, payload: dict, compiled=None) -> None:
    keys = payload.get("pixel_keys", {})
    index = {"scope": scope, "compiled": compiled or {}}
    try:
        previous = json.loads((root / "capture_pixels.json").read_bytes())
        stamps = previous.get("stamps", {})
        expected = {
            relative: checksum
            for kind in ("sprites", "scenes")
            for _, relative, checksum in previous[kind].values()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        stamps, expected = {}, {}
    digest = _pixel_reader(root)
    files = dict.fromkeys(
        payload[kind][name]
        for kind in ("sprites", "scenes")
        for name in keys.get(kind, {})
        if payload[kind].get(name)
    )

    def check(relative):
        return relative, digest(relative, expected.get(relative), stamps.get(relative))

    hashes = dict(bounded_file_work(check, files))
    index["stamps"] = {path: stamp for path, (_, stamp) in hashes.items() if stamp}
    for kind in ("sprites", "scenes"):
        entries = {}
        for name, key in keys.get(kind, {}).items():
            relative = payload[kind].get(name)
            if not relative:
                continue
            entries[name] = [key, relative, hashes[relative][0]]
        index[kind] = entries
    path = root / "capture_pixels.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
