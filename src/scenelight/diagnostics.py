"""Local, bounded support sessions shared by Setup, CLI, capture and Preview.

No uploads or asset collection. Each process owns its journal so parallel capture
workers cannot corrupt one another's records. Export produces a readable report
and machine-readable evidence with personal paths and common secrets redacted.
"""

from __future__ import annotations

import hashlib
import heapq
import html
import importlib.metadata
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .release import release_content_sha256
from .runtime import log_privacy
from .sidecar import storage_root

SEGMENT_BYTES = 2 * 1024 * 1024
SEGMENTS = 4
_session = None
_lock = threading.RLock()


def logs_root() -> Path:
    return storage_root().parent / "logs"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _platform_description() -> str:
    # platform.platform() may launch `ver`/other subprocesses on Windows.
    # Diagnostics must stay cheap and independent of process-launch failures.
    if hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        return f"Windows {version.major}.{version.minor}.{version.build} · {'64' if sys.maxsize > 2**32 else '32'}-bit"
    if hasattr(os, "uname"):
        value = os.uname()
        return f"{value.sysname} {value.release} {value.machine}"
    return sys.platform


def _atomic_json(path: Path, payload) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(
                log_privacy.mask_value(payload),
                indent=2,
                default=lambda v: log_privacy.mask_text(str(v)),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, area: str, *, root: Path | None = None, existing: Path | None = None):
        self.area = area
        self.path = existing or (root or logs_root()) / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        )
        self.path.mkdir(parents=True, exist_ok=True)
        self.journal = self.path / f"events-{os.getpid()}.jsonl"
        self.console = self.path / f"console-{os.getpid()}.log"
        self._last_progress = 0.0
        self._console_stream = None
        self._console_bytes = self.console.stat().st_size if self.console.exists() else 0
        self._console_flushed = time.monotonic()
        self._owns_summary = existing is None
        self._guard = threading.RLock()
        self._started = time.monotonic()
        self._last_stage = ""
        self._sequence = 0
        self._capture_state = {"workers": {}}
        self._summary = {
            "schema": 1,
            "id": self.path.name,
            "area": area,
            "started": _stamp(),
            "version": __version__,
            "status": "running",
            "python": sys.version,
            "platform": _platform_description(),
            "executable": sys.executable,
        }
        if existing is None:
            runtime = Path(__file__).with_name("runtime") / "scenelight_runtime.rpy"
            self._summary["runtime_sha256"] = hashlib.sha256(runtime.read_bytes()).hexdigest()
            self._summary["build_sha256"] = release_content_sha256()
            self._summary["components"] = {}
            for name in (
                "numpy",
                "Pillow",
                "opencv-python-headless",
                "PySide6-Essentials",
                "PyOpenGL",
                "psutil",
                "cupy-cuda12x",
            ):
                try:
                    self._summary["components"][name] = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    self._summary["components"][name] = "not installed"
            _atomic_json(self.path / "session.json", self._summary)
        self.event("session", "Process joined support session", pid=os.getpid(), area=area)

    def event(self, stage: str, message: str, level: str = "info", **details) -> None:
        try:
            with self._guard:
                self._sequence += 1
                record = {
                    "time": _stamp(),
                    "elapsed_s": round(time.monotonic() - self._started, 3),
                    "pid": os.getpid(),
                    "sequence": self._sequence,
                    "area": self.area,
                    "stage": stage,
                    "level": level,
                    "message": str(message)[:65536],
                    "details": details,
                }
                if self.journal.exists() and self.journal.stat().st_size >= SEGMENT_BYTES:
                    for index in range(SEGMENTS - 1, 0, -1):
                        old = (
                            self.journal.with_suffix(f".jsonl.{index - 1}")
                            if index > 1
                            else self.journal
                        )
                        if old.exists():
                            os.replace(old, self.journal.with_suffix(f".jsonl.{index}"))
                with self.journal.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            log_privacy.mask_value(record),
                            default=lambda v: log_privacy.mask_text(str(v)),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                if level == "error" and self._owns_summary:
                    self.update(
                        error_count=self._summary.get("error_count", 0) + 1,
                        last_error=str(message)[:500],
                    )
        except OSError:
            # Logging must never turn an otherwise successful game operation into a failure.
            pass

    def _write_capture_state(self) -> None:
        try:
            _atomic_json(self.path / f"capture-state-{os.getpid()}.json", self._capture_state)
        except OSError:
            pass

    def capture_batch(self, sizes: list[int], restored: list[bool]) -> None:
        with self._guard:
            self._capture_state["workers"] = {
                str(i): {"assigned": size, "status": "restored" if saved else "queued"}
                for i, (size, saved) in enumerate(zip(sizes, restored), 1)
            }
            self._write_capture_state()

    def capture_status(self, worker: int | None, *, new_attempt=False, **details) -> None:
        # Keep the last observation even if thousands of skip messages rotate the journal.
        with self._guard:
            state = (
                self._capture_state.setdefault("main", {})
                if worker is None
                else self._capture_state["workers"].setdefault(str(worker), {})
            )
            if new_attempt:
                for key in set(state) - {"assigned"}:
                    del state[key]
            state.update(details, observed=_stamp())
            self._write_capture_state()

    def output(self, line: str) -> None:
        line = log_privacy.mask_text(line)
        try:
            with self._guard:
                if self._console_bytes >= SEGMENT_BYTES:
                    self.flush(close=True)
                    for index in range(SEGMENTS - 1, 0, -1):
                        old = (
                            self.console.with_suffix(f".log.{index - 1}")
                            if index > 1
                            else self.console
                        )
                        if old.exists():
                            os.replace(old, self.console.with_suffix(f".log.{index}"))
                    self._console_bytes = 0
                if self._console_stream is None:
                    self._console_stream = self.console.open("a", encoding="utf-8", buffering=65536)
                value = f"{_stamp()} {line.rstrip()[:65536]}\n"
                self._console_stream.write(value)
                self._console_bytes += len(value.encode("utf-8"))
                if time.monotonic() - self._console_flushed >= 0.5:
                    self.flush()
        except OSError:
            pass
        lower = line.lower()
        level = (
            "error"
            if re.search(r"\b(?:error|exception|traceback|failed|failure)\b", lower)
            else "warning"
            if "warning" in lower
            else "info"
        )
        progress = re.search(r"\b(\d+)/(\d+):", line)
        stage = re.match(r"SceneLight stage ([a-z-]+) ", line)
        stage_changed = stage is not None and stage[1] != self._last_stage
        self._last_stage = stage[1] if stage is not None else ""
        now = time.monotonic()
        if line.startswith(
            (
                "SceneLight worker ",
                "SceneLight sprite batches:",
                "SceneLight capture outcome:",
                "SceneLight background cache:",
                "SceneLight applied ",
                "SceneLight capture cache:",
            )
        ) and not line.startswith(("SceneLight worker copies ", "SceneLight worker cleanup ")):
            self.event("progress", line.rstrip(), level)
        elif level != "info" or line.startswith((">", "[")):
            self.event("output", line.rstrip(), level)
        elif progress and (
            stage_changed or progress[1] == progress[2] or now - self._last_progress >= 1.0
        ):
            self._last_progress = now
            self.event("progress", line.rstrip(), current=int(progress[1]), total=int(progress[2]))

    def update(self, **details) -> None:
        try:
            with self._guard:
                self.flush()
                if details.get("status") == "closed" and self._summary.get("error_count", 0):
                    details["status"] = "closed with errors"
                self._summary.update(details, updated=_stamp())
                _atomic_json(self.path / "session.json", self._summary)
        except OSError:
            pass

    def flush(self, *, close: bool = False) -> None:
        with self._guard:
            if self._console_stream is not None:
                try:
                    self._console_stream.flush()
                    if close:
                        self._console_stream.close()
                        self._console_stream = None
                except OSError:
                    pass
            self._console_flushed = time.monotonic()

    def exception(self, stage: str, error: BaseException) -> None:
        self.event(
            stage,
            str(error),
            "error",
            exception=type(error).__name__,
            traceback="".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )

    def attach_text(self, label: str, text: str) -> None:
        try:
            safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", log_privacy.mask_text(label))[:80]
            folder = self.path / "evidence"
            folder.mkdir(exist_ok=True)
            # Keep the useful tail of a runaway engine log, with the truncation explicit.
            raw = log_privacy.mask_text(text).encode("utf-8", "replace")
            if len(raw) > SEGMENT_BYTES:
                raw = (
                    b"[Earlier content omitted: attachment exceeded 2 MiB]\n" + raw[-SEGMENT_BYTES:]
                )
            (folder / (f"{os.getpid()}-{safe}-{uuid.uuid4().hex[:8]}.txt")).write_bytes(raw)
        except OSError:
            pass


