import json
from pathlib import Path

import pytest
from test_project import make_project

import scenelight.cli as cli_module
from scenelight.calibration import profile_path
from scenelight.cli import (
    _batch_quote,
    _config_sha256,
    _launch_config,
    _playback_command,
    _runtime_capture_launchers,
    main,
)
from scenelight.sidecar import managed_project_root


def test_batch_launcher_arguments_cannot_expand_environment_variables() -> None:
    assert _batch_quote(r"C:\Games\100% Complete\%TEMP%\mod") == (
        r'"C:\Games\100%% Complete\%%TEMP%%\mod"'
    )


def test_legacy_game_uses_renpy7_compatibility_runtime(tmp_path: Path) -> None:
    project = tmp_path / "Legacy Game"
    compatibility = tmp_path / "compatibility-runtime"
    for root in (project, compatibility):
        (root / "renpy").mkdir(parents=True)
    native = project / "LegacyGame.exe"
    sdk = compatibility / "renpy.exe"
    native.touch()
    sdk.touch()
    (project / "renpy" / "__init__.py").write_text(
        "version_tuple = (6, 99, 12, 4, 'test')\n", encoding="utf-8"
    )
    (compatibility / "renpy" / "__init__.py").write_text(
        "version_tuple = (7, 5, 3, 'test')\n", encoding="utf-8"
    )

    assert _runtime_capture_launchers(project, sdk) == [
        (sdk.resolve(), False, "SceneLight's Ren'Py 7 compatibility runtime")
    ]
    assert _playback_command(sdk, project, native_runtime=False) == [
        str(sdk),
        str(project),
        "run",
    ]


def test_launch_detects_new_and_changed_external_lighting_profile(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed" / "projects"))
    project = make_project(tmp_path / "project")

    assert _launch_config(project, {}) == (None, False)

    profile = profile_path(project)
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text('{"calibration_version":1,"strength":0.72}', encoding="utf-8")
    resolved, changed = _launch_config(project, {})
    assert resolved == profile
    assert changed

    installed = {"config": str(profile), "config_sha256": _config_sha256(profile)}
    assert _launch_config(project, installed) == (profile, False)

    profile.write_text('{"calibration_version":1,"strength":0.84}', encoding="utf-8")
    assert _launch_config(project, installed) == (profile, True)


def test_install_creates_full_hybrid_gpu_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "project")
    original_files = sorted(
        path.relative_to(project) for path in project.rglob("*") if path.is_file()
    )

    assert (
        main(
            [
                "install",
                "--project",
                str(project),
                "--grid",
                "2x2",
                "--workers",
                "1",
                "--no-backup",
            ]
        )
        == 0
    )

    managed = managed_project_root(project)
    game = managed / "game"
    runtime = (game / "scenelight_runtime.rpy").read_text(encoding="utf-8")
    manifest = json.loads(
        (game / "scenelight_runtime" / "manifest.json").read_text(encoding="utf-8")
    )
    forms = json.loads(
        (game / "scenelight_runtime" / "sprite_form_manifest.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (game / "scenelight_runtime" / "install_report.json").read_text(encoding="utf-8")
    )

    assert "scenelight.dynamic_sprite" in runtime
    assert "SceneLightImageLike" in runtime
    assert "def _scenelight_resolve_form_entry(form_key, base_form_key):" in runtime
    assert "requested.issubset(attributes)" in runtime
    assert runtime.index("requested.issubset(attributes)") < runtime.index(
        "return SCENELIGHT_FORM_SPRITES.get(base_form_key)"
    )
    assert manifest["version"] == 8
    assert manifest["transport_atlas"]["planes"] == 26
    assert list(forms["sprites"]) == ["nova idle"]
    assert not (game / "scenelight_capture.rpy").exists()
    assert report["mode"] == "hybrid-gpu"
    assert report["final_sprite_prebake"] is False
    assert report["source_untouched"] is True
    assert not (game / "scenelight_live.json").exists()
    assert main(["verify", "--project", str(project)]) == 0
    assert (
        sorted(path.relative_to(project) for path in project.rglob("*") if path.is_file())
        == original_files
    )
    assert not (project / "game" / "scenelight_runtime.rpy").exists()


def test_attach_adds_only_reversible_namespace_and_removes_temporary_copy(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "project")
    authored = project / "game" / "script.rpy"
    original = authored.read_bytes()

    assert main(["attach", "--project", str(project), "--grid", "2x2", "--workers", "1"]) == 0

    assert authored.read_bytes() == original
    assert (project / "game" / "scenelight_runtime" / "bootstrap.rpy").is_file()
    assert (project / ".scenelight_developer_install.json").is_file()
    assert not managed_project_root(project).exists()
    assert main(["verify", "--project", str(project)]) == 0
    verification = cli_module._verify(project)
    assert verification["install_location"] == "in-place"
    assert verification["verified_project"] == str(project.resolve())
    assert verification["source_untouched"] is False


def test_attach_refuses_occupied_namespace_before_expensive_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "project")
    reserved = project / "game" / "scenelight_runtime"
    reserved.mkdir()
    (reserved / "authors-file.txt").write_text("keep me", encoding="utf-8")
    build_started = False

    def unexpected_build(*_args, **_kwargs):
        nonlocal build_started
        build_started = True
        raise AssertionError("analysis must not start")

    monkeypatch.setattr(cli_module, "build_project", unexpected_build)

    with pytest.raises(FileExistsError, match="will not overwrite"):
        main(["attach", "--project", str(project), "--grid", "2x2", "--workers", "1"])

    assert not build_started
    assert (reserved / "authors-file.txt").read_text(encoding="utf-8") == "keep me"
    assert not managed_project_root(project).exists()


