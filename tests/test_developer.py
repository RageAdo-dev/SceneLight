import hashlib
import json
import os
from pathlib import Path

import pytest

from scenelight.calibration import profile_path
from scenelight.developer import (
    EMBED_ROOT,
    MANIFEST_NAME,
    developer_status,
    embed_from_managed,
    preflight_embed_destination,
    preflight_refresh_destination,
    refresh_embedded_from_managed,
    remove_embedded,
)
from scenelight.sidecar import analysis_cache_root


def _projects(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "source-mod"
    game = project / "game"
    game.mkdir(parents=True)
    (project / "DDLC.exe").write_bytes(b"original game executable")
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    managed = tmp_path / "managed-mod"
    managed_game = managed / "game"
    runtime_data = managed_game / "scenelight_runtime"
    runtime_data.mkdir(parents=True)
    (managed_game / "scenelight_runtime.rpy").write_text(
        "init -900 python:\n    SCENELIGHT = True\n", encoding="utf-8"
    )
    (runtime_data / "manifest.json").write_text('{"version": 5}\n', encoding="utf-8")
    (runtime_data / "transport_atlas.png").write_bytes(b"transport")
    return project, managed


def test_developer_embed_and_remove_touch_only_owned_namespace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed-root"))
    project, managed = _projects(tmp_path)
    source_script = project / "game" / "script.rpy"
    original = source_script.read_bytes()

    installed = embed_from_managed(project, managed)

    assert installed["existing_files_modified"] is False
    assert source_script.read_bytes() == original
    assert (project / EMBED_ROOT / "bootstrap.rpy").is_file()
    assert (project / EMBED_ROOT / "REMOVE-SCENELIGHT.txt").is_file()
    assert (project / MANIFEST_NAME).is_file()
    manifest = json.loads((project / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["scenelight_version"] == "1.0.0"
    assert manifest["release"]["product_version"] == "1.0.0"
    assert len(manifest["release"]["content_sha256"]) == 64
    assert all(str(tmp_path) not in str(value) for value in manifest.values())
    status = developer_status(project)
    assert status.clean
    assert status.installed_version == "1.0.0"
    assert status.installed_content_sha256 == manifest["release"]["content_sha256"]
    analysis_cache = analysis_cache_root(project)
    analysis_cache.mkdir(parents=True)
    (analysis_cache / "capture.json").write_text("cached", encoding="utf-8")

    (project / EMBED_ROOT / "bootstrap.rpyc").write_bytes(b"native compiler output")
    removed = remove_embedded(project)

    assert removed["removed"] is True
    assert removed["analysis_cache_removed"] is True
    assert source_script.read_bytes() == original
    assert not analysis_cache.exists()
    assert not (project / EMBED_ROOT).exists()
    assert not (project / MANIFEST_NAME).exists()


def test_developer_status_detects_new_assets_and_ignores_source_backed_bytecode(
    tmp_path: Path,
) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    (project / "game" / "script.rpyc").write_bytes(b"compiler cache")
    test_capture = project / "tests" / "screenshots" / "capture.png"
    test_capture.parent.mkdir(parents=True)
    test_capture.write_bytes(b"test output")
    save_capture = project / "game" / "saves" / "slot-preview.png"
    save_capture.parent.mkdir(parents=True)
    save_capture.write_bytes(b"player data")
    compiler_cache = project / "game" / "cache" / "compiled-only.rpyc"
    compiler_cache.parent.mkdir(parents=True)
    compiler_cache.write_bytes(b"generated cache")

    assert not developer_status(project).refresh_required

    added = project / "game" / "images" / "new-rooftop.png"
    added.parent.mkdir()
    added.write_bytes(b"new background")
    status = developer_status(project)

    assert status.clean
    assert status.refresh_required
    assert "game/images/new-rooftop.png" in status.changed_sources


def test_external_preview_profile_is_tracked_without_leaking_its_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "appdata" / "projects"))
    project, managed = _projects(tmp_path)
    profile = profile_path(project)
    profile.parent.mkdir(parents=True)
    profile.write_text('{"strength":0.72}', encoding="utf-8")
    digest = hashlib.sha256(profile.read_bytes()).hexdigest()
    (managed / ".scenelight_install.json").write_text(
        json.dumps({"config": str(profile), "config_sha256": digest}), encoding="utf-8"
    )

    embed_from_managed(project, managed)
    manifest_text = (project / MANIFEST_NAME).read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    assert manifest["config"] == "$profile"
    assert str(profile) not in manifest_text
    assert not developer_status(project).refresh_required

    profile.write_text('{"strength":0.84}', encoding="utf-8")
    status = developer_status(project)
    assert status.refresh_required
    assert "SceneLight profile" in status.changed_sources


def test_profile_created_after_direct_install_requires_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "appdata" / "projects"))
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    assert not developer_status(project).refresh_required

    profile = profile_path(project)
    profile.parent.mkdir(parents=True)
    profile.write_text('{"strength":0.72}', encoding="utf-8")

    status = developer_status(project)
    assert status.refresh_required
    assert "SceneLight profile" in status.changed_sources


