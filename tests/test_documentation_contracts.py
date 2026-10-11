from pathlib import Path

from scenelight import developer_guide, effects
from scenelight.preview.calibration_dialog import CalibrationEditor

ROOT = Path(__file__).resolve().parents[1]


def test_strength_range_and_percent_conversion_agree_across_guides():
    quickstart = (ROOT / "docs/AUTHOR_QUICKSTART.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs/MOD_AUTHOR_API.md").read_text(encoding="utf-8")
    assert "strength ranges from 0 to 2" in quickstart
    assert "78% in Preview is `strength=0.78`" in quickstart
    assert "| `strength` | 0–2 |" in reference
    topic = next(topic for topic in developer_guide.TOPICS if topic.key == "setting-strength")
    assert "Range: 0–2." in " ".join(topic.details)


def test_experimental_effect_status_matches_runtime_gate_and_identifier_parser():
    doc = (ROOT / "docs/EFFECT_PACKS.md").read_text(encoding="utf-8")
    runtime = (ROOT / "src/scenelight/runtime/scenelight_runtime.rpy").read_text(encoding="utf-8")
    assert "Experimental, script-only API" in doc
    assert "_SCENELIGHT_PLAYER_EFFECT_UI_ENABLED = False" in runtime
    assert "Identifiers start with a lowercase letter" in doc and "at most 48" in doc
    assert effects._IDENTIFIER.fullmatch("a" + "_2" * 23 + "z")
    assert not effects._IDENTIFIER.fullmatch("_leading")
    assert not effects._IDENTIFIER.fullmatch("a" * 49)


def test_guide_navigation_and_project_polling_match_current_controls():
    text = "\n".join(" ".join(topic.details) for topic in developer_guide.TOPICS)
    assert "Adjust → Light color" in text
    assert "checks the selected project every five seconds" in text
    assert "does not watch the project folder" not in text
    editor_source = (ROOT / "src/scenelight/preview/calibration_dialog.py").read_text(
        encoding="utf-8"
    )
    assert '"Light color"' in editor_source
    assert CalibrationEditor is not None
