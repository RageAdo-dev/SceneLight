import copy

import pytest
from test_developer_guide import _runtime_api

from scenelight.calibration import Calibration
from scenelight.runtime.inspector import Session, describe, finite_number


def test_explains_shadowed_rules_hard_bypass_and_master_without_mutation():
    rules = {
        "defaults": {"strength": 1},
        "backgrounds": {"lake": {"strength": 0.22}},
        "scene": {"enabled": False, "exposure_bias": -0.3},
        "characters": {"zack": {"strength": 0.78}},
        "images": {"zack neutral": {"enabled": True}},
    }
    original = copy.deepcopy(rules)
    report = describe(
        Calibration().as_dict(),
        0.6,
        {"ambient_strength": 0.4},
        {"ambient_strength": 0.7},
        rules,
        "lake",
        "zack",
        "zack neutral",
        True,
        0.5,
    )
    assert report["values"]["ambient_strength"] == 0.7
    assert report["origins"]["ambient_strength"] == "Background profile: lake"
    assert report["effective_strength"] == 0.39
    assert not report["effective_enabled"]
    assert report["origins"]["enabled"] == "Scene off (hard bypass)"
    assert [row["value"] for row in report["chains"]["strength"]] == [0.6, 1, 0.22, 0.78]
    assert rules == original


def test_temporary_changes_are_scoped_and_reset_restores_originals():
    session = Session()
    target = ("lake", "zack", "zack neutral")
    controls = {
        "enabled": False,
        "strength": 0.22,
        "strength_override": True,
        "calibration": {"exposure_bias": -0.2},
    }
    original = copy.deepcopy(controls)
    session.update(target, {"strength": 0.78, "enabled": True, "light_color_amount": -0.5})
    updated = session.apply(*target, controls)
    assert updated["strength"] == 0.78 and updated["enabled"]
    assert updated["calibration"]["light_color_amount"] == -0.5
    assert session.apply("room", "zack", "zack neutral", controls) is controls
    assert session.apply("lake", "zack", "zack happy", controls) is controls
    session.clear(target, "strength")
    assert session.apply(*target, controls)["strength"] == 0.22
    session.master.update(strength=0.5, enabled=False)
    assert session.serializable()["master"]["enabled"] is False
    session.clear()
    assert not session.active() and session.apply(*target, controls) is controls
    assert controls == original


def test_runtime_uses_the_same_temporary_overrides_as_inspector():
    from types import SimpleNamespace

    ns = _runtime_api()
    session = Session()
    ns["renpy"].display = SimpleNamespace(_scenelight_inspector=session)
    api = ns["scenelight"]
    api.background("lake", strength=0.22)
    api.character("zack", strength=0.78)
    api.off()
    rules = api.state()
    session.update(("lake", "zack", "zack neutral"), {"strength": 0.4, "enabled": True})
    session.master["strength"] = 0.6
    actual = ns["_scenelight_control_snapshot"]("lake", "zack", "zack neutral")
    report = describe(
        Calibration().as_dict(), 1, {}, {}, rules, "lake", "zack", "zack neutral", True, 1, session
    )
    assert actual["strength"] == report["values"]["strength"] == 0.4
    assert actual["enabled"] == report["effective_enabled"] is True
    assert report["effective_strength"] == 0.24
    assert report["origins"]["enabled"] == "Temporary inspector edit"
    assert api.state() == rules


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "3", "-0.1", "__import__('os')"])
def test_inspector_does_not_accept_invalid_or_executable_values(text):
    with pytest.raises(ValueError):
        finite_number(text, 0, 2)


def test_background_hex_api_and_profile_agree_and_preserve_other_settings():
    ns = _runtime_api()
    api = ns["scenelight"]
    api.background(
        "lake", light_color="#4080FF", light_color_amount=-0.5, light_color_tolerance=0.3
    )
    runtime = api.state()["backgrounds"]["lake"]
    calibration = Calibration.from_mapping(
        {"light_color": "#4080FF", "light_color_amount": -0.5, "light_color_tolerance": 0.3}
    )
    assert all(calibration.as_dict()[name] == value for name, value in runtime.items())
    assert calibration.uniform_blocks()[8] == (64 / 255, 128 / 255, 1.0, -0.5)
    assert calibration.uniform_blocks()[4][3] == 0.3
    for color in ("blue", "#abcd", "#xx0000", None):
        with pytest.raises(ValueError):
            api.background("lake", light_color=color)
        with pytest.raises(ValueError):
            Calibration.from_mapping({"light_color": color})


