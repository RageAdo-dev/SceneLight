import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scenelight import diagnostics


def test_export_includes_worker_results_and_crashes_while_setup_is_open(tmp_path):
    setup = diagnostics.Session("setup", root=tmp_path)
    worker = diagnostics.Session("cli", existing=setup.path)
    worker.event("capture.process", "Capture process started", attempt_id="attempt1", engine_pid=45)
    worker.event(
        "capture",
        "Capture did not complete",
        "error",
        attempt_id="attempt1",
        exit_code=3221225477,
        last_progress=["form.start", 42, 98, "actor idle"],
        last_step={"stage": "rendering", "token": "secret-value"},
    )
    worker.event("capture.summary", "Worker 2 finished", captured_sprites=82, skipped_assets=1)
    destination = tmp_path / "report.zip"
    diagnostics.export_report(setup.path, destination)
    with zipfile.ZipFile(destination) as archive:
        summary = archive.read("SUMMARY.txt").decode()
        assert "Status: running" in summary
        assert "Last error: Capture did not complete" in summary
        assert "0xC0000005" in summary and "42/98, actor idle" in summary
        capture = archive.read("capture.json")
        assert b"secret-value" not in capture
        assert {row["stage"] for row in json.loads(capture)} == {
            "capture.process",
            "capture",
            "capture.summary",
        }
        assert len(json.loads(archive.read("session.json"))["build_sha256"]) == 64


def test_sessions_retain_failure_context_and_search_after_reopening(tmp_path):
    session = diagnostics.Session("setup", root=tmp_path)
    session.update(operation="install", project="D:/games/example")
    session.event("capture", "Starting batch", worker=3, renderer="gl2")
    try:
        raise ValueError("bad sprite map")
    except ValueError as error:
        session.exception("capture", error)
    session.update(status="failed", failure="bad sprite map", exit_code=1)
    listing = diagnostics.sessions(tmp_path)
    assert listing[0]["status"] == "failed"
    rows = diagnostics.read_events(listing[0]["path"], query="sprite", level="error")
    assert len(rows) == 1
    assert "raise ValueError" in rows[0]["details"]["traceback"]
    assert rows[0]["pid"]
    assert json.loads((session.path / "session.json").read_text())["runtime_sha256"]


def test_live_capture_report_survives_rotation_and_discards_old_batch_state(tmp_path, monkeypatch):
    session = diagnostics.Session("setup", root=tmp_path)
    session.capture_status(None, new_attempt=True, status="script error", purpose="review")
    session.capture_status(None, error='File "game/broken.rpy", line 2: expected statement.')
    session.event("capture.script-error", "Ren'Py could not compile the game scripts", "error")
    session.output("Loading error handling took 0.04s")
    destination = tmp_path / "report.zip"
    diagnostics.export_report(session.path, destination)
    with zipfile.ZipFile(destination) as archive:
        summary = archive.read("SUMMARY.txt").decode()
        assert "No parallel sprite batch" in summary
        assert 'File "game/broken.rpy", line 2' in summary
        assert "Last error: Ren'Py could not compile" in summary
    session.capture_status(None, new_attempt=True, status="result returned", purpose="plan")
    session.capture_batch([12] * 7, [False] * 7)
    session.capture_status(7, status="stopped", exit_code=75)
    session.capture_batch([10] * 6, [True] + [False] * 5)
    session.capture_status(2, status="started", engine_pid=33, renderer="gl2")
    session.capture_status(
        2,
        status="in progress",
        progress={
            "stage": "form.start",
            "current": 3,
            "total": 10,
            "item": "actor idle",
            "token": "test-key",
        },
    )
    monkeypatch.setattr(diagnostics, "SEGMENT_BYTES", 180)
    for _ in range(24):
        session.event("capture.asset_skipped", "Skipped unrelated form")
    diagnostics.export_report(session.path, destination)
    with zipfile.ZipFile(destination) as archive:
        text = archive.read("SUMMARY.txt").decode()
        assert "Worker 1: restored" in text and "Worker 6: queued" in text
        assert "Worker 7" not in text and "Main capture: script error" not in text
        assert "form.start 3/10 · actor idle" in text
        data = archive.read("capture-state.json")
        assert b"test-key" not in data
        workers = next(iter(json.loads(data).values()))["workers"]
        assert workers["2"]["engine_pid"] == 33


