"""Native setup window for the existing SceneLight command-line installer.

The GUI runs scan, install and verification through the CLI. It displays
progress and manages the worker processes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, diagnostics
from .branding import ICON_PATH, ICON_PNG, set_process_identity
from .calibration import profile_path
from .compatibility import RENPY_VERSION, cached_renpy_executable, compatibility_root
from .cuda_detection import CudaSupport, detect_cuda_support
from .developer import DeveloperStatus, developer_status
from .progress import STAGE_LABELS
from .project_watch import ProjectWatch, source_metadata
from .release import (
    ReleaseRelation,
    classify_release,
    release_content_sha256_from_manifest,
    release_version_from_manifest,
)
from .setup_theme import soft_controls
from .sidecar import (
    find_native_executable,
    managed_project_root,
    renpy_runtime_command,
    renpy_runtime_major,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2]
SDK_LAUNCHER = SOURCE_ROOT / "scenelight_sdk.py"
PREVIEW_LAUNCHER = SOURCE_ROOT / "scenelight_preview.pyw"
REQUIREMENTS = SOURCE_ROOT / "requirements.txt"
PREVIEW_REQUIREMENTS = SOURCE_ROOT / "requirements-preview.txt"
OFFLINE_WHEELHOUSE = SOURCE_ROOT / "wheelhouse"
DEPENDENCIES = {
    "numpy": "NumPy",
    "cv2": "OpenCV",
    "PIL": "Pillow",
}
BASE_REQUIREMENTS = (
    "numpy==2.2.6",
    "opencv-python-headless==5.0.0.93",
    "Pillow==12.3.0",
    "psutil==7.2.2",
    "PySide6-Essentials==6.11.2",
    "imageio-ffmpeg==0.6.0",
)
PACKAGING_REQUIREMENTS = (
    "pip==26.2.1",
    "setuptools==84.0.0",
    "wheel==0.48.0",
)
BASE_DEPENDENCIES = {
    "numpy": BASE_REQUIREMENTS[0],
    "cv2": BASE_REQUIREMENTS[1],
    "PIL": BASE_REQUIREMENTS[2],
    "psutil": BASE_REQUIREMENTS[3],
    "PySide6": BASE_REQUIREMENTS[4],
    "imageio_ffmpeg": BASE_REQUIREMENTS[5],
}
CUDA_REQUIREMENT = "cupy-cuda12x==14.2.0"
PREVIEW_DEPENDENCIES = {
    **BASE_DEPENDENCIES,
    "PySide6.QtOpenGLWidgets": "PySide6-Essentials==6.11.2",
    "OpenGL": "PyOpenGL==3.1.10",
}


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Stop one supervised operation and every renderer/installer it spawned."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=flags,
        )
        if result.returncode == 0 or process.poll() is not None:
            return
    process.terminate()


DEPENDENCY_LABELS = {
    "numpy": "NumPy",
    "opencv-python-headless": "OpenCV",
    "Pillow": "Pillow",
    "PySide6": "PySide6",
    "PyOpenGL": "PyOpenGL",
    "psutil": "psutil",
    "imageio-ffmpeg": "imageio-ffmpeg",
    "cupy-cuda12x": "CuPy CUDA 12",
    "pip": "pip",
    "setuptools": "setuptools",
    "wheel": "wheel",
}
COMPONENT_OUTPUT_LABELS = {
    **DEPENDENCY_LABELS,
    "pyside6-addons": "PySide6 Addons",
    "pyside6-essentials": "PySide6 Essentials",
    "shiboken6": "Shiboken6",
    "packaging": "Packaging",
    "scipy": "SciPy",
    "networkx": "NetworkX",
    "imageio": "imageio",
    "tifffile": "tifffile",
    "lazy-loader": "lazy-loader",
}


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    root: Path | None
    valid: bool
    message: str


@dataclass(frozen=True, slots=True)
class ProjectInspection:
    selection: ProjectSelection
    developer_status: DeveloperStatus | None = None
    managed_install_present: bool = False
    managed_launcher: Path | None = None
    direct_launch_command: tuple[str, ...] | None = None
    managed_version: str | None = None
    managed_content_sha256: str | None = None
    reserved_namespace_present: bool = False
    error: str | None = None
    source_metadata: dict | None = None
    managed_refresh_required: bool = False

    @property
    def direct_install_ready(self) -> bool:
        status = self.developer_status
        return bool(status and status.installed and status.clean)

    @property
    def direct_install_needs_attention(self) -> bool:
        status = self.developer_status
        return bool(status and status.installed and not status.clean)

    @property
    def direct_launch_ready(self) -> bool:
        return self.direct_install_ready and self.direct_launch_command is not None

    @property
    def direct_refresh_required(self) -> bool:
        status = self.developer_status
        return bool(status and status.installed and status.clean and status.refresh_required)

    @property
    def refresh_required(self) -> bool:
        return self.direct_refresh_required or self.managed_refresh_required

    @property
    def managed_install_ready(self) -> bool:
        return self.managed_install_present and self.managed_launcher is not None

    @property
    def managed_install_needs_attention(self) -> bool:
        return self.managed_install_present and self.managed_launcher is None

    @property
    def direct_release_relation(self) -> ReleaseRelation | None:
        status = self.developer_status
        if not (status and status.installed and status.clean):
            return None
        return classify_release(
            status.installed_version,
            installed_content_sha256=status.installed_content_sha256,
        )

    @property
    def managed_release_relation(self) -> ReleaseRelation | None:
        if not self.managed_install_ready:
            return None
        return classify_release(
            self.managed_version,
            installed_content_sha256=self.managed_content_sha256,
        )

    @property
    def preferred_release_relation(self) -> ReleaseRelation | None:
        return self.direct_release_relation or self.managed_release_relation

    @property
    def release_replacement_available(self) -> bool:
        relation = self.preferred_release_relation
        return bool(relation and relation.replacement_available)

    @property
    def release_update_operation(self) -> str | None:
        relation = self.preferred_release_relation
        if relation is None or not relation.replacement_available:
            return None
        return "refresh" if self.direct_release_relation is not None else "install"

    @property
    def unmanaged_namespace_present(self) -> bool:
        status = self.developer_status
        return self.reserved_namespace_present and not bool(status and status.installed)


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    phase: str
    label: str
    current: int
    total: int
    item: str = ""


@dataclass(frozen=True, slots=True)
class ComponentProgress:
    message: str
    current: float | None = None
    total: float | None = None
    active_download: str = ""


@dataclass(frozen=True, slots=True)
class DependencyState:
    python_executable: Path
    runtime_ready: bool
    required: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.runtime_ready and not self.missing

    @property
    def verified_count(self) -> int:
        return sum(ready for _, ready in self.component_statuses)

    @property
    def component_statuses(self) -> tuple[tuple[str, bool], ...]:
        return (("SceneLight runtime", self.runtime_ready), *requirement_statuses(self))

    @property
    def verification_summary(self) -> str:
        total = len(self.component_statuses)
        if self.ready:
            return f"{total} components verified."
        return f"{self.verified_count} of {total} components verified"


def normalize_project_path(value: str | os.PathLike[str], *, find_nested: bool = True) -> Path:
    """Accept a project, its game folder, or an unambiguous extraction wrapper."""

    expanded = Path(os.path.expandvars(os.path.expanduser(str(value).strip().strip('"'))))
    resolved = expanded.resolve()
    if resolved.name.lower() == "game" and resolved.is_dir():
        return resolved.parent
    if not find_nested or not resolved.is_dir() or (resolved / "game").is_dir():
        return resolved

    pending = [(resolved, 0)]
    candidates: list[Path] = []
    visited = 0
    entries_seen = 0
    while pending:
        directory, depth = pending.pop(0)
        visited += 1
        if visited > 64:
            raise ValueError("Too many subfolders. Choose a folder closer to the game.")
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > 2048:
                    raise ValueError("Too many files. Choose the game's extracted folder.")
                if entry.name.startswith(".") or entry.name == "__MACOSX":
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    continue
                attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                    continue
                child = Path(entry.path)
                game = child / "game"
                if (
                    game.is_dir()
                    and not game.is_symlink()
                    and game.resolve().is_relative_to(resolved)
                ):
                    candidates.append(child)
                elif depth < 2:
                    pending.append((child, depth + 1))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = ", ".join(str(path.relative_to(resolved)) for path in sorted(candidates))
        raise ValueError(f"More than one game was found ({names}). Choose the game you want.")
    return resolved


def initial_project_from_arguments(arguments: list[str]) -> str | None:
    """Accept either ``--project PATH`` or the legacy positional PATH form."""
    for index, value in enumerate(arguments):
        if value == "--project" and index + 1 < len(arguments):
            return arguments[index + 1]
    if arguments and not arguments[0].startswith("-"):
        return arguments[0]
    return None


def developer_mode_from_arguments(arguments: list[str]) -> bool:
    """Return whether Setup was opened through the mod-author entry point."""

    return "--developer" in arguments


def inspect_project_path(value: str | os.PathLike[str]) -> ProjectSelection:
    if not str(value).strip():
        return ProjectSelection(None, False, "Choose a Ren'Py game or mod folder.")
    try:
        root = normalize_project_path(value)
    except (OSError, RuntimeError, ValueError) as error:
        return ProjectSelection(None, False, f"That path could not be opened: {error}")
    if not root.is_dir():
        return ProjectSelection(root, False, "The selected folder does not exist.")
    if not (root / "game").is_dir():
        return ProjectSelection(root, False, "No 'game' folder was found inside this folder.")
    script_count = sum(1 for _ in (root / "game").rglob("*.rpy"))
    archive_count = sum(1 for _ in (root / "game").glob("*.rpa"))
    script_label = "script" if script_count == 1 else "scripts"
    archive_label = "archive" if archive_count == 1 else "archives"
    detail = f"{script_count} {script_label} · {archive_count} {archive_label}"
    return ProjectSelection(root, True, detail)


def component_environment_root() -> Path:
    override = os.environ.get("SCENELIGHT_COMPONENT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".scenelight"
    return (base / "SceneLight" / "python-env").resolve() if local else (base / "python-env")


def component_python() -> Path:
    from .desktop import bundled_python

    bundled = bundled_python()
    if bundled is not None:
        return bundled
    root = component_environment_root()
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def preferred_runtime_python() -> Path:
    """Use SceneLight's isolated environment when the source release created one."""

    from .desktop import bundled_python

    bundled = bundled_python()
    if bundled is not None:
        return bundled
    private_python = component_python()
    if SDK_LAUNCHER.is_file() and private_python.is_file():
        return private_python
    return Path(sys.executable)


def operation_environment(
    base: dict[str, str] | None = None,
    *,
    source_root: Path = SOURCE_ROOT,
) -> dict[str, str]:
    """Make packaged SceneLight modules importable from its isolated runtime."""

    environment = dict(os.environ if base is None else base)
    source_path = str((source_root / "src").resolve())
    existing = environment.get("PYTHONPATH", "")
    entries = [item for item in existing.split(os.pathsep) if item]
    normalized = {os.path.normcase(os.path.abspath(item)) for item in entries}
    if os.path.normcase(os.path.abspath(source_path)) not in normalized:
        entries.insert(0, source_path)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    environment.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    return environment


