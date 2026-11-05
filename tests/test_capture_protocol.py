"""The controller and the Ren'Py helper agree on form names and skip lists."""

from pathlib import Path

import scenelight.capture as capture

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src" / "scenelight" / "runtime" / "scenelight_capture.rpy"


def test_helper_leaves_out_the_forms_the_controller_records():
    text = HELPER.read_text(encoding="utf-8")

    assert 'request.get("skip_forms")' in text
    assert "if actual_name not in host_skips" in text


def test_helper_names_character_captures_by_form_digest_only():
    text = HELPER.read_text(encoding="utf-8")

    # A readable prefix would make the path depend on the planned spelling,
    # which is what made earlier restores miss their own files.
    assert 'return "sprite_%s.png" % digest' in text


def test_helper_recovers_pixels_that_lost_their_checkpoint_marker():
    text = HELPER.read_text(encoding="utf-8")

    assert "_scenelight_is_raw_surface(absolute)" in text
    assert 'restore_stats["recovered"] += 1' in text


def test_helper_records_each_render_stage_for_a_stopped_form():
    text = HELPER.read_text(encoding="utf-8")

    # A crash between these records says whether Ren'Py died in the render
    # tree, in the software blit, or while saving the pixels.
    for stage in ('"stage": "rendering"', '"stage": "rendered"', '"stage": "composited"'):
        assert stage in text


def test_helper_controller_form_key_matches_the_helper_definition():
    # The helper builds tag + sorted(unique attributes), lowercased.
    assert capture._form_key("Yuri  GJ  wings6 1") == "yuri 1 gj wings6"
    assert capture._form_key("andres") == "andres"
    assert capture._form_key("  ") == ""
