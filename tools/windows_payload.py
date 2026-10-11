"""Copy runtime-only Windows payloads without modifying the source installs."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

PROFILES = ("desktop", "compatibility", "docs", "examples")
DEVELOPMENT_SUFFIXES = {".a", ".lib", ".pdb", ".h", ".hpp", ".pyi"}
DEVELOPMENT_DIRECTORIES = {"include", "headers", "cmake", "pkgconfig", "test", "tests"}
PREBUILT_PACKAGES = {"numpy", "cv2", "pil", "pyside6", "shiboken6", "psutil"}
QT_TOOLS = {
    "assistant.exe",
    "designer.exe",
    "linguist.exe",
    "lrelease.exe",
    "lupdate.exe",
    "qmlformat.exe",
    "qmllint.exe",
    "qmltyperegistrar.exe",
    "qsb.exe",
    "rcc.exe",
    "uic.exe",
}
OFFLINE_DIAGRAMS = {
    "media/lighting-comparison.png",
    "media/surface-maps.png",
    "media/scenelight-banner.svg",
    "media/preview-workspace.png",
    "media/preview-glow.png",
    "media/preview-export.png",
    "media/ingame-inspector.png",
}
CONTRIBUTOR_DOCS = {
    "architecture.md",
    "fresh_machine_validation.md",
    "releasing.md",
    "testing.md",
}
ONLINE_FILES = "https://github.com/RageAdo-dev/SceneLight/blob/main/"


def filesystem_path(path: Path) -> Path:
    """Qt's generated asset names exceed MAX_PATH in ordinary staging paths."""
    if os.name == "nt":
        # Extended Windows paths do not interpret parent-directory segments.
        path = Path(os.path.normpath(path))
    path = path.resolve()
    if os.name != "nt" or str(path).startswith("\\\\?\\"):
        return path
    text = str(path)
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def keep(relative: Path, profile: str) -> bool:
    """One policy for newly built and reused runtime directories."""
    parts = tuple(part.lower() for part in relative.parts)
    if not parts:
        return True
    if "__pycache__" in parts or any(part.endswith(".egg-info") for part in parts):
        return False
    if profile == "compatibility":
        # Keep both supported Windows architectures and Python 2 bytecode.
        # Ren'Py's common directory includes assets needed by running games.
        if parts[0] == "lib":
            return len(parts) == 1 or parts[1] in {
                "python2.7",
                "py2-windows-x86_64",
                "py2-windows-i686",
            }
        return parts[0] in {
            "renpy.exe",
            "renpy-32.exe",
            "renpy.py",
            "license.txt",
            "renpy",
            "module",
        }
    if profile == "examples":
        return parts[0] not in {"effect-packs", "synthetic"}
    if profile == "docs":
        if parts[0] == "effect_packs.md" or parts[0] in CONTRIBUTOR_DOCS:
            return False
        if parts[0] != "media" or len(parts) == 1:
            return True
        return relative.as_posix().lower() in OFFLINE_DIAGRAMS or relative.suffix.lower() in {
            ".md",
            ".txt",
            ".json",
        }
    if profile != "desktop":
        raise ValueError("Unknown payload profile: " + profile)
    # Some optional libraries (for example CuPy) need headers at runtime for
    # JIT compilation. Strip build inputs only from the shipped prebuilt stack
    # and the interpreter tree, not from arbitrary added packages.
    package = None
    if "site-packages" in parts:
        index = parts.index("site-packages") + 1
        if index < len(parts):
            package = parts[index]
    prebuilt = package is None or package in PREBUILT_PACKAGES
    if relative.suffix.lower() in {".pyc", ".pyo", ".pyi", ".pdb"}:
        return False
    if prebuilt and relative.suffix.lower() in DEVELOPMENT_SUFFIXES:
        return False
    if any(part in {"test", "tests"} for part in parts) or (
        prebuilt and any(part in DEVELOPMENT_DIRECTORIES for part in parts)
    ):
        return False
    if parts[0] in {"doc", "docs", "tools", "libs"}:
        return False
    if len(parts) > 1 and parts[:2] in {("lib", "idlelib"), ("lib", "turtledemo")}:
        return False
    if "pyside6" in parts:
        if parts[-1] in QT_TOOLS or any(part in {"glue", "typesystems"} for part in parts):
            return False
    return True


def copy_payload(source: Path, destination: Path, profile: str, prefix: Path = Path()) -> None:
    source = filesystem_path(source.resolve(strict=True))
    destination = filesystem_path(destination)
    if profile not in PROFILES:
        raise ValueError("Unknown payload profile: " + profile)
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination must be separate trees")
    if destination.exists():
        raise FileExistsError(destination)

    def ignored(directory: str, names: list[str]) -> list[str]:
        parent = Path(directory)
        for name in names:
            target = parent / name
            if target.is_symlink():
                raise ValueError("Payload must not contain symbolic links: " + str(target))
        return [
            name
            for name in names
            if not keep(prefix / (parent / name).relative_to(source), profile)
        ]

    shutil.copytree(source, destination, ignore=ignored)


def package_docs(repository: Path, package: Path) -> None:
    repository = filesystem_path(repository.resolve(strict=True))
    package = filesystem_path(package.resolve(strict=True))
    if repository == package or package in repository.parents or repository in package.parents:
        raise ValueError("Package documentation must be staged outside the source tree")
    copy_payload(repository / "docs", package / "docs", "docs")
    # Link omitted contributor files and large media to the source repository.
    pattern = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
    for output in [*sorted(package.glob("*.md")), *sorted((package / "docs").rglob("*.md"))]:
        original = repository / output.relative_to(package)

        def replace_link(match: re.Match[str]) -> str:
            image, label, url = match.groups()
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path:
                return match.group(0)
            target = filesystem_path(original.parent / unquote(parsed.path))
            if repository not in target.parents or not target.is_file():
                return match.group(0)
            relative = target.relative_to(repository)
            if (package / relative).is_file():
                return match.group(0)
            online = ONLINE_FILES + quote(relative.as_posix())
            if parsed.query:
                online += "?" + parsed.query
            if parsed.fragment:
                online += "#" + parsed.fragment
            return f"[{label}{' (online example)' if image else ''}]({online})"

        text = pattern.sub(replace_link, original.read_text(encoding="utf-8"))
        output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.profile == "docs":
        package_docs(args.source, args.destination)
    else:
        copy_payload(args.source, args.destination, args.profile)
