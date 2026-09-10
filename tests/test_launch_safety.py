from pathlib import Path

from scenelight.launch_safety import (
    detect_save_directory,
    install_native_launcher,
    restore_native_launcher,
    snapshot_saves,
)


def _packaged_project(root: Path) -> Path:
    (root / "game").mkdir(parents=True)
    (root / "game" / "options.rpy").write_text(
        'define config.save_directory = "SceneLight-Test-123"\n', encoding="utf-8"
    )
    (root / "DDLC.exe").write_bytes(b"original launcher")
    return root


def test_save_snapshot_copies_project_and_renpy_saves(tmp_path: Path, monkeypatch) -> None:
    project = _packaged_project(tmp_path / "project")
    (project / "game" / "saves").mkdir()
    (project / "game" / "saves" / "local.save").write_bytes(b"local")
    roaming = tmp_path / "roaming"
    external = roaming / "RenPy" / "SceneLight-Test-123"
    external.mkdir(parents=True)
    (external / "persistent").write_bytes(b"external")
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    result = snapshot_saves(project)

    backup = Path(str(result["path"]))
    assert result["created"] is True
    assert detect_save_directory(project) == "SceneLight-Test-123"
    assert (backup / "project-saves" / "local.save").read_bytes() == b"local"
    assert (backup / "renpy-saves" / "persistent").read_bytes() == b"external"
    assert not backup.is_relative_to(project)


def test_runtime_save_directory_overrides_unavailable_static_source(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "archive-only"
    (project / "game").mkdir(parents=True)
    roaming = tmp_path / "roaming"
    external = roaming / "RenPy" / "Archive-Only-456"
    external.mkdir(parents=True)
    (external / "persistent").write_bytes(b"preserved")
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    result = snapshot_saves(project, save_directory="Archive-Only-456")

    backup = Path(str(result["path"]))
    assert result["save_directory"] == "Archive-Only-456"
    assert (backup / "renpy-saves" / "persistent").read_bytes() == b"preserved"


def test_native_launcher_replaces_and_restores_normal_executable(
    tmp_path: Path, monkeypatch
) -> None:
    project = _packaged_project(tmp_path / "project")
    playback = tmp_path / "renpy7" / "renpy.exe"
    playback.parent.mkdir()
    playback.write_bytes(b"runtime")
    launcher = tmp_path / "bridge.exe"
    launcher.write_bytes(b"bridge")
    monkeypatch.setattr("scenelight.launch_safety.launcher_asset", lambda: launcher)

    metadata = install_native_launcher(project, playback)

    executable = project / "DDLC.exe"
    assert executable.read_bytes() == b"bridge"
    assert Path(str(metadata["original_backup"])).read_bytes() == b"original launcher"
    assert Path(str(metadata["config"])).read_text(encoding="utf-8").strip() == str(
        playback.resolve()
    )

    restore_native_launcher(project, metadata)
    assert executable.read_bytes() == b"original launcher"