def test_refresh_refuses_modified_owned_runtime_before_expensive_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "project")
    assert (
        main(
            [
                "embed",
                "--project",
                str(project),
                "--grid",
                "2x2",
                "--workers",
                "1",
                "--analyzer",
                "cpu",
            ]
        )
        == 0
    )
    runtime = project / "game" / "scenelight_runtime" / "bootstrap.rpy"
    runtime.write_text("developer changed this", encoding="utf-8")
    analysis_started = False

    def unexpected_analysis(*_args, **_kwargs):
        nonlocal analysis_started
        analysis_started = True
        raise AssertionError("analysis must not start")

    monkeypatch.setattr(cli_module, "_install_managed", unexpected_analysis)

    with pytest.raises(RuntimeError, match="Refresh refused before analysis"):
        main(["refresh", "--project", str(project)])

    assert not analysis_started
    assert runtime.read_text(encoding="utf-8") == "developer changed this"


def test_native_game_preflight_runs_before_expensive_analysis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "Playable Mod")
    (project / "PlayableMod.exe").touch()
    events: list[str] = []
    real_build = cli_module.build_project

    def fake_preflight(*_args, **_kwargs) -> None:
        events.append("preflight")

    def observed_build(*args, **kwargs):
        events.append("build")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cli_module, "preflight_runtime", fake_preflight)
    monkeypatch.setattr(cli_module, "build_project", observed_build)
    monkeypatch.setattr(cli_module, "needs_runtime_capture", lambda _discovery: False)

    assert main(["install", "--project", str(project), "--grid", "2x2", "--workers", "1"]) == 0
    assert events == ["preflight", "build"]
    report = json.loads(
        (
            managed_project_root(project) / "game" / "scenelight_runtime" / "install_report.json"
        ).read_text(encoding="utf-8")
    )
    assert report["runtime_preflight"] is True


def test_failed_default_renderer_retries_bundled_angle_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    project = make_project(tmp_path / "Legacy Mod")
    (project / "LegacyMod.exe").touch()
    (project / "renpy" / "angle").mkdir(parents=True)
    (project / "renpy" / "gl").mkdir()
    (project / "renpy" / "angle" / "renderer.py").write_text("# marker\n", encoding="utf-8")
    (project / "renpy" / "gl" / "renderer.py").write_text("# marker\n", encoding="utf-8")
    attempted: list[str | None] = []

    def fake_preflight(*_args, renderer=None, **_kwargs) -> None:
        attempted.append(renderer)
        if renderer is None:
            raise RuntimeError("automatic OpenGL path failed")

    monkeypatch.setattr(cli_module, "preflight_runtime", fake_preflight)
    monkeypatch.setattr(cli_module, "needs_runtime_capture", lambda _discovery: False)

    assert main(["install", "--project", str(project), "--grid", "2x2", "--workers", "1"]) == 0
    assert attempted == [None, "angle"]
    report = json.loads(
        (
            managed_project_root(project) / "game" / "scenelight_runtime" / "install_report.json"
        ).read_text(encoding="utf-8")
    )
    assert report["runtime_renderer"] == "angle"
