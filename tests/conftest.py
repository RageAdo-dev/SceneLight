"""Keep support sessions out of the user's own logs and isolated between tests."""

import pytest

from scenelight import diagnostics


@pytest.fixture(autouse=True)
def isolated_support_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_session", None)
    monkeypatch.setattr(diagnostics, "logs_root", lambda: tmp_path / "support-logs")
    monkeypatch.delenv("SCENELIGHT_LOG_SESSION", raising=False)
    yield
    session = diagnostics.current_session()
    if session is not None:
        session.flush(close=True)
