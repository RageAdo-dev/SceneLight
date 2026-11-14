"""User-visible groups for the steps reported by Setup operations."""

from __future__ import annotations

from typing import NamedTuple


class Substep(NamedTuple):
    name: str
    description: str
    state: str
    tasks: tuple[str, ...]


class Stage(NamedTuple):
    name: str
    state: str
    steps: tuple[Substep, ...]


_INSTALL = (
    (
        "Check project",
        (
            (
                "Game files",
                "Read project files and check for edits",
                "stage-source-index scan scan-files",
            ),
            ("Installation", "Check the existing installation", "stage-install-verify"),
            ("Saved analysis", "Restore saved artwork analysis", "stage-cache-restore"),
            (
                "Renderer",
                "Start and check the game renderer",
                "compatibility-download renderer preflight",
            ),
        ),
    ),
    (
        "Capture artwork",
        (
            (
                "Find artwork",
                "Find artwork and check saved captures",
                "capture stage-capture-inputs stage-capture-reuse opening-game resolver-inventory resolver-families resolver-geometry resolver-catalog",
            ),
            ("Backgrounds", "Capture dynamic backgrounds", "resolver-backgrounds"),
            (
                "Sprite forms",
                "Resolve poses and run the capture workers",
                "resolver-plan resolver-restore resolver-resume resolver-checkpoints resolver-work resolver-parallel resolver-workers resolver-worker-cleanup resolver-worker-retry stage-worker-checkpoints resolver",
            ),
            (
                "Save captures",
                "Prepare and save captured artwork",
                "surface-deduplication surface-normalization composite-assembly stage-capture-save",
            ),
        ),
    ),
    (
        "Build lighting",
        (
            (
                "Background light",
                "Analyze backgrounds and pack their lighting",
                "stage-background-cache stage-background-fields stage-movie-prepare transport scene",
            ),
            (
                "Sprite maps",
                "Prepare and build sprite lighting maps",
                "form-inventory stage-form-cache form stage-form-workers stage-form-index",
            ),
            (
                "Save analysis",
                "Save lighting data for future updates",
                "stage-analysis-report stage-cache-save stage-cache-commit stage-cache-cleanup",
            ),
        ),
    ),
    (
        "Apply files",
        (
            ("Prepare", "Prepare the game runtime", "stage-runtime-setup"),
            ("Verify files", "Verify runtime files and maps", "stage-runtime-hashes verify-final"),
            (
                "Copy files",
                "Apply updated files to the game",
                "stage-runtime-copy stage-runtime-apply",
            ),
            (
                "Finish",
                "Record the installation and clean up",
                "stage-install-record stage-runtime-cleanup applied stage-workspace-cleanup",
            ),
        ),
    ),
)

_SCAN = (
    (
        "Read files",
        (
            ("Project", "Read the project structure and settings", "scan-1"),
            ("Working copy", "Prepare the inspection copy and read its files", "scan-2 scan-files"),
        ),
    ),
    (
        "Check runtime",
        (
            (
                "Start game",
                "Open the game with the selected runtime",
                "scan-3 compatibility-download renderer capture opening-game",
            ),
            ("Renderer", "Check that the renderer starts", "preflight"),
        ),
    ),
    (
        "Review assets",
        (
            ("Inventory", "Identify characters and backgrounds", "inventory"),
            ("Review", "Prepare the list of assets for review", "scan-4"),
        ),
    ),
)


def _locations(plan):
    return {
        phase: (i, j)
        for i, (_, steps) in enumerate(plan)
        for j, (_, _, phases) in enumerate(steps)
        for phase in phases.split()
    }


_INSTALL_LOCATIONS = _locations(_INSTALL)
_SCAN_LOCATIONS = _locations(_SCAN)


class StageProgress:
    def __init__(self, operation):
        self.plan = (
            _SCAN
            if operation == "scan"
            else _INSTALL
            if operation in {"embed", "refresh", "install", "attach"}
            else ()
        )
        self.current = (0, -1)
        self.tasks: dict[tuple[int, int], list[str]] = {}
        self.visited = {0}
        self.update_mode = ""
        self._snapshot = None

    def observe(self, phase, label, current):
        if not self.plan:
            return
        if self.plan is _SCAN:
            if phase == "scan":
                phase = f"scan-{current}"
                if phase in _SCAN_LOCATIONS:
                    i, j = _SCAN_LOCATIONS[phase]
                    label = _SCAN[i][1][j][1]
            elif phase.startswith(("resolver", "surface-", "composite-")):
                phase = "inventory"
            position = _SCAN_LOCATIONS.get(phase)
        else:
            if phase == "stage-install-verify" and max(self.visited) >= 2:
                phase = "verify-final"
            if phase == "stage-workspace-cleanup" and 3 not in self.visited:
                # Temporary inspection copies can also be cleaned up before capture.
                position = self.current
            else:
                position = _INSTALL_LOCATIONS.get(phase)
        if position is None or position[1] < 0:
            return
        tasks = self.tasks.setdefault(position, [])
        if self.current != position or not tasks or tasks[-1] != label:
            self.current = position
            self.visited.add(position[0])
            if label in tasks:
                tasks.remove(label)
            tasks.append(label)
            self._snapshot = None

    def set_update_mode(self, mode):
        if mode != self.update_mode:
            self.update_mode = mode
            self._snapshot = None

    def snapshot(self):
        if self._snapshot is None:
            self._snapshot = tuple(
                self._stage(i, name, steps) for i, (name, steps) in enumerate(self.plan)
            )
        return self._snapshot

    def _stage(self, index, name, steps):
        if self.current[0] == index:
            state = "active"
        elif index in self.visited:
            state = "done"
        elif index < max(self.visited) or (
            self.update_mode in {"unchanged", "runtime-only", "settings-only"} and index in {1, 2}
        ):
            state = "skipped"
        else:
            state = "pending"
        rows = []
        for j, (short, description, _) in enumerate(steps):
            position = (index, j)
            tasks = tuple(self.tasks.get(position, ()))
            if position == self.current:
                status = "active"
            elif tasks:
                status = "done"
            elif state in {"skipped", "done"}:
                status = "skipped"
            else:
                status = "pending"
            rows.append(Substep(short, description, status, tasks))
        return Stage(name, state, tuple(rows))