def test_verified_refresh_replaces_only_runtime_and_records_current_sources(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    source_script = project / "game" / "script.rpy"
    original_script = source_script.read_bytes()
    embed_from_managed(project, managed)
    added = project / "game" / "images" / "new-pose.png"
    added.parent.mkdir()
    added.write_bytes(b"new pose")
    (managed / "game" / "scenelight_runtime" / "transport_atlas.png").write_bytes(
        b"refreshed transport"
    )

    assert developer_status(project).refresh_required
    result = refresh_embedded_from_managed(project, managed)

    assert result["developer_refreshed"] is True
    assert result["cleanup_warning"] is None
    assert source_script.read_bytes() == original_script
    assert added.read_bytes() == b"new pose"
    assert (project / EMBED_ROOT / "transport_atlas.png").read_bytes() == b"refreshed transport"
    status = developer_status(project)
    assert status.clean
    assert not status.refresh_required
    assert remove_embedded(project)["removed"]


def test_verified_refresh_migrates_versionless_pre_release_manifest(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    manifest_path = project / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("scenelight_version")
    manifest.pop("release")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert developer_status(project).installed_version is None

    refresh_embedded_from_managed(project, managed)

    status = developer_status(project)
    assert status.clean
    assert status.installed_version == "1.0.0"
    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert migrated["release"]["sprite_form_version"] == 7


def test_refresh_preflight_refuses_a_modified_runtime_before_analysis(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    runtime = project / EMBED_ROOT / "transport_atlas.png"
    runtime.write_bytes(b"developer edit")

    with pytest.raises(RuntimeError, match="Refresh refused before analysis"):
        preflight_refresh_destination(project)

    assert runtime.read_bytes() == b"developer edit"


def test_refresh_swap_failure_restores_previous_verified_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    runtime = project / EMBED_ROOT / "transport_atlas.png"
    manifest_path = project / MANIFEST_NAME
    original_runtime = runtime.read_bytes()
    original_manifest = manifest_path.read_bytes()
    (managed / "game" / "scenelight_runtime" / "transport_atlas.png").write_bytes(b"new")
    real_replace = os.replace

    def fail_installing_staged_runtime(source, destination) -> None:
        if Path(source).name == "runtime" and Path(destination) == project / EMBED_ROOT:
            raise OSError("simulated refresh swap failure")
        real_replace(source, destination)

    monkeypatch.setattr("scenelight.developer.os.replace", fail_installing_staged_runtime)

    with pytest.raises(OSError, match="simulated refresh swap failure"):
        refresh_embedded_from_managed(project, managed)

    assert runtime.read_bytes() == original_runtime
    assert manifest_path.read_bytes() == original_manifest
    assert developer_status(project).clean
    assert not list((project / "game").glob(".sl-*"))


def test_legacy_embed_owns_and_removes_compatibility_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, managed = _projects(tmp_path)
    compatibility = tmp_path / "renpy7" / "renpy.exe"
    compatibility.parent.mkdir()
    compatibility.touch()
    appdata = tmp_path / "appdata"
    roaming_saves = appdata / "RenPy" / "SceneLight-Legacy-Test"
    roaming_saves.mkdir(parents=True)
    (roaming_saves / "persistent").write_bytes(b"player progress")
    monkeypatch.setenv("APPDATA", str(appdata))
    (managed / ".scenelight_install.json").write_text(
        json.dumps(
            {
                "playback_native": False,
                "playback_executable": str(compatibility),
                "save_backup": {"save_directory": "SceneLight-Legacy-Test"},
            }
        ),
        encoding="utf-8",
    )

    result = embed_from_managed(project, managed)

    launcher = project / "DDLC.exe"
    assert result["launcher"] == str(launcher)
    assert launcher.read_bytes() != b"original game executable"
    assert str(compatibility.resolve()) in (project / EMBED_ROOT / "native-launcher.txt").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((project / MANIFEST_NAME).read_text(encoding="utf-8"))
    save_backup = manifest["save_backup"]
    assert save_backup["save_directory"] == "SceneLight-Legacy-Test"
    assert any(source["source"] == str(roaming_saves) for source in save_backup["sources"])
    assert developer_status(project).clean
    original_backup = project / str(manifest["native_launcher"]["original_backup"])
    backup_bytes = original_backup.read_bytes()
    (managed / "game" / "scenelight_runtime" / "transport_atlas.png").write_bytes(
        b"legacy refreshed transport"
    )

    refreshed = refresh_embedded_from_managed(project, managed)

    assert refreshed["developer_refreshed"] is True
    assert launcher.read_bytes() != b"original game executable"
    assert original_backup.read_bytes() == backup_bytes
    assert (project / EMBED_ROOT / "transport_atlas.png").read_bytes() == (
        b"legacy refreshed transport"
    )
    assert developer_status(project).clean
    assert remove_embedded(project)["removed"]
    assert launcher.read_bytes() == b"original game executable"


def test_developer_embed_refuses_preexisting_namespace(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    existing = project / EMBED_ROOT
    existing.mkdir(parents=True)
    authored = existing / "authors-file.txt"
    authored.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="will not overwrite"):
        embed_from_managed(project, managed)

    assert authored.read_text(encoding="utf-8") == "keep me"
    assert not (project / MANIFEST_NAME).exists()


def test_embed_preflight_refuses_existing_install_before_managed_build(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)

    with pytest.raises(FileExistsError, match="already embedded"):
        preflight_embed_destination(project)


def test_developer_remove_refuses_modified_owned_file_before_deleting(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    bootstrap = project / EMBED_ROOT / "bootstrap.rpy"
    other_owned = project / EMBED_ROOT / "manifest.json"
    bootstrap.write_text("developer changed this", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Removal refused before deleting anything"):
        remove_embedded(project)

    assert bootstrap.read_text(encoding="utf-8") == "developer changed this"
    assert other_owned.is_file()
    assert (project / MANIFEST_NAME).is_file()


def test_developer_status_is_not_clean_when_owned_file_is_missing(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    missing = project / EMBED_ROOT / "bootstrap.rpy"
    missing.unlink()

    status = developer_status(project)

    assert status.installed
    assert not status.clean
    assert missing.relative_to(project).as_posix() in status.missing
    with pytest.raises(RuntimeError, match="missing:"):
        remove_embedded(project)
    assert (project / MANIFEST_NAME).is_file()
    assert (project / EMBED_ROOT / "manifest.json").is_file()


def test_developer_remove_refuses_unowned_file_before_deleting(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    unowned = project / EMBED_ROOT / "my_notes.txt"
    unowned.write_text("developer content", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unowned"):
        remove_embedded(project)

    assert unowned.read_text(encoding="utf-8") == "developer content"
    assert (project / EMBED_ROOT / "bootstrap.rpy").is_file()


def test_tampered_manifest_cannot_escape_project(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    victim = tmp_path / "victim.txt"
    victim.write_text("safe", encoding="utf-8")
    manifest_path = project / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {"../victim.txt": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unsafe path"):
        remove_embedded(project)

    assert victim.read_text(encoding="utf-8") == "safe"


def test_developer_manifest_remains_safe_after_project_is_moved(tmp_path: Path) -> None:
    project, managed = _projects(tmp_path)
    source_script = project / "game" / "script.rpy"
    original = source_script.read_bytes()
    embed_from_managed(project, managed)

    moved = project.rename(tmp_path / "moved-or-cloned-mod")

    assert developer_status(moved).clean
    assert remove_embedded(moved)["removed"] is True
    assert (moved / "game" / "script.rpy").read_bytes() == original
    assert not (moved / EMBED_ROOT).exists()
    assert not (moved / MANIFEST_NAME).exists()
