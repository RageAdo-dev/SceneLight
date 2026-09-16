"""Compile the Windows launcher with product version metadata.

The launcher is a tiny C program that starts the bundled interpreter. Windows
shows its version resource in the file properties, which is also what a
code-signing certificate later attaches to.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/desktop_launcher.c"
RESOURCE = ROOT / "tools/desktop_launcher.rc"
DESTINATION = ROOT / "src/scenelight/assets/scenelight-desktop.exe"


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


def resource_text(version: str) -> str:
    quad = version_quad(version)
    numeric = ", ".join(str(part) for part in quad)
    return (
        "#include <windows.h>\n"
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
        '            VALUE "CompanyName", "SceneLight\\0"\n'
        '            VALUE "FileDescription", "SceneLight setup and preview\\0"\n'
        f'            VALUE "FileVersion", "{version}\\0"\n'
        '            VALUE "InternalName", "SceneLight\\0"\n'
        '            VALUE "LegalCopyright", "MIT licensed\\0"\n'
        '            VALUE "OriginalFilename", "SceneLight.exe\\0"\n'
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


def write_resource(version: str) -> Path:
    RESOURCE.write_text(resource_text(version), encoding="utf-8", newline="\n")
    return RESOURCE


def compile_launcher(version: str, windres: str, gcc: str) -> None:
    resource = write_resource(version)
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
                str(SOURCE),
                str(compiled),
                "-o",
                str(DESTINATION),
                "-luser32",
            ],
            check=True,
            cwd=str(ROOT),
        )


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        raise RuntimeError("The desktop launcher is built on Windows")
    windres = "windres" if len(argv) < 2 else argv[1]
    gcc = "gcc" if len(argv) < 3 else argv[2]
    version = package_version()
    compile_launcher(version, windres, gcc)
    print(f"Built {DESTINATION} for SceneLight {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
