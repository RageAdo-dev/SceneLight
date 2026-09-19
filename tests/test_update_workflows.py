"""Exercise real discovery/build/update paths with isolated authored projects.

Only external engine startup is stubbed here. The native validation runner uses
the same fixtures with real Ren'Py 7/8 and records runtime bindings separately.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from scenelight import cli
from scenelight.calibration import profile_path
from scenelight.capture import CaptureResult
from scenelight.developer import developer_status
from scenelight.setup_gui import save_character_selection
from scenelight.sidecar import managed_project_root

AUTHOR_RULES = """init 10 python:
    if "scenelight" in globals():
        scenelight.character("hero", strength=0.43, exposure_bias=-0.35)
        scenelight.image("hero idle", strength=0.67, rim_strength=0.21)
"""


def make_update_project(root: Path, *, updated: bool = False) -> Path:
    """Add/remove real assets and replace a form without changing its timestamp."""
    game = root / "game"
    images = game / "images"
    images.mkdir(parents=True, exist_ok=True)
    tags = ("hero", "excluded", "newcomer" if updated else "retired")
    for index, tag in enumerate(tags):
        path = images / f"{tag}.png"
        old_stat = path.stat() if path.exists() else None
        picture = Image.new("RGBA", (96, 144))
        draw = ImageDraw.Draw(picture)
        draw.ellipse((27, 6, 69, 50), fill=(220, 173, 140, 255))
        right = 88 if updated and tag == "hero" else 76
        draw.rounded_rectangle((18, 48, right, 139), 12, fill=(70 + index * 35, 115, 155, 255))
        picture.save(path)
        if old_stat is not None and tag == "hero":
            os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    room = "garden" if updated else "room"
    background = Image.new("RGB", (320, 180), (45, 62, 90))
    ImageDraw.Draw(background).ellipse((14, 5, 109, 102), fill=(228, 177, 105))
    background.save(images / f"{room}.png")
    if updated:
        for old in ("retired.png", "room.png"):
            (images / old).unlink(missing_ok=True)
    lines = [
        "define config.screen_width = 320",
        "define config.screen_height = 180",
        "define config.save_directory = None",
        f'image bg {room} = "images/{room}.png"',
    ]
    for tag in tags:
        lines.extend(
            (
                f'define {tag}_speaker = Character("{tag}", image="{tag}")',
                f'image {tag} idle = "images/{tag}.png"',
            )
        )
    lines.extend(("label start:", f"    scene bg {room}"))
    lines.extend(f"    show {tag} idle" for tag in tags)
    lines.extend(("    return", ""))
    (game / "script.rpy").write_text("\n".join(lines), encoding="utf-8")
    rules = game / "lighting_rules.rpy"
    if not rules.exists():
        rules.write_text(AUTHOR_RULES, encoding="utf-8")
    saves = game / "saves"
    saves.mkdir(exist_ok=True)
    marker = saves / "qa-save-marker.txt"
    if not marker.exists():
        marker.write_text("User progress must survive updates.\n", encoding="utf-8")
    return root


def write_selection(project: Path, *, automatic: bool) -> Path:
    profile = profile_path(project)
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps(
            {
                "strength": 0.71,
                "calibration": {"exposure_bias": -0.12, "color_adaptation": 0.64},
                "auto_include_new_characters": automatic,
                "character_selection": "automatic" if automatic else "manual",
                "character_tags": ["hero", "retired"],
                "excluded_character_tags": ["excluded"],
            }
        ),
        encoding="utf-8",
    )
    return profile


def installed_manifests(project: Path, embedded: bool) -> tuple[dict, dict]:
    destination = project if embedded else managed_project_root(project)
    data = destination / "game" / "scenelight_runtime"
    return (
        json.loads((data / "manifest.json").read_text(encoding="utf-8")),
        json.loads((data / "sprite_form_manifest.json").read_text(encoding="utf-8")),
    )


def authored_hashes(project: Path) -> dict[str, str]:
    paths = [project / "game/script.rpy", project / "game/lighting_rules.rpy"]
    paths.extend((project / "game/images").glob("*.png"))
    paths.extend((project / "game/saves").glob("*.txt"))
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


@pytest.mark.parametrize("embedded", [False, True], ids=["player", "developer"])
@pytest.mark.parametrize("automatic", [True, False], ids=["auto-on", "auto-off"])
def test_update_rebuilds_changed_assets_and_preserves_author_choices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedded: bool, automatic: bool
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "isolated/projects"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    sdk = tmp_path / "test-sdk/renpy.exe"
    sdk.parent.mkdir()
    sdk.touch()
    monkeypatch.setattr(cli, "_resolve_renpy_executable", lambda *_args: sdk)
    monkeypatch.setattr(
        cli, "_runtime_capture_launchers", lambda *_args: [(sdk, False, "Test renderer")]
    )
    monkeypatch.setattr(cli, "preflight_runtime", lambda *_args, **_kwargs: None)

    def capture_static_registry(discovery, *_args, **_kwargs):
        # The engine may return every registered image family. Exercise the
        # real merge's exclusion handling rather than pre-filtering its input.
        images = discovery.game_root / "images"
        tags = ["hero", "excluded", "newcomer" if (images / "newcomer.png").exists() else "retired"]
        return CaptureResult(
            scenes=dict(discovery.scenes),
            sprites={tag + " idle": images / (tag + ".png") for tag in tags},
            character_tags=tags,
            background_inventory_requested=True,
            scene_requests=len(discovery.scenes),
            resolved_requests=[],
            errors=[],
            cached=False,
        )

    monkeypatch.setattr(cli, "capture_runtime_assets", capture_static_registry)
    launched = []
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda command, **_kwargs: launched.append(command) or SimpleNamespace(pid=1234),
    )

    project = make_update_project(tmp_path / "authored-project")
    profile = write_selection(project, automatic=automatic)
    original_profile = profile.read_bytes()
    original = authored_hashes(project)
    command = "embed" if embedded else "install"
    common = ["--project", str(project), "--workers", "1", "--analyzer", "cpu"]
    assert cli._main([command, *common]) == 0
    before, before_forms = installed_manifests(project, embedded)
    assert set(before_forms["sprites"]) == {"hero idle", "retired idle"}
    assert set(before["scenes"]) == {"room"}
    assert authored_hashes(project) == original
    managed_save = managed_project_root(project) / "game/saves/player-progress.txt"
    if not embedded:
        managed_save.parent.mkdir(parents=True)
        managed_save.write_text("Managed game progress.", encoding="utf-8")

    make_update_project(project, updated=True)
    updated_hashes = authored_hashes(project)
    if embedded:
        status = developer_status(project)
        assert status.refresh_required
        assert "game/images/hero.png" in status.changed_sources
        assert "game/images/newcomer.png" in status.changed_sources
        assert "game/images/retired.png" in status.changed_sources
        assert cli._main(["refresh", *common]) == 0
        assert developer_status(project).clean
        assert not developer_status(project).refresh_required
    else:
        # Launch is the player's automatic update path, without pressing Scan.
        result = cli._launch_managed(project)
        assert result["updated_before_launch"] is True
        assert len(launched) == 1
        assert managed_save.read_text(encoding="utf-8") == "Managed game progress."
        assert cli._launch_managed(project)["updated_before_launch"] is False

    after, after_forms = installed_manifests(project, embedded)
    expected = {"hero idle", "newcomer idle"} if automatic else {"hero idle"}
    assert set(after_forms["sprites"]) == expected
    assert "excluded" not in after["character_tags"]
    assert "retired" not in after["character_tags"]
    assert ("newcomer" in after["character_tags"]) is automatic
    assert set(after["scenes"]) == {"garden"}
    assert (
        before_forms["sprites"]["hero idle"]["source_sha256"]
        != after_forms["sprites"]["hero idle"]["source_sha256"]
    )
    assert after["strength"] == pytest.approx(0.71)
    assert after["calibration"]["exposure_bias"] == pytest.approx(-0.12)
    assert after["calibration"]["color_adaptation"] == pytest.approx(0.64)
    assert profile.read_bytes() == original_profile
    assert authored_hashes(project) == updated_hashes
    assert (project / "game/lighting_rules.rpy").read_text(encoding="utf-8") == AUTHOR_RULES
    assert cli._verify(project)["ok"] is True

    # The same review menu remains useful after installation: switch families
    # and freeze auto-inclusion, keeping all unrelated profile/author settings.
    save_character_selection(
        project,
        "manual",
        ["excluded", "newcomer"],
        candidates=["hero", "excluded", "newcomer"],
    )
    if embedded:
        assert developer_status(project).refresh_required
        assert cli._main(["refresh", *common]) == 0
        assert not developer_status(project).refresh_required
    else:
        assert cli._launch_managed(project)["updated_before_launch"] is True
        assert managed_save.read_text(encoding="utf-8") == "Managed game progress."
    reselected, reselected_forms = installed_manifests(project, embedded)
    assert set(reselected["character_tags"]) == {"excluded", "newcomer"}
    assert set(reselected_forms["sprites"]) == {"excluded idle", "newcomer idle"}
    assert reselected["strength"] == pytest.approx(0.71)
    assert reselected["calibration"]["exposure_bias"] == pytest.approx(-0.12)
    assert authored_hashes(project) == updated_hashes