def start_session(area: str, **context) -> Session | None:
    global _session
    try:
        with _lock:
            if _session is not None:
                _session.flush(close=True)
            _session = Session(area)
            _session.update(**context)
            return _session
    except OSError:
        return None


def current_session() -> Session | None:
    global _session
    with _lock:
        if _session is None and os.environ.get("SCENELIGHT_LOG_SESSION"):
            try:
                _session = Session("worker", existing=Path(os.environ["SCENELIGHT_LOG_SESSION"]))
            except OSError:
                pass
        return _session


def event(stage: str, message: str, level: str = "info", **details) -> None:
    session = current_session()
    if session is not None:
        session.event(stage, message, level, **details)


def sessions(root: Path | None = None) -> list[dict]:
    rows = []
    for path in (root or logs_root()).glob("*/session.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(item, dict) or not all(
                key in item for key in ("started", "area", "status", "id")
            ):
                continue
            rows.append({**log_privacy.mask_value(item), "path": path.parent})
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda item: str(item.get("started", "")), reverse=True)


def session_game_root(row: dict) -> Path | None:
    path = row.get("managed_project") or row.get("project")
    if not path:
        return None
    if path == "<USER>":
        return Path.home()
    if path.startswith(("<USER>/", "<USER>\\")):
        tail = path[7:]
        if "<USER>" not in tail and not Path(tail).anchor and ".." not in Path(tail).parts:
            return Path.home() / tail
    return None if "<USER>" in path else Path(path)


