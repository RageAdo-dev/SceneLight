"""Per-asset capture failures must not invalidate healthy parallel work."""

import json
import zipfile
from dataclasses import replace

import pytest
from PIL import Image

from scenelight import capture, diagnostics
from scenelight.project import ProjectDiscovery
from scenelight.setup_gui import skipped_asset_notice


def _worker(sprites=None, errors=()):
    return {"version": capture.CAPTURE_VERSION, "sprites": sprites or {}, "errors": list(errors)}


def test_parallel_merge_keeps_valid_assets_and_records_missing_and_unsupported_forms(tmp_path):
    (tmp_path / "game").mkdir()
    image = tmp_path / "good.png"
    Image.new("RGBA", (16, 16), "white").save(image)
    errors = [
        "sprite hero missing: IOError: Couldn't find file 'hat.png'.",
        "sprite hero broken: ValueError: invalid image data",
    ]
    master = {"version": capture.CAPTURE_VERSION, "plan_only": True, "character_tags": ["hero"]}
    merged = capture._merge_parallel_capture_payloads(
        master,
        [_worker({"hero good": "good.png"}), _worker(errors=errors)],
        {name: [name] for name in ("hero good", "hero missing", "hero broken")},
    )
    assert merged["capture_summary"] == {
        "planned_sprites": 3,
        "captured_sprites": 1,
        "skipped_sprites": 2,
    }
    assert merged["sprites"] == {"hero good": "good.png"}
    assert merged["resolved_requests"] == ["hero good"]
    assert merged["errors"] == errors
    discovery = ProjectDiscovery(
        tmp_path,
        tmp_path / "game",
        {},
        {},
        ["hero"],
        runtime_sprite_names=["hero good", "hero missing", "hero broken"],
        explicit_character_tags=["hero"],
    )
    result = capture._decode_result(discovery, merged, cached=False)
    # Most requests failed individually: this must not trip the old 75% guard.
    assert capture._validate_result(discovery, result) is result
    capture.merge_capture(discovery, result)
    assert set(discovery.sprites) == {"hero good"}
    assert {row["sprite"] for row in discovery.skipped_sprites} == {"hero missing", "hero broken"}
    with pytest.raises(RuntimeError, match="fewer than 75%"):
        capture._validate_result(discovery, replace(result, errors=[]))


@pytest.mark.parametrize(
    "errors", [[], ["sprite other: IOError: missing"], ["sprite hero missing: "]]
)
def test_unreported_missing_worker_output_remains_a_real_failure(errors):
    with pytest.raises(RuntimeError, match="reported no asset error"):
        capture._merge_parallel_capture_payloads(
            {}, [_worker(errors=errors)], {"hero missing": ["hero missing"]}
        )


@pytest.mark.parametrize(
    "error",
    ["IOError: missing file", "ValueError: corrupt image", "RuntimeError: unsupported displayable"],
)
def test_completed_worker_with_skips_is_reused_including_an_entirely_skipped_batch(tmp_path, error):
    forms = ["hero missing"]
    path = tmp_path / "complete.json"
    payload = _worker(errors=[f"sprite hero missing: {error}"])
    path.write_text(json.dumps({"version": 1, "forms": forms, "payload": payload}))
    restored = capture._saved_worker_result(tmp_path, path, forms)
    assert restored is not None and restored["sprites"] == {}
    assert restored["errors"] == payload["errors"]
    # An unreported newly planned form cannot be mistaken for a saved skip.
    assert capture._saved_worker_result(tmp_path, path, forms + ["hero added"]) is None


def test_adding_previously_missing_art_invalidates_the_capture_signature(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "story.rpy").write_text('image hero = "missing.png"\n')
    discovery = ProjectDiscovery(tmp_path, game, {}, {}, ["hero"])
    before = capture._capture_content_signature(discovery)
    Image.new("RGBA", (16, 16), "white").save(game / "missing.png")
    assert capture._capture_content_signature(discovery) != before


def test_activity_and_export_include_every_skip_reason_for_saved_worker(tmp_path, monkeypatch):
    session = diagnostics.Session("setup", root=tmp_path / "logs")
    monkeypatch.setattr(diagnostics, "_session", session)
    failures = [
        f"sprite hero missing{i}: IOError: Couldn't find file 'hat{i}.png'." for i in range(6)
    ]
    payload = _worker({"hero good": "never-collect-this.png"}, failures)
    capture._record_capture_outcome(payload, tmp_path, "Saved worker 2")
    rows = diagnostics.read_events(session.path, level="warning", query="hat4.png")
    assert len(rows) == 1
    assert rows[0]["details"]["name"] == "hero missing4"
    destination = tmp_path / "report.zip"
    diagnostics.export_report(session.path, destination)
    with zipfile.ZipFile(destination) as archive:
        evidence = [name for name in archive.namelist() if name.startswith("evidence/")]
        assert len(evidence) == 1
        report = json.loads(archive.read(evidence[0]))
        assert report["captured_sprites"] == 1 and report["skipped_assets"] == 6
        assert len(report["skipped"]) == 6
        assert report["skipped"][4]["error"] == "IOError: Couldn't find file 'hat4.png'."
        assert not any(name.endswith(".png") for name in archive.namelist())
    assert "6 sprite form(s) were skipped" in skipped_asset_notice(
        {"skipped_sprites": report["skipped"]}
    )
    assert skipped_asset_notice({}) == ""


@pytest.mark.parametrize("count", [2, 10])
def test_corrupt_capture_and_its_alias_skip_without_losing_valid_images(
    tmp_path, monkeypatch, count
):
    sprites = {}
    raw = []
    for index in range(count):
        path = tmp_path / f"image{index}.png"
        if index:
            Image.new("RGBA", (16, 16), (20 + index, 100, 160, 200)).save(path)
        else:
            path.write_bytes(b"not a valid image")
        sprites[f"hero p{index}"] = path.name
        raw.append(path.name)
    sprites["hero alias"] = raw[0]
    payload = {
        "sprites": sprites,
        "surface_captures": raw,
        "errors": [],
        "resolved_requests": list(sprites),
        "character_candidates": {"hero": raw[0]},
    }
    monkeypatch.setattr(capture, "_surface_normalization_worker_count", lambda _count: 2)
    capture._normalize_surface_captures(tmp_path, payload)
    assert len(payload["sprites"]) == count - 1
    assert "hero p0" not in payload["sprites"] and "hero alias" not in payload["sprites"]
    assert set(capture._asset_capture_errors(payload["errors"], "sprite")) == {
        "hero p0",
        "hero alias",
    }
    assert payload["character_candidates"]["hero"] is None
    assert "hero p0" not in payload["resolved_requests"]
    assert payload["surface_captures"] == []
    for relative in payload["sprites"].values():
        with Image.open(tmp_path / relative) as image:
            assert image.mode == "RGBA"


def test_output_write_failure_is_not_mislabeled_as_a_bad_asset(tmp_path, monkeypatch):
    image = tmp_path / "good.png"
    Image.new("RGBA", (16, 16), "red").save(image)
    payload = {"sprites": {"hero good": image.name}, "surface_captures": [image.name]}

    def write_failure(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(capture.os, "replace", write_failure)
    with pytest.raises(OSError, match="disk full"):
        capture._normalize_surface_captures(tmp_path, payload)
    assert payload["sprites"] == {"hero good": image.name}
