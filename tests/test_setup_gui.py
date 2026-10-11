import io
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import scenelight.setup_gui as setup_gui
from scenelight.calibration import profile_path
from scenelight.developer import DeveloperStatus
from scenelight.setup_gui import (
    BASE_REQUIREMENTS,
    CUDA_REQUIREMENT,
    PACKAGING_REQUIREMENTS,
    PREVIEW_DEPENDENCIES,
    ProgressUpdate,
    ProjectInspection,
    ProjectSelection,
    build_cli_command,
    character_review_candidates,
    character_review_mode,
    character_review_required,
    character_review_selected_tags,
    component_command_status,
    component_environment_root,
    component_python,
    dependency_install_commands,
    dependency_state,
    describe_dependency_plan,
    describe_operation_failure,
    describe_scan,
    developer_mode_from_arguments,
    extract_last_json,
    format_progress_status,
    format_requirement,
    initial_project_from_arguments,
    inspect_project_installation,
    inspect_project_path,
    installed_direct_launch_command,
    installed_managed_launcher,
    installed_managed_version,
    normalize_command_batch,
    normalize_project_path,
    operation_copy,
    operation_environment,
    parse_component_progress,
    parse_progress,
    parse_runtime_progress,
    preview_action_state,
    progress_moves_forward,
    requirement_statuses,
    save_character_selection,
    terminate_process_tree,
    thumbnail_subsample_factor,
)
from scenelight.sidecar import managed_project_root


def test_project_picker_accepts_project_or_game_folder(tmp_path: Path) -> None:
    project = tmp_path / "Friendly Mod"
    game = project / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    assert normalize_project_path(project) == project.resolve()
    assert normalize_project_path(game) == project.resolve()
    result = inspect_project_path(game)
    assert result.valid
    assert result.root == project.resolve()
    assert "1 script" in result.message


def test_project_picker_rejects_unrelated_folder(tmp_path: Path) -> None:
    result = inspect_project_path(tmp_path)
    assert not result.valid
    assert "No 'game' folder" in result.message


def test_project_picker_unwraps_nested_extraction_and_ignores_macos_metadata(tmp_path):
    outer = tmp_path / "GraveyardGirls-1.2-pc"
    project = outer / "GraveyardGirls-1.2-pc"
    (project / "game").mkdir(parents=True)
    (project / "game/script.rpy").write_text("label start:\n    return\n")
    (outer / "__MACOSX/duplicate/game").mkdir(parents=True)
    (outer / "README.txt").write_text("Read me")
    result = inspect_project_path(outer)
    assert result.valid and result.root == project.resolve()
    assert "1 script" in result.message
    assert normalize_project_path(project / "game") == project.resolve()


def test_project_picker_finds_unique_game_under_several_wrapper_levels(tmp_path):
    project = tmp_path / "download" / "windows" / "title"
    (project / "game").mkdir(parents=True)
    (tmp_path / "documentation").mkdir()
    assert normalize_project_path(tmp_path) == project


def test_project_picker_never_chooses_between_two_games(tmp_path):
    for name in ("Game One", "Game Two"):
        (tmp_path / name / "game").mkdir(parents=True)
    result = inspect_project_path(tmp_path)
    assert not result.valid
    assert "More than one game" in result.message
    assert "Game One" in result.message and "Game Two" in result.message


def test_direct_game_selection_takes_priority_over_nested_backups(tmp_path):
    (tmp_path / "game").mkdir()
    (tmp_path / "backup/game").mkdir(parents=True)
    assert normalize_project_path(tmp_path) == tmp_path


def test_sdk_path_is_not_mistaken_for_its_bundled_sample_games(tmp_path, monkeypatch):
    sdk = tmp_path / "SDK"
    for name in ("launcher", "tutorial", "the_question"):
        (sdk / name / "game").mkdir(parents=True)
    project = tmp_path / "my-game"
    view = SimpleNamespace(
        _selection=lambda: ProjectSelection(project, True, "Game"),
        sdk_var=SimpleNamespace(get=lambda: str(sdk)),
        cuda_var=SimpleNamespace(get=lambda: False),
    )
    command = setup_gui.SceneLightSetup._command(view, "scan")
    assert command[command.index("--renpy-sdk") + 1] == str(sdk)


def test_project_picker_bounds_broad_folder_search(tmp_path):
    for index in range(70):
        (tmp_path / f"folder-{index}").mkdir()
    result = inspect_project_path(tmp_path)
    assert not result.valid and "Too many subfolders" in result.message


def test_cuda_detection_does_not_override_an_active_operation_or_user_choice():
    from scenelight.cuda_detection import CudaSupport

    values = []
    support = CudaSupport(("GPU",), True, False, "GPU detected")
    window = SimpleNamespace(
        _cuda_probe_generation=2,
        _cuda_support=None,
        _running=True,
        _cuda_user_choice=False,
        _cuda_apply_when_idle=False,
        cuda_detail_var=SimpleNamespace(set=lambda text: None),
        cuda_var=SimpleNamespace(get=lambda: False, set=values.append),
        _refresh_dependency_display=lambda: None,
        _refresh_project_state=lambda: None,
    )
    setup_gui.SceneLightSetup._finish_cuda_detection(window, support, 1)
    assert window._cuda_support is None
    setup_gui.SceneLightSetup._finish_cuda_detection(window, support, 2)
    assert window._cuda_apply_when_idle and values == []
    window._running = False
    window._cuda_user_choice = True
    setup_gui.SceneLightSetup._finish_cuda_detection(window, support)
    assert values == []


