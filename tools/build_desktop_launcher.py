"""Compile the Windows launchers with product version metadata.

Both launchers are tiny C programs: one starts the bundled interpreter, the
other routes a game's executable through SceneLight's compatibility runtime.
Windows shows their version resources in the file properties, which is also what
a code-signing certificate later attaches to.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/desktop_launcher.c"
NATIVE_SOURCE = ROOT / "tools/native_launcher.c"
RESOURCE = ROOT / "tools/desktop_launcher.rc"
NATIVE_RESOURCE = ROOT / "tools/native_launcher.rc"
DESTINATION = ROOT / "src/scenelight/assets/scenelight-desktop.exe"
NATIVE_DESTINATION = ROOT / "src/scenelight/assets/scenelight-launcher.exe"
PROJECT_URL = "https://github.com/RageAdo-dev/SceneLight"
COPYRIGHT = "Copyright (c) 2026 RageAdo-dev. MIT licensed."


def package_version() -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        (ROOT / "src/scenelight/__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError("Could not read the SceneLight version")
    return match.group(1)


def version_quad(version: str) -> tuple[int, int, int, int]:
    numbers = [int(part) for part in version.split(".") if part.isdigit()]
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers[:4])  # type: ignore[return-value]


def resource_text(
    version: str,
    *,
    description: str = "SceneLight setup and preview",
    original_name: str = "SceneLight.exe",
) -> str:
    quad = version_quad(version)
    numeric = ", ".join(str(part) for part in quad)
    return (
        "#include <windows.h>\n"
        "\n"
        '1 ICON "src/scenelight/assets/scenelight.ico"\n'
        "\n"
        "VS_VERSION_INFO VERSIONINFO\n"
        f" FILEVERSION {numeric}\n"
        f" PRODUCTVERSION {numeric}\n"
        " FILEFLAGSMASK 0x3fL\n"
        " FILEFLAGS 0x0L\n"
        " FILEOS 0x40004L\n"
        " FILETYPE 0x1L\n"
        " FILESUBTYPE 0x0L\n"
        "BEGIN\n"
        '    BLOCK "StringFileInfo"\n'
        "    BEGIN\n"
        '        BLOCK "040904b0"\n'
        "        BEGIN\n"
        '            VALUE "Comments", "' + PROJECT_URL + '\\0"\n'
        '            VALUE "CompanyName", "RageAdo-dev\\0"\n'
        '            VALUE "FileDescription", "' + description + '\\0"\n'
        f'            VALUE "FileVersion", "{version}\\0"\n'
        '            VALUE "InternalName", "SceneLight\\0"\n'
        '            VALUE "LegalCopyright", "' + COPYRIGHT + '\\0"\n'
        '            VALUE "OriginalFilename", "' + original_name + '\\0"\n'
        '            VALUE "ProductName", "SceneLight\\0"\n'
        f'            VALUE "ProductVersion", "{version}\\0"\n'
        "        END\n"
        "    END\n"
        '    BLOCK "VarFileInfo"\n'
        "    BEGIN\n"
        '        VALUE "Translation", 0x409, 1200\n'
        "    END\n"
        "END\n"
    )


def native_resource_text(version: str) -> str:
    return resource_text(
        version,
        description="SceneLight game launcher",
        original_name="scenelight-launcher.exe",
    )


def write_resources(version: str) -> tuple[Path, Path]:
    RESOURCE.write_text(resource_text(version), encoding="utf-8", newline="\n")
    NATIVE_RESOURCE.write_text(native_resource_text(version), encoding="utf-8", newline="\n")
    return RESOURCE, NATIVE_RESOURCE


def _link(source: Path, resource: Path, destination: Path, windres: str, gcc: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        compiled = Path(directory) / "launcher.res.o"
        subprocess.run(
            [windres, str(resource), "-O", "coff", "-o", str(compiled)],
            check=True,
            cwd=str(ROOT),
        )
        subprocess.run(
            [
                gcc,
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-municode",
                "-mwindows",
                "-static-libgcc",
                "-s",
                # Keep the PE timestamp out of the image so rebuilding the same
                # source reproduces the same bytes and the recorded hash holds.
                "-Wl,--no-insert-timestamp",
                str(source),
                str(compiled),
                "-o",
                str(destination),
                "-luser32",
            ],
            check=True,
            cwd=str(ROOT),
        )


def compile_launchers(version: str, windres: str, gcc: str) -> None:
    resource, native_resource = write_resources(version)
    _link(SOURCE, resource, DESTINATION, windres, gcc)
    _link(NATIVE_SOURCE, native_resource, NATIVE_DESTINATION, windres, gcc)


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        raise RuntimeError("The desktop launcher is built on Windows")
    windres = "windres" if len(argv) < 2 else argv[1]
    gcc = "gcc" if len(argv) < 3 else argv[2]
    version = package_version()
    compile_launchers(version, windres, gcc)
    print(f"Built {DESTINATION} and {NATIVE_DESTINATION} for SceneLight {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
