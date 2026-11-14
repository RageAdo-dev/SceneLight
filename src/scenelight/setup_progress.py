"""Setup progress helpers shared by the controller and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .progress import STAGE_LABELS
from .runtime import log_privacy
from .setup_dependencies import DEPENDENCY_LABELS, PACKAGING_REQUIREMENTS
from .setup_stages import StageProgress
from .setup_timing import RunTiming

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

    @property
    def unit(self) -> str:
        if self.phase in {
            "resolver-parallel",
            "resolver",
            "form-inventory",
            "resolver-restore",
            "resolver-work",
        }:
            return "sprite form" if self.total == 1 else "sprite forms"
        if self.phase in {
            "scene",
            "transport",
            "resolver-backgrounds",
            "stage-background-cache",
            "stage-background-fields",
        }:
            return "background" if self.total == 1 else "backgrounds"
        if self.phase in {
            "stage-install-verify",
            "stage-runtime-copy",
            "stage-runtime-apply",
            "stage-runtime-hashes",
            "scan-files",
        }:
            return "file" if self.total == 1 else "files"
        if self.phase == "stage-worker-checkpoints":
            return "batch" if self.total == 1 else "batches"
        return ""


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
        "Processing sprite forms",
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
        re.compile(r"^SceneLight resolver capturing form (\d+)/(\d+)(?:: (.*))?$"),
        "resolver",
        "Resolving dynamic sprite forms",
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
            item = (groups[2] or "").strip() if len(groups) > 2 else ""
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


class OperationProgress:
    """Keep the operation clock, the current step and worker events independent."""

    def __init__(self, title: str, now: float, *, operation: str = ""):
        self.run = RunTiming(operation, now)
        self.started = self.step_started = self.step_started_rate = self.last_advance = now
        self.last_update = now
        self.step = ProgressUpdate("", title, 0, 0)
        self.origin = 0
        self.samples = 0
        self.batch_count = 0
        self.batches: dict[int, str] = {}
        self.batch_counts: tuple[tuple[int, int], ...] = ()
        self.batch_pace: dict[int, tuple[int, float, int, float]] = {}
        self.stages = StageProgress(operation)
        self.worker_note = ""
        self.sprite_summary = ""
        self.background_summary = ""

    def observe(self, line: str, now: float) -> None:
        line = line.rstrip()
        if line.startswith("SceneLight update plan: "):
            mode = line.removeprefix("SceneLight update plan: ")
            if mode in {"analysis", "runtime-only", "settings-only", "unchanged"}:
                self.run.mode = mode
                self.stages.set_update_mode(mode)
            return
        if not line.startswith(
            (
                "SceneLight ",
                "scene ",
                "form ",
                "transport ",
                "composite ",
                "surface ",
                "compatibility download ",
            )
        ):
            return
        if match := re.fullmatch(r"SceneLight sprite batches: (\d+)", line):
            self.batch_count = int(match[1])
            self.last_update = now
            self.batches.clear()
            self.batch_pace.clear()
            self.batch_counts = ()
            self.worker_note = ""
            return
        if match := re.fullmatch(r"SceneLight worker (\d+)/(\d+): (.+)", line):
            worker, total = int(match[1]), int(match[2])
            if not 1 <= worker <= total:
                return
            self.batch_count = total
            self.last_update = now
            status = match[3]
            if status in {"saved", "restored", "running"}:
                self.batches[worker] = status
                if self.worker_note.startswith(f"Worker {worker} "):
                    self.worker_note = ""
            else:
                self.batches[worker] = (
                    "retrying"
                    if status.startswith("retrying")
                    else "stopped"
                    if status == "stopped"
                    else "waiting"
                )
                self.batch_pace.pop(worker, None)
                if status.startswith("retrying"):
                    self.stages.observe("resolver-parallel", f"Retrying worker {worker}", 0)
                self.worker_note = f"Worker {worker} {log_privacy.mask_text(status)}"
                self.samples = 0
                self.origin = self.step.current
                self.step_started_rate = now
            return
        batch_counts = ()
        if line.startswith("SceneLight parallel forms ") and " | batches " in line:
            line, _, counts = line.partition(" | batches ")
            if re.fullmatch(r"\d+/\d+(?: \d+/\d+){0,5}", counts):
                batch_counts = tuple(tuple(map(int, pair.split("/"))) for pair in counts.split())
        if match := re.fullmatch(
            r"SceneLight capture outcome: (\d+) sprite forms ready "
            r"\((\d+) reused\); (\d+) skipped\. Background captures reused: (\d+)\.",
            line,
        ):
            ready, reused, skipped, _ = map(int, match.groups())
            self.run.sizes.update(forms=ready + skipped, maps=max(0, ready - reused))
            if self.run.capture_finished is None:
                self.run.capture_finished = now
            self.sprite_summary = f"{reused:,} sprites reused · {ready - reused:,} captured"
            if skipped:
                self.sprite_summary += f" · {skipped:,} skipped"
            return
        if match := re.fullmatch(
            r"SceneLight background cache: (\d+)/(\d+) reused; (\d+) analyzed", line
        ):
            self.background_summary = (
                f"{int(match[1]):,} backgrounds reused · {int(match[3]):,} analyzed"
            )
            return
        if match := re.fullmatch(
            r"SceneLight capture cache: (\d+) sprites, (\d+) backgrounds reused", line
        ):
            self.sprite_summary = f"{int(match[1]):,} sprites reused"
            self.background_summary = f"{int(match[2]):,} background captures reused"
            return
        if match := re.fullmatch(r"SceneLight (renderer|capture) (\d+)/(\d+): trying (.+)", line):
            title = (
                "Starting the game renderer" if match[1] == "renderer" else "Starting game capture"
            )
            progress = ProgressUpdate(
                match[1], title, 0, 0, f"Attempt {match[2]} of {match[3]} · {match[4]}"
            )
        elif line == "SceneLight opening game capture":
            progress = ProgressUpdate(
                "opening-game",
                "Loading the game for capture",
                0,
                0,
                "Waiting for Ren’Py to report its first asset",
            )
        elif line.startswith("SceneLight applied "):
            progress = ProgressUpdate(
                "applied",
                "Finishing the update",
                0,
                0,
                line.removeprefix("SceneLight applied ").rstrip("."),
            )
        else:
            progress = parse_progress(line)
        if progress is None:
            return
        if progress.phase == "resolver-workers" and self.step.phase == "resolver-parallel":
            # Runtime copies finish concurrently with captures.
            if not self.worker_note or self.worker_note.startswith("Preparing capture workers"):
                self.worker_note = (
                    f"Preparing capture workers ({progress.current} of {progress.total} ready)"
                )
            if progress.current == progress.total and self.worker_note.startswith(
                "Preparing capture workers"
            ):
                self.worker_note = ""
            return
        if progress.phase == "resolver-worker-cleanup":
            progress = ProgressUpdate(
                progress.phase, "Finishing sprite capture", 0, 0, "Releasing temporary game copies"
            )
        previous = self.step
        if not progress_moves_forward(
            progress,
            previous_phase=previous.phase,
            previous_current=previous.current,
            previous_total=previous.total,
        ):
            return
        if progress.phase != previous.phase or (
            previous.total and progress.total != previous.total
        ):
            self.step_started = self.step_started_rate = self.last_advance = now
            self.origin = progress.current
            self.samples = 0
        elif progress.current > previous.current:
            self.samples += 1
            self.last_advance = now
        self.step = progress
        self.run.observe(progress.phase, progress.total, now)
        self.last_update = now
        if (
            batch_counts
            and len(batch_counts) == self.batch_count
            and sum(done for done, _ in batch_counts) == progress.current
            and sum(size for _, size in batch_counts) == progress.total
            and all(0 <= done <= size for done, size in batch_counts)
        ):
            for worker, (done, size) in enumerate(batch_counts, 1):
                last = self.batch_pace.get(worker)
                if done == 0 or done == size:
                    self.batch_pace.pop(worker, None)
                elif last is None or done < last[2]:
                    self.batch_pace[worker] = (done, now, done, now)
                elif done > last[2]:
                    self.batch_pace[worker] = (last[0], last[1], done, now)
            self.batch_counts = batch_counts
        self.stages.observe(progress.phase, progress.label, progress.current)

    def milestone_states(self) -> tuple[tuple[str, str], ...]:
        return tuple((stage.name, stage.state) for stage in self.stages.snapshot())

    def step_seconds_left(self, now: float) -> float | None:
        step = self.step
        if step.phase == "resolver-parallel" and self.batch_counts:
            remaining = []
            for worker, (done, size) in enumerate(self.batch_counts, 1):
                if done >= size:
                    continue
                pace = self.batch_pace.get(worker)
                if pace is None:
                    return None
                first, started, latest, updated = pace
                if latest <= first or updated - started < 3 or now - updated >= 10:
                    return None
                remaining.append((size - done) * (updated - started) / (latest - first))
            return max(remaining, default=0.0)
        advanced = step.current - self.origin
        if (
            0 < step.current < step.total
            and advanced > 0
            and self.samples >= 2
            and self.last_advance - self.step_started_rate >= 3
            and now - self.last_advance < 10
        ):
            return (
                (step.total - step.current)
                * (self.last_advance - self.step_started_rate)
                / advanced
            )
        return None

    def timing(self, now: float) -> str:
        step = self.step
        parts = [f"Total elapsed {format_duration(now - self.started)}"]
        if step.phase:
            parts.append(f"This step {format_duration(now - self.step_started)}")
        remaining = self.step_seconds_left(now)
        if remaining is not None:
            parts.append(f"About {format_duration(remaining)} left in this step")
        if now - self.last_update >= 20 and step.phase:
            parts.append(f"Last update {format_duration(now - self.last_update)} ago")
        return "   ·   ".join(parts)

    def detail(self) -> str:
        if self.batch_count and self.step.phase in {"resolver-parallel", "resolver-worker-cleanup"}:
            saved = sum(status in {"saved", "restored"} for status in self.batches.values())
            line = f"Worker batches saved  {saved} of {self.batch_count}"
            return line + ("   ·   " + self.worker_note if self.worker_note else "")
        return log_privacy.mask_text(self.step.item) if self.step.item != "Complete" else ""

    def summary(self) -> str:
        return "   |   ".join(filter(None, (self.sprite_summary, self.background_summary)))

    def worker_states(self) -> tuple[str, ...]:
        if self.step.phase not in {"resolver-parallel", "resolver-worker-cleanup"}:
            return ()
        return tuple(self.batches.get(i + 1, "queued") for i in range(min(6, self.batch_count)))