def test_bounded_journal_and_concurrent_writers_keep_complete_json(tmp_path, monkeypatch):
    import gc

    # Finalize any prior native GUI test's unreachable objects on the UI thread
    # before worker allocations can trigger cyclic GC in a background thread.
    gc.collect()
    monkeypatch.setattr(diagnostics, "SEGMENT_BYTES", 1800)
    session = diagnostics.Session("test", root=tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(lambda i: session.event("worker", f"event {i}", worker=i % 4), range(100))
        )
    journals = list(session.path.glob("events*"))
    assert len(journals) <= diagnostics.SEGMENTS
    for path in journals:
        for line in path.read_text().splitlines():
            assert json.loads(line)["sequence"] > 0
    rows = diagnostics.read_events(session.path, limit=5)
    assert len(rows) == 5
    assert rows[-1]["sequence"] == 101
    with session.journal.open("a") as stream:
        stream.write('{"incomplete')
    assert diagnostics.read_events(session.path, limit=5) == rows


def test_support_export_redacts_credentials_escapes_html_and_never_collects_assets(tmp_path):
    session = diagnostics.Session("preview", root=tmp_path / "sessions")
    session.event(
        "failure",
        "<script>alert(1)</script>",
        "error",
        path=str(Path.home() / "secret"),
        token="abc123",
        command="https://name:pass@example.com/asset",
    )
    session.attach_text("engine", "Traceback\nValueError: broken")
    game = tmp_path / "game"
    game.mkdir()
    (game / "log.txt").write_text("API_KEY=sensitive\nrenderer: gl2")
    (game / "scenelight-inspector.json").write_text(
        json.dumps({"effective_strength": 0.39, "origins": {"strength": "Character: hero"}})
    )
    (game / "art.png").write_bytes(b"private artwork")
    (game / "persistent").write_text("private save")
    destination = tmp_path / "report.zip"
    diagnostics.export_report(session.path, destination, notes="Repro steps", game_root=game)
    with zipfile.ZipFile(destination) as archive:
        assert "report.html" in archive.namelist()
        assert "game/log.txt" in archive.namelist()
        assert (
            json.loads(archive.read("game/scenelight-inspector.json"))["effective_strength"] == 0.39
        )
        assert not any(name.endswith(("art.png", "persistent")) for name in archive.namelist())
        text = "\n".join(archive.read(name).decode() for name in archive.namelist())
        assert "abc123" not in text and "sensitive" not in text and "name:pass@" not in text
        assert str(Path.home()).replace("\\", "\\\\") not in text
        report = archive.read("report.html").decode()
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report
        assert "<script>alert(1)</script>" not in report
        assert "Repro steps" in archive.read("SUMMARY.txt").decode()


def test_progress_is_compact_but_full_console_remains_available(tmp_path):
    session = diagnostics.Session("setup", root=tmp_path)
    for i in range(1000):
        session.output(f"form {i}/1000: sprite_{i}\n")
    session.output("form 1000/1000: complete\n")
    session.flush()
    assert len(diagnostics.read_events(session.path)) < 20
    raw = diagnostics.read_console(session.path)
    assert "sprite_0" in raw and "sprite_999" in raw
    assert "1000/1000" in raw
    assert "sprite_999" in diagnostics.read_console(session.path, query="sprite_999")
    session.attach_text("same-worker", "first failure")
    session.attach_text("same-worker", "second failure")
    assert len(list((session.path / "evidence").glob("*.txt"))) == 2