def session_signature(path: Path) -> tuple:
    result = []
    for candidate in path.glob("*.*"):
        try:
            stat = candidate.stat()
            result.append((candidate.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(result))


def read_events(
    path: Path, *, query: str = "", level: str = "all", limit: int = 1500
) -> list[dict]:
    rows = []
    order = 0
    for file in path.glob("events-*.jsonl*"):
        try:
            stream = file.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue  # Writer may still be appending the last record.
                if not isinstance(item, dict):
                    continue
                if level != "all" and item.get("level") != level:
                    continue
                if query.casefold() not in line.casefold():
                    continue
                order += 1
                key = (item.get("time", ""), item.get("pid", 0), item.get("sequence", 0), order)
                heapq.heappush(rows, (key, item))
                if len(rows) > limit:
                    heapq.heappop(rows)
    return [log_privacy.mask_value(item) for _key, item in sorted(rows)]


def event_text(row: dict) -> str:
    details = json.dumps(row.get("details", {}), indent=2, ensure_ascii=False)
    return (
        f"{row.get('time', '')} [{row.get('level', 'info').upper()}] {row.get('stage', '')} · process {row.get('pid', '')}\n{row.get('message', '')}\n"
        + (details + "\n" if details != "{}" else "")
    )


def read_console(path: Path, *, query: str = "", limit: int = 1500) -> str:
    lines = deque(maxlen=limit)
    candidates = []
    for file in path.glob("console-*.log*"):
        try:
            candidates.append((file.stat().st_mtime_ns, file))
        except OSError:
            continue
    for _time, file in sorted(candidates):
        try:
            with file.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    if query.casefold() in line.casefold():
                        lines.append(line)
        except OSError:
            continue
    return log_privacy.mask_text("".join(lines))


_SECRET_KEYS = {
    "authorization",
    "proxyauthorization",
    "token",
    "accesstoken",
    "refreshtoken",
    "password",
    "passwd",
    "apikey",
    "secret",
    "clientsecret",
    "cookie",
    "setcookie",
}
_SECRET_NAME = r"(?:authorization|proxy[_-]?authorization|(?:access[_-]?|refresh[_-]?)?token|password|passwd|api[_-]?key|(?:client[_-]?)?secret|(?:set[_-]?)?cookie)"


def _redact_value(value):
    if isinstance(value, dict):
        return {
            log_privacy.mask_text(key): "<REDACTED>"
            if re.sub(r"[^a-z0-9]", "", key.casefold()) in _SECRET_KEYS
            else "<USER>"
            if log_privacy.is_account_key(key)
            else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def redact(text: str) -> str:
    # Parse structured records before the text fallback so quoted credentials,
    # nested headers and JSON encoded inside a string are handled as whole values.
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        pass
    else:
        if isinstance(value, (dict, list)):
            return json.dumps(_redact_value(value), ensure_ascii=False)
    if "\n" in text:
        return "".join(
            redact(line.rstrip("\r\n")) + line[len(line.rstrip("\r\n")) :]
            for line in text.splitlines(keepends=True)
        )
    text = log_privacy.mask_text(text)
    for quote in ('"', "'"):
        text = re.sub(
            rf"(?i)((?:[\"']?{_SECRET_NAME}[\"']?)\s*[:=]\s*){quote}(?:\\.|[^{quote}\\])*{quote}",
            rf"\g<1>{quote}<REDACTED>{quote}",
            text,
        )
    text = re.sub(
        rf"(?i)(\\[\"']{_SECRET_NAME}\\[\"']\s*[:=]\s*\\[\"']).*",
        r"\g<1><REDACTED>",
        text,
    )
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,\"']+", r"\1<REDACTED>", text
    )
    text = re.sub(
        r"(?i)((?:token|password|api[_-]?key|secret)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&]+",
        r"\1<REDACTED>",
        text,
    )
    text = re.sub(r"https?://[^\s/]+:[^\s@]+@", "https://<REDACTED>@", text)
    return text


def _capture_state_report(session_path: Path, files: dict) -> str:
    states = {}
    lines = []
    for path in sorted(session_path.glob("capture-state-*.json")):
        try:
            data = _redact_value(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("workers"), dict):
            continue
        pid = path.stem.rsplit("-", 1)[-1]
        states[pid] = data
        lines.append(f"Capture supervisor {pid} · latest observations:")
        workers = data["workers"]
        entries = [("Main capture", data.get("main"))] + [
            (f"Worker {number}", worker) for number, worker in workers.items()
        ]
        for label, state in entries:
            if not isinstance(state, dict):
                continue
            status = state.get("status", "unknown")
            if state.get("batch_error"):
                status = f"batch failed (last status: {status})"
            info = [status]
            if state.get("purpose") and label == "Main capture":
                info.append(str(state["purpose"]))
            if "assigned" in state:
                info.append(f"{state['assigned']} assigned")
            if state.get("renderer"):
                info.append(f"renderer: {state['renderer']}")
            progress = state.get("progress")
            if isinstance(progress, dict):
                info.append(
                    f"{progress.get('stage')} {progress.get('current')}/{progress.get('total')}"
                    + (f" · {progress['item']}" if progress.get("item") else "")
                )
            if state.get("exit_code") is not None:
                info.append(f"exit {state['exit_code']}")
            if state.get("error") or state.get("batch_error"):
                info.append((state.get("error") or state["batch_error"]).splitlines()[0][:512])
            lines.append(f"  {label}: " + "; ".join(info))
        if not workers:
            lines.append("  No parallel sprite batch was recorded by this supervisor.")
    if not states:
        return ""
    files["capture-state.json"] = json.dumps(states, indent=2, ensure_ascii=False)
    return "\n".join(lines) + "\n"


def export_report(
    session_path: Path, destination: Path, *, notes: str = "", game_root: Path | None = None
) -> None:
    """Export only diagnostic text; never walk the user's game or collect art/saves."""
    if _session is not None and _session.path == session_path:
        _session.flush()
    files = {}
    for path in [
        session_path / "session.json",
        *session_path.glob("events-*.jsonl*"),
        *session_path.glob("console-*.log*"),
        *session_path.glob("evidence/*.txt"),
    ]:
        if path.is_file():
            try:
                files[log_privacy.mask_text(path.relative_to(session_path).as_posix())] = redact(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                continue  # A live session can rotate a segment during export.
    if game_root is not None:
        for name in (
            "scenelight-runtime.jsonl",
            "scenelight-runtime.jsonl.1",
            "scenelight-inspector.json",
            "errors.txt",
            "traceback.txt",
            "log.txt",
        ):
            path = game_root / name
            if path.is_file():
                if name == "scenelight-inspector.json":
                    if path.stat().st_size <= 32 * 1024 * 1024:
                        files["game/" + name] = redact(
                            path.read_text(encoding="utf-8", errors="replace")
                        )
                    else:
                        files["game/" + name] = json.dumps(
                            {
                                "omitted": "Inspector report exceeds 32 MiB; send the in-game support ZIP instead."
                            }
                        )
                    continue
                with path.open("rb") as stream:
                    size = path.stat().st_size
                    stream.seek(max(0, size - SEGMENT_BYTES))
                    raw = stream.read(SEGMENT_BYTES).decode("utf-8", "replace")
                files["game/" + name] = redact(
                    ("[Earlier content omitted]\n" if size > SEGMENT_BYTES else "") + raw
                )
    summary = json.loads(files.get("session.json", "{}"))
    rows = [_redact_value(row) for row in read_events(session_path, limit=20000)]
    errors = [row for row in rows if row.get("level") == "error"]
    structured_errors = [row for row in errors if row.get("stage") != "output"]
    last_error = (
        (structured_errors[-1].get("message") if structured_errors else None)
        or summary.get("failure")
        or summary.get("last_error")
        or (errors[-1].get("message") if errors else None)
    )
    error_label = (
        "Earlier error (operation succeeded)"
        if last_error and summary.get("status") in {"complete", "succeeded"}
        else "Last error"
    )
    capture = [
        row
        for row in rows
        if row.get("stage")
        in {"capture.process", "capture.result", "capture.summary", "capture.script-error"}
        or (row.get("stage") == "capture" and row.get("level") == "error")
    ]
    capture_note = _capture_state_report(session_path, files)
    if capture:
        stops = [row for row in capture if row.get("message") == "Capture did not complete"]
        if stops:
            capture_note += (
                f"Recorded capture stops: {len(stops)} (including retries). See capture.json.\n"
            )
            details = stops[-1].get("details") or {}
            progress = details.get("last_progress")
            if isinstance(progress, list) and len(progress) == 4:
                stage, current, total, item = progress
                capture_note += (
                    f"Last progress on that attempt: {stage} {current}/{total}, {item}\n"
                )
            if details.get("exit_code") in (3221225477, -1073741819):
                capture_note += (
                    "That process exited with a Windows access violation (0xC0000005).\n"
                )
        files["capture.json"] = json.dumps(capture, indent=2, ensure_ascii=False)
    files["SUMMARY.txt"] = redact(
        f"SceneLight support report · {session_path.name}\nStatus: {summary.get('status', 'unknown')}\n"
        f"Operation: {summary.get('operation', summary.get('area', 'unknown'))}\n"
        f"Version: {summary.get('version', 'unknown')}\nBuild: {summary.get('build_sha256', 'not recorded')}\n"
        f"{error_label}: {str(last_error).splitlines()[0][:512] if last_error else 'none recorded'}\n"
        + capture_note
        + f"\nUser description:\n{notes or '(not supplied)'}\n\n"
        + "Recent errors:\n"
        + "\n".join(event_text(row) for row in errors[-8:])
        + "\n\nLogs are bounded; rotated older events may be omitted. Running means no completion was recorded (still running or interrupted).\n"
        + "Personal home paths and common credentials are redacted. Review before sharing; project and image names remain. No assets or saves are included.\n"
    )
    entries = "".join(
        "<details data-level='"
        + html.escape(str(row.get("level", "info")), quote=True)
        + "'><summary>"
        + html.escape(
            redact(
                f"{row.get('time')} · {row.get('level')} · {row.get('stage')} · {str(row.get('message', ''))[:180]}"
            )
        )
        + "</summary><pre>"
        + html.escape(redact(event_text(row)))
        + "</pre></details>"
        for row in rows
    )
    files["report.html"] = (
        """<!doctype html><meta charset='utf-8'><title>SceneLight support report</title>
<style>body{background:#101821;color:#e3edf7;font:15px system-ui;margin:28px}input,select{background:#20354b;color:white;padding:12px;border:1px solid #63819c;border-radius:6px}details{border-bottom:1px solid #344557;padding:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}input{width:55%}</style>
<h1>SceneLight support report</h1><pre>"""
        + html.escape(files["SUMMARY.txt"])
        + """</pre>
<input id='query' placeholder='Search message, worker, renderer, sprite…'><select id='level'><option value='all'>All levels</option><option>error</option><option>warning</option><option>info</option></select>
<p>Open an event for its full details. Raw journals and engine evidence are in this ZIP.</p>"""
        + entries
        + """<script>
function filter(){let q=document.getElementById('query').value.toLowerCase(),l=document.getElementById('level').value;document.querySelectorAll('details').forEach(e=>e.hidden=!e.textContent.toLowerCase().includes(q)||(l!=='all'&&e.dataset.level!==l))}document.getElementById('query').oninput=filter;document.getElementById('level').onchange=filter;</script>"""
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