def test_declining_optional_cuda_continues_with_cpu_and_shows_actual_target(tmp_path, monkeypatch):
    from scenelight.cuda_detection import CudaSupport

    runtime = tmp_path / "bundled-runtime/python.exe"
    state = setup_gui.DependencyState(runtime, True, (CUDA_REQUIREMENT,), (CUDA_REQUIREMENT,))
    monkeypatch.setattr(setup_gui, "dependency_state", lambda **kwargs: state)
    prompts, values, scheduled = [], [], []

    def decline(title, message):
        prompts.append((title, message))
        return False

    monkeypatch.setattr(setup_gui.messagebox, "askyesno", decline)
    window = SimpleNamespace(
        cuda_var=SimpleNamespace(get=lambda: True, set=values.append),
        _cuda_support=CudaSupport(("NVIDIA Test GPU",), True, False, "Detected"),
        after=lambda delay, callback: scheduled.append(callback),
        _run_primary_action=lambda: None,
    )
    setup_gui.SceneLightSetup._install_components(window, continue_setup=True)
    assert values == [False]
    assert scheduled == [window._run_primary_action]
    assert "NVIDIA Test GPU" in prompts[0][1]
    assert str(runtime.parent) in prompts[0][1]
    assert "No: continue with CPU analysis" in prompts[0][1]


def test_project_inspection_reports_unmanaged_reserved_namespace(tmp_path: Path) -> None:
    project = tmp_path / "legacy mod"
    (project / "game" / "scenelight_runtime").mkdir(parents=True)
    (project / "game" / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    inspection = inspect_project_installation(project)

    assert inspection.selection.valid
    assert inspection.unmanaged_namespace_present
    assert not inspection.direct_install_ready


def test_project_inspection_reports_existing_managed_launcher(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "title"
    (project / "game").mkdir(parents=True)
    (project / "game" / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / ".scenelight_install.json").write_text("{}", encoding="utf-8")
    (managed / "Game.exe").write_bytes(b"launcher")

    inspection = inspect_project_installation(project)

    assert inspection.managed_install_ready
    assert inspection.managed_launcher == (managed / "Game.exe").resolve()
    assert inspection.managed_release_relation is not None
    assert inspection.managed_release_relation.kind == "pre_release"
    assert inspection.release_update_operation == "install"


def test_managed_source_project_accepts_generated_sdk_launcher(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "source project"
    (project / "game").mkdir(parents=True)
    (project / "game" / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / ".scenelight_install.json").write_text("{}", encoding="utf-8")
    launcher = managed / "Launch with SceneLight.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")

    assert installed_managed_launcher(project) == launcher.resolve()


def test_source_only_direct_install_uses_recorded_playback_runtime(tmp_path: Path) -> None:
    project = tmp_path / "source project"
    runtime = tmp_path / "renpy-7-sdk" / "renpy.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"launcher")
    report = project / "game" / "scenelight_runtime" / "install_report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "playback_executable": str(runtime),
                "playback_native": False,
            }
        ),
        encoding="utf-8",
    )

    assert installed_direct_launch_command(project) == (
        str(runtime.resolve()),
        str(project.resolve()),
        "run",
    )


def test_process_tree_termination_falls_back_to_direct_process_on_posix(monkeypatch) -> None:
    class Process:
        pid = 123

        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

    process = Process()
    monkeypatch.setattr(setup_gui.os, "name", "posix")

    terminate_process_tree(process)

    assert process.terminated


def test_current_managed_install_does_not_offer_replacement(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "title"
    (project / "game").mkdir(parents=True)
    (project / "game" / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / ".scenelight_install.json").write_text(
        json.dumps({"scenelight_version": "1.0.0"}), encoding="utf-8"
    )
    (managed / "Game.exe").write_bytes(b"launcher")

    inspection = inspect_project_installation(project)

    assert installed_managed_version(project) == "1.0.0"
    assert inspection.managed_release_relation is not None
    assert inspection.managed_release_relation.kind == "current"
    assert not inspection.release_replacement_available
    assert inspection.release_update_operation is None


def test_versionless_direct_install_uses_transactional_refresh_operation(tmp_path: Path) -> None:
    selection = ProjectSelection(tmp_path, True, "Ren'Py project found")
    status = DeveloperStatus(
        installed=True,
        clean=True,
        files=(),
        missing=(),
        modified=(),
        unowned=(),
        installed_version=None,
    )
    inspection = ProjectInspection(selection, developer_status=status)

    assert inspection.direct_release_relation is not None
    assert inspection.direct_release_relation.kind == "pre_release"
    assert inspection.release_replacement_available
    assert inspection.release_update_operation == "refresh"


def test_current_direct_install_keeps_asset_refresh_separate_from_release_update(
    tmp_path: Path,
) -> None:
    selection = ProjectSelection(tmp_path, True, "Ren'Py project found")
    status = DeveloperStatus(
        installed=True,
        clean=True,
        files=(),
        missing=(),
        modified=(),
        unowned=(),
        refresh_required=True,
        changed_sources=("game/images/new-background.png",),
        installed_version="1.0.0",
    )
    inspection = ProjectInspection(selection, developer_status=status)

    assert inspection.direct_refresh_required
    assert inspection.direct_release_relation is not None
    assert inspection.direct_release_relation.kind == "current"
    assert not inspection.release_replacement_available
    assert inspection.release_update_operation is None

    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )
    assert 'label = "Update SceneLight" if self._scan_ok else "Check changed assets"' in source


def test_release_update_prompt_uses_plain_language() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )

    assert "recorded build fingerprint" not in source
    assert "Existing analysis will be reused" not in source
    assert "Compatible analysis stays cached" not in source
    assert "owned namespace is replaced transactionally" not in source
    assert "reserved runtime and ownership manifest" not in source
    assert "previous SceneLight ownership" not in source
    assert "verified refresh before release testing" not in source
    assert "Yes: update\\nNo: keep the current installation and play\\nCancel: go back" in source


