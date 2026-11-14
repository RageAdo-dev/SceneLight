"""Estimate remaining setup work from timed phases of successful operations."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

from .runtime import log_privacy

_DIMENSIONS = {
    "stage-source-index": "sources",
    "scan-files": "sources",
    "resolver-inventory": "story",
    "resolver-parallel": "forms",
    "resolver": "forms",
    "form-inventory": "forms",
    "resolver-backgrounds": "backgrounds",
    "scene": "backgrounds",
    "stage-background-fields": "backgrounds",
    "stage-background-cache": "backgrounds",
    "transport": "transport",
    "form": "maps",
    "stage-install-verify": "files",
}


@dataclass(frozen=True)
class TimingSample:
    mode: str
    steps: tuple[tuple[str, float, int], ...]

    @property
    def sizes(self):
        return {
            _DIMENSIONS[key]: total for key, _, total in self.steps if key in _DIMENSIONS and total
        }

    @classmethod
    def read(cls, data):
        if not isinstance(data, dict) or data.get("schema") != 1:
            return None
        rows = data.get("steps")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
            return None
        steps = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                return None
            key, seconds, total = row
            if not (
                isinstance(key, str)
                and isinstance(total, int)
                and 0 <= total <= 2**53
                and isinstance(seconds, (float, int))
                and 0 <= seconds < 604800
            ):
                return None
            steps.append((key, seconds, total))
        if not isinstance(data.get("mode"), str):
            return None
        return cls(data["mode"], tuple(steps))


def previous_runs(root: Path, project: str, operation: str) -> list[TimingSample]:
    """Only session summaries are read. Detailed console logs can be several MiB."""
    target = os.path.normcase(log_privacy.mask_text(project))
    try:
        recent = sorted(root.iterdir(), key=lambda p: p.name, reverse=True)[:48]
    except OSError:
        return []
    samples = []
    for folder in recent:
        try:
            row = json.loads((folder / "session.json").read_bytes())
            if (
                not isinstance(row, dict)
                or row.get("status") != "succeeded"
                or row.get("operation") != operation
            ):
                continue
            if (
                not isinstance(row.get("project"), str)
                or os.path.normcase(row["project"]) != target
            ):
                continue
            sample = TimingSample.read(row.get("setup_timing"))
            if sample is not None:
                samples.append(sample)
                if len(samples) == 8:
                    break
        except (OSError, ValueError, RecursionError):
            continue
    return samples


@lru_cache(maxsize=1)
def _reference_runs():
    path = Path(__file__).parent / "assets/setup_timing.json"
    try:
        return tuple(s for row in json.loads(path.read_bytes()) if (s := TimingSample.read(row)))
    except (OSError, ValueError, TypeError):
        return ()


class RunTiming:
    def __init__(self, operation: str, now: float):
        self.operation = operation
        self.mode = {
            "embed": "install",
            "attach": "install",
            "install": "install",
            "scan": "scan",
        }.get(operation, "")
        self.history: list[TimingSample] = []
        self.steps: list[tuple[str, float, int]] = []
        self.started = now
        self.capture_finished: float | None = None
        self.phase = "start"
        self.since = now
        self.total = 0
        self.sizes: dict[str, int] = {}
        self._last_display = None
        self._display_label = ""
        self._has_estimate = False

    def label(self, now: float, current_left: float | None) -> str:
        key = (int(now), self.mode, self.phase, self.total, len(self.history))
        if self.operation == "refresh" and not self.mode:
            return "Checking update size…"
        if key != self._last_display:
            self._last_display = key
            bounds = self.estimate(now, current_left)
            self._display_label = (
                "Recalculating total time…"
                if bounds is None and self._has_estimate
                else remaining_label(bounds)
            )
            self._has_estimate |= bounds is not None
        return self._display_label

    def observe(self, phase: str, total: int, now: float) -> None:
        if not phase:
            return
        if phase != self.phase:
            if len(self.steps) < 256:
                self.steps.append((self.phase, max(0.0, now - self.since), self.total))
            self.phase, self.since, self.total = phase, now, 0
        self.total = max(total, self.total)
        if total and phase in _DIMENSIONS:
            self.sizes[_DIMENSIONS[phase]] = total

    def snapshot(self, now: float) -> dict | None:
        if not self.mode or len(self.steps) >= 256:
            return None
        steps = [*self.steps, (self.phase, max(0.0, now - self.since), self.total)]
        return {"schema": 1, "mode": self.mode, "steps": [[k, round(t, 3), n] for k, t, n in steps]}

    def _large_install_bounds(self, now: float):
        forms, backgrounds = self.sizes.get("forms", 0), self.sizes.get("backgrounds", 0)
        bounds = []
        for sample in _reference_runs():
            if sample.mode != "install-total" or len(sample.steps) != 2:
                continue
            (first, capture, n_forms), (last, build, n_backgrounds) = sample.steps
            if (first, last) != ("capture-complete", "finish") or not n_forms or not n_backgrounds:
                continue
            f, b = forms / n_forms, backgrounds / n_backgrounds
            if not (0.5 <= f <= 2 and 0.5 <= b <= 2):
                continue
            # Captures scale with forms; building maps and fields uses both kinds of artwork.
            tail = build * (b + f) / 2
            if self.capture_finished is None:
                duration, elapsed = capture * f + tail, now - self.started
            else:
                duration, elapsed = tail, now - self.capture_finished
            if elapsed < duration * 1.55:
                bounds.append((max(1, duration * 0.55 - elapsed), duration * 1.55 - elapsed))
        if bounds:
            return min(lo for lo, _ in bounds), max(3, max(hi for _, hi in bounds))
        return None

    def estimate(self, now: float, current_left: float | None = None):
        local = [s for s in self.history if s.mode == self.mode]
        samples = local or [s for s in _reference_runs() if s.mode == self.mode]
        if not samples or (not local and not self.sizes):
            return None
        if self.mode == "install" and not local:
            if not self.sizes.get("forms") and self.sizes.get("backgrounds", 0) > 4 * max(
                (s.sizes.get("backgrounds", 0) for s in samples), default=0
            ):
                return None
            if not any(self.sizes.get(k) for k in ("forms", "backgrounds")):
                return None
            if self.phase not in {
                "form",
                "applied",
                "stage-install-verify",
                "stage-install-record",
            } and not self.phase.startswith("stage-runtime-"):
                broad = self._large_install_bounds(now)
                if broad is not None:
                    return broad
        predictions = []
        past = {}
        for key, duration, _ in self.steps:
            past.setdefault(key, []).append(duration)
        for sample in samples:
            sizes = sample.sizes
            ratios = [
                abs(math.log((1 + value) / (1 + sizes[k])))
                for k, value in self.sizes.items()
                if sizes.get(k)
            ]
            if not local and not ratios:
                continue
            # Match the second ownership check to the second check in the reference,
            # even when a renderer retry inserted extra capture phases in between.
            positions = [i for i, (key, _, _) in enumerate(sample.steps) if key == self.phase]
            phase_elapsed = max(0.0, now - self.since)
            same_phase = bool(positions)
            occurrence = len(past.get(self.phase, ()))
            if not positions:
                for earlier, duration, _ in reversed(self.steps):
                    phase_elapsed += duration
                    positions = [i for i, (key, _, _) in enumerate(sample.steps) if key == earlier]
                    if positions:
                        occurrence = len(past[earlier]) - 1
                        break
                if not positions:
                    continue
            index = positions[min(occurrence, len(positions) - 1)]
            scale = {}
            for key, ref in sizes.items():
                count = self.sizes.get(key)
                if count is None and key == "maps" and self.mode == "install":
                    count = self.sizes.get("forms")
                if count is None and key == "transport" and self.mode == "install":
                    count = self.sizes.get("backgrounds")
                if count is not None:
                    scale[key] = count / ref
            rates = []
            visits = {}
            remaining = 0.0
            pace = 1.0
            for i, (key, seconds, _) in enumerate(sample.steps):
                factor = scale.get(_DIMENSIONS.get(key), 1.0)
                # Even an empty batch has a startup cost.
                expected = min(1.0, seconds) + max(0.0, seconds - 1) * factor
                if i < index:
                    occurrence = visits.get(key, 0)
                    visits[key] = occurrence + 1
                    measured = past.get(key, ())
                    if (
                        occurrence < len(measured)
                        and expected >= 1.5
                        and measured[occurrence] >= 0.5
                    ):
                        rates.append(measured[occurrence] / expected)
                    continue
                if i == index and rates:
                    pace = max(0.2, min(8.0, median(rates)))
                expected *= pace
                if i == index:
                    elapsed = phase_elapsed
                    if same_phase and current_left is not None:
                        expected = current_left
                    elif elapsed >= max(5.0, 2 * expected):
                        # A blocked or unusually slow step has exhausted its reference.
                        break
                    else:
                        expected = max(0.0, expected - elapsed)
                remaining += expected
            else:
                predictions.append((max(ratios, default=0.0), remaining))
        if not predictions:
            return None
        predictions.sort()
        best_distance = predictions[0][0]
        matches = [seconds for distance, seconds in predictions if distance <= best_distance + 0.7][
            :5
        ]
        spread = 0.22 if local and len(matches) >= 2 else 0.35 if local else 0.55
        if best_distance > math.log(4):
            # A project outside the measured sizes has a less predictable tail.
            spread = max(spread, 0.75)
        low = max(1, min(matches) * (1 - spread))
        high = max(3, max(matches) * (1 + spread))
        return low, high


def remaining_label(bounds) -> str:
    if bounds is None:
        return "Estimating total time…"
    low, high = bounds
    if high < 10:
        return "Under 10 sec left overall"
    if high < 90:
        return f"About {max(1, math.floor(low / 5) * 5)}–{math.ceil(high / 5) * 5} sec left overall"
    if high < 3600:
        if low < 60:
            return f"Under {math.ceil(high / 60)} min left overall"
        return f"About {max(1, math.floor(low / 60))}–{math.ceil(high / 60)} min left overall"
    return f"About {max(0.1, math.floor(low / 360) / 10):g}–{math.ceil(high / 360) / 10:g} hr left overall"
