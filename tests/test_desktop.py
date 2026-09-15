from pathlib import Path

from scenelight import desktop, setup_gui


def test_bundled_app_uses_its_runtime_instead_of_a_stale_user_environment(tmp_path, monkeypatch):
    runtime = tmp_path / "package" / "_scenelight" / "python"
    runtime.mkdir(parents=True)
    python = runtime / "python.exe"
    python.touch()
    (runtime / "scenelight-runtime.json").write_text("{}")
    monkeypatch.setattr(desktop.sys, "executable", str(runtime / "pythonw.exe"))
    monkeypatch.setenv("SCENELIGHT_COMPONENT_ROOT", str(tmp_path / "old-components"))
    probed = []

    def missing(dependencies, executable=None):
        probed.append(Path(executable))
        return []

    monkeypatch.setattr(setup_gui, "_missing_modules", missing)
    state = setup_gui.dependency_state(source_mode=True)
    assert state.ready
    assert state.python_executable == python
    assert probed == [python]
    assert setup_gui.preferred_runtime_python() == python
    commands = setup_gui.dependency_install_commands(include_preview=True, include_cuda=False)
    assert commands[0] == [str(python), "-m", "ensurepip", "--upgrade"]
    assert all(command[0] == str(python) for command in commands)
    assert all("venv" not in command for command in commands)


def test_ordinary_python_is_not_mistaken_for_the_bundled_runtime(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(desktop.sys, "executable", str(python))
    assert desktop.bundled_python() is None