def test_project_inspection_reports_storage_errors_instead_of_stranding_the_ui(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "title"
    (project / "game").mkdir(parents=True)
    (project / "game" / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    def fail_storage(_project: Path) -> Path:
        raise OSError("storage unavailable")

    monkeypatch.setattr(setup_gui, "managed_project_root", fail_storage)

    inspection = inspect_project_installation(project)

    assert inspection.selection.valid
    assert inspection.error == "storage unavailable"


def test_setup_entry_point_accepts_project_flag_without_showing_flag_as_path() -> None:
    assert initial_project_from_arguments(["--project", r"C:\Games\Friendly Mod"]) == (
        r"C:\Games\Friendly Mod"
    )
    assert initial_project_from_arguments([r"C:\Games\Legacy Mod"]) == r"C:\Games\Legacy Mod"


def test_setup_entry_point_has_a_dedicated_developer_mode() -> None:
    assert developer_mode_from_arguments(["--developer"])
    assert developer_mode_from_arguments(["--project", r"C:\Games\Friendly Mod", "--developer"])
    assert not developer_mode_from_arguments(["--project", r"C:\Games\Friendly Mod"])


def test_cli_command_preserves_the_existing_installer_contract(tmp_path: Path) -> None:
    project = tmp_path / "mod"
    sdk = tmp_path / "renpy-sdk"
    command = build_cli_command(
        "install",
        project,
        renpy_sdk=sdk,
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=Path("scenelight_sdk.py"),
    )
    assert command == [
        "python.exe",
        "scenelight_sdk.py",
        "install",
        "--project",
        str(project),
        "--analyzer",
        "auto",
        "--renpy-sdk",
        str(sdk),
    ]


def test_setup_scan_requests_runtime_review_and_sdk(tmp_path: Path) -> None:
    project = tmp_path / "mod"
    sdk = tmp_path / "renpy-sdk"

    command = build_cli_command(
        "scan",
        project,
        renpy_sdk=sdk,
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=Path("scenelight_sdk.py"),
    )

    assert command == [
        "python.exe",
        "scenelight_sdk.py",
        "scan",
        "--project",
        str(project),
        "--runtime-review",
        "--renpy-sdk",
        str(sdk),
    ]


def test_developer_embed_uses_the_same_analyzer_contract(tmp_path: Path) -> None:
    command = build_cli_command(
        "embed",
        tmp_path / "mod",
        analyzer="cuda",
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=Path("scenelight_sdk.py"),
    )
    assert command == [
        "python.exe",
        "scenelight_sdk.py",
        "embed",
        "--project",
        str(tmp_path / "mod"),
        "--analyzer",
        "cuda",
    ]


def test_developer_refresh_uses_the_same_analyzer_contract(tmp_path: Path) -> None:
    command = build_cli_command(
        "refresh",
        tmp_path / "mod",
        analyzer="cpu",
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=Path("scenelight_sdk.py"),
    )

    assert command == [
        "python.exe",
        "scenelight_sdk.py",
        "refresh",
        "--project",
        str(tmp_path / "mod"),
        "--analyzer",
        "cpu",
    ]


def test_in_place_attach_uses_the_same_analyzer_contract(tmp_path: Path) -> None:
    command = build_cli_command(
        "attach",
        tmp_path / "mod",
        analyzer="cpu",
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=Path("scenelight_sdk.py"),
    )
    assert command[2:5] == ["attach", "--project", str(tmp_path / "mod")]
    assert command[-2:] == ["--analyzer", "cpu"]


def test_setup_offers_in_place_or_separate_copy_after_scan() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )

    assert 'text="Add to this game"' in source
    assert 'text="Create separate copy"' in source


def test_cuda_dependency_is_an_explicit_release_requirement() -> None:
    assert CUDA_REQUIREMENT == "cupy-cuda12x==14.2.0"


def test_private_environment_bootstrap_tools_are_security_pinned() -> None:
    assert PACKAGING_REQUIREMENTS == (
        "pip==26.2.1",
        "setuptools==84.0.0",
        "wheel==0.48.0",
    )


def test_preview_dependency_action_includes_base_analysis_components() -> None:
    assert PREVIEW_DEPENDENCIES["numpy"] == "numpy==2.2.6"
    assert PREVIEW_DEPENDENCIES["cv2"] == "opencv-python-headless==5.0.0.93"
    assert PREVIEW_DEPENDENCIES["PIL"] == "Pillow==12.3.0"
    assert PREVIEW_DEPENDENCIES["psutil"] == "psutil==7.2.2"
    assert set(BASE_REQUIREMENTS) <= set(PREVIEW_DEPENDENCIES.values())


def test_preview_action_is_standalone_and_only_blocked_by_an_active_operation() -> None:
    assert preview_action_state(False) == "normal"
    assert preview_action_state(True) == "disabled"


@pytest.mark.parametrize("with_project", [False, True])
def test_open_preview_does_not_require_a_selected_game(
    tmp_path: Path,
    monkeypatch,
    with_project: bool,
) -> None:
    preview_launcher = tmp_path / "scenelight_preview.pyw"
    preview_launcher.touch()
    runtime_python = tmp_path / "python.exe"
    runtime_python.touch()
    project = tmp_path / "game" if with_project else None
    if project is not None:
        project.mkdir()
    commands: list[tuple[list[str], dict[str, object]]] = []
    statuses: list[str] = []
    window = type(
        "PreviewWindowStub",
        (),
        {
            "_selection": lambda self: ProjectSelection(
                project,
                project is not None,
                "ready" if project is not None else "no game selected",
            ),
            "cuda_var": type("Value", (), {"get": lambda self: False})(),
            "operation_var": type(
                "Value", (), {"set": lambda self, value: statuses.append(value)}
            )(),
            "_install_components": lambda self, **kwargs: pytest.fail(
                f"unexpected component install: {kwargs}"
            ),
        },
    )()
    monkeypatch.setattr(setup_gui, "PREVIEW_LAUNCHER", preview_launcher)
    monkeypatch.setattr(setup_gui, "preferred_runtime_python", lambda: runtime_python)
    monkeypatch.setattr(
        setup_gui,
        "dependency_state",
        lambda **_kwargs: type("DependencyState", (), {"ready": True})(),
    )
    monkeypatch.setattr(
        setup_gui.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )

    setup_gui.SceneLightSetup._open_preview(window)

    assert len(commands) == 1
    command, _kwargs = commands[0]
    assert command[:2] == [str(runtime_python), str(preview_launcher)]
    if project is None:
        assert "--project" not in command
    else:
        assert command[-2:] == ["--project", str(project)]
    assert statuses == ["Starting Preview & Calibrator in its own window…"]


def test_standalone_preview_can_install_missing_optional_components(monkeypatch) -> None:
    installs: list[bool] = []
    window = type(
        "PreviewInstallStub",
        (),
        {
            "_selection": lambda self: ProjectSelection(None, False, "no game selected"),
            "cuda_var": type("Value", (), {"get": lambda self: False})(),
            "_install_components": lambda self, *, include_preview: installs.append(
                include_preview
            ),
        },
    )()
    monkeypatch.setattr(
        setup_gui,
        "dependency_state",
        lambda **_kwargs: type("DependencyState", (), {"ready": False})(),
    )

    setup_gui.SceneLightSetup._open_preview(window)

    assert installs == [True]


def test_core_install_does_not_download_optional_preview_stack() -> None:
    assert "psutil==7.2.2" in BASE_REQUIREMENTS
    assert "PySide6-Essentials==6.11.2" in BASE_REQUIREMENTS
    assert "imageio-ffmpeg==0.6.0" in BASE_REQUIREMENTS
    assert all(not requirement.startswith("PySide6==") for requirement in BASE_REQUIREMENTS)
    assert all(not requirement.startswith("PyOpenGL==") for requirement in BASE_REQUIREMENTS)
    assert "skimage" not in PREVIEW_DEPENDENCIES


def test_player_components_do_not_make_the_optional_preview_appear_installed(monkeypatch):
    from scenelight import setup_gui

    installed = dict(item.split("==") for item in BASE_REQUIREMENTS)

    def package_version(name):
        if name not in installed:
            raise setup_gui.PackageNotFoundError(name)
        return installed[name]

    monkeypatch.setattr(setup_gui, "version", package_version)
    monkeypatch.setattr(
        setup_gui.importlib.util,
        "find_spec",
        lambda name: None if name in {"OpenGL", "PySide6.QtOpenGLWidgets"} else object(),
    )
    assert setup_gui.missing_dependencies() == []
    assert setup_gui.missing_preview_dependencies() == [
        "PySide6-Essentials==6.11.2",
        "PyOpenGL==3.1.10",
    ]


def test_missing_parent_of_preview_module_is_reported_as_missing(monkeypatch):
    from scenelight import setup_gui

    monkeypatch.setattr(setup_gui, "version", lambda name: "6.9.2")

    def missing_parent(name):
        raise ModuleNotFoundError("No module named PySide6")

    monkeypatch.setattr(setup_gui.importlib.util, "find_spec", missing_parent)
    assert setup_gui._missing_modules({"PySide6.QtOpenGLWidgets": "PySide6==6.9.2"}) == [
        "PySide6==6.9.2"
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows GUI/console interpreter pair")
def test_gui_interpreter_checks_its_console_packages_without_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_gui.sys, "executable", str(tmp_path / "pythonw.exe"))
    monkeypatch.setattr(setup_gui, "version", lambda name: "2.1.3")
    monkeypatch.setattr(setup_gui.importlib.util, "find_spec", lambda name: object())

    def forbidden(*args, **kwargs):
        pytest.fail("Opening a bundled menu must not spawn an interpreter")

    monkeypatch.setattr(setup_gui.subprocess, "run", forbidden)
    assert setup_gui._missing_modules({"numpy": "numpy==2.1.3"}, tmp_path / "python.exe") == []
    assert setup_gui._missing_modules({"numpy": "numpy==1.0.0"}, tmp_path / "python.exe") == [
        "numpy==1.0.0"
    ]


def test_different_interpreter_directory_is_still_probed(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_gui.sys, "executable", str(tmp_path / "pythonw.exe"))
    target = tmp_path / "other" / "python.exe"
    target.parent.mkdir()
    target.touch()
    commands = []

    def probe(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='["numpy"]')

    monkeypatch.setattr(setup_gui.subprocess, "run", probe)
    assert setup_gui._missing_modules({"numpy": "numpy==2.1.3"}, target) == ["numpy==2.1.3"]
    assert commands[0][0] == str(target)


def test_preview_opens_with_optional_cuda_missing(tmp_path, monkeypatch):
    probes = []
    launches = []
    status = []

    def dependencies(**kwargs):
        probes.append(kwargs)
        missing = (CUDA_REQUIREMENT,) if kwargs["include_cuda"] else ()
        return setup_gui.DependencyState(tmp_path / "python.exe", True, (), missing)

    def forbidden(**kwargs):
        pytest.fail("Preview must not request CUDA installation")

    monkeypatch.setattr(setup_gui, "dependency_state", dependencies)
    monkeypatch.setattr(setup_gui, "preferred_runtime_python", lambda: tmp_path / "python.exe")
    monkeypatch.setattr(
        setup_gui.subprocess, "Popen", lambda command, **kwargs: launches.append(command)
    )
    view = SimpleNamespace(
        _selection=lambda: ProjectSelection(None, False, "No game selected"),
        cuda_var=SimpleNamespace(get=lambda: True),
        _install_components=forbidden,
        operation_var=SimpleNamespace(set=status.append),
    )
    setup_gui.SceneLightSetup._open_preview(view)
    assert probes == [{"include_preview": True, "include_cuda": False, "source_mode": True}]
    assert len(launches) == 1
    assert status[-1].startswith("Starting Preview")


def test_dependency_state_reports_every_exact_missing_version_for_new_environment(
    tmp_path: Path,
) -> None:
    state = dependency_state(
        include_preview=True,
        include_cuda=False,
        source_mode=True,
        python_executable=tmp_path / "missing" / "python.exe",
    )

    assert not state.runtime_ready
    assert state.missing == state.required
    assert len(state.required) == len(set(PREVIEW_DEPENDENCIES.values()))
    assert "NumPy 2.2.6" in describe_dependency_plan(state)
    assert format_requirement("opencv-python-headless==4.10.0.84") == "OpenCV 4.10.0.84"
    statuses = requirement_statuses(state)
    assert statuses[0] == ("NumPy 2.2.6", False)
    assert len(statuses) == len(set(PREVIEW_DEPENDENCIES.values()))
    assert state.verified_count == 0
    assert state.verification_summary == "0 of 8 components verified"


def test_verification_summary_matches_rows_including_runtime_and_optional_cuda(
    tmp_path, monkeypatch
):
    from scenelight import setup_gui

    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(setup_gui, "_missing_modules", lambda *args: [])
    for cuda, expected in ((False, 7), (True, 8)):
        state = dependency_state(include_preview=False, include_cuda=cuda, python_executable=python)
        assert len(state.component_statuses) == expected
        assert all(ready for _, ready in state.component_statuses)
        assert state.verified_count == expected
        assert state.verification_summary == f"{expected} components verified."


def test_missing_preview_binding_marks_shared_package_once(tmp_path, monkeypatch):
    from scenelight import setup_gui

    python = tmp_path / "python.exe"
    python.touch()
    qt = "PySide6-Essentials==6.11.2"
    monkeypatch.setattr(setup_gui, "_missing_modules", lambda *args: [qt, qt])
    state = dependency_state(include_preview=True, python_executable=python)
    assert state.required.count(qt) == 1
    assert state.missing == (qt,)
    assert state.verified_count == 7
    assert state.verification_summary == "7 of 8 components verified"
    assert dict(state.component_statuses)["PySide6-Essentials 6.11.2"] is False


def test_vm_renderer_failure_is_not_mislabeled_as_a_dependency_failure() -> None:
    title, message = describe_operation_failure(
        "Number of texture units: 0\nCan't find a workable environment.\n"
    )

    assert title == "No usable graphics renderer"
    assert "no compatible graphics acceleration" in message
    assert "host computer" in message


def test_missing_packaged_module_explains_incomplete_runtime_setup() -> None:
    title, message = describe_operation_failure(
        "python.exe: Error while finding module specification for "
        "'scenelight.compatibility' (ModuleNotFoundError: No module named 'scenelight')"
    )

    assert title == "SceneLight setup is incomplete"
    assert "newest SceneLight release" in message
    assert "selected game or mod was not changed" in message


def test_exhausted_renderer_fallback_explains_that_every_backend_was_tried() -> None:
    title, message = describe_operation_failure(
        "SceneLight tried every compatible graphics backend bundled with the game.\n"
        "Number of texture units: 0\n"
    )

    assert title == "No compatible renderer worked"
    assert "automatically tried every graphics backend" in message


def test_native_access_violation_is_not_mislabeled_as_a_progress_line() -> None:
    title, message = describe_operation_failure(
        "SceneLight resolver form 1/10731: monika 1\n"
        "RuntimeError: SceneLight could not resolve this mod's dynamic assets.\n"
        "Ren'Py could not capture dynamic SceneLight assets (exit 3221225477).\n"
    )

    assert title == "The game renderer stopped unexpectedly"
    assert "preparing character forms" in message
    assert "form 1/10731" not in message


def test_update_operation_uses_a_product_name_instead_of_internal_api_wording() -> None:
    title, subtitle, status = operation_copy("refresh")

    assert title == "Updating SceneLight"
    assert "developer API" not in f"{title} {subtitle} {status}"


def test_setup_window_is_responsive_and_dependency_prompt_is_concise() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )

    assert "self.resizable(True, True)" in source
    assert "self._fit_to_screen(self, 780, 540)" in source
    assert 'name="scenelight-project-inspection"' in source
    assert 'self._events.put(("project-inspection"' in source
    assert "The packages will be read from the bundled offline wheelhouse." not in source
    assert "Progress and every command will appear in the activity log." not in source
    assert "return 300_000" in source
    assert "if changed:\n                self._refresh_project_state()" in source
    assert "self.after(1500, self._poll_dependency_state)" not in source
    assert "self._install_components(include_preview=True)" in source


