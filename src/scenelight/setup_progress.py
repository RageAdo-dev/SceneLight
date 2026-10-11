"""Setup progress helpers shared by the controller and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .progress import STAGE_LABELS
from .setup_dependencies import DEPENDENCY_LABELS, PACKAGING_REQUIREMENTS

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