def test_inspector_locates_authored_overrides_and_drops_cleared_call_sites():
    ns = _runtime_api()
    api = ns["scenelight"]
    ns["renpy"].get_filename_line = lambda: ("game/story.rpy", 42)
    api.background("lake", strength=0.22)
    ns["renpy"].get_filename_line = lambda: ("game/characters.rpy", 87)
    api.character("zack", strength=0.78)
    report = describe(
        Calibration().as_dict(), 1, {}, {}, api.state(), "lake", "zack", "zack neutral", True, 1
    )
    assert report["locations"]["strength"] == {"file": "game/characters.rpy", "line": 87}
    assert report["chains"]["strength"][-2]["location"]["line"] == 42
    api.clear_character("zack")
    assert "zack" not in api.state()["call_sites"]["characters"]
    report = describe(
        Calibration().as_dict(), 1, {}, {}, api.state(), "lake", "zack", "zack neutral", True, 1
    )
    assert report["locations"]["strength"]["line"] == 42


def test_one_bundle_has_readable_checks_identity_logs_and_optional_picture(tmp_path):
    import json
    import zipfile

    from scenelight.runtime.inspector import write_support_bundle

    runtime = tmp_path / "game/scenelight_runtime"
    runtime.mkdir(parents=True)
    (runtime / "bootstrap.rpy").write_text("private source code")
    (runtime / "install_report.json").write_text('{"sprite_count":18000}')
    (tmp_path / ".scenelight_developer_install.json").write_text(
        json.dumps(
            {
                "release": {"content_sha256": "exact-build"},
                "files": {"art.png": "hash"},
                "source_state": {"secret-script.rpy": "private inventory"},
            }
        )
    )
    (tmp_path / "log.txt").write_text("token=secret-value\nRenderer: tested")
    (tmp_path / "private-art.png").write_bytes(b"artwork")
    (tmp_path / "save.dat").write_bytes(b"save")
    report = {
        "notes": "<script>bad</script> café",
        "sprites": [
            {
                "image": "héro",
                "managed": True,
                "mapped_form": False,
                "effective_enabled": True,
                "effective_strength": 0.39,
                "master": {"strength": 0.5},
                "origins": {"strength": "Character: hero"},
                "chains": {"strength": [{"value": 0.22}, {"value": 0.78}]},
            }
        ],
    }
    name = write_support_bundle(str(tmp_path), report)
    with zipfile.ZipFile(tmp_path / name) as archive:
        assert "scene.png" not in archive.namelist()
        assert not any(
            "private-art" in name or "save.dat" in name or name.endswith(".rpy")
            for name in archive.namelist()
        )
        data = json.loads(archive.read("scenelight-inspector.json"))
        assert data["runtime_files_sha256"]["game/scenelight_runtime/bootstrap.rpy"]
        assert data["installation"][".scenelight_developer_install.json"]["owned_file_count"] == 1
        text = "\n".join(archive.read(path).decode() for path in archive.namelist())
        assert "secret-value" not in text and "private inventory" not in text
        assert "&lt;script&gt;bad&lt;/script&gt;" in archive.read("report.html").decode()
        assert any("wins" in row["message"] for row in data["findings"])
    second = write_support_bundle(str(tmp_path), report, screenshot=b"selected screenshot")
    with zipfile.ZipFile(tmp_path / second) as archive:
        assert archive.read("scene.png") == b"selected screenshot"


def test_recording_stops_and_bounds_large_samples(monkeypatch):
    from scenelight.runtime import inspector

    monkeypatch.setattr(inspector.time, "time", lambda: 10.0)
    session = Session()
    session.start_recording()
    for _ in range(150):
        session.record([{"image": "hero", "values": {"glow_rules": ["x" * 150000]}}])
    assert len(session.history) == 100 and not session.recording
    assert "omitted" in session.history[0]