def test_component_environment_can_be_redirected_without_touching_global_python(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "private-python"
    monkeypatch.setenv("SCENELIGHT_COMPONENT_ROOT", str(root))

    assert component_environment_root() == root.resolve()
    expected = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert component_python() == expected.resolve()


def test_source_dependency_install_is_a_shell_free_private_environment_batch(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "scene env"
    requirements = tmp_path / "preview requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")

    commands = dependency_install_commands(
        include_preview=True,
        include_cuda=True,
        source_mode=True,
        system_python=Path("host-python.exe"),
        environment_root=environment,
        requirements_path=requirements,
    )

    private_python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert commands == [
        ["host-python.exe", "-m", "venv", str(environment)],
        [
            str(private_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *PACKAGING_REQUIREMENTS,
        ],
        [
            str(private_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
            CUDA_REQUIREMENT,
        ],
    ]


def test_installed_package_dependency_install_stays_in_callers_environment(
    tmp_path: Path,
) -> None:
    commands = dependency_install_commands(
        include_preview=False,
        include_cuda=False,
        source_mode=False,
        system_python=Path("venv-python.exe"),
        requirements_path=tmp_path / "missing.txt",
    )

    assert commands == [
        [
            "venv-python.exe",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *BASE_REQUIREMENTS,
        ]
    ]


def test_source_dependency_install_uses_adjacent_offline_wheelhouse(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "placeholder-1.0-py3-none-any.whl").touch()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")

    commands = dependency_install_commands(
        include_preview=False,
        include_cuda=False,
        source_mode=True,
        system_python=Path("host-python.exe"),
        environment_root=tmp_path / "private",
        requirements_path=requirements,
        wheelhouse_path=wheelhouse,
    )

    for command in commands[1:]:
        assert command[5:8] == ["--no-index", "--find-links", str(wheelhouse.resolve())]


def test_process_batches_never_require_shell_parsing() -> None:
    assert normalize_command_batch(["python", "-m", "scenelight.cli"]) == [
        ["python", "-m", "scenelight.cli"]
    ]
    assert normalize_command_batch([["python", "-m", "venv", "target"]]) == [
        ["python", "-m", "venv", "target"]
    ]


def test_isolated_runtime_can_import_packaged_scenelight_source(tmp_path: Path) -> None:
    source_root = tmp_path / "_scenelight"
    source = source_root / "src"
    source.mkdir(parents=True)
    environment = operation_environment(
        {"PYTHONPATH": str(tmp_path / "existing")},
        source_root=source_root,
    )

    entries = environment["PYTHONPATH"].split(os.pathsep)
    assert entries[0] == str(source.resolve())
    assert entries[1] == str(tmp_path / "existing")
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONUNBUFFERED"] == "1"


def test_component_output_reports_package_and_transfer_progress() -> None:
    started = parse_component_progress(
        "Downloading pyside6_addons-6.9.2-cp39-abi3-win_amd64.whl (160.2 MB)"
    )
    assert started is not None
    assert started.message == "Downloading PySide6 Addons (160.2 MB)…"
    assert (started.current, started.total, started.active_download) == (
        0.0,
        160.2,
        "PySide6 Addons",
    )

    transferred = parse_component_progress(
        "━━━━━━━━ 72.6/160.2 MB 17.0 MB/s 0:00:04",
        started.active_download,
    )
    assert transferred is not None
    assert transferred.message == "Downloading PySide6 Addons — 72.6 of 160.2 MB…"
    assert (transferred.current, transferred.total) == (72.6, 160.2)


def test_component_output_reports_prepare_install_and_verify_stages() -> None:
    collecting = parse_component_progress("Collecting numpy==2.1.3")
    installing = parse_component_progress("Installing collected packages: numpy, Pillow")
    finished = parse_component_progress("Successfully installed numpy-2.1.3 Pillow-12.3.0")

    assert collecting is not None and collecting.message == "Preparing NumPy…"
    assert installing is not None and installing.message == "Installing 2 components…"
    assert (installing.current, installing.total) == (92.0, 100.0)
    assert finished is not None
    assert finished.message == "Components installed. Verifying exact versions…"


def test_component_commands_explain_each_first_time_setup_step() -> None:
    assert component_command_status(["python", "-m", "venv", "runtime"], 1, 3) == (
        "Step 1 of 3: Creating the SceneLight runtime…"
    )
    assert (
        component_command_status(["python", "-m", "pip", "install", *PACKAGING_REQUIREMENTS], 2, 3)
        == "Step 2 of 3: Preparing the component installer…"
    )
    assert (
        component_command_status(["python", "-m", "pip", "install", "-r", "requirements.txt"], 3, 3)
        == "Step 3 of 3: Downloading and installing SceneLight components…"
    )


def test_prepare_phase_uses_purposeful_consumer_language() -> None:
    assert operation_copy("components") == (
        "Setting up SceneLight",
        "Download and installation progress appears below.",
        "Starting SceneLight component setup…",
    )
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )
    assert '"2  Scan"' in source
    assert '"2  Check"' not in source


def test_setup_window_displays_the_canonical_release_version() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )

    assert 'self.title(f"SceneLight {__version__}")' in source
    assert 'text=f"SceneLight v{__version__}"' in source


def test_installed_setup_falls_back_to_package_module_cli(tmp_path: Path) -> None:
    missing_launcher = tmp_path / "missing-scenelight-sdk.py"
    command = build_cli_command(
        "scan",
        tmp_path / "mod",
        frozen=False,
        executable=Path("python.exe"),
        sdk_launcher=missing_launcher,
    )
    assert command == [
        "python.exe",
        "-m",
        "scenelight.cli",
        "scan",
        "--project",
        str(tmp_path / "mod"),
        "--runtime-review",
    ]


def test_frozen_setup_routes_back_to_its_embedded_cli(tmp_path: Path) -> None:
    command = build_cli_command(
        "verify",
        tmp_path,
        frozen=True,
        executable=Path("SceneLight-Setup.exe"),
    )
    assert command == [
        "SceneLight-Setup.exe",
        "--cli",
        "verify",
        "--project",
        str(tmp_path),
    ]


def test_sidecar_launcher_path_is_outside_the_selected_project(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "mod"
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))

    launcher = managed_project_root(project) / "Launch with SceneLight.bat"

    assert project.resolve() not in launcher.parents


