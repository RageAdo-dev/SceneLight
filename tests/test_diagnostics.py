import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scenelight import diagnostics


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