def _missing_modules(
    dependencies: dict[str, str], python_executable: Path | None = None
) -> list[str]:
    program = Path(python_executable or sys.executable)
    target = program.resolve()
    active = Path(sys.executable).resolve()
    # Windows' GUI and console executables in the same environment share their
    # packages. Treating pythonw.exe as a different environment spawned a new
    # interpreter (and blocked Tk) whenever Settings refreshed its component list.
    same_environment = target == active or (
        os.name == "nt"
        and target.parent == active.parent
        and {target.name.lower(), active.name.lower()} <= {"python.exe", "pythonw.exe"}
    )
    if same_environment:
        missing: list[str] = []
        for module, requirement in dependencies.items():
            distribution, separator, expected = requirement.partition("==")
            try:
                installed = version(distribution)
            except PackageNotFoundError:
                installed = ""
            try:
                available = importlib.util.find_spec(module) is not None
            except (ModuleNotFoundError, ValueError):
                available = False
            if not available or not separator or installed != expected:
                missing.append(requirement)
        return missing
    if not program.is_file():
        return list(dependencies.values())
    probe = """import importlib.metadata
import importlib.util
import json
import sys

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
missing = []
for module, requirement in pairs:
    distribution, separator, expected = requirement.partition("==")
    try:
        installed = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        installed = ""
    try:
        available = importlib.util.find_spec(module) is not None
    except (ModuleNotFoundError, ValueError):
        available = False
    if not available or not separator or installed != expected:
        missing.append(module)
print(json.dumps(missing))
"""
    arguments = [value for item in dependencies.items() for value in item]
    try:
        result = subprocess.run(
            [str(program), "-c", probe, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        missing_modules = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        missing_modules = None
    if not isinstance(missing_modules, list):
        return list(dependencies.values())
    return [
        requirement for module, requirement in dependencies.items() if module in missing_modules
    ]


def missing_dependencies(python_executable: Path | None = None) -> list[str]:
    missing = _missing_modules(BASE_DEPENDENCIES, python_executable)
    return [requirement.split("==", 1)[0] for requirement in missing]


def missing_preview_dependencies(python_executable: Path | None = None) -> list[str]:
    return _missing_modules(PREVIEW_DEPENDENCIES, python_executable)


def dependency_state(
    *,
    include_preview: bool = True,
    include_cuda: bool = False,
    source_mode: bool | None = None,
    python_executable: Path | None = None,
) -> DependencyState:
    """Probe exact package versions in SceneLight's actual target environment."""

    source = SDK_LAUNCHER.is_file() if source_mode is None else source_mode
    target = Path(
        python_executable or (component_python() if source else Path(sys.executable))
    ).resolve()
    dependencies = dict(PREVIEW_DEPENDENCIES if include_preview else BASE_DEPENDENCIES)
    if include_cuda:
        dependencies["cupy"] = CUDA_REQUIREMENT
    required = tuple(dict.fromkeys(dependencies.values()))
    runtime_ready = target.is_file()
    missing = (
        tuple(dict.fromkeys(_missing_modules(dependencies, target))) if runtime_ready else required
    )
    return DependencyState(target, runtime_ready, required, missing)


def preview_action_state(operation_running: bool) -> str:
    """Preview is standalone; only an active component/install operation blocks it."""

    return "disabled" if operation_running else "normal"


def format_requirement(requirement: str) -> str:
    distribution, separator, expected = requirement.partition("==")
    label = DEPENDENCY_LABELS.get(distribution, distribution)
    return f"{label} {expected}" if separator else label


def describe_dependency_plan(state: DependencyState) -> str:
    if state.ready:
        return ""
    packages = ", ".join(format_requirement(item) for item in state.missing)
    return f"Will install and verify: {packages}."


def requirement_statuses(state: DependencyState) -> tuple[tuple[str, bool], ...]:
    """Return each exact requirement and whether that version is verified."""

    missing = set(state.missing)
    return tuple((format_requirement(item), item not in missing) for item in state.required)


def describe_operation_failure(output: str) -> tuple[str, str]:
    """Extract the failure reason from CLI output for the Setup window."""

    lowered = output.lower()
    if "capturescripterror:" in lowered or "could not compile the game scripts" in lowered:
        return (
            "The game scripts could not be compiled",
            "Ren'Py reported a script error. Activity and the support report contain the "
            "file and line. Check that the mod runs with its intended Ren'Py version, then "
            "fix the reported syntax or select that compatible runtime. The current "
            "installation and completed analysis are retained.",
        )
    if "captureinstanceconflict:" in lowered:
        return (
            "The mod allows only one running copy",
            "Close other copies of this mod or other SceneLight setup sessions, then retry. "
            "SceneLight has retained completed sprite checkpoints. The activity log contains "
            "the mod's original diagnostic.",
        )
    if "no module named 'scenelight'" in lowered or 'no module named "scenelight"' in lowered:
        return (
            "SceneLight setup is incomplete",
            "The SceneLight runtime was created, but its packaged program files were not added "
            "to that runtime. Close this copy, use the newest SceneLight release, and try again. "
            "The selected game or mod was not changed.",
        )
    if "tried every compatible graphics backend" in lowered:
        return (
            "No compatible renderer worked",
            "SceneLight automatically tried every graphics backend bundled with this game and "
            "any selected SDK, but none could start here. The activity log lists each attempted "
            "backend. The selected game or mod was not changed.",
        )
    if "number of texture units: 0" in lowered or "can't find a workable environment" in lowered:
        return (
            "No usable graphics renderer",
            "This virtual machine has no compatible graphics acceleration. Enable virtual 3D "
            "acceleration or test SceneLight on the host computer.",
        )
    if "could not initialize the selected game's renderer" in lowered:
        return (
            "The game renderer did not initialize",
            "The selected game's own Ren'Py runtime exited before SceneLight could create its "
            "graphics callback. Open the activity log for the game log and traceback. The "
            "original mod was not changed.",
        )
    if "exit 3221225477" in lowered and "dynamic scenelight assets" in lowered:
        return (
            "The game renderer stopped unexpectedly",
            "Ren'Py closed while SceneLight was preparing character forms. The activity log "
            "contains the renderer details. The selected game or mod was not changed.",
        )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    reported_errors = [
        line.split(":", 1)[1].strip()
        for line in lines
        if line.startswith(("RuntimeError:", "ValueError:", "FileNotFoundError:", "OSError:"))
        and ":" in line
    ]
    meaningful = [
        line
        for line in lines
        if not line.startswith("SceneLight resolver ")
        and not (line.startswith("[") and "failed with exit code" in line)
    ]
    if reported_errors:
        detail = reported_errors[-1]
    else:
        detail = meaningful[-1] if meaningful else "No additional diagnostic text was produced."
    if len(detail) > 260:
        detail = detail[:257] + "…"
    return (
        "SceneLight could not continue",
        f"The operation did not complete: {detail}\n\nThe complete output is in the activity "
        "log. The selected game or mod was not changed.",
    )


def cuda_dependency_installed(python_executable: Path | None = None) -> bool:
    return not _missing_modules({"cupy": CUDA_REQUIREMENT}, python_executable)


def dependency_install_commands(
    *,
    include_preview: bool,
    include_cuda: bool,
    source_mode: bool | None = None,
    system_python: Path | None = None,
    environment_root: Path | None = None,
    requirements_path: Path | None = None,
    wheelhouse_path: Path | None = None,
) -> list[list[str]]:
    """Build shell-free install commands, isolating source-release dependencies."""

    from .desktop import bundled_python

    source = SDK_LAUNCHER.is_file() if source_mode is None else source_mode
    host_python = Path(system_python or sys.executable)
    bundled = bundled_python() if system_python is None and environment_root is None else None
    if bundled is not None:
        host_python = bundled
        source = False
    selected_requirements = requirements_path or (
        PREVIEW_REQUIREMENTS if include_preview else REQUIREMENTS
    )
    fallback = list(PREVIEW_DEPENDENCIES.values()) if include_preview else list(BASE_REQUIREMENTS)
    wheelhouse = Path(wheelhouse_path or OFFLINE_WHEELHOUSE)
    offline = (
        ["--no-index", "--find-links", str(wheelhouse.resolve())]
        if source and wheelhouse.is_dir() and any(wheelhouse.glob("*.whl"))
        else []
    )
    commands: list[list[str]] = []
    if bundled is not None:
        commands.append([str(host_python), "-m", "ensurepip", "--upgrade"])
    if source:
        private_root = Path(environment_root or component_environment_root())
        private_python = private_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        commands.append([str(host_python), "-m", "venv", str(private_root)])
        installer_python = private_python
        commands.append(
            [
                str(installer_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *offline,
                *PACKAGING_REQUIREMENTS,
            ]
        )
    else:
        installer_python = host_python
    install = [
        str(installer_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *offline,
    ]
    if selected_requirements.is_file():
        install.extend(("-r", str(selected_requirements)))
    else:
        install.extend(fallback)
    if include_cuda:
        install.append(CUDA_REQUIREMENT)
    commands.append(install)
    return commands


def normalize_command_batch(command: list[str] | list[list[str]]) -> list[list[str]]:
    """Normalize one command or a command batch without invoking a shell."""

    if not command:
        raise ValueError("A process command cannot be empty.")
    if isinstance(command[0], str):
        return [list(command)]  # type: ignore[list-item]
    return [list(item) for item in command]  # type: ignore[arg-type]


def extract_last_json(output: str) -> dict[str, object] | None:
    """Return the last complete JSON object from mixed progress and CLI output."""

    decoder = json.JSONDecoder()
    result: dict[str, object] | None = None
    for index, character in enumerate(output):
        if character != "{":
            continue
        # CLI reports begin at column zero. Ignoring indented opening braces is
        # important: raw_decode can also parse a nested dictionary by itself,
        # which previously replaced the full scan report with its final nested
        # character-candidate mapping.
        line_start = output.rfind("\n", 0, index) + 1
        if index != line_start:
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result = value
    return result


def skipped_asset_notice(result: dict[str, object]) -> str:
    skipped = result.get("skipped_sprites", [])
    if not isinstance(skipped, list) or not skipped:
        return ""
    return f" {len(skipped)} sprite form(s) were skipped; see Activity for the names and reasons."


_PROGRESS_PATTERNS = (
    (
        re.compile(r"SceneLight scan files\s+(\d+)/(\d+):\s*(.*)"),
        "scan-files",
        "Reading game files",
    ),
    (
        re.compile(r"SceneLight scan\s+(\d+)/(\d+):\s*(.*)"),
        "scan",
        "Scanning game",
    ),
    (
        re.compile(r"compatibility download\s+(\d+)/(\d+):\s*(.*)"),
        "compatibility-download",
        "Downloading verified legacy support",
    ),
    (
        re.compile(r"SceneLight preflight\s+(\d+)/(\d+):\s*(.*)"),
        "preflight",
        "Testing the game runtime",
    ),
    (
        re.compile(r"SceneLight resolver planned\s+(\d+)\s+canonical forms"),
        "resolver",
        "Resolving dynamic sprite forms",
    ),
    (
        re.compile(r"SceneLight resolver background\s+(\d+)/(\d+)"),
        "resolver-backgrounds",
        "Capturing dynamic backgrounds",
    ),
    (
        re.compile(r"SceneLight story inventory\s+(\d+)/(\d+)"),
        "resolver-inventory",
        "Reading the story",
    ),
    (
        re.compile(r"SceneLight image families\s+(\d+)/(\d+)"),
        "resolver-families",
        "Finding character families",
    ),
    (
        re.compile(r"SceneLight character geometry\s+(\d+)/(\d+)"),
        "resolver-geometry",
        "Checking character artwork",
    ),
    (
        re.compile(r"SceneLight image catalog\s+(\d+)/(\d+)"),
        "resolver-catalog",
        "Building the image catalog",
    ),
    (
        re.compile(r"SceneLight resolver plan\s+(\d+)/(\d+)"),
        "resolver-plan",
        "Planning character appearances",
    ),
    (
        re.compile(r"SceneLight restored\s+(\d+)/(\d+)\s+completed sprite forms"),
        "resolver-restore",
        "Restoring completed sprite captures",
    ),
    (
        re.compile(r"SceneLight resolver resume\s+(\d+)/(\d+)"),
        "resolver-resume",
        "Starting the next safe capture batch",
    ),
    (
        re.compile(r"SceneLight checkpoint scan\s+(\d+)/(\d+)"),
        "resolver-checkpoints",
        "Checking saved sprite captures",
    ),
    (
        re.compile(r"SceneLight capture work\s+(\d+)/(\d+):\s*(.*)"),
        "resolver-work",
        "Saving sprite captures",
    ),
    (
        re.compile(r"SceneLight parallel forms\s+(\d+)/(\d+):\s*(.*)"),
        "resolver-parallel",
        "Processing sprite forms (captures and skips)",
    ),
    (
        re.compile(r"SceneLight worker copies\s+(\d+)/(\d+):\s*(.*)"),
        "resolver-workers",
        "Preparing parallel capture workers",
    ),
    (
        re.compile(r"SceneLight worker cleanup\s+(\d+)/(\d+):\s*(.*)"),
        "resolver-worker-cleanup",
        "Releasing parallel capture workers",
    ),
    (
        re.compile(r"SceneLight worker\s+(\d+)/(\d+):\s*(.*)"),
        "resolver-worker-retry",
        "Retrying a capture worker",
    ),
    (
        re.compile(r"SceneLight resolver form\s+(\d+)/(\d+)"),
        "resolver",
        "Resolving dynamic sprite forms",
    ),
    (
        re.compile(r"transport\s+(\d+)/(\d+):\s*(.*)"),
        "transport",
        "Analyzing background lighting",
    ),
    (
        re.compile(r"scene\s+(\d+)/(\d+):\s*(.*)"),
        "scene",
        "Packing background lighting",
    ),
    (
        re.compile(r"form inventory\s+(\d+)/(\d+):\s*(.*)"),
        "form-inventory",
        "Checking sprite forms",
    ),
    (
        re.compile(r"surface normalization\s+(\d+)/(\d+):\s*(.*)"),
        "surface-normalization",
        "Preparing captured sprite pixels",
    ),
    (
        re.compile(r"surface deduplication\s+(\d+)/(\d+):\s*(.*)"),
        "surface-deduplication",
        "Finding identical sprite captures",
    ),
    (
        re.compile(r"composite assembly\s+(\d+)/(\d+):\s*(.*)"),
        "composite-assembly",
        "Building layered sprite captures",
    ),
    (
        re.compile(r"form\s+(\d+)/(\d+):\s*(.*)"),
        "form",
        "Building unique sprite surface maps",
    ),
)


def parse_progress(line: str) -> ProgressUpdate | None:
    """Extract any long-running SceneLight phase from streamed CLI output."""

    stage = re.search(r"SceneLight stage ([a-z-]+) (\d+)/(\d+):\s*(.*)", line)
    if stage is not None:
        phase, current, total, item = stage.groups()
        if phase not in STAGE_LABELS or (int(total) and int(current) > int(total)):
            return None
        return ProgressUpdate("stage-" + phase, STAGE_LABELS[phase], int(current), int(total), item)
    for pattern, phase, label in _PROGRESS_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        groups = match.groups()
        if phase == "resolver" and len(groups) == 1:
            current, total, item = 0, int(groups[0]), "planning canonical forms"
        else:
            current, total = int(groups[0]), int(groups[1])
            item = groups[2].strip() if len(groups) > 2 else ""
        if total <= 0 or current < 0 or current > total:
            return None
        return ProgressUpdate(phase, label, current, total, item)
    return None


def _component_output_name(value: str) -> str:
    token = Path(value.strip().strip("'\"")).name
    token = re.sub(r"\.(?:whl|zip|tar\.gz|metadata)$", "", token, flags=re.IGNORECASE)
    distribution = re.split(r"-(?=\d)", token, maxsplit=1)[0]
    normalized = distribution.replace("_", "-").lower()
    return COMPONENT_OUTPUT_LABELS.get(normalized, distribution.replace("_", " "))


def parse_component_progress(
    line: str,
    active_download: str = "",
) -> ComponentProgress | None:
    """Turn pip/venv output into concise live installer status."""

    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
    if not clean:
        return None

    download = re.search(
        r"Downloading\s+([^\s(]+)(?:\s+\(([\d.]+)\s*(kB|MB|GB)\))?",
        clean,
        flags=re.IGNORECASE,
    )
    if download is not None:
        name = _component_output_name(download.group(1))
        size = download.group(2)
        unit = download.group(3)
        detail = f" ({size} {unit})" if size and unit else ""
        return ComponentProgress(
            f"Downloading {name}{detail}…",
            0.0 if size else None,
            float(size) if size else None,
            name,
        )

    transfer = re.search(r"([\d.]+)/([\d.]+)\s*(kB|MB|GB)", clean, flags=re.IGNORECASE)
    if transfer is not None:
        current = float(transfer.group(1))
        total = float(transfer.group(2))
        unit = transfer.group(3)
        name = active_download or "components"
        return ComponentProgress(
            f"Downloading {name} — {transfer.group(1)} of {transfer.group(2)} {unit}…",
            current,
            total,
            name,
        )

    collecting = re.search(r"^Collecting\s+([^\s<(=]+)", clean, flags=re.IGNORECASE)
    if collecting is not None:
        name = _component_output_name(collecting.group(1))
        return ComponentProgress(f"Preparing {name}…", active_download=active_download)

    satisfied = re.search(
        r"^Requirement already satisfied:\s+([^\s<(=]+)", clean, flags=re.IGNORECASE
    )
    if satisfied is not None:
        name = _component_output_name(satisfied.group(1))
        return ComponentProgress(f"Verified {name}.", active_download=active_download)

    installing = re.search(r"^Installing collected packages:\s*(.*)", clean, flags=re.IGNORECASE)
    if installing is not None:
        packages = [item.strip() for item in installing.group(1).split(",") if item.strip()]
        count = len(packages)
        noun = "component" if count == 1 else "components"
        return ComponentProgress(
            f"Installing {count} {noun}…",
            92.0,
            100.0,
            active_download,
        )

    if clean.lower().startswith("successfully installed"):
        return ComponentProgress(
            "Components installed. Verifying exact versions…",
            98.0,
            100.0,
            active_download,
        )

    if clean.lower().startswith(("error:", "failed to")):
        return ComponentProgress("Component setup encountered an error.")
    return None


def component_command_status(command: list[str], current: int, total: int) -> str:
    """Describe a component setup subprocess without exposing its command line."""

    lowered = [item.lower() for item in command]
    if lowered[1:3] == ["-m", "venv"]:
        return f"Step {current} of {total}: Creating the SceneLight runtime…"
    if "pip" in lowered and all(item in command for item in PACKAGING_REQUIREMENTS):
        return f"Step {current} of {total}: Preparing the component installer…"
    return f"Step {current} of {total}: Downloading and installing SceneLight components…"


def operation_copy(operation: str) -> tuple[str, str, str]:
    """Return the title, explanation, and initial status for a live operation."""

    copies = {
        "components": (
            "Setting up SceneLight",
            "Download and installation progress appears below.",
            "Starting SceneLight component setup…",
        ),
        "compatibility": (
            "Preparing legacy game support",
            "Download and setup progress appears below.",
            "Starting the Ren'Py support download…",
        ),
        "scan": (
            "Scanning this game",
            "Checking its files without changing them.",
            "Reading game files…",
        ),
        "attach": (
            "Installing SceneLight",
            "Scan and installation progress appears below.",
            "Preparing an in-place installation…",
        ),
        "install": (
            "Creating a SceneLight copy",
            "Copy, scan, and installation progress appears below.",
            "Preparing a separate game copy…",
        ),
        "embed": (
            "Installing the developer API",
            "Scan and installation progress appears below.",
            "Preparing the SceneLight developer runtime…",
        ),
        "refresh": (
            "Updating SceneLight",
            "Checking the project and updating changed assets.",
            "Checking the current installation…",
        ),
        "verify": (
            "Verifying SceneLight",
            "Checking the installed SceneLight files.",
            "Verifying the installation…",
        ),
        "inspector": (
            "Applying inspector setting",
            "Adding or removing the optional in-game tool. Existing analysis is kept.",
            "Applying the inspector choice…",
        ),
        "remove": (
            "Removing SceneLight",
            "Checking the SceneLight copy before removing it.",
            "Checking the SceneLight copy…",
        ),
        "unembed": (
            "Removing the developer API",
            "Checking the SceneLight files before removing them.",
            "Checking the developer installation…",
        ),
        "launch": (
            "Starting the game",
            "Opening the game's normal executable.",
            "Starting the game…",
        ),
    }
    return copies.get(
        operation,
        (
            "SceneLight is working",
            "Live progress is reported below.",
            "Starting the requested operation…",
        ),
    )


def parse_runtime_progress(line: str) -> tuple[int, int] | None:
    """Extract dynamic-asset progress emitted by the Ren'Py resolver."""

    progress = parse_progress(line)
    if progress is None or progress.phase != "resolver":
        return None
    return progress.current, progress.total


def format_duration(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds_value:02d}s"
    return f"{seconds_value}s"


def format_progress_status(
    progress: ProgressUpdate,
    *,
    elapsed_seconds: float,
    completed_since_start: int,
) -> str:
    """Format progress with elapsed time and an estimated time remaining."""

    if progress.total == 0:
        count = f" — {progress.current:,} files processed" if progress.current else ""
        parts = [progress.label + count, f"elapsed {format_duration(elapsed_seconds)}"]
        if progress.item:
            parts.append(progress.item[:100])
        return "  •  ".join(parts)
    percent = 100.0 * progress.current / progress.total
    parts = [
        f"{progress.label} — {progress.current:,} of {progress.total:,} ({percent:.1f}%)",
        f"elapsed {format_duration(elapsed_seconds)}",
    ]
    if progress.current < progress.total:
        if elapsed_seconds >= 0.5 and completed_since_start > 0:
            remaining = progress.total - progress.current
            eta = remaining * elapsed_seconds / completed_since_start
            parts.append(f"about {format_duration(eta)} left")
        else:
            parts.append("estimating time remaining")
    if progress.phase.startswith("stage-") and progress.item and progress.item != "Complete":
        parts.append(progress.item[:100])
    return "  •  ".join(parts)


def progress_moves_forward(
    progress: ProgressUpdate,
    *,
    previous_phase: str | None,
    previous_current: int,
    previous_total: int,
) -> bool:
    """Reject only a repeated backend's catch-up updates for the same plan."""

    return (
        progress.phase != previous_phase
        or progress.total != previous_total
        or progress.current >= previous_current
    )


def describe_scan(payload: dict[str, object]) -> str:
    scenes = payload.get("scenes", {})
    sprites = payload.get("sprites", {})
    tags = payload.get("character_tags", [])
    unsupported = payload.get("unsupported", [])
    runtime = bool(payload.get("requires_runtime_inventory"))
    preflight = bool(payload.get("runtime_preflight"))
    return (
        f"Found {len(scenes) if isinstance(scenes, dict) else 0} background(s), "
        f"{len(sprites) if isinstance(sprites, dict) else 0} static sprite expression(s), "
        f"and {len(tags) if isinstance(tags, list) else 0} character tag(s). "
        f"Runtime discovery: {'needed' if runtime else 'not needed'}. "
        f"Renderer preflight: {'passed' if preflight else 'not available'}. "
        f"Review items: {len(unsupported) if isinstance(unsupported, list) else 0}."
    )


def character_review_candidates(payload: dict[str, object]) -> dict[str, str | None]:
    """Decode scan candidates without trusting arbitrary payload types."""

    raw = payload.get("character_candidates", {})
    if not isinstance(raw, dict):
        return {}
    candidates: dict[str, str | None] = {}
    for raw_tag, raw_preview in raw.items():
        parts = str(raw_tag).strip().lower().split()
        if not parts or not re.fullmatch(r"[a-z0-9_]+", parts[0]):
            continue
        tag = parts[0]
        candidates[tag] = str(raw_preview) if isinstance(raw_preview, str) else None
    return dict(sorted(candidates.items()))


def character_review_mode(payload: dict[str, object]) -> str:
    """Keep existing choices; new installations include detected characters."""

    auto_include = payload.get("auto_include_new_characters")
    if isinstance(auto_include, bool):
        return "automatic" if auto_include else "manual"
    mode = payload.get("character_selection")
    if isinstance(mode, str) and mode in {"manual", "automatic"}:
        return mode
    return "automatic" if mode is None else "manual"


def character_review_selected_tags(payload: dict[str, object]) -> set[str]:
    """Use one selection rule for visible checks and persisted update policy."""

    def tags(key: str) -> set[str]:
        values = payload.get(key, [])
        return (
            {str(value).strip().lower() for value in values} if isinstance(values, list) else set()
        )

    chosen = tags("explicit_character_tags")
    if character_review_mode(payload) == "automatic":
        chosen.update(tags("suggested_character_tags") | tags("character_tags"))
    return chosen - tags("excluded_character_tags")


def character_review_required(
    payload: dict[str, object], *, installed: bool, force: bool = False
) -> bool:
    """Require deliberate review for first install or newly suggested families."""

    if force or not installed:
        return True
    if character_review_mode(payload) == "automatic":
        return False
    explicit = payload.get("explicit_character_tags", [])
    suggested = payload.get("suggested_character_tags", payload.get("character_tags", []))
    explicit_tags = (
        {str(tag).strip().lower() for tag in explicit if isinstance(tag, str) and str(tag).strip()}
        if isinstance(explicit, list)
        else set()
    )
    suggested_tags = (
        {str(tag).strip().lower() for tag in suggested if isinstance(tag, str) and str(tag).strip()}
        if isinstance(suggested, list)
        else set()
    )
    excluded = payload.get("excluded_character_tags", [])
    excluded_tags = set(excluded) if isinstance(excluded, list) else set()
    return bool(suggested_tags - explicit_tags - excluded_tags)


def thumbnail_subsample_factor(width: int, height: int, limit: int = 72) -> int:
    """Return an integer Tk subsample factor that fits inside ``limit`` pixels."""

    if limit <= 0:
        raise ValueError("Thumbnail limit must be positive.")
    return max(1, (max(1, width) + limit - 1) // limit, (max(1, height) + limit - 1) // limit)


def save_character_selection(
    project_root: Path,
    mode: str,
    tags: list[str],
    *,
    candidates: list[str] | None = None,
) -> Path:
    """Save an authoritative per-user selection outside the chosen game."""

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"manual", "automatic"}:
        raise ValueError("Character selection mode must be manual or automatic")
    normalized_tags: list[str] = []
    for raw in tags:
        parts = raw.strip().lower().split()
        if parts and re.fullmatch(r"[a-z0-9_]+", parts[0]):
            normalized_tags.append(parts[0])
    normalized_tags = sorted(set(normalized_tags))
    destination = profile_path(project_root)
    payload: dict[str, object] = {}
    project_config = project_root / "scenelight.json"
    if project_config.is_file():
        configured = json.loads(project_config.read_text(encoding="utf-8"))
        if isinstance(configured, dict) and "excluded_character_tags" in configured:
            payload["excluded_character_tags"] = configured["excluded_character_tags"]
    if destination.is_file():
        loaded = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("The existing SceneLight profile is not a JSON object")
        payload.update(loaded)
    payload["character_selection"] = normalized_mode
    payload["auto_include_new_characters"] = normalized_mode == "automatic"
    payload["character_tags"] = normalized_tags
    prior_exclusions = payload.get("excluded_character_tags", [])
    prior_exclusions = prior_exclusions if isinstance(prior_exclusions, list) else []
    excluded = set()
    for value in [*prior_exclusions, *(candidates or [])]:
        parts = str(value).strip().lower().split()
        if parts and re.fullmatch(r"[a-z0-9_]+", parts[0]):
            excluded.add(parts[0])
    excluded.difference_update(normalized_tags)
    payload["excluded_character_tags"] = sorted(excluded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def installed_managed_launcher(project_root: Path) -> Path | None:
    """Return a launcher only for a completed managed install, never a scan sidecar."""

    managed_root = managed_project_root(project_root)
    if not (managed_root / ".scenelight_install.json").is_file():
        return None
    native = find_native_executable(managed_root)
    if native is not None:
        return native
    sdk_launcher = managed_root / "Launch with SceneLight.bat"
    return sdk_launcher.resolve() if sdk_launcher.is_file() else None


def installed_direct_launch_command(project_root: Path) -> tuple[str, ...] | None:
    """Return the verified playback command recorded for an in-place install.

    Source-only Ren'Py projects often have no bundled executable. SceneLight's
    install report records the compatible SDK used for capture and playback, so
    Setup can launch that project without guessing at unrelated batch files.
    """

    root = project_root.expanduser().resolve()
    native = find_native_executable(root)
    if native is not None:
        return (str(native),)
    report_path = root / "game" / "scenelight_runtime" / "install_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(report, dict):
        return None
    playback_value = report.get("playback_executable")
    if not playback_value:
        return None
    playback = Path(str(playback_value)).expanduser().resolve()
    if not playback.is_file():
        return None
    native_runtime = bool(report.get("playback_native", False))
    return tuple(renpy_runtime_command(playback, root, native_runtime=native_runtime))


def installed_managed_release(project_root: Path) -> tuple[str | None, str | None]:
    """Return product/build identity, treating missing fields as pre-1.0."""

    path = managed_project_root(project_root) / ".scenelight_install.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(
            f"SceneLight could not read the existing installation: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("SceneLight found an invalid existing installation record.")
    return (
        release_version_from_manifest(payload),
        release_content_sha256_from_manifest(payload),
    )


def installed_managed_version(project_root: Path) -> str | None:
    return installed_managed_release(project_root)[0]


def inspect_project_installation(value: str | os.PathLike[str]) -> ProjectInspection:
    """Inspect a project and any prior SceneLight install without changing it."""

    try:
        selection = inspect_project_path(value)
    except (OSError, RuntimeError, ValueError) as caught:
        return ProjectInspection(
            ProjectSelection(None, False, f"That project could not be inspected: {caught}"),
            error=str(caught),
        )
    if not selection.valid or selection.root is None:
        return ProjectInspection(selection)

    project_root = selection.root
    try:
        reserved_namespace = (project_root / "game" / "scenelight_runtime").exists()
        managed_root = managed_project_root(project_root)
        managed_install_present = (managed_root / ".scenelight_install.json").is_file()
        managed_launcher = installed_managed_launcher(project_root)
        direct_launch_command = installed_direct_launch_command(project_root)
        managed_version, managed_content_sha256 = (
            installed_managed_release(project_root) if managed_install_present else (None, None)
        )
    except (OSError, RuntimeError, ValueError) as caught:
        return ProjectInspection(selection, error=str(caught))
    try:
        snapshot = source_metadata(project_root)
        managed_refresh = False
        if managed_install_present:
            manifest = json.loads(
                (managed_root / ".scenelight_install.json").read_text(encoding="utf-8")
            )
            previous = manifest.get("source_state")
            if isinstance(previous, dict):
                managed_refresh = {
                    name: tuple(value[:2]) for name, value in previous.items()
                } != snapshot
    except (OSError, TypeError, ValueError) as caught:
        return ProjectInspection(selection, error=str(caught))
    status: DeveloperStatus | None = None
    error: str | None = None
    try:
        status = developer_status(project_root)
    except (OSError, RuntimeError, ValueError) as caught:
        error = str(caught)
    return ProjectInspection(
        selection=selection,
        source_metadata=snapshot,
        managed_refresh_required=managed_refresh,
        developer_status=status,
        managed_install_present=managed_install_present,
        managed_launcher=managed_launcher,
        direct_launch_command=direct_launch_command,
        managed_version=managed_version,
        managed_content_sha256=managed_content_sha256,
        reserved_namespace_present=reserved_namespace,
        error=error,
    )


def build_cli_command(
    operation: str,
    project: Path,
    *,
    renpy_sdk: Path | None = None,
    analyzer: str = "auto",
    frozen: bool | None = None,
    executable: Path | None = None,
    sdk_launcher: Path = SDK_LAUNCHER,
) -> list[str]:
    """Build a shell-free command for the source or packaged setup app."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    program = Path(executable or sys.executable)
    if is_frozen:
        command = [str(program), "--cli", operation, "--project", str(project)]
    elif sdk_launcher.is_file():
        command = [str(program), str(sdk_launcher), operation, "--project", str(project)]
    else:
        command = [str(program), "-m", "scenelight.cli", operation, "--project", str(project)]
    if operation == "scan":
        command.append("--runtime-review")
        if renpy_sdk is not None:
            command.extend(("--renpy-sdk", str(renpy_sdk)))
    if operation in {"install", "attach", "embed", "refresh"}:
        command.extend(("--analyzer", analyzer))
        if renpy_sdk is not None:
            command.extend(("--renpy-sdk", str(renpy_sdk)))
    return command


class SceneLightSetup(tk.Tk):
    """A compact setup front end for local Ren'Py projects."""

    def __init__(self, initial_project: str | None = None, *, developer_mode: bool = False) -> None:
        set_process_identity()
        super().__init__()
        diagnostics.start_session("setup", operation="startup", project=initial_project or "")
        self.developer_mode = developer_mode
        self.title(f"SceneLight {__version__}")
        self.geometry("780x540")
        self.minsize(620, 440)
        self.resizable(True, True)
        self.configure(background="#080a0d")

        self.project_var = tk.StringVar(value=initial_project or "")
        self.sdk_var = tk.StringVar()
        self.cuda_var = tk.BooleanVar(value=False)
        self.inspector_var = tk.BooleanVar(value=True)
        self.inspector_detail_var = tk.StringVar(
            value="Choose a project to configure its in-game inspector."
        )
        self._inspector_selection_key = None
        self._cuda_support: CudaSupport | None = None
        self._cuda_user_choice = False
        self._cuda_probe_generation = 0
        self._applying_cuda_default = False
        self._cuda_apply_when_idle = False
        self.cuda_detail_var = tk.StringVar(
            value="Checking this computer for optional CUDA acceleration…"
        )
        self.status_var = tk.StringVar(value="Choose a Ren'Py project to begin.")
        self.preview_var = tk.StringVar(value="Nothing has been scanned or changed.")
        self.operation_var = tk.StringVar(value="Ready")
        self.runtime_status_var = tk.StringVar(value="Checking SceneLight runtime…")
        self.dependencies_status_var = tk.StringVar(value="Checking component versions…")
        self.dependency_detail_var = tk.StringVar(value="")
        self.gpu_status_var = tk.StringVar(value="Checking available acceleration…")
        self.requirements_var = tk.StringVar(value="Checking components…")
        self.installation_var = tk.StringVar(value="No existing SceneLight installation found.")
        self.workflow_title_var = tk.StringVar(
            value="Choose your mod project" if developer_mode else "Choose your game"
        )
        self.workflow_subtitle_var = tk.StringVar(
            value=(
                "Install the SceneLight runtime and author API into a Ren'Py project."
                if developer_mode
                else "Select a Ren'Py game or mod folder to get started."
            )
        )
        self.project_name_var = tk.StringVar(value="No game selected")
        self.project_path_var = tk.StringVar(value="Choose a folder to continue")
        self._events: queue.Queue[tuple[object, ...]] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()
        self._running = False
        self._active_operation: str | None = None
        self._update_reason = ""
        self._component_download = ""
        self._continue_after_components = False
        self._scan_ok = False
        self._review_completed_for: Path | None = None
        self._character_review_pending_for: Path | None = None
        self._force_character_review = False
        self._last_scan_payload: dict[str, object] = {}
        self._attached = False
        self._last_launcher: Path | None = None
        self._project_inspection: ProjectInspection | None = None
        self._project_inspection_value = ""
        self._project_checking = False
        self._project_generation = 0
        self._source_watch = ProjectWatch()
        self._watch_busy = False
        self._progress_phase: str | None = None
        self._progress_started_at = 0.0
        self._progress_origin = 0
        self._progress_current = 0
        self._progress_total = 0
        self._latest_progress = None
        self._progress_indeterminate = False
        self._last_elapsed_refresh = 0.0
        self._dependency_state: DependencyState | None = None
        self._dependency_key: tuple[object, ...] | None = None
        self._options_window: tk.Toplevel | None = None
        self._developer_guide_window: tk.Toplevel | None = None
        self._options_notebook: ttk.Notebook | None = None
        self._system_tab: ttk.Frame | None = None
        self._advanced_tab: ttk.Frame | None = None
        self._activity_tab: ttk.Frame | None = None
        self._character_review_window: tk.Toplevel | None = None
        self.mode_button: ttk.Button | None = None
        self.step_labels: list[tk.Label] = []
        self._icon_images: list[tk.PhotoImage] = []
        self._log_lines: deque[str] = deque(maxlen=1500)
        self.log: tk.Text | None = None
        self._destroying = False

        self.sdk_entry: ttk.Entry | None = None
        self.sdk_browse: ttk.Button | None = None
        self.cuda_check: ttk.Checkbutton | None = None
        self.inspector_check: ttk.Checkbutton | None = None
        self.inspector_apply: ttk.Button | None = None
        self.components_button: ttk.Button | None = None
        self.advanced_components_button: ttk.Button | None = None
        self.verify_button: ttk.Button | None = None
        self.open_button: ttk.Button | None = None
        self.preview_button: ttk.Button | None = None
        self.review_button: ttk.Button | None = None
        self.characters_button: ttk.Button | None = None
        self.remove_button: ttk.Button | None = None
        self.embed_button: ttk.Button | None = None
        self.unembed_button: ttk.Button | None = None
        self.requirements_list_frame: tk.Frame | None = None
        self.requirements_canvas: tk.Canvas | None = None
        self.manage_button: ttk.Button | None = None
        self.cancel_operation_button: ttk.Button | None = None

        self._apply_window_icon(self)
        self.after(50, lambda: self._apply_dark_titlebar(self))
        self.after(350, lambda: self._apply_dark_titlebar(self))
        self._configure_styles()
        self._build_window()
        self.after_idle(lambda: self._fit_to_screen(self, 780, 540))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._drain_events)
        self.project_var.trace_add("write", self._project_changed)
        self.cuda_var.trace_add("write", self._cuda_changed)
        self._refresh_dependency_display()
        self._project_changed()
        self.after(self._dependency_poll_delay(), self._poll_dependency_state)
        self._begin_cuda_detection()
        self.after(5_000, self._poll_project_sources)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", background="#080a0d", foreground="#f2f4f7", font=("Segoe UI", 10))
        style.configure("Page.TFrame", background="#080a0d")
        style.configure("Card.TFrame", background="#12161c", relief="flat")
        style.configure("Inner.TFrame", background="#181d24", relief="flat")
        style.configure(
            "CardTitle.TLabel",
            background="#12161c",
            foreground="#f7f8fa",
            font=("Segoe UI Semibold", 16),
        )
        style.configure(
            "Eyebrow.TLabel",
            background="#12161c",
            foreground="#6fc8f4",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "Body.TLabel", background="#12161c", foreground="#aab3bf", font=("Segoe UI", 10)
        )
        style.configure(
            "BrightBody.TLabel",
            background="#12161c",
            foreground="#e7ebef",
            font=("Segoe UI", 10),
        )
        style.configure(
            "FlowBody.TLabel",
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background="#181d24",
            foreground="#dce5ee",
            padding=(0, 0),
            font=("Segoe UI", 9),
        )
        style.configure(
            "Trust.TLabel",
            background="#101b18",
            foreground="#85d9b3",
            padding=(10, 8),
            font=("Segoe UI", 9),
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(18, 11),
            background="#70caf2",
            foreground="#080a0d",
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#95dcfb"), ("disabled", "#2a3038")],
            foreground=[("disabled", "#737c87")],
        )
        style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 9),
            padding=(12, 9),
            background="#20262e",
            foreground="#e9edf2",
            borderwidth=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#303844"), ("disabled", "#171b21")],
            foreground=[("disabled", "#626b76")],
        )
        style.configure(
            "Quiet.TButton",
            font=("Segoe UI", 9),
            padding=(10, 6),
            background="#0d1014",
            foreground="#8d99a6",
            borderwidth=0,
        )
        style.map(
            "Quiet.TButton",
            background=[("active", "#171d24")],
            foreground=[("active", "#e8edf2")],
        )
        style.configure(
            "Cancel.TButton",
            font=("Segoe UI Semibold", 9),
            padding=(12, 7),
            background="#3a2023",
            foreground="#f5c8c8",
            borderwidth=0,
        )
        style.map(
            "Cancel.TButton",
            background=[("active", "#553034"), ("disabled", "#211719")],
            foreground=[("disabled", "#765e60")],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            background="#303844",
            troughcolor="#12161c",
            bordercolor="#12161c",
            arrowcolor="#dce5ee",
            lightcolor="#303844",
            darkcolor="#303844",
        )
        style.configure(
            "Dark.TEntry",
            fieldbackground="#090c10",
            foreground="#f2f4f7",
            insertcolor="#ffffff",
            bordercolor="#303741",
            lightcolor="#303741",
            darkcolor="#303741",
            padding=7,
        )
        style.configure(
            "Dark.TCheckbutton",
            background="#12161c",
            foreground="#d5dbe2",
            indicatorbackground="#090c10",
            indicatorforeground="#70caf2",
        )
        style.map("Dark.TCheckbutton", background=[("active", "#12161c")])
        style.configure(
            "Scene.Horizontal.TProgressbar",
            background="#70caf2",
            troughcolor="#20262e",
            bordercolor="#20262e",
            lightcolor="#70caf2",
            darkcolor="#70caf2",
        )
        style.configure(
            "Scene.TNotebook",
            background="#080a0d",
            borderwidth=0,
            bordercolor="#252c35",
            lightcolor="#252c35",
            darkcolor="#252c35",
        )
        style.configure(
            "Scene.TNotebook.Tab",
            background="#151a21",
            foreground="#aab3bf",
            padding=(13, 8),
            borderwidth=0,
            bordercolor="#252c35",
            lightcolor="#252c35",
            darkcolor="#252c35",
        )
        style.map(
            "Scene.TNotebook.Tab",
            background=[("selected", "#242c36")],
            foreground=[("selected", "#f4f7fa")],
        )
        self._control_images = soft_controls(self, style)

    def _apply_window_icon(self, window: tk.Misc) -> None:
        try:
            if sys.platform == "win32" and ICON_PATH.is_file():
                top = window.winfo_toplevel()
                top.iconbitmap(str(ICON_PATH))
                top.iconbitmap(default=str(ICON_PATH))
            elif ICON_PNG.is_file():
                if not hasattr(self, "_app_icon"):
                    self._app_icon = tk.PhotoImage(master=self, file=str(ICON_PNG))
                window.winfo_toplevel().iconphoto(True, self._app_icon)
        except tk.TclError:
            pass

    @staticmethod
    def _apply_dark_titlebar(window: tk.Misc) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            window.update_idletasks()
            widget_handle = window.winfo_id()
            parent_handle = ctypes.windll.user32.GetParent(widget_handle)
            enabled = ctypes.c_int(1)
            build = sys.getwindowsversion().build
            attribute = 20 if build >= 22000 else 19
            for handle in {widget_handle, parent_handle} - {0}:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    handle,
                    attribute,
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled),
                )
        except (AttributeError, OSError, tk.TclError):
            pass

    @staticmethod
    def _fit_to_screen(window: tk.Misc, preferred_width: int, preferred_height: int) -> None:
        """Fit and center a window inside the current display's usable bounds."""
        try:
            window.update_idletasks()
            margin = 48
            available_width = max(360, window.winfo_screenwidth() - margin)
            available_height = max(280, window.winfo_screenheight() - margin)
            width = min(preferred_width, available_width)
            height = min(preferred_height, available_height)
            x = max(0, (window.winfo_screenwidth() - width) // 2)
            y = max(0, (window.winfo_screenheight() - height) // 2)
            window.winfo_toplevel().geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            pass

    def _build_window(self) -> None:
        shell = tk.Frame(self, background="#080a0d")
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        flow = tk.Frame(shell, background="#0d1014", padx=48, pady=20)
        flow.grid(row=0, column=0, sticky="nsew")
        flow.grid_columnconfigure(0, weight=1)

        top_row = tk.Frame(flow, background="#0d1014")
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)
        tk.Label(
            top_row,
            text=f"SceneLight v{__version__}",
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.mode_button = ttk.Button(
            top_row,
            text="For players" if self.developer_mode else "For mod developers",
            command=self._toggle_developer_mode,
            style="Quiet.TButton",
        )
        self.mode_button.grid(row=0, column=1, sticky="e", padx=(0, 14))
        self.more_button = ttk.Button(
            top_row, text="Settings", command=self._show_options, style="Quiet.TButton"
        )
        self.more_button.grid(row=0, column=2, sticky="e")

        tk.Label(
            flow,
            textvariable=self.workflow_title_var,
            background="#0d1014",
            foreground="#f7f9fb",
            font=("Segoe UI Semibold", 22),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 3))
        tk.Label(
            flow,
            textvariable=self.workflow_subtitle_var,
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=660,
        ).grid(row=2, column=0, sticky="ew")

        steps = tk.Frame(
            flow,
            background="#10151b",
            highlightbackground="#202832",
            highlightthickness=1,
            padx=12,
            pady=6,
        )
        steps.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for column, text in enumerate(("1  Choose", "2  Scan", "3  Review", "4  Install")):
            steps.grid_columnconfigure(column, weight=1, uniform="steps")
            label = tk.Label(
                steps,
                text=text,
                background="#10151b",
                foreground="#66727f",
                font=("Segoe UI Semibold", 9),
            )
            label.grid(row=0, column=column, sticky="ew", padx=4)
            self.step_labels.append(label)

        selection = tk.Frame(
            flow,
            background="#141a20",
            highlightbackground="#242d36",
            highlightthickness=1,
            padx=16,
            pady=10,
        )
        selection.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        selection.grid_columnconfigure(0, weight=1)
        tk.Label(
            selection,
            textvariable=self.project_name_var,
            background="#141a20",
            foreground="#f2f5f8",
            font=("Segoe UI Semibold", 11),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.project_path_label = tk.Label(
            selection,
            textvariable=self.project_path_var,
            background="#141a20",
            foreground="#7f8a96",
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=350,
        )
        self.project_path_label.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.project_browse = ttk.Button(
            selection,
            text="Browse…",
            command=self._browse_project,
            style="Secondary.TButton",
        )
        self.project_browse.grid(row=0, column=1, rowspan=2, padx=(14, 0))
        self.characters_button = ttk.Button(
            selection,
            text="Characters…",
            command=self._review_characters,
            style="Secondary.TButton",
        )
        self.characters_button.grid(row=0, column=2, rowspan=2, padx=(8, 0))

        self.project_status = tk.Label(
            flow,
            textvariable=self.status_var,
            background="#0d1014",
            foreground="#7f8a96",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.project_status.grid(row=5, column=0, sticky="ew", pady=(6, 0))

        self.state_row = tk.Frame(flow, background="#0d1014")
        self.state_row.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.state_row.grid_columnconfigure(1, weight=1)
        self.state_dot = tk.Canvas(
            self.state_row,
            width=12,
            height=12,
            background="#0d1014",
            highlightthickness=0,
        )
        self.state_dot.grid(row=0, column=0, sticky="w", padx=(1, 8))
        self.state_dot.create_oval(2, 2, 10, 10, fill="#7f8a96", outline="", tags="dot")
        self.requirements_label = tk.Label(
            self.state_row,
            textvariable=self.requirements_var,
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI", 9),
        )
        self.requirements_label.grid(row=0, column=1, sticky="w")

        self.installation_status = tk.Label(
            flow,
            textvariable=self.installation_var,
            background="#0d1014",
            foreground="#7f8a96",
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=620,
        )
        self.installation_status.grid(row=7, column=0, sticky="ew", pady=(4, 0))

        self.primary_button = ttk.Button(
            flow,
            text="Choose a game or mod",
            command=self._run_primary_action,
            style="Primary.TButton",
        )
        self.primary_button.grid(row=8, column=0, sticky="ew", pady=(9, 0))

        self.install_choice_frame = tk.Frame(flow, background="#0d1014")
        self.install_choice_frame.grid(row=8, column=0, sticky="ew", pady=(14, 0))
        for column in (0, 1):
            self.install_choice_frame.grid_columnconfigure(column, weight=1, uniform="install")
        self.attach_button = ttk.Button(
            self.install_choice_frame,
            text="Add to this game",
            command=self._attach,
            style="Primary.TButton",
        )
        self.attach_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.copy_button = ttk.Button(
            self.install_choice_frame,
            text="Create separate copy",
            command=self._install,
            style="Secondary.TButton",
        )
        self.copy_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.install_choice_frame.grid_remove()

        self.manage_button = ttk.Button(
            flow,
            text="Manage existing installation",
            command=lambda: self._show_options(tab="tools"),
            style="Quiet.TButton",
        )
        self.manage_button.grid(row=9, column=0, sticky="w", pady=(7, 0))
        self.manage_button.grid_remove()

        self.progress_frame = tk.Frame(flow, background="#0d1014")
        self.progress_frame.grid(row=10, column=0, sticky="ew", pady=(9, 0))
        self.progress_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            self.progress_frame, mode="indeterminate", style="Scene.Horizontal.TProgressbar"
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        self.cancel_operation_button = ttk.Button(
            self.progress_frame,
            text="Cancel",
            command=self._cancel_operation,
            style="Cancel.TButton",
        )
        self.cancel_operation_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ttk.Label(
            self.progress_frame,
            textvariable=self.operation_var,
            style="FlowBody.TLabel",
            wraplength=440,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))
        self.progress_frame.grid_remove()
        flow.bind(
            "<Configure>",
            lambda event: self.project_path_label.configure(wraplength=max(220, event.width - 190)),
        )

    def _toggle_advanced(self) -> None:
        self._show_options(tab="advanced")

    def _set_log_visible(self, visible: bool) -> None:
        if visible:
            self._show_options(tab="activity")

    def _toggle_log(self) -> None:
        self._show_options(tab="activity")

    def _show_options(self, tab: str = "tools") -> None:
        if self._options_window is None or not self._options_window.winfo_exists():
            window = tk.Toplevel(self)
            self._options_window = window
            window.title("SceneLight options")
            window.geometry("760x600")
            window.minsize(620, 480)
            window.resizable(True, True)
            window.configure(background="#080a0d")
            self._apply_window_icon(window)
            window.after(50, lambda: self._apply_dark_titlebar(window))
            window.after(350, lambda: self._apply_dark_titlebar(window))
            window.after_idle(lambda: self._fit_to_screen(window, 760, 600))
            notebook = ttk.Notebook(window, style="Scene.TNotebook")
            notebook.pack(fill="both", expand=True, padx=14, pady=14)
            self._options_notebook = notebook

            tools_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
            tools_tab.columnconfigure(0, weight=1)
            notebook.add(tools_tab, text="Tools")
            ttk.Label(tools_tab, text="Optional tools", style="CardTitle.TLabel").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
            )
            ttk.Label(
                tools_tab,
                textvariable=self.installation_var,
                style="Body.TLabel",
                wraplength=640,
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))
            self.preview_button = ttk.Button(
                tools_tab,
                text="Open Preview & Calibrator",
                command=self._open_preview,
                style="Primary.TButton",
            )
            self.preview_button.grid(row=2, column=0, columnspan=2, sticky="ew")
            self.review_button = ttk.Button(
                tools_tab,
                text="Review character families",
                command=self._review_characters,
                style="Secondary.TButton",
            )
            self.review_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
            self.verify_button = ttk.Button(
                tools_tab,
                text="Verify SceneLight copy",
                command=self._verify,
                style="Secondary.TButton",
            )
            self.verify_button.grid(row=4, column=0, sticky="ew", pady=(10, 0), padx=(0, 5))
            self.open_button = ttk.Button(
                tools_tab,
                text="Open original folder",
                command=self._open_project,
                style="Secondary.TButton",
            )
            self.open_button.grid(row=4, column=1, sticky="ew", pady=(10, 0), padx=(5, 0))
            self.remove_button = ttk.Button(
                tools_tab,
                text="Remove SceneLight copy",
                command=self._remove_current,
                style="Secondary.TButton",
            )
            self.remove_button.grid(row=5, column=0, columnspan=2, sticky="w", pady=(18, 0))

            system_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
            system_tab.columnconfigure(0, weight=1)
            self._system_tab = system_tab
            notebook.add(system_tab, text="System")
            ttk.Label(system_tab, text="System details", style="CardTitle.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, 12)
            )
            for row, variable in enumerate(
                (self.runtime_status_var, self.dependencies_status_var, self.gpu_status_var),
                start=1,
            ):
                ttk.Label(
                    system_tab, textvariable=variable, style="BrightBody.TLabel", wraplength=620
                ).grid(row=row, column=0, sticky="w", pady=(0, 7))
            ttk.Label(
                system_tab,
                textvariable=self.dependency_detail_var,
                style="Body.TLabel",
                wraplength=620,
                justify="left",
            ).grid(row=4, column=0, sticky="ew", pady=(6, 12))
            self.components_button = ttk.Button(
                system_tab,
                text="Install components",
                command=self._install_components,
                style="Primary.TButton",
            )
            self.components_button.grid(row=5, column=0, sticky="w")

            advanced_tab = ttk.Frame(notebook, style="Card.TFrame", padding=12)
            advanced_tab.columnconfigure(1, weight=1)
            advanced_tab.rowconfigure(7, weight=1)
            self._advanced_tab = advanced_tab
            notebook.add(advanced_tab, text="Advanced")
            ttk.Label(advanced_tab, text="Analysis & compatibility", style="CardTitle.TLabel").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
            )
            self.developer_guide_button = ttk.Button(
                advanced_tab,
                text="Developer guide",
                command=self._show_developer_guide,
                style="Secondary.TButton",
            )
            self.developer_guide_button.grid(row=0, column=2, sticky="e", pady=(0, 6))
            self.cuda_check = ttk.Checkbutton(
                advanced_tab,
                text="Use the detected NVIDIA GPU to speed up first-time analysis",
                variable=self.cuda_var,
                style="Dark.TCheckbutton",
            )
            self.cuda_check.grid(row=1, column=0, columnspan=3, sticky="w")
            ttk.Label(
                advanced_tab,
                textvariable=self.cuda_detail_var,
                style="Body.TLabel",
                wraplength=660,
                justify="left",
            ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(3, 0))
            ttk.Label(advanced_tab, text="Ren'Py SDK (optional)", style="Body.TLabel").grid(
                row=3, column=0, sticky="w", pady=(8, 0)
            )
            self.sdk_entry = ttk.Entry(advanced_tab, textvariable=self.sdk_var, style="Dark.TEntry")
            self.sdk_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=(8, 0))
            self.sdk_browse = ttk.Button(
                advanced_tab, text="Browse…", command=self._browse_sdk, style="Secondary.TButton"
            )
            self.sdk_browse.grid(row=3, column=2, pady=(8, 0))
            ttk.Separator(advanced_tab, orient="horizontal").grid(
                row=4, column=0, columnspan=3, sticky="ew", pady=(12, 9)
            )
            inspector_card = ttk.Frame(advanced_tab, style="Card.TFrame")
            inspector_card.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 12))
            inspector_card.columnconfigure(0, weight=1)
            self.inspector_check = ttk.Checkbutton(
                inspector_card,
                text="Include in-game inspector · Shift+F9",
                variable=self.inspector_var,
                style="Dark.TCheckbutton",
            )
            self.inspector_check.grid(row=0, column=0, sticky="w")
            self.inspector_apply = ttk.Button(
                inspector_card,
                text="Apply to project",
                command=self._apply_inspector_option,
                style="Secondary.TButton",
            )
            self.inspector_apply.grid(row=0, column=1, padx=(12, 0))
            ttk.Label(
                inspector_card,
                textvariable=self.inspector_detail_var,
                style="Body.TLabel",
                wraplength=650,
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
            ttk.Label(
                advanced_tab,
                text="Required components · individually verified",
                style="CardTitle.TLabel",
            ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 5))
            requirements_view = tk.Frame(advanced_tab, background="#12161c")
            requirements_view.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(0, 6))
            requirements_view.grid_columnconfigure(0, weight=1)
            requirements_view.grid_rowconfigure(0, weight=1)
            self.requirements_canvas = tk.Canvas(
                requirements_view,
                background="#12161c",
                highlightthickness=0,
                height=118,
            )
            requirements_scrollbar = ttk.Scrollbar(
                requirements_view,
                orient="vertical",
                command=self.requirements_canvas.yview,
                style="Dark.Vertical.TScrollbar",
            )
            self.requirements_canvas.configure(yscrollcommand=requirements_scrollbar.set)
            self.requirements_canvas.grid(row=0, column=0, sticky="nsew")
            requirements_scrollbar.grid(row=0, column=1, sticky="ns")
            self.requirements_list_frame = tk.Frame(self.requirements_canvas, background="#12161c")
            self.requirements_list_frame.grid_columnconfigure(
                1, weight=1, uniform="requirement-labels"
            )
            self.requirements_list_frame.grid_columnconfigure(
                4, weight=1, uniform="requirement-labels"
            )
            requirements_window = self.requirements_canvas.create_window(
                (0, 0), window=self.requirements_list_frame, anchor="nw"
            )
            self.requirements_list_frame.bind(
                "<Configure>",
                lambda _event: (
                    self.requirements_canvas
                    and self.requirements_canvas.configure(
                        scrollregion=self.requirements_canvas.bbox("all")
                    )
                ),
            )
            self.requirements_canvas.bind(
                "<Configure>",
                lambda event: (
                    self.requirements_canvas
                    and self.requirements_canvas.itemconfigure(
                        requirements_window, width=event.width
                    )
                ),
            )
            self.advanced_components_button = ttk.Button(
                advanced_tab,
                text="Install missing components",
                command=self._install_components,
                style="Primary.TButton",
            )
            self.advanced_components_button.grid(
                row=8, column=0, columnspan=3, sticky="w", pady=(3, 0)
            )
            activity_tab = ttk.Frame(notebook, style="Card.TFrame", padding=14)
            activity_tab.columnconfigure(0, weight=1)
            activity_tab.rowconfigure(1, weight=1)
            self._activity_tab = activity_tab
            notebook.add(activity_tab, text="Activity")
            from .diagnostics_ui import mount_activity

            browser = mount_activity(activity_tab)
            browser.grid(row=0, column=0, rowspan=2, sticky="nsew")

            def closed() -> None:
                self.log = None
                self.sdk_entry = None
                self.sdk_browse = None
                self.cuda_check = None
                self.inspector_check = None
                self.inspector_apply = None
                self._inspector_selection_key = None
                self.components_button = None
                self.advanced_components_button = None
                self.verify_button = None
                self.open_button = None
                self.preview_button = None
                self.review_button = None
                self.remove_button = None
                self.embed_button = None
                self.unembed_button = None
                self.requirements_list_frame = None
                self.requirements_canvas = None
                self._options_window = None
                self._options_notebook = None
                self._system_tab = None
                self._advanced_tab = None
                self._activity_tab = None
                window.destroy()

            window.protocol("WM_DELETE_WINDOW", closed)
            self._refresh_dependency_display()
            self._refresh_project_state()
        else:
            self._options_window.deiconify()
            self._options_window.lift()

        tabs = {
            "system": self._system_tab,
            "advanced": self._advanced_tab,
            "activity": self._activity_tab,
        }
        target = tabs.get(tab)
        if target is not None and self._options_notebook is not None:
            self._options_notebook.select(target)

    def _show_developer_guide(self) -> None:
        # The guide is local text and Tk only; no project, component probe, or
        # optional Preview installation is needed to browse author commands.
        if self._developer_guide_window is None or not self._developer_guide_window.winfo_exists():
            from .developer_guide_ui import DeveloperGuide

            window = DeveloperGuide(self)
            self._developer_guide_window = window
            self._apply_window_icon(window)
            self._fit_to_screen(window, 1000, 690)
            self._apply_dark_titlebar(window)
        else:
            self._developer_guide_window.deiconify()
            self._developer_guide_window.lift()

    def _run_primary_action(self) -> None:
        if self._running or self._project_checking:
            return
        selection = self._selection()
        if not selection.valid:
            self._browse_project()
            return
        inspection = self._project_inspection
        if inspection is not None and (
            inspection.direct_install_needs_attention
            or inspection.managed_install_needs_attention
            or inspection.unmanaged_namespace_present
            or inspection.error is not None
        ):
            self._show_options(tab="tools")
            return
        if self._dependency_state is None or not self._dependency_state.ready:
            self._install_components(continue_setup=True)
        elif selection.root == self._character_review_pending_for and self._last_scan_payload:
            self._show_character_review(self._last_scan_payload)
        elif inspection is not None and inspection.release_replacement_available:
            if self._scan_ok:
                self._update_existing_install(inspection)
            else:
                relation = inspection.preferred_release_relation
                self._force_character_review = bool(
                    relation and relation.kind in {"pre_release", "unrecognized"}
                )
                self._scan()
        elif inspection is not None and inspection.refresh_required:
            if self._scan_ok:
                if inspection.direct_install_ready:
                    self._refresh_embed()
                else:
                    self._install()
            else:
                self._scan()
        elif self.developer_mode:
            if self._attached:
                if self._scan_ok:
                    self._refresh_embed()
                elif inspection is not None and inspection.refresh_required:
                    self._scan()
                else:
                    self._open_project()
            elif self._scan_ok:
                self._embed()
            else:
                self._scan()
        elif self._attached:
            if inspection is not None and inspection.direct_launch_ready:
                self._launch_attached()
            else:
                self._open_project()
        elif self._last_launcher is not None and self._last_launcher.is_file():
            self._launch()
        elif self._scan_ok:
            return
        else:
            self._scan()

    def _browse_project(self) -> None:
        selected = filedialog.askdirectory(title="Choose a Ren'Py game or mod folder")
        if selected:
            self.project_var.set(selected)

    def _browse_sdk(self) -> None:
        selected = filedialog.askdirectory(title="Choose a compatible Ren'Py SDK folder")
        if selected:
            self.sdk_var.set(selected)

    def _project_changed(self, *_: object) -> None:
        self._close_character_review_window()
        self._scan_ok = False
        self._review_completed_for = None
        self._character_review_pending_for = None
        self._force_character_review = False
        self._last_scan_payload = {}
        self._attached = False
        self._last_launcher = None
        self.preview_var.set("Project changed. Scan it before installing.")
        self._begin_project_inspection()

    def _cuda_changed(self, *_: object) -> None:
        if not self._applying_cuda_default:
            self._cuda_user_choice = True
        self._refresh_dependency_display()
        self._refresh_project_state()

    def _begin_cuda_detection(self) -> None:
        # Driver initialization and optional compiler checks never run on Tk's thread.
        self._cuda_probe_generation += 1
        generation = self._cuda_probe_generation
        python = component_python()
        target_exists = python.is_file()
        if not target_exists:
            python = Path(sys.executable)

        def worker() -> None:
            support = detect_cuda_support(python, check_backend=target_exists)
            self._events.put(("cuda-detection", generation, support))

        threading.Thread(target=worker, name="scenelight-cuda-detection", daemon=True).start()

    def _finish_cuda_detection(self, support: CudaSupport, generation: int | None = None) -> None:
        if generation is not None and generation != self._cuda_probe_generation:
            return
        self._cuda_support = support
        self.cuda_detail_var.set(support.message)
        if self._running:
            self._cuda_apply_when_idle = True
            return
        self._cuda_apply_when_idle = False
        if (
            not support.recommended or not self._cuda_user_choice
        ) and self.cuda_var.get() != support.recommended:
            self._applying_cuda_default = True
            try:
                self.cuda_var.set(support.recommended)
            finally:
                self._applying_cuda_default = False
        else:
            self._refresh_dependency_display()
            self._refresh_project_state()

    def _selection(self) -> ProjectSelection:
        value = self.project_var.get()
        if self._project_inspection is not None and self._project_inspection_value == value:
            return self._project_inspection.selection
        if value.strip():
            return ProjectSelection(None, False, "Inspecting the selected folder…")
        return ProjectSelection(None, False, "Choose a Ren'Py game or mod folder.")

    def _begin_project_inspection(self) -> None:
        """Inspect the selected game on a worker so Tk never blocks on file hashing."""

        value = self.project_var.get()
        self._project_generation += 1
        generation = self._project_generation
        self._project_inspection = None
        self._project_inspection_value = value
        if not value.strip():
            self._project_checking = False
            self._project_inspection = ProjectInspection(inspect_project_path(value))
            self.operation_var.set("Ready")
            self._refresh_project_state()
            return

        self._project_checking = True
        self.operation_var.set("Checking the selected game…")
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.progress.start(12)
        self.progress_frame.grid()
        self._refresh_project_state()

        def worker() -> None:
            try:
                inspection = inspect_project_installation(value)
            except Exception as error:  # noqa: BLE001 - never strand Tk on a failed worker.
                inspection = ProjectInspection(
                    ProjectSelection(
                        None,
                        False,
                        f"That project could not be inspected: {error}",
                    ),
                    error=str(error),
                )
            self._events.put(("project-inspection", generation, value, inspection))

        threading.Thread(
            target=worker,
            name="scenelight-project-inspection",
            daemon=True,
        ).start()

    def _finish_project_inspection(
        self, generation: int, value: str, inspection: ProjectInspection
    ) -> None:
        if generation != self._project_generation or value != self.project_var.get():
            return
        self._project_checking = False
        self._source_watch = ProjectWatch(inspection.source_metadata)
        self._project_inspection = inspection
        self._project_inspection_value = value
        self.progress.stop()
        if not self._running:
            self.progress_frame.grid_remove()
            self.operation_var.set("Ready")
        self._refresh_project_state()

    def _poll_project_sources(self) -> None:
        if self._destroying:
            return
        inspection = self._project_inspection
        if (
            not self._running
            and not self._project_checking
            and not self._watch_busy
            and inspection is not None
            and inspection.selection.valid
        ):
            root = inspection.selection.root
            generation = self._project_generation
            self._watch_busy = True

            def worker():
                try:
                    snapshot = source_metadata(root)
                except OSError:
                    snapshot = None  # An editor may be replacing a file; retry next poll.
                self._events.put(("project-sources", generation, snapshot))

            threading.Thread(target=worker, name="scenelight-project-watch", daemon=True).start()
        self.after(5_000, self._poll_project_sources)

    def _finish_project_sources(self, generation, snapshot) -> None:
        self._watch_busy = False
        if (
            generation != self._project_generation
            or self._running
            or self._project_checking
            or snapshot is None
        ):
            return
        if not self._source_watch.observe(snapshot):
            return
        self._scan_ok = False
        self._review_completed_for = None
        self._character_review_pending_for = None
        self._last_scan_payload = {}
        self._close_character_review_window()
        self.preview_var.set("Project files changed. Update SceneLight, then restart the game.")
        self._append_log("[Project files changed; checking the installed lighting data.]\n")
        self._begin_project_inspection()

    def _poll_dependency_state(self) -> None:
        if not self._running:
            changed = self._refresh_dependency_display()
            # Project verification can hash thousands of managed files. It only
            # needs to be repeated here when an external dependency install
            # actually changed whether the selected project can be used.
            if changed:
                self._refresh_project_state()
        self.after(self._dependency_poll_delay(), self._poll_dependency_state)

    def _dependency_poll_delay(self) -> int:
        """Return a quiet idle poll interval while still noticing external installs."""

        if self._running:
            return 5_000
        if self._dependency_state is not None and self._dependency_state.ready:
            return 300_000
        return 5_000

    def _render_requirement_rows(self, state: DependencyState) -> None:
        frame = self.requirements_list_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        rows = state.component_statuses
        row_count = (len(rows) + 1) // 2
        for index, (label, ready) in enumerate(rows):
            row = index % row_count
            column = (index // row_count) * 3
            color = "#75d6ad" if ready else "#f0b66d"
            marker = "✓" if ready else "○"
            tk.Label(
                frame,
                text=marker,
                background="#12161c",
                foreground=color,
                font=("Segoe UI Semibold", 10),
                width=2,
                anchor="w",
            ).grid(row=row, column=column, sticky="w", pady=2)
            tk.Label(
                frame,
                text=label,
                background="#12161c",
                foreground="#e2e7ec" if ready else "#c7cdd4",
                font=("Segoe UI", 8),
                anchor="w",
            ).grid(row=row, column=column + 1, sticky="w", pady=2)
            tk.Label(
                frame,
                text="Verified" if ready else "Missing",
                background="#12161c",
                foreground=color,
                font=("Segoe UI", 8),
                anchor="e",
            ).grid(row=row, column=column + 2, sticky="e", pady=2, padx=(8, 12))
        canvas = self.requirements_canvas
        if canvas is not None:

            def scroll_requirements(event: tk.Event[tk.Misc]) -> str:
                direction = -1 if event.delta > 0 else 1
                canvas.yview_scroll(direction, "units")
                return "break"

            canvas.bind("<MouseWheel>", scroll_requirements)
            frame.bind("<MouseWheel>", scroll_requirements)
            for child in frame.winfo_children():
                child.bind("<MouseWheel>", scroll_requirements)

    def _refresh_dependency_display(self) -> bool:
        source_install = SDK_LAUNCHER.is_file() and not getattr(sys, "frozen", False)
        state = dependency_state(
            include_preview=False,
            include_cuda=self.cuda_var.get(),
            source_mode=source_install,
        )
        self._dependency_state = state
        key = (state.runtime_ready, state.required, state.missing, self.cuda_var.get())
        changed = key != self._dependency_key
        self._dependency_key = key

        ready_color = "#75d6ad"
        missing_color = "#f0b66d"
        if state.runtime_ready:
            self.runtime_status_var.set("SceneLight runtime ready.")
        else:
            self.runtime_status_var.set(
                f"SceneLight runtime will be installed · {state.python_executable.parent}"
            )
        self.dependencies_status_var.set(state.verification_summary)
        self.dependency_detail_var.set(describe_dependency_plan(state))
        self._render_requirement_rows(state)
        if self.cuda_var.get():
            cuda_ready = CUDA_REQUIREMENT not in state.missing
            self.gpu_status_var.set(
                "Analysis: NVIDIA CUDA · Lighting: Intel, AMD, NVIDIA"
                if cuda_ready
                else "NVIDIA CUDA selected · component setup required."
            )
        elif self._cuda_support is None:
            self.gpu_status_var.set("Analysis: CPU · Checking optional CUDA acceleration…")
        elif self._cuda_support.recommended:
            self.gpu_status_var.set("Analysis: CPU (CUDA available) · Lighting: Intel, AMD, NVIDIA")
        else:
            self.gpu_status_var.set("Analysis: CPU · Lighting: Intel, AMD, NVIDIA")
        if state.ready:
            self.requirements_var.set("System ready")
            self.requirements_label.configure(foreground=ready_color)
            self.state_dot.itemconfigure("dot", fill=ready_color)
            if self.components_button is not None:
                self.components_button.grid_remove()
            if self.advanced_components_button is not None:
                self.advanced_components_button.grid_remove()
        else:
            self.requirements_var.set("One-time setup required")
            self.requirements_label.configure(foreground=missing_color)
            self.state_dot.itemconfigure("dot", fill=missing_color)
            if self.components_button is not None:
                self.components_button.grid()
                self.components_button.configure(
                    text="Install components", state="disabled" if self._running else "normal"
                )
            if self.advanced_components_button is not None:
                self.advanced_components_button.grid()
                self.advanced_components_button.configure(
                    text="Install missing components",
                    state="disabled" if self._running else "normal",
                )
        if changed and self._running:
            self._append_log(f"[dependency check: {state.verification_summary}]\n")
        return changed

    def _toggle_developer_mode(self) -> None:
        if self._running:
            return
        self._close_character_review_window()
        self.developer_mode = not self.developer_mode
        self._scan_ok = False
        self._review_completed_for = None
        self._character_review_pending_for = None
        self._force_character_review = False
        self._last_scan_payload = {}
        self._attached = False
        self._last_launcher = None
        self.preview_var.set("Nothing has been scanned or changed.")
        self._refresh_project_state()

    def _refresh_project_state(self) -> None:
        if self.mode_button is not None:
            self.mode_button.configure(
                text="For players" if self.developer_mode else "For mod developers",
                state="disabled" if self._running or self._project_checking else "normal",
            )
        selection = self._selection()
        inspection = self._project_inspection
        release_relation = inspection.preferred_release_relation if inspection is not None else None
        release_replacement_available = bool(
            release_relation and release_relation.replacement_available
        )
        self._attached = bool(inspection and inspection.direct_install_ready)
        self._last_launcher = inspection.managed_launcher if inspection is not None else None
        existing_issue = bool(
            inspection
            and (
                inspection.direct_install_needs_attention
                or inspection.managed_install_needs_attention
                or inspection.unmanaged_namespace_present
                or inspection.error is not None
            )
        )
        existing_install = bool(
            inspection
            and (
                inspection.direct_install_ready
                or inspection.direct_install_needs_attention
                or inspection.managed_install_present
                or inspection.unmanaged_namespace_present
            )
        )
        if self.inspector_check is not None:
            self._refresh_inspector_option(selection, inspection, existing_issue)
        state = self._dependency_state
        dependencies_ready = bool(state and state.ready)
        character_review_pending = bool(
            selection.valid
            and selection.root is not None
            and selection.root == self._character_review_pending_for
            and self._last_scan_payload
        )
        if self._project_checking:
            raw_path = self.project_var.get().strip().strip('"')
            self.project_name_var.set(Path(raw_path).name or "Selected folder")
            self.project_path_var.set(raw_path)
            self.status_var.set("Checking the selected game…")
            self.project_status.configure(foreground="#70caf2")
            self.installation_var.set("Checking for an existing SceneLight installation…")
            self.installation_status.configure(foreground="#98a4b1")
        elif selection.valid and selection.root is not None:
            self.project_name_var.set(selection.root.name)
            self.project_path_var.set(str(selection.root))
            self.status_var.set(selection.message)
            self.project_status.configure(foreground="#75d6ad")
            if self._running and self._active_operation in {
                "install",
                "attach",
                "embed",
                "refresh",
            }:
                self.installation_var.set(
                    "An existing installation was detected. The update is still running; "
                    "wait for the completion message below."
                    if existing_install
                    else "Installation is still running. Wait for the completion message below."
                )
                self.installation_status.configure(foreground="#70caf2")
            elif inspection is not None and inspection.error is not None:
                self.installation_var.set(
                    "SceneLight found an installation it cannot safely update. "
                    "Open Manage installation for details."
                )
                self.installation_status.configure(foreground="#e28b82")
            elif inspection is not None and inspection.direct_install_needs_attention:
                status = inspection.developer_status
                assert status is not None
                problem_count = len(status.missing) + len(status.modified) + len(status.unowned)
                self.installation_var.set(
                    f"SceneLight found {problem_count} changed or missing installation file(s). "
                    "Review them before launching or updating."
                )
                self.installation_status.configure(foreground="#e28b82")
            elif inspection is not None and inspection.unmanaged_namespace_present:
                self.installation_var.set(
                    "This game already contains SceneLight runtime files from another setup. "
                    "SceneLight will not replace them automatically."
                )
                self.installation_status.configure(foreground="#e28b82")
            elif release_replacement_available and release_relation is not None:
                if release_relation.kind == "different_build":
                    message = f"SceneLight {__version__} is installed. An update is available."
                elif release_relation.kind == "downgrade":
                    message = (
                        f"{release_relation.installed_label[:1].upper()}"
                        f"{release_relation.installed_label[1:]} is installed. "
                        f"This package contains SceneLight {__version__}."
                    )
                else:
                    message = (
                        f"{release_relation.installed_label[:1].upper()}"
                        f"{release_relation.installed_label[1:]} is installed. "
                        f"SceneLight {__version__} is available."
                    )
                self.installation_var.set(message)
                self.installation_status.configure(foreground="#f0b66d")
            elif inspection is not None and inspection.refresh_required:
                self.installation_var.set(
                    "Project files changed. Update SceneLight, then restart the game."
                )
                self.installation_status.configure(foreground="#f0b66d")
            elif inspection is not None and inspection.direct_install_ready:
                suffix = (
                    " A separate SceneLight copy also exists."
                    if inspection.managed_install_ready
                    else ""
                )
                launch_note = (
                    " Setup can launch it with the compatible Ren'Py runtime recorded during "
                    "installation."
                    if inspection.direct_launch_ready
                    and find_native_executable(selection.root) is None
                    else " Use the game's normal executable."
                    if inspection.direct_launch_ready
                    else " Open it with the matching Ren'Py SDK."
                )
                self.installation_var.set(
                    f"SceneLight is installed and ready.{launch_note}{suffix}"
                )
                self.installation_status.configure(foreground="#75d6ad")
            elif inspection is not None and inspection.managed_install_needs_attention:
                self.installation_var.set(
                    "A separate SceneLight copy is recorded, but its launcher is missing. "
                    "Verify or remove that copy before reinstalling."
                )
                self.installation_status.configure(foreground="#e28b82")
            elif inspection is not None and inspection.managed_install_ready:
                self.installation_var.set(
                    "A separate SceneLight copy is ready. The original game is unchanged."
                )
                self.installation_status.configure(foreground="#75d6ad")
            else:
                self.installation_var.set(
                    "SceneLight is not installed. Scanning will not change the game."
                )
                self.installation_status.configure(foreground="#7f8a96")
        else:
            self.project_name_var.set("No game selected")
            self.project_path_var.set("Choose a folder to continue")
            if self.project_var.get().strip():
                self.status_var.set(selection.message)
                self.project_status.configure(foreground="#e28b82")
            else:
                self.status_var.set("")
                self.project_status.configure(foreground="#7f8a96")
            self.installation_var.set("No existing SceneLight installation selected.")
            self.installation_status.configure(foreground="#7f8a96")

        player_ready = self._attached or bool(
            inspection and inspection.managed_install_ready and not self._project_checking
        )
        workflow_ready = self._attached if self.developer_mode else player_ready
        current_step = 0
        if selection.valid:
            current_step = 1
        if self._scan_ok or character_review_pending:
            current_step = 2
        if workflow_ready:
            current_step = 3
        if release_replacement_available:
            current_step = 3 if self._scan_ok else 2 if character_review_pending else 1
        for index, label_widget in enumerate(self.step_labels):
            if index < current_step:
                label_widget.configure(foreground="#75d6ad")
            elif index == current_step:
                label_widget.configure(foreground="#70caf2")
            else:
                label_widget.configure(foreground="#66727f")

        can_use = (
            selection.valid
            and not self._running
            and not self._project_checking
            and dependencies_ready
            and not existing_issue
        )
        editing_state = "disabled" if self._running or self._project_checking else "normal"
        self.project_browse.configure(state=editing_state)
        if selection.valid or self._project_checking:
            self.project_browse.configure(text="Change…")
            self.state_row.grid()
            self.primary_button.grid()
        else:
            self.project_browse.configure(text="Choose…")
            self.state_row.grid_remove()
            self.install_choice_frame.grid_remove()
        for widget in (self.sdk_entry, self.sdk_browse):
            if widget is not None:
                widget.configure(state=editing_state)
        if self.cuda_check is not None:
            self.cuda_check.configure(
                state=editing_state
                if self._cuda_support and self._cuda_support.recommended
                else "disabled"
            )
        for widget in (self.verify_button, self.review_button, self.characters_button):
            if widget is not None:
                allowed = can_use
                if widget is self.verify_button:
                    allowed = bool(
                        inspection
                        and inspection.managed_install_present
                        and selection.valid
                        and not self._running
                    )
                widget.configure(state="normal" if allowed else "disabled")
        if self.preview_button is not None:
            self.preview_button.configure(state=preview_action_state(self._running))
        if self.open_button is not None:
            self.open_button.configure(
                state="normal" if selection.valid and not self._running else "disabled"
            )
        for widget in (self.remove_button, self.unembed_button):
            if widget is not None:
                widget.configure(
                    state=(
                        "normal"
                        if existing_install and not existing_issue and not self._running
                        else "disabled"
                    )
                )
        if self.remove_button is not None:
            self.remove_button.configure(
                text=(
                    "Remove developer API"
                    if self._attached and self.developer_mode
                    else "Remove from this game"
                    if self._attached
                    else "Remove SceneLight copy"
                )
            )
        if self.embed_button is not None:
            self.embed_button.configure(state="normal" if can_use and self._scan_ok else "disabled")
        launcher_ready = self._attached or (
            not self._running and self._last_launcher is not None and self._last_launcher.is_file()
        )
        show_install_choices = bool(
            not self.developer_mode
            and self._scan_ok
            and can_use
            and not launcher_ready
            and not existing_issue
            and not self._running
        )
        if show_install_choices:
            self.primary_button.grid_remove()
            self.install_choice_frame.grid()
            self.attach_button.configure(state="normal")
            self.copy_button.configure(state="normal")
        else:
            self.install_choice_frame.grid_remove()
            if selection.valid or self._project_checking:
                self.primary_button.grid()
        if self.manage_button is not None:
            if existing_install or existing_issue:
                self.manage_button.grid()
                self.manage_button.configure(
                    state="disabled" if self._running or self._project_checking else "normal"
                )
            else:
                self.manage_button.grid_remove()
        if self._running:
            label = "Working…"
            primary_state = "disabled"
            title, subtitle, _status = operation_copy(self._active_operation or "")
            self.workflow_title_var.set(title)
            self.workflow_subtitle_var.set(getattr(self, "_update_reason", "") or subtitle)
        elif self._project_checking:
            label = "Inspecting selected game…"
            primary_state = "disabled"
            self.workflow_title_var.set("Checking your selection")
            self.workflow_subtitle_var.set(
                "SceneLight is checking the game and any existing installation."
            )
        elif not selection.valid:
            label = "Choose a mod project" if self.developer_mode else "Choose a game or mod"
            primary_state = "normal"
            self.workflow_title_var.set(
                "Choose your mod project" if self.developer_mode else "Choose your game"
            )
            self.workflow_subtitle_var.set(
                "Install the SceneLight runtime and author API into a Ren'Py project."
                if self.developer_mode
                else "Select a Ren'Py game or mod folder to get started."
            )
        elif existing_issue:
            label = "Review existing SceneLight files"
            primary_state = "normal"
            self.workflow_title_var.set("Existing installation needs attention")
            self.workflow_subtitle_var.set(
                "SceneLight will not change or launch files until the problem is reviewed."
            )
        elif not dependencies_ready:
            label = "Set up SceneLight"
            primary_state = "normal"
            self.workflow_title_var.set("Prepare SceneLight")
            self.workflow_subtitle_var.set(
                "Install the SceneLight runtime and required components on this computer."
            )
        elif character_review_pending:
            label = "Review characters"
            primary_state = "normal"
            self.workflow_title_var.set("Choose character families")
            self.workflow_subtitle_var.set(
                "Confirm which image families should receive SceneLight character lighting."
            )
        elif release_replacement_available and release_relation is not None:
            verb = (
                "Replace with"
                if release_relation.kind in {"downgrade", "different_build"}
                else "Update to"
            )
            label = (
                f"{verb} SceneLight {__version__}"
                if self._scan_ok
                else f"Review update to SceneLight {__version__}"
            )
            primary_state = "normal"
            self.workflow_title_var.set("SceneLight update available")
            self.workflow_subtitle_var.set(
                (
                    "Review the detected character families, then confirm the update."
                    if not self._scan_ok
                    else "SceneLight is ready to update this installation."
                )
            )
        elif inspection is not None and inspection.refresh_required:
            label = "Update SceneLight" if self._scan_ok else "Check changed assets"
            primary_state = "normal"
            self.workflow_title_var.set("Game changes detected")
            self.workflow_subtitle_var.set(
                "Review changed assets, then update the affected lighting data before play."
            )
        elif workflow_ready:
            if self.developer_mode:
                label = (
                    "Update SceneLight"
                    if self._scan_ok
                    else "Check new assets"
                    if inspection is not None and inspection.refresh_required
                    else "Open mod project"
                )
            elif self._attached:
                label = (
                    "Play installed game"
                    if inspection is not None and inspection.direct_launch_ready
                    else "Open game folder"
                )
            else:
                label = "Launch existing SceneLight copy"
            primary_state = "normal"
            if self.developer_mode:
                if inspection is not None and inspection.refresh_required:
                    self.workflow_title_var.set("Project changes detected")
                    self.workflow_subtitle_var.set(
                        "Review new characters, then update lighting data and surface maps."
                    )
                elif self._scan_ok:
                    self.workflow_title_var.set("Ready to update SceneLight")
                    self.workflow_subtitle_var.set("SceneLight is ready to update this project.")
                else:
                    self.workflow_title_var.set("Developer API installed")
                    self.workflow_subtitle_var.set(
                        "SceneLight now loads with the mod and can be controlled from Ren'Py script."
                    )
            else:
                launch_ready = bool(
                    not self._attached or inspection is not None and inspection.direct_launch_ready
                )
                self.workflow_title_var.set(
                    "Ready to play" if launch_ready else "SceneLight installed"
                )
                self.workflow_subtitle_var.set(
                    "SceneLight is installed in this game and ready."
                    if self._attached and launch_ready
                    else "SceneLight is installed; launch this source project with its matching "
                    "Ren'Py SDK."
                    if self._attached
                    else "Your separate SceneLight copy is installed and ready."
                )
        elif self._scan_ok:
            if self.developer_mode:
                label = "Install developer API"
                primary_state = "normal"
                self.workflow_title_var.set("Ready to add the author API")
                self.workflow_subtitle_var.set(
                    "The installer uses one reserved folder and never rewrites your scripts."
                )
            else:
                label = "Choose installation"
                primary_state = "disabled"
                self.workflow_title_var.set("Choose how to install")
                self.workflow_subtitle_var.set(
                    "Add SceneLight here, or keep this folder unchanged and create a copy."
                )
        else:
            label = "Scan game"
            primary_state = "normal"
            self.workflow_title_var.set(
                "Ready to scan project" if self.developer_mode else "Ready to scan"
            )
            self.workflow_subtitle_var.set("Scan assets, then review detected characters.")
        self.primary_button.configure(text=label, state=primary_state)
        if self._running or self._project_checking:
            # Live progress replaces the action button while work is active,
            # leaving enough room for the exact current operation and transfer.
            self.primary_button.grid_remove()
        if state is not None and self.components_button is not None and not state.ready:
            self.components_button.configure(
                state="disabled" if self._running or state.ready else "normal"
            )
        if state is not None and self.advanced_components_button is not None and not state.ready:
            self.advanced_components_button.configure(
                state="disabled" if self._running or state.ready else "normal"
            )

    def _command(self, operation: str) -> list[str]:
        selection = self._selection()
        if not selection.valid or selection.root is None:
            raise ValueError(selection.message)
        sdk = (
            normalize_project_path(self.sdk_var.get(), find_nested=False)
            if self.sdk_var.get().strip()
            else None
        )
        analyzer = "auto" if self.cuda_var.get() else "cpu"
        return build_cli_command(
            operation,
            selection.root,
            renpy_sdk=sdk,
            analyzer=analyzer,
            executable=preferred_runtime_python(),
        )

    def _refresh_inspector_option(self, selection, inspection, existing_issue: bool) -> None:
        from .inspector_install import inspector_enabled

        enabled = (
            selection.valid
            and selection.root is not None
            and not existing_issue
            and not self._running
            and not self._project_checking
        )
        self.inspector_check.configure(state="normal" if enabled else "disabled")
        self.inspector_apply.configure(state="normal" if enabled else "disabled")
        if not selection.valid or selection.root is None:
            self._inspector_selection_key = None
            self.inspector_detail_var.set("Choose a project to configure its in-game inspector.")
            return
        embedded = self._attached or not (inspection and inspection.managed_install_present)
        key = (selection.root, embedded)
        if not self._running and key != self._inspector_selection_key:
            self._inspector_selection_key = key
            current = inspector_enabled(selection.root, embedded=embedded)
            self.inspector_var.set(current)
            installed = self._attached or bool(inspection and inspection.managed_install_present)
            self.inspector_detail_var.set(
                (
                    "Enabled. Press Shift+F9 in game."
                    if current
                    else "Disabled. The inspector is not included."
                )
                + " Restart the game after applying changes."
                if installed
                else "Save this choice for the next installation."
            )

    def _apply_inspector_option(self) -> None:
        if self._running or self._project_checking or self._inspector_selection_key is None:
            return
        _project, embedded = self._inspector_selection_key
        command = self._command("inspector") + [
            "--enabled",
            "on" if self.inspector_var.get() else "off",
            "--installation",
            "embedded" if embedded else "managed",
        ]
        self._start_operation("inspector", command)

    def _review_characters(self) -> None:
        """Refresh discovery before reopening the authoritative selection."""

        self._close_character_review_window()
        self._review_completed_for = None
        self._character_review_pending_for = None
        self._force_character_review = True
        self._scan_ok = False
        self._scan()

    def _close_character_review_window(self) -> None:
        """Release and close the review dialog without losing its resumable state."""

        window = self._character_review_window
        self._character_review_window = None
        if window is None:
            return
        try:
            if window.winfo_exists():
                if window.grab_current() is window:
                    window.grab_release()
                window.destroy()
        except tk.TclError:
            pass

    def _show_character_review(self, payload: dict[str, object]) -> None:
        selection = self._selection()
        if not selection.valid or selection.root is None:
            return
        existing_window = self._character_review_window
        if existing_window is not None:
            try:
                if existing_window.winfo_exists():
                    existing_window.deiconify()
                    existing_window.lift()
                    existing_window.focus_force()
                    return
            except tk.TclError:
                pass
            self._character_review_window = None
        project_root = selection.root
        candidates = character_review_candidates(payload)
        existing_tags = character_review_selected_tags(payload)
        inspection = self._project_inspection
        installed = bool(
            self._attached or inspection is not None and inspection.managed_install_present
        )
        raw_suggested_tags = payload.get(
            "suggested_character_tags", payload.get("character_tags", [])
        )
        suggested_tags = (
            {
                str(tag).strip().lower()
                for tag in raw_suggested_tags
                if isinstance(tag, str) and tag.strip()
            }
            if isinstance(raw_suggested_tags, list)
            else set()
        )

        window = tk.Toplevel(self)
        self._character_review_window = window
        window.title("Choose character families")
        window.geometry("680x560")
        window.minsize(540, 440)
        window.configure(background="#0d1014")
        window.transient(self)
        self._apply_window_icon(window)
        window.after(50, lambda: self._apply_dark_titlebar(window))

        def fit_review() -> None:
            # Measure after Tk has laid out DPI-scaled fonts and controls.
            window.update_idletasks()
            self._fit_to_screen(
                window, max(680, window.winfo_reqwidth()), max(640, window.winfo_reqheight())
            )

        window.after_idle(fit_review)
        window.grab_set()

        def cancel_review() -> None:
            self._close_character_review_window()
            if self._character_review_pending_for == project_root:
                self.operation_var.set("Review characters to continue.")
            self._refresh_project_state()

        window.protocol("WM_DELETE_WINDOW", cancel_review)

        page = tk.Frame(window, background="#0d1014", padx=28, pady=24)
        page.pack(fill="both", expand=True)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(4, weight=1)
        tk.Label(
            page,
            text="Choose characters to light",
            background="#0d1014",
            foreground="#f7f9fb",
            font=("Segoe UI Semibold", 20),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            page,
            text=(
                "Suggestions come from this game's images. Select the characters to light; "
                "each family includes its poses and expressions. Leave backgrounds, UI and "
                "props unchecked. Apply an update after changing these choices."
            ),
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=610,
        ).grid(row=1, column=0, sticky="ew", pady=(5, 14))

        automatic_var = tk.BooleanVar(value=character_review_mode(payload) == "automatic")
        mode_row = tk.Frame(page, background="#0d1014")
        mode_row.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ttk.Checkbutton(
            mode_row,
            text="Automatically include new characters on scan / update",
            variable=automatic_var,
        ).pack(anchor="w")
        tk.Label(
            mode_row,
            text="Unchecked families stay excluded. Turn off to keep only your selection.",
            background="#0d1014",
            foreground="#98a4b1",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        controls = tk.Frame(page, background="#0d1014")
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)
        count_var = tk.StringVar(value=f"{len(candidates)} image families")
        tk.Label(
            controls,
            textvariable=count_var,
            background="#0d1014",
            foreground="#aab3bf",
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")

        list_shell = tk.Frame(
            page,
            background="#12161c",
            highlightbackground="#242d36",
            highlightthickness=1,
        )
        list_shell.grid(row=4, column=0, sticky="nsew")
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            list_shell,
            background="#12161c",
            highlightthickness=0,
            borderwidth=0,
            yscrollincrement=28,
        )
        scrollbar = ttk.Scrollbar(
            list_shell,
            orient="vertical",
            command=canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        rows = tk.Frame(canvas, background="#12161c")
        rows.grid_columnconfigure(1, weight=1)
        canvas_window = canvas.create_window((0, 0), window=rows, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        rows.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )

        wheel_remainder = [0]

        def scroll_rows(event: tk.Event) -> str:
            delta = int(getattr(event, "delta", 0))
            if delta:
                wheel_remainder[0] += delta
                steps = int(wheel_remainder[0] / 120)
                wheel_remainder[0] -= steps * 120
                if steps:
                    canvas.yview_scroll(-steps, "units")
            else:
                canvas.yview_scroll(-1 if getattr(event, "num", 0) == 4 else 1, "units")
            return "break"

        window.bind("<MouseWheel>", scroll_rows, add="+")
        window.bind("<Button-4>", scroll_rows, add="+")
        window.bind("<Button-5>", scroll_rows, add="+")

        def scroll_key(event: tk.Event) -> str | None:
            # Home/End in the tag entry belong to text editing, not the list.
            if event.widget.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox"}:
                return None
            if event.keysym in {"Home", "End"}:
                canvas.yview_moveto(0.0 if event.keysym == "Home" else 1.0)
            else:
                canvas.yview_scroll(-1 if event.keysym == "Prior" else 1, "pages")
            return "break"

        for key in ("Prior", "Next", "Home", "End"):
            window.bind(f"<{key}>", scroll_key, add="+")

        tag_vars: dict[str, tk.BooleanVar] = {}
        preview_images: list[object] = []

        def add_candidate(tag: str, preview: str | None) -> None:
            if tag in tag_vars:
                return
            row = len(tag_vars)
            variable = tk.BooleanVar(value=tag in existing_tags)
            tag_vars[tag] = variable
            thumbnail = tk.Label(
                rows,
                text="No preview",
                width=11,
                height=4,
                background="#181d24",
                foreground="#6f7a86",
                font=("Segoe UI", 8),
            )
            if preview:
                try:
                    from PIL import Image, ImageTk

                    with Image.open(preview) as source:
                        image = source.convert("RGBA")
                    image.thumbnail((72, 72), Image.Resampling.LANCZOS)
                    checker = Image.new("RGBA", (72, 72), (28, 33, 40, 255))
                    checker.alpha_composite(
                        image,
                        ((72 - image.width) // 2, (72 - image.height) // 2),
                    )
                    rendered = ImageTk.PhotoImage(checker)
                    preview_images.append(rendered)
                    thumbnail.configure(image=rendered, text="", width=72, height=72)
                except (ImportError, OSError, ValueError, tk.TclError):
                    # The compact launcher intentionally keeps Pillow out of
                    # its bootstrap runtime. Tk 8.6 can still decode the PNG
                    # previews produced by Ren'Py, so retain visible review
                    # thumbnails without adding another installer dependency.
                    try:
                        rendered = tk.PhotoImage(file=preview)
                        factor = thumbnail_subsample_factor(rendered.width(), rendered.height())
                        if factor > 1:
                            rendered = rendered.subsample(factor, factor)
                        preview_images.append(rendered)
                        thumbnail.configure(image=rendered, text="", width=72, height=72)
                    except (OSError, ValueError, tk.TclError):
                        pass
            thumbnail.grid(row=row, column=0, padx=(10, 12), pady=7)
            label = f"{tag}  · detected in this game" if tag in suggested_tags else tag
            ttk.Checkbutton(rows, text=label, variable=variable).grid(
                row=row, column=1, sticky="w", pady=7
            )

        for candidate_tag, candidate_preview in candidates.items():
            add_candidate(candidate_tag, candidate_preview)
        for configured_tag in sorted(existing_tags - set(candidates)):
            add_candidate(configured_tag, None)
        if not tag_vars:
            tk.Label(
                rows,
                text=(
                    "No image families found. Add a character's image tag "
                    "(for example: hero), or choose automatic suggestions."
                ),
                background="#12161c",
                foreground="#aab3bf",
                font=("Segoe UI", 10),
                justify="left",
                wraplength=560,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=18)

        def set_all(value: bool) -> None:
            for variable in tag_vars.values():
                variable.set(value)

        ttk.Button(
            controls,
            text="Select all",
            command=lambda: set_all(True),
            style="Quiet.TButton",
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            controls,
            text="Clear",
            command=lambda: set_all(False),
            style="Quiet.TButton",
        ).grid(row=0, column=2, padx=(4, 0))

        add_row = tk.Frame(page, background="#0d1014")
        add_row.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        add_row.grid_columnconfigure(0, weight=1)
        add_var = tk.StringVar()
        add_entry = ttk.Entry(add_row, textvariable=add_var, style="Dark.TEntry")
        add_entry.grid(row=0, column=0, sticky="ew")

        def add_typed_tag() -> None:
            parts = add_var.get().strip().lower().split()
            if not parts or not re.fullmatch(r"[a-z0-9_]+", parts[0]):
                messagebox.showerror(
                    "Invalid image tag",
                    "Enter the first Ren'Py image tag, using letters, numbers, or underscores.",
                    parent=window,
                )
                return
            add_candidate(parts[0], None)
            tag_vars[parts[0]].set(True)
            add_var.set("")
            count_var.set(f"{len(tag_vars)} image families")
            canvas.update_idletasks()
            canvas.yview_moveto(1.0)

        ttk.Button(
            add_row, text="Add image tag", command=add_typed_tag, style="Secondary.TButton"
        ).grid(row=0, column=1, padx=(8, 0))
        add_entry.bind("<Return>", lambda _event: add_typed_tag())

        actions = tk.Frame(page, background="#0d1014")
        actions.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        actions.grid_columnconfigure(0, weight=1)

        def save_review() -> None:
            chosen = sorted(tag for tag, variable in tag_vars.items() if variable.get())
            if not chosen:
                if not messagebox.askyesno(
                    "No characters selected",
                    "No image families will receive SceneLight. Save this empty selection?",
                    parent=window,
                ):
                    return
            try:
                save_character_selection(
                    project_root,
                    "automatic" if automatic_var.get() else "manual",
                    chosen,
                    candidates=sorted(tag_vars),
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                messagebox.showerror("Selection could not be saved", str(error), parent=window)
                return
            self._close_character_review_window()
            self._review_completed_for = project_root
            self._character_review_pending_for = None
            operation = "refresh" if self._attached else "install" if installed else "scan"
            self.operation_var.set("Character selection saved. Applying your choices…")
            self._start_operation(operation, self._command(operation))

        ttk.Button(actions, text="Cancel", command=cancel_review, style="Quiet.TButton").grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(
            actions,
            text="Apply selection & update" if installed else "Save selection and continue",
            command=save_review,
            style="Primary.TButton",
        ).grid(row=0, column=2)

        def focus_review() -> None:
            try:
                if window.winfo_exists():
                    window.deiconify()
                    window.lift()
                    window.focus_force()
            except tk.TclError:
                pass

        # A review can finish while the Settings window is in front. Bring the
        # required dialog back above every SceneLight window once it is fully
        # laid out so switching games cannot make it appear to have vanished.
        window.after_idle(focus_review)

    def report_callback_exception(self, kind, error, trace) -> None:
        session = diagnostics.current_session() or diagnostics.start_session("setup")
        if session is not None:
            session.exception("setup.ui", error.with_traceback(trace))
            session.update(status="error", failure=str(error))
        super().report_callback_exception(kind, error, trace)

    def _append_log(self, text: str, *, record: bool = True) -> None:
        self._log_lines.append(text)
        session = diagnostics.current_session()
        if session is not None and record:
            session.output(text)
        if self.log is not None:
            self.log.configure(state="normal")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.configure(state="disabled")

    def _scan(self) -> None:
        selection = self._selection()
        native = find_native_executable(selection.root) if selection.root is not None else None
        native_major = renpy_runtime_major(native)
        if (
            native_major is not None
            and native_major < 7
            and cached_renpy_executable() is None
            and not (SOURCE_ROOT / "compatibility-runtime" / "renpy.exe").is_file()
            and not self.sdk_var.get().strip()
        ):
            approved = messagebox.askyesno(
                "Legacy Ren'Py support needed",
                "This game uses Ren'Py 6. SceneLight needs its verified Ren'Py 7 "
                "compatibility runtime to inspect it safely.\n\n"
                "Download: 158 MB from renpy.org\n"
                f"Version: Ren'Py {RENPY_VERSION}\n"
                "Verification: pinned SHA-256 checksum\n"
                f"Install location: {cached_renpy_executable() or compatibility_root()}\n\n"
                "It is used only by SceneLight and does not replace the game's engine. "
                "Download it now?",
                icon="question",
            )
            if approved:
                self._start_operation(
                    "compatibility",
                    [str(preferred_runtime_python()), "-m", "scenelight.compatibility"],
                )
            return
        self._start_operation("scan", self._command("scan"))

    def _verify(self) -> None:
        self._start_operation("verify", self._command("verify"))

    def _install(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        updating = bool(self._project_inspection and self._project_inspection.managed_install_ready)
        approved = messagebox.askyesno(
            "Update SceneLight copy?" if updating else "Create a SceneLight copy?",
            (
                "Update the existing SceneLight copy of:\n\n"
                if updating
                else "Create a separate SceneLight-enabled copy of:\n\n"
            )
            + f"{selection.root}\n\n"
            + ("The copy's saves and lighting choices will be kept. " if updating else "")
            + "The selected source game will not be changed.\n\nContinue?",
            icon="question",
        )
        if approved:
            self._start_operation("install", self._command("install"))

    def _attach(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        approved = messagebox.askyesno(
            "Add SceneLight to this game?",
            "Add SceneLight to:\n\n"
            f"{selection.root}\n\n"
            "Story, art, and saves will not be changed. Older Ren'Py games may need a "
            "reversible update to their normal executable; SceneLight backs up the original "
            "first.\n\nContinue?",
            icon="question",
        )
        if approved:
            self._start_operation("attach", self._command("attach"))

    def _launch_attached(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        inspection = self._project_inspection
        command = (
            inspection.direct_launch_command
            if inspection is not None and inspection.direct_install_ready
            else installed_direct_launch_command(selection.root)
        )
        if command is None:
            messagebox.showerror(
                "Game executable not found",
                "SceneLight is installed, but this source project has no bundled executable and "
                "its recorded Ren'Py playback runtime is unavailable. Open the folder in its "
                "matching Ren'Py SDK.",
            )
            return
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen(list(command), cwd=selection.root, creationflags=flags)
        self.operation_var.set("Game launched with SceneLight.")

    def _install_components(
        self,
        *,
        continue_setup: bool = False,
        include_preview: bool = False,
    ) -> None:
        source_install = SDK_LAUNCHER.is_file() and not getattr(sys, "frozen", False)
        include_cuda = self.cuda_var.get() and not include_preview
        state = dependency_state(
            include_preview=include_preview,
            include_cuda=include_cuda,
            source_mode=source_install,
        )
        if not include_preview:
            self._dependency_state = state
        if state.ready:
            self._refresh_dependency_display()
            self.operation_var.set(
                "Preview components are already verified."
                if include_preview
                else "All required SceneLight components are already verified."
            )
            if continue_setup:
                self.after(50, self._run_primary_action)
            return
        destination = f"SceneLight runtime:\n{state.python_executable.parent}"
        exact = "\n".join(f"  • {format_requirement(item)}" for item in state.missing)
        bootstrap = ""
        if source_install and not state.runtime_ready:
            bootstrap = (
                "\n\nSceneLight will first install its runtime and prepare these installer tools:\n"
                + "\n".join(f"  • {format_requirement(item)}" for item in PACKAGING_REQUIREMENTS)
            )
        cuda_only = (
            include_cuda and state.runtime_ready and set(state.missing) == {CUDA_REQUIREMENT}
        )
        if cuda_only:
            gpu = ", ".join(self._cuda_support.devices) if self._cuda_support else "your NVIDIA GPU"
            approved = messagebox.askyesno(
                "Speed up setup with your GPU?",
                f"Detected: {gpu}\n\nThis GPU can speed up first-time analysis. "
                f"SceneLight can also continue using the CPU.\n\nOptional component:\n{exact}"
                f"\n\nLocation:\n{destination}\n\nYes: install CUDA acceleration.\nNo: continue with CPU analysis.",
            )
        else:
            approved = messagebox.askyesno(
                "Set up Preview & Calibrator?" if include_preview else "Set up SceneLight?",
                f"SceneLight will install and verify these "
                f"{'optional Preview components' if include_preview else 'selected components'}:"
                f"\n\n{exact}"
                f"{bootstrap}\n\nLocation:\n{destination}\n\nContinue?",
            )
        if approved:
            self._continue_after_components = continue_setup
            self._start_operation(
                "preview-components" if include_preview else "components",
                dependency_install_commands(
                    include_preview=include_preview,
                    include_cuda=include_cuda,
                    source_mode=source_install,
                ),
            )
        else:
            self._continue_after_components = False
            if cuda_only:
                self.cuda_var.set(False)
                if continue_setup:
                    self.after(50, self._run_primary_action)

    def _open_preview(self) -> None:
        selection = self._selection()
        project_root = selection.root if selection.valid else None
        state = dependency_state(
            include_preview=True,
            # Preview renders through OpenGL. CUDA is optional analysis
            # acceleration and must not gate opening an already usable viewer.
            include_cuda=False,
            source_mode=SDK_LAUNCHER.is_file() and not getattr(sys, "frozen", False),
        )
        if not state.ready:
            self._install_components(include_preview=True)
            return
        runtime_python = preferred_runtime_python()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = (
            [str(runtime_python), str(PREVIEW_LAUNCHER)]
            if PREVIEW_LAUNCHER.is_file()
            else [str(runtime_python), "-m", "scenelight.preview"]
        )
        if project_root is not None:
            command.extend(("--project", str(project_root)))
        try:
            subprocess.Popen(
                command,
                cwd=SOURCE_ROOT,
                creationflags=flags,
            )
        except OSError as error:
            messagebox.showerror("Preview could not start", str(error))
            return
        self.operation_var.set("Starting Preview & Calibrator in its own window…")

    def _remove(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        approved = messagebox.askyesno(
            "Remove SceneLight copy?",
            "This removes only SceneLight's separate copy and its generated analysis.\n\n"
            f"The selected game remains untouched:\n{selection.root}\n\n"
            "You can install SceneLight again later. Continue?",
            icon="warning",
        )
        if approved:
            self._start_operation("remove", self._command("remove"))

    def _remove_current(self) -> None:
        if self._attached:
            self._unembed()
        else:
            self._remove()

    def _embed(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        approved = messagebox.askyesno(
            "Embed SceneLight for mod development?",
            "Add the SceneLight runtime and developer API to:\n\n"
            f"{selection.root}\n\n"
            "Use this for a mod project that should include SceneLight in its normal build. "
            "Story, art, and saves will not be changed. Older Ren'Py projects may need a "
            "reversible update to their normal executable; SceneLight backs up the original "
            "first.\n\nContinue?",
            icon="warning",
        )
        if approved:
            self._start_operation("embed", self._command("embed"))

    def _refresh_embed(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        approved = messagebox.askyesno(
            "Refresh SceneLight?",
            "SceneLight will update new or changed backgrounds, videos, scripts, and sprite "
            "forms. The current installation will keep working if the refresh fails. Story, "
            "art, and saves will not be changed.\n\n"
            f"{selection.root}\n\nContinue?",
            icon="question",
        )
        if approved:
            self._start_operation("refresh", self._command("refresh"))

    def _update_existing_install(self, inspection: ProjectInspection) -> None:
        relation = inspection.preferred_release_relation
        if relation is None or not relation.replacement_available:
            return
        operation = inspection.release_update_operation
        if operation is None:
            return
        direct = operation == "refresh"
        if relation.kind == "downgrade":
            title = "Replace a newer SceneLight version?"
            opening = (
                f"{relation.installed_label[:1].upper()}{relation.installed_label[1:]} is "
                "installed, but this package is "
                f"SceneLight {__version__}. Replacing it may remove newer behavior."
            )
        elif relation.kind == "different_build":
            title = "Update SceneLight?"
            opening = f"SceneLight {__version__} is already installed."
        elif relation.kind == "pre_release":
            title = f"Update pre-1.0 SceneLight to {__version__}?"
            opening = "This game has a SceneLight version from before 1.0.0."
        else:
            title = f"Update to SceneLight {__version__}?"
            opening = (
                f"{relation.installed_label[:1].upper()}{relation.installed_label[1:]} "
                "is currently installed."
            )
        if direct:
            completion_safety = (
                "Your game, saves, and settings will be kept. If the update fails, your current "
                "installation will stay in place."
            )
        else:
            completion_safety = (
                "Your original game will not be changed. If the update fails, your current copy "
                "will stay in place."
            )
        approved = messagebox.askyesnocancel(
            title,
            opening
            + "\n\n"
            + completion_safety
            + "\n\nYes: update\nNo: keep the current installation and play\nCancel: go back",
            icon="question" if relation.kind != "downgrade" else "warning",
        )
        if approved is None:
            return
        if not approved:
            if direct:
                self._launch_attached()
            else:
                self._launch()
            return
        self._start_operation(operation, self._command(operation))

    def _unembed(self) -> None:
        selection = self._selection()
        if selection.root is None:
            return
        approved = messagebox.askyesno(
            "Remove SceneLight from this project?",
            "SceneLight will stop if it finds changed or unknown files, so project work is not "
            "removed by mistake. Older games will have their original executable restored, and "
            "current saves are backed up first.\n\n"
            f"{selection.root}\n\nContinue?",
            icon="warning",
        )
        if approved:
            self._start_operation("unembed", self._command("unembed"))

    def _cancel_operation(self) -> None:
        """Cancel the supervised CLI operation without freezing the Setup UI."""

        if not self._running or self._cancel_requested.is_set():
            return
        self._cancel_requested.set()
        self.operation_var.set("Cancelling the current operation…")
        if self.cancel_operation_button is not None:
            self.cancel_operation_button.configure(state="disabled", text="Cancelling…")
        process = self._process
        if process is not None:
            threading.Thread(
                target=terminate_process_tree,
                args=(process,),
                name="scenelight-cancel-operation",
                daemon=True,
            ).start()

    def _start_operation(self, operation: str, command: list[str] | list[list[str]]) -> None:
        if self._running:
            return
        commands = normalize_command_batch(command)
        self._cancel_requested.clear()
        self._running = True
        self._active_operation = operation
        self._update_reason = ""
        previous_session = diagnostics.current_session()
        if previous_session is not None and previous_session._summary.get("operation") == "startup":
            previous_session.update(status="ready")
        diagnostics.start_session("setup", operation=operation, project=self.project_var.get())
        self._component_download = ""
        self._refresh_project_state()
        _title, _subtitle, initial_status = operation_copy(operation)
        self.operation_var.set(initial_status)
        self.progress_frame.grid()
        if self.cancel_operation_button is not None:
            self.cancel_operation_button.configure(state="normal", text="Cancel")
            self.cancel_operation_button.grid()
        self._progress_phase = None
        self._progress_started_at = 0.0
        self._progress_origin = 0
        self._progress_current = 0
        self._progress_total = 0
        self._latest_progress = None
        self._progress_indeterminate = False
        self._last_elapsed_refresh = 0.0
        if operation in {"components", "preview-components"}:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=len(commands), value=0)
        else:
            self.progress.configure(mode="indeterminate", maximum=100, value=0)
            self.progress.start(12)
        for item in commands:
            self._append_log("\n> " + subprocess.list2cmdline(item) + "\n")

        def worker() -> None:
            output: list[str] = []
            environment = operation_environment()
            session = diagnostics.current_session()
            if session is not None:
                environment["SCENELIGHT_LOG_SESSION"] = str(session.path)
            flags = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0
            )
            try:
                return_code = 0
                for command_index, item in enumerate(commands, start=1):
                    if self._cancel_requested.is_set():
                        return_code = 130
                        break
                    self._events.put(
                        ("command-start", operation, command_index, len(commands), item)
                    )
                    self._process = subprocess.Popen(
                        item,
                        cwd=str(SOURCE_ROOT),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        env=environment,
                        creationflags=flags,
                    )
                    # Cancel may arrive while Popen is creating the process,
                    # before the UI can see self._process. Close that race
                    # before a silent child's stdout can block this worker.
                    if self._cancel_requested.is_set():
                        terminate_process_tree(self._process)
                    assert self._process.stdout is not None
                    for line in self._process.stdout:
                        output.append(line)
                        if session is not None:
                            session.output(line)
                        self._events.put(("log", line, session is not None))
                    return_code = self._process.wait()
                    diagnostics.event(
                        operation,
                        "Command exited",
                        "error" if return_code else "info",
                        command=item,
                        exit_code=return_code,
                        pid=self._process.pid,
                    )
                    self._process = None
                    self._events.put(("command-finished", operation, command_index, len(commands)))
                    if operation in {"components", "preview-components"}:
                        self._events.put(("dependency-check",))
                    if return_code != 0 or self._cancel_requested.is_set():
                        if self._cancel_requested.is_set():
                            return_code = 130
                        break
            except Exception as error:  # Process failures belong in the visible setup log.
                if session is not None:
                    session.exception(operation, error)
                detail = f"{type(error).__name__}: {error}\n"
                output.append(detail)
                self._events.put(("log", detail))
                return_code = 1
            finally:
                self._process = None
            combined = "".join(output)
            payload = extract_last_json(combined)
            if (
                return_code == 0
                and operation
                in {
                    "scan",
                    "attach",
                    "install",
                    "verify",
                    "launch",
                    "remove",
                    "embed",
                    "refresh",
                    "unembed",
                    "inspector",
                }
                and payload is None
            ):
                return_code = 1
                self._events.put(("log", "SceneLight finished without a readable result report.\n"))
            self._events.put(
                (
                    "done",
                    operation,
                    return_code,
                    payload,
                    combined,
                    self._cancel_requested.is_set(),
                )
            )

        threading.Thread(target=worker, name=f"scenelight-{operation}", daemon=True).start()

    def _command_started(
        self,
        operation: str,
        current: int,
        total: int,
        command: list[str],
    ) -> None:
        if operation not in {"components", "preview-components"}:
            return
        self._component_download = ""
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=total, value=current - 1)
        self.operation_var.set(component_command_status(command, current, total))

    def _apply_component_progress(self, update: ComponentProgress) -> None:
        if update.active_download:
            self._component_download = update.active_download
        self.operation_var.set(update.message)
        if update.current is None or update.total is None or update.total <= 0:
            return
        self.progress.stop()
        self.progress.configure(
            mode="determinate",
            maximum=update.total,
            value=min(update.current, update.total),
        )

    def _drain_events(self) -> None:
        deadline = time.monotonic() + 0.012
        try:
            while time.monotonic() < deadline:
                event = self._events.get_nowait()
                if event[0] == "log":
                    line = str(event[1])
                    self._append_log(line, record=not (len(event) > 2 and event[2]))
                    if line.startswith("SceneLight update: ") and self._active_operation in {
                        "install",
                        "refresh",
                    }:
                        self._update_reason = line.removeprefix("SceneLight update: ").strip()
                        self.workflow_subtitle_var.set(self._update_reason)
                    if self._active_operation in {"components", "preview-components"}:
                        component_update = parse_component_progress(
                            line,
                            self._component_download,
                        )
                        if component_update is not None:
                            self._apply_component_progress(component_update)
                    progress = parse_progress(line)
                    if progress is not None and progress_moves_forward(
                        progress,
                        previous_phase=self._progress_phase,
                        previous_current=self._progress_current,
                        previous_total=self._progress_total,
                    ):
                        now = time.monotonic()
                        if progress.phase != self._progress_phase or (
                            progress.total != self._progress_total
                            and not progress.phase.startswith("stage-")
                        ):
                            self._progress_phase = progress.phase
                            self._progress_started_at = now
                            self._progress_origin = progress.current
                        self._progress_current = progress.current
                        self._progress_total = progress.total
                        self._latest_progress = progress
                        elapsed = now - self._progress_started_at
                        completed = max(0, progress.current - self._progress_origin)
                        if progress.total == 0 and progress.item != "Complete":
                            if not getattr(self, "_progress_indeterminate", False):
                                self.progress.stop()
                                self.progress.configure(mode="indeterminate", maximum=100, value=0)
                                self.progress.start(20)
                                self._progress_indeterminate = True
                        else:
                            self.progress.stop()
                            self.progress.configure(
                                mode="determinate",
                                maximum=max(1, progress.total),
                                value=progress.current if progress.total else 1,
                            )
                            self._progress_indeterminate = False
                        self.operation_var.set(
                            format_progress_status(
                                progress,
                                elapsed_seconds=elapsed,
                                completed_since_start=completed,
                            )
                        )
                elif event[0] == "done":
                    self._operation_done(
                        str(event[1]),
                        int(event[2]),
                        event[3],
                        str(event[4]),
                        cancelled=bool(event[5]) if len(event) > 5 else False,
                    )
                elif event[0] == "command-start" and isinstance(event[4], list):
                    self._command_started(
                        str(event[1]),
                        int(event[2]),
                        int(event[3]),
                        event[4],
                    )
                elif event[0] == "command-finished" and str(event[1]) in {
                    "components",
                    "preview-components",
                }:
                    self.progress.stop()
                    self.progress.configure(
                        mode="determinate",
                        maximum=int(event[3]),
                        value=int(event[2]),
                    )
                elif event[0] == "dependency-check":
                    self._refresh_dependency_display()
                elif event[0] == "project-sources":
                    self._finish_project_sources(event[1], event[2])
                elif event[0] == "project-inspection" and isinstance(event[3], ProjectInspection):
                    self._finish_project_inspection(int(event[1]), str(event[2]), event[3])
                elif event[0] == "cuda-detection" and isinstance(event[2], CudaSupport):
                    self._finish_cuda_detection(event[2], int(event[1]))
        except queue.Empty:
            pass
        self._refresh_elapsed_progress()
        self.after(10 if not self._events.empty() else 100, self._drain_events)

    def _refresh_elapsed_progress(self) -> None:
        progress = getattr(self, "_latest_progress", None)
        if (
            self._active_operation is None
            or progress is None
            or not progress.phase.startswith("stage-")
            or progress.item == "Complete"
        ):
            return
        now = time.monotonic()
        if now - getattr(self, "_last_elapsed_refresh", 0.0) < 0.5:
            return
        self._last_elapsed_refresh = now
        self.operation_var.set(
            format_progress_status(
                progress,
                elapsed_seconds=now - self._progress_started_at,
                completed_since_start=max(0, progress.current - self._progress_origin),
            )
        )

    def _operation_done(
        self,
        operation: str,
        return_code: int,
        payload: object,
        output: str = "",
        *,
        cancelled: bool = False,
    ) -> None:
        session = diagnostics.current_session()
        if session is not None:
            session.update(
                status="cancelled" if cancelled else "failed" if return_code else "succeeded",
                exit_code=return_code,
                managed_project=payload.get("managed_project")
                if isinstance(payload, dict)
                else None,
                failure=describe_operation_failure(output)[0]
                if return_code and not cancelled
                else "",
            )
        continue_setup = operation == "components" and self._continue_after_components
        if operation == "components":
            self._continue_after_components = False
        self._running = False
        self._active_operation = None
        self._component_download = ""
        if self.cancel_operation_button is not None:
            self.cancel_operation_button.grid_remove()
            self.cancel_operation_button.configure(state="normal", text="Cancel")
        self.progress.stop()
        if return_code == 0 and operation in {"components", "preview-components"}:
            self.progress.configure(mode="determinate", maximum=100, value=100)
        else:
            self.progress.configure(mode="indeterminate", maximum=100, value=0)
        result = payload if isinstance(payload, dict) else {}
        if cancelled:
            continue_setup = False
            self.operation_var.set("Operation cancelled.")
            self._append_log(f"[{operation} cancelled by user]\n")
        elif return_code == 0:
            completion = {
                "components": "SceneLight component setup completed.",
                "compatibility": "Legacy game support is ready.",
                "scan": "Scan complete.",
                "attach": "SceneLight installation completed.",
                "install": "SceneLight copy created successfully.",
                "verify": "SceneLight verification completed.",
                "launch": "The game started successfully.",
                "remove": "SceneLight removal completed.",
                "embed": "Developer API installation completed.",
                "refresh": "SceneLight update completed.",
                "unembed": "Developer API removal completed.",
                "inspector": "In-game inspector setting applied. Restart the game to use it.",
            }
            self.operation_var.set(completion.get(operation, "Operation completed successfully."))
            if operation == "inspector" and result.get("installed") is False:
                self.operation_var.set("Inspector choice saved for the next installation.")
            if result.get("update_mode") == "runtime-only":
                self.operation_var.set(
                    "SceneLight updated. Existing sprite and background analysis was reused."
                )
            elif result.get("update_mode") == "settings-only":
                self.operation_var.set(
                    "Settings updated. Existing sprite and background maps were kept."
                )
            elif result.get("update_mode") == "unchanged":
                self.operation_var.set(
                    "SceneLight is already current. No assets needed rebuilding."
                )
            if operation == "compatibility":
                self._scan()
                return
            if operation == "scan":
                self._last_scan_payload = result
                selection = self._selection()
                needs_review = character_review_required(
                    result,
                    installed=self._attached,
                    force=self._force_character_review,
                )
                if (
                    selection.valid
                    and selection.root is not None
                    and self._review_completed_for != selection.root
                    and needs_review
                ):
                    self._scan_ok = False
                    self._character_review_pending_for = selection.root
                    self._force_character_review = False
                    self.preview_var.set(
                        "Scan complete. Review the detected character families before installing."
                    )
                    self.operation_var.set("Review characters to continue.")
                    self.progress_frame.grid_remove()
                    self._refresh_project_state()
                    self._show_character_review(result)
                    return
                self._force_character_review = False
                self._character_review_pending_for = None
                if selection.valid and selection.root is not None:
                    self._review_completed_for = selection.root
                self._scan_ok = True
                self.preview_var.set(describe_scan(result))
            elif operation in {"attach", "install", "verify"}:
                launcher = result.get("launcher")
                self._last_launcher = Path(str(launcher)) if launcher else None
                skipped = result.get("skipped_sprites", [])
                skipped_count = len(skipped) if isinstance(skipped, list) else 0
                warning = (
                    f" {skipped_count} incompatible sprite form(s) were skipped and listed "
                    "in the activity log; all compatible assets remain enabled."
                    if skipped_count
                    else ""
                )
                if operation == "install":
                    self.preview_var.set(
                        f"Installed {result.get('scene_count', 0)} background(s) and "
                        f"{result.get('sprite_count', 0)} sprite form(s) in a separate copy. "
                        "Start that copy with its normal game executable. The selected "
                        f"game was not changed.{warning}"
                    )
                elif operation == "attach":
                    self._last_launcher = None
                    self._attached = True
                    self.preview_var.set(
                        "SceneLight was added. For an older packaged game, the normal executable "
                        "now starts SceneLight and the original executable was backed up. Story, "
                        "art, and current saves "
                        f"were not changed.{warning}"
                    )
                if skipped_count:
                    names = []
                    for item in skipped:
                        if isinstance(item, dict):
                            names.append(str(item.get("sprite", "unknown sprite")))
                    self._append_log(
                        "[warning] skipped incompatible sprite forms: " + ", ".join(names) + "\n"
                    )
            elif operation == "launch":
                self.operation_var.set("Game launched with its native Ren'Py engine.")
            elif operation == "remove":
                self._last_launcher = None
                if result.get("removed"):
                    self.preview_var.set(
                        "SceneLight's managed copy was removed. The selected game was not changed."
                    )
                else:
                    self.preview_var.set(
                        "No managed copy existed. The selected game was not changed."
                    )
            elif operation == "unembed":
                self._attached = False
                if result.get("removed"):
                    bridge = result.get("save_compatibility_bridge")
                    if bridge:
                        self.preview_var.set(
                            "SceneLight lighting was removed and the original game launcher was "
                            "restored. A small verified save bridge was kept because "
                            f"{result.get('newer_save_count', 0)} newer save file(s) still need it. "
                            "Current saves were backed up before removal."
                        )
                    else:
                        self.preview_var.set(
                            "SceneLight was removed. Current saves were backed up before the "
                            "original launcher was restored."
                        )
                else:
                    self.preview_var.set("SceneLight was not installed in this game.")
            elif operation == "embed":
                self._attached = True
                self._last_launcher = None
                self.preview_var.set(
                    f"Installed {result.get('owned_file_count', 0)} SceneLight file(s) without "
                    "editing story or art files. For older packaged games, the "
                    "normal executable now loads SceneLight and its original is backed up."
                    + skipped_asset_notice(result)
                )
            elif operation == "refresh":
                self._attached = True
                self._scan_ok = False
                self._last_launcher = None
                warning = result.get("cleanup_warning")
                self.preview_var.set(
                    f"Refreshed {result.get('owned_file_count', 0)} SceneLight file(s). New or "
                    "changed backgrounds, videos, selected characters, and sprite forms were "
                    "updated; story, art, and saves were not edited."
                    + (f" Cleanup note: {warning}" if warning else "")
                    + skipped_asset_notice(result)
                )
            elif operation == "components":
                importlib.invalidate_caches()
                self._begin_cuda_detection()
                self._refresh_dependency_display()
                if self._dependency_state is not None and self._dependency_state.ready:
                    self.operation_var.set(
                        "SceneLight is ready. Scanning this game…"
                        if continue_setup
                        else "All SceneLight components are installed and verified."
                    )
                else:
                    self.operation_var.set(
                        "Component installation finished, but one or more versions did not verify."
                    )
            elif operation == "preview-components":
                importlib.invalidate_caches()
                self.operation_var.set("Preview components installed. Click Open Preview again.")
            self._append_log(f"[{operation} finished successfully]\n")
        else:
            continue_setup = False
            title, message = describe_operation_failure(output)
            self.operation_var.set(message.split(". ", 1)[0] + ".")
            self._append_log(f"[{operation} failed with exit code {return_code}]\n")
            messagebox.showerror(title, message)
        self._refresh_dependency_display()
        if operation == "inspector":
            self._inspector_selection_key = None
        if self._cuda_apply_when_idle and self._cuda_support is not None:
            self._finish_cuda_detection(self._cuda_support)
        if operation in {
            "attach",
            "install",
            "verify",
            "remove",
            "embed",
            "refresh",
            "unembed",
            "inspector",
        }:
            self._begin_project_inspection()
        else:
            self._refresh_project_state()
        if continue_setup and self._dependency_state is not None and self._dependency_state.ready:
            self.after(150, self._run_primary_action)
        self.after(3200, self._hide_idle_progress)

    def _hide_idle_progress(self) -> None:
        if not self._running and not self._project_checking:
            self.progress_frame.grid_remove()

    def _open_project(self) -> None:
        selection = self._selection()
        if selection.root is not None and selection.root.is_dir():
            os.startfile(selection.root)  # type: ignore[attr-defined]

    def _launch(self) -> None:
        self._start_operation("launch", self._command("launch"))

    def _close(self) -> None:
        if self._running and not messagebox.askyesno(
            "Operation still running",
            "SceneLight is still working. Closing now can interrupt analysis. Close anyway?",
            icon="warning",
        ):
            return
        if self._process is not None:
            self._cancel_requested.set()
            terminate_process_tree(self._process)
        self._close_character_review_window()
        self.destroy()

    def destroy(self) -> None:
        """Tear down Tk once; Tk itself owns and removes queued child callbacks."""

        if self._destroying:
            return
        self._destroying = True
        super().destroy()


def main(initial_project: str | None = None, *, developer_mode: bool = False) -> int:
    if initial_project is None:
        initial_project = initial_project_from_arguments(sys.argv[1:])
    if not developer_mode:
        developer_mode = developer_mode_from_arguments(sys.argv[1:])
    app = SceneLightSetup(initial_project, developer_mode=developer_mode)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