def test_scan_sidecar_is_not_mistaken_for_completed_install(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "mod"
    project.mkdir()
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed"))
    managed = managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / "Game.exe").touch()

    assert installed_managed_launcher(project) is None

    (managed / ".scenelight_install.json").write_text("{}\n", encoding="utf-8")
    assert installed_managed_launcher(project) == (managed / "Game.exe").resolve()


def test_progress_output_yields_the_final_json_object() -> None:
    output = 'transport 1/2: hall [cuda]\n{"ok": true, "scene_count": 2}\n'
    assert extract_last_json(output) == {"ok": True, "scene_count": 2}


def test_progress_output_keeps_complete_report_instead_of_nested_dictionary() -> None:
    report = {
        "project": "DDLC",
        "character_candidates": {
            "monika": "monika.png",
            "sayori": "sayori.png",
        },
        "runtime_preflight": True,
    }
    output = "SceneLight preflight completed\n" + json.dumps(report, indent=2) + "\n"

    assert extract_last_json(output) == report


def test_runtime_capture_progress_is_exposed_to_the_setup_window() -> None:
    assert parse_runtime_progress("SceneLight resolver form 2075/2091\n") == (2075, 2091)
    assert parse_runtime_progress("transport 1/2: hall [cuda]\n") is None
    assert parse_runtime_progress("SceneLight resolver form 4/3\n") is None