def test_account_names_are_masked_on_disk_in_activity_and_in_legacy_exports(tmp_path):
    account = "Jane Élodie O'Neil"
    folder = "C:\\Users\\" + account + "\\Desktop\\Eidolon"
    other = "/home/" + account + "/mods/bg.png"
    fields = {
        "username": account,
        folder: {"message": other},
        "request": json.dumps({"user_name": account}),
    }
    session = diagnostics.Session("setup", root=tmp_path / "sessions")
    project = Path.home() / "Desktop" / "Eidolon"
    session.update(project=str(project), failure=folder)
    session.event("capture", folder, "error", values=fields)
    session.capture_status(3, status="stopped", executable=folder, progress={"item": "dog"})
    session.output("Opening " + folder)
    session.attach_text("worker", json.dumps(fields) + "\n" + json.dumps(fields))
    session.flush(close=True)
    for path in session.path.rglob("*"):
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            assert account not in body and "Neil" not in body
    row = diagnostics.sessions(tmp_path / "sessions")[0]
    assert row["project"].startswith("<USER>") and diagnostics.session_game_root(row) == project
    assert diagnostics.session_game_root({"project": r"C:\Users\<USER>\Game"}) is None
    # Simulate a journal and engine log saved on a different machine by an older release.
    with session.journal.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"stage": "old", "message": folder, "details": fields}) + "\n")
    (tmp_path / "log.txt").write_text(
        "Windows username: " + account + "\n" + other, encoding="utf-8"
    )
    out = tmp_path / "support.zip"
    diagnostics.export_report(session.path, out, game_root=tmp_path)
    assert "Neil" not in str(diagnostics.read_events(session.path))
    with zipfile.ZipFile(out) as archive:
        for name in archive.namelist():
            body = archive.read(name).decode()
            assert "Neil" not in name + body
            if name.endswith(".json"):
                json.loads(body)
        assert "/mods/bg.png" in archive.read("game/log.txt").decode()


def test_large_inspector_json_is_exported_whole_not_a_broken_tail(tmp_path, monkeypatch):
    session = diagnostics.Session("test", root=tmp_path / "logs")
    game = tmp_path / "project"
    game.mkdir()
    content = {"recording": [{"details": "x" * 5000}]}
    (game / "scenelight-inspector.json").write_text(json.dumps(content))
    monkeypatch.setattr(diagnostics, "SEGMENT_BYTES", 100)
    destination = tmp_path / "report.zip"
    diagnostics.export_report(session.path, destination, game_root=game)
    with zipfile.ZipFile(destination) as archive:
        assert json.loads(archive.read("game/scenelight-inspector.json")) == content


def test_nested_and_quoted_credentials_are_absent_from_every_export_member(tmp_path):
    secrets = ["fake-bearer-329", "fake-key with spaces", "fake-escaped-873", "fake-cookie-654"]
    headers = {"Authorization": "Bearer " + secrets[0], "X-Request-ID": "keep-this"}
    payload = {"headers": headers, "items": [{"API_key": secrets[1]}], "Cookie": secrets[3]}
    session = diagnostics.Session("test", root=tmp_path / "logs")
    session.event(
        "request",
        "Failed request",
        "error",
        response=payload,
        nested=json.dumps({"Authorization": "Bearer " + secrets[2]}),
    )
    session.output(json.dumps(payload) + "\n")
    session.attach_text(
        "headers", "headers: " + repr(payload) + "\nAuthorization: Bearer " + secrets[0]
    )
    game = tmp_path / "game"
    game.mkdir()
    (game / "scenelight-inspector.json").write_text(json.dumps(payload))
    destination = tmp_path / "report.zip"
    diagnostics.export_report(
        session.path, destination, game_root=game, notes='Authorization="Bearer ' + secrets[0] + '"'
    )
    with zipfile.ZipFile(destination) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode()
            assert all(secret not in text for secret in secrets), name
            if name.endswith(".json"):
                json.loads(text)
            if ".jsonl" in name:
                for line in text.splitlines():
                    json.loads(line)
        content = json.loads(archive.read("game/scenelight-inspector.json"))
        assert content["headers"]["X-Request-ID"] == "keep-this"
        assert content["headers"]["Authorization"] == "<REDACTED>"
