"""Recognize additive, file-backed character declarations for the open playtest."""

from __future__ import annotations

import re

_NAME = r"[a-zA-Z_]\w*"
_IMAGE = re.compile(
    r"""image\s+([a-z]\w*(?: +\w+)+)\s*=\s*(["'])([\w ./-]+\.(?:png|jpg|jpeg|webp|bmp))\2\s*"""
)
_CHARACTER = re.compile(
    rf"""define\s+{_NAME}\s*=\s*Character\(\s*["'][\w -]+["']\s*,\s*image\s*=\s*(["'])({_NAME})\1\s*\)\s*"""
)
_SHOW = re.compile(
    rf" +(?P<action>show|hide) +(?!screen\b|expression\b|layer\b)(?P<tag>{_NAME})(?: +\w+)*\s*"
)
_POSE = re.compile(
    rf"(?P<indent> +)show +(?!screen\b|expression\b|layer\b)(?P<tag>{_NAME})"
    rf"(?: +(?!(?:at|as|behind|onlayer|zorder|with)\b)\w+)*"
    rf"(?: +at +(?P<transform>{_NAME}))? *"
)
_SAY = re.compile(r' +(?:[A-Za-z_]\w* +)?"[^"\\\n]*"\s*')
_LAYER = re.compile(rf"layeredimage +({_NAME}(?: +\w+)*)\s*:\s*(?:#.*)?$")
_PIECE = re.compile(r"""^\s*(["'])([\w ./-]+\.(?:png|webp|bmp|jpeg|jpg))\1\s*$""", re.I)


def _split_layers(source):
    rest, blocks = [], {}
    block = None
    for line in source.decode("utf-8-sig").splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            block = None
            match = _LAYER.fullmatch(line)
            if match:
                block = match[1]
                if block in blocks:
                    raise ValueError("Duplicate layered image")
                blocks[block] = []
                continue
        if block is None:
            rest.append(line)
        else:
            blocks[block].append(line)
    return "\n".join(rest).encode(), blocks


def layered_changes(before, after):
    """Let the game resolve layered attributes, defaults and conditions itself."""
    old, previous = _split_layers(before)
    new, current = _split_layers(after)
    if previous.keys() - current.keys():
        return None
    tags, files = set(), set()
    for name, lines in current.items():
        if lines == previous.get(name):
            continue
        tags.add(name.split()[0])
        prior = set(previous.get(name, ()))
        for line in lines:
            if line in prior:
                continue
            code = line.split("#", 1)[0].strip()
            if not code:
                continue
            if code.startswith(("attribute ", "always ")):
                # A layer's filename may follow its attribute on the same line.
                literal = re.search(
                    r"""["'][^"']+\.(?:png|webp|bmp|jpeg|jpg)["']\s*$""", code, re.I
                )
                if literal:
                    code = literal[0]
            piece = _PIECE.fullmatch(code)
            if piece:
                if any(p in {"", ".", ".."} for p in piece[2].split("/")):
                    return None
                files.add(piece[2])
            elif not code.startswith(
                (
                    "group ",
                    "attribute ",
                    "always:",
                    "xoffset ",
                    "yoffset ",
                    "pos ",
                    "anchor ",
                    "subpixel ",
                )
            ):
                return None
    return old, new, tags, files


def sprite_script_changes(before: bytes, after: bytes):
    """Recognize additions and expression changes on an existing show statement."""
    original = iter(before.decode("utf-8-sig").splitlines())
    prior = next(original, None)
    images, tags, shown = {}, set(), set()
    for line in after.decode("utf-8-sig").splitlines():
        if line == prior:
            prior = next(original, None)
        elif match := _SHOW.fullmatch(line):
            if match["action"] == "show":
                shown.add(match["tag"])
                old_pose = _POSE.fullmatch(prior or "")
                new_pose = _POSE.fullmatch(line)
                if old_pose and new_pose and old_pose.groups() == new_pose.groups():
                    prior = next(original, None)
        elif not line.strip() or _SAY.fullmatch(line):
            continue
        elif match := _IMAGE.fullmatch(line):
            name, _, path = match.groups()
            if name in images or any(p in {"", ".", ".."} for p in path.split("/")):
                return None
            images[name] = path
        elif match := _CHARACTER.fullmatch(line):
            tags.add(match[2])
        else:
            return None
    return (images, tags, shown) if prior is None else None