def test_every_expensive_install_phase_has_user_visible_progress() -> None:
    expected = {
        "SceneLight scan 2/4: preparing the isolated inspection copy": ("scan", 2, 4),
        "SceneLight scan files 400/18000: game/images.rpa": ("scan-files", 400, 18000),
        "SceneLight preflight 1/1: native runtime ready": ("preflight", 1, 1),
        "SceneLight resolver planned 1517 canonical forms for 1566 requests.": (
            "resolver",
            0,
            1517,
        ),
        "SceneLight resolver background 4/39": ("resolver-backgrounds", 4, 39),
        "SceneLight story inventory 500/12000": ("resolver-inventory", 500, 12000),
        "SceneLight image families 500/9000": ("resolver-families", 500, 9000),
        "SceneLight character geometry 3/4": ("resolver-geometry", 3, 4),
        "SceneLight image catalog 1000/9000": ("resolver-catalog", 1000, 9000),
        "SceneLight resolver plan 75/400": ("resolver-plan", 75, 400),
        "SceneLight restored 1300/1517 completed sprite forms; 217 remain.": (
            "resolver-restore",
            1300,
            1517,
        ),
        "SceneLight resolver resume 1300/1517: starting the next memory-safe capture batch": (
            "resolver-resume",
            1300,
            1517,
        ),
        "SceneLight checkpoint scan 900/1517": (
            "resolver-checkpoints",
            900,
            1517,
        ),
        "SceneLight capture work 1200/1517: saved sprite captures": (
            "resolver-work",
            1200,
            1517,
        ),
        "SceneLight parallel forms 1200/7386: 6 isolated capture workers": (
            "resolver-parallel",
            1200,
            7386,
        ),
        "SceneLight worker copies 4/6: isolated game runtimes ready": (
            "resolver-workers",
            4,
            6,
        ),
        "SceneLight worker cleanup 1/1: releasing isolated game runtimes in the background": (
            "resolver-worker-cleanup",
            1,
            1,
        ),
        "SceneLight worker 4/6: retrying with the angle2 renderer": (
            "resolver-worker-retry",
            4,
            6,
        ),
        "transport 4/39: hallway [cpu]": ("transport", 4, 39),
        "scene 12/39: hallway": ("scene", 12, 39),
        "form inventory 700/1566: monika forward": ("form-inventory", 700, 1566),
        "surface normalization 640/1517: preparing sprite pixels": (
            "surface-normalization",
            640,
            1517,
        ),
        "surface deduplication 900/1517: checking captured sprite identity": (
            "surface-deduplication",
            900,
            1517,
        ),
        "composite assembly 700/1517: finishing layered sprite captures": (
            "composite-assembly",
            700,
            1517,
        ),
        "form 842/1517: monika forward": ("form", 842, 1517),
    }
    for line, values in expected.items():
        progress = parse_progress(line)
        assert progress is not None
        assert (progress.phase, progress.current, progress.total) == values


def test_progress_status_communicates_total_percent_elapsed_and_eta() -> None:
    status = format_progress_status(
        ProgressUpdate("form", "Building unique sprite surface maps", 842, 1517),
        elapsed_seconds=372,
        completed_since_start=842,
    )

    assert "842 of 1,517 (55.5%)" in status
    assert "elapsed 6m 12s" in status
    assert "about 4m 58s left" in status


def test_renderer_fallback_cannot_move_visible_progress_backward() -> None:
    assert not progress_moves_forward(
        ProgressUpdate("resolver", "Resolving dynamic sprite forms", 25, 7386),
        previous_phase="resolver",
        previous_current=140,
        previous_total=7386,
    )
    assert progress_moves_forward(
        ProgressUpdate("resolver", "Resolving dynamic sprite forms", 145, 7386),
        previous_phase="resolver",
        previous_current=140,
        previous_total=7386,
    )
    assert progress_moves_forward(
        ProgressUpdate("resolver-plan", "Planning character appearances", 1, 48),
        previous_phase="resolver-backgrounds",
        previous_current=157,
        previous_total=157,
    )


def test_scan_summary_is_short_and_user_facing() -> None:
    summary = describe_scan(
        {
            "scenes": {"hall": "hall.png"},
            "sprites": {"nova idle": ["nova.png"]},
            "character_tags": ["nova"],
            "requires_runtime_inventory": True,
            "unsupported": ["dynamic background"],
        }
    )
    assert "1 background" in summary
    assert "1 static sprite" in summary
    assert "Runtime discovery: needed" in summary
    assert "Review items: 1" in summary


def test_character_review_explains_that_suggestions_come_from_the_game() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/scenelight/setup_gui.py").read_text(
        encoding="utf-8"
    )

    assert "Suggestions come from this game's images." in source
    assert "detected in this game" in source


def test_character_review_payload_is_normalized_and_rejects_invalid_tags() -> None:
    assert character_review_candidates(
        {
            "character_candidates": {
                "Nova Happy": "nova.png",
                "poem_sticker": None,
                "bad-tag": "bad.png",
                "": "empty.png",
            }
        }
    ) == {"nova": "nova.png", "poem_sticker": None}


def test_character_review_mode_preserves_only_supported_modes() -> None:
    assert character_review_mode({"character_selection": "automatic"}) == "automatic"
    assert character_review_mode({"character_selection": "manual"}) == "manual"
    assert character_review_mode({"character_selection": "surprise"}) == "manual"
    assert character_review_mode({"character_selection": []}) == "manual"
    assert character_review_mode({}) == "automatic"
    assert character_review_mode({"auto_include_new_characters": False}) == "manual"


def test_character_review_is_automatic_only_for_first_install_or_new_suggestions() -> None:
    existing = {
        "character_selection": "manual",
        "explicit_character_tags": ["nova"],
        "suggested_character_tags": ["nova"],
    }
    with_new_character = {
        **existing,
        "suggested_character_tags": ["nova", "guest"],
    }

    assert character_review_required(existing, installed=False)
    assert not character_review_required(existing, installed=True)
    assert character_review_required(with_new_character, installed=True)
    assert character_review_required(existing, installed=True, force=True)
    assert not character_review_required(
        {**with_new_character, "character_selection": "automatic"}, installed=True
    )


def test_thumbnail_subsample_factor_fits_bootstrap_tk_preview() -> None:
    assert thumbnail_subsample_factor(72, 72) == 1
    assert thumbnail_subsample_factor(73, 40) == 2
    assert thumbnail_subsample_factor(144, 108) == 2
    assert thumbnail_subsample_factor(721, 720) == 11

    with pytest.raises(ValueError, match="positive"):
        thumbnail_subsample_factor(72, 72, 0)


def test_manual_character_selection_is_saved_outside_the_game(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "mod"
    (project / "game").mkdir(parents=True)
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed" / "projects"))

    saved = save_character_selection(project, "manual", ["Nova happy", "nova", "chibi"])
    payload = __import__("json").loads(saved.read_text(encoding="utf-8"))

    assert saved == profile_path(project)
    assert project.resolve() not in saved.parents
    assert payload["character_selection"] == "manual"
    assert payload["character_tags"] == ["chibi", "nova"]


def test_automatic_selection_keeps_exclusions_and_can_be_frozen(tmp_path, monkeypatch):
    import json

    project = tmp_path / "mod"
    (project / "game").mkdir(parents=True)
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "managed" / "projects"))
    saved = save_character_selection(project, "automatic", ["nova"], candidates=["nova", "sticker"])
    payload = json.loads(saved.read_text())
    assert payload["auto_include_new_characters"] is True
    assert payload["character_tags"] == ["nova"]
    assert payload["excluded_character_tags"] == ["sticker"]
    review = {
        **payload,
        "explicit_character_tags": payload["character_tags"],
        "suggested_character_tags": ["nova", "sticker", "guest"],
    }
    assert character_review_selected_tags(review) == {"nova", "guest"}

    save_character_selection(project, "manual", ["nova"], candidates=["nova", "guest"])
    frozen = json.loads(saved.read_text())
    assert frozen["auto_include_new_characters"] is False
    assert frozen["excluded_character_tags"] == ["guest", "sticker"]
    frozen_review = {**review, **frozen, "explicit_character_tags": ["nova"]}
    assert character_review_selected_tags(frozen_review) == {"nova"}
    assert not character_review_required(frozen_review, installed=True)

    save_character_selection(
        project, "automatic", ["nova", "sticker"], candidates=["nova", "sticker"]
    )
    restored = json.loads(saved.read_text())
    assert restored["excluded_character_tags"] == ["guest"]


@pytest.mark.parametrize("close_window", [False, True])
def test_cancel_during_process_creation_is_not_lost(monkeypatch, tmp_path, close_window):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "projects"))
    event = threading.Event()

    def noop(*args, **kwargs):
        pass

    widget = SimpleNamespace(set=noop, configure=noop, grid=noop, start=noop, stop=noop)
    app = SimpleNamespace(
        _running=False,
        _process=None,
        _cancel_requested=event,
        _refresh_project_state=noop,
        operation_var=widget,
        progress_frame=widget,
        progress=widget,
        cancel_operation_button=widget,
        _append_log=noop,
        _events=queue.Queue(),
        project_var=SimpleNamespace(get=lambda: str(tmp_path / "game")),
        _close_character_review_window=noop,
        destroy=noop,
    )
    process = SimpleNamespace(stdout=io.StringIO(""), wait=lambda: -1, pid=12345)

    spawned = []

    def spawn(*args, **kwargs):
        spawned.append(args)
        if close_window:
            setup_gui.SceneLightSetup._close(app)
        else:
            event.set()  # UI cancelled while the OS was creating the child.
        return process

    killed = []
    monkeypatch.setattr(setup_gui.messagebox, "askyesno", lambda *a, **kw: True)
    monkeypatch.setattr(setup_gui.subprocess, "Popen", spawn)
    monkeypatch.setattr(setup_gui, "terminate_process_tree", killed.append)
    monkeypatch.setattr(
        setup_gui.threading, "Thread", lambda target, **kw: SimpleNamespace(start=target)
    )
    setup_gui.SceneLightSetup._start_operation(app, "scan", [["fake-command"], ["second-command"]])
    assert killed == [process]
    assert len(spawned) == 1
    messages = list(app._events.queue)
    assert messages[-1][0] == "done"
    assert messages[-1][2] == 130
    assert messages[-1][-1] is True


def test_declining_close_leaves_running_operation_untouched(monkeypatch):
    event = threading.Event()
    app = SimpleNamespace(_running=True, _cancel_requested=event)
    monkeypatch.setattr(setup_gui.messagebox, "askyesno", lambda *a, **kw: False)
    setup_gui.SceneLightSetup._close(app)
    assert not event.is_set()


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree cancellation integration")
def test_cancel_stops_real_silent_worker_and_its_child():
    import psutil

    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "print(child.pid,flush=True); time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    child = None
    try:
        child = psutil.Process(int(process.stdout.readline()))
        setup_gui.terminate_process_tree(process)
        assert process.wait(timeout=5) != 0
        child.wait(timeout=5)
        assert not child.is_running()
    finally:
        if process.poll() is None:
            setup_gui.terminate_process_tree(process)
        process.stdout.close()
        if child is not None and child.is_running():
            child.kill()
