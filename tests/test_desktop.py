import importlib.util
from pathlib import Path

from PIL import Image

from scenelight import desktop, setup_gui
from scenelight.branding import ICON_PATH, ICON_PNG


def _launcher_builder():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "scenelight_launcher_builder", root / "tools/build_desktop_launcher.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_launcher_version_resource_matches_the_packaged_version():
    module = _launcher_builder()
    version = module.package_version()
    assert version == __import__("scenelight").__version__
    assert module.version_quad(version) == (1, 0, 1, 0)
    checked_in = module.RESOURCE.read_text(encoding="utf-8").splitlines()
    assert checked_in == module.resource_text(version).splitlines()
    native = module.NATIVE_RESOURCE.read_text(encoding="utf-8").splitlines()
    assert native == module.native_resource_text(version).splitlines()
    for lines in (checked_in, native):
        text = "\n".join(lines)
        assert "RageAdo-dev" in text
        assert "github.com/RageAdo-dev/SceneLight" in text
        assert "MIT licensed" in text


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


def test_application_icon_has_a_visible_mark_at_every_windows_size():
    expected = {(size, size) for size in (16, 24, 32, 48, 64, 128, 256)}
    with Image.open(ICON_PATH) as icon:
        assert icon.ico.sizes() == expected
        for size in expected:
            frame = icon.ico.getimage(size).convert("RGBA")
            assert frame.getchannel("A").getextrema() == (0, 255)
            # A nontransparent black square is still a broken app icon.
            visible_mark = sum(
                1
                for red, green, blue, alpha in frame.get_flattened_data()
                if alpha > 128 and max(red, green, blue) > 100
            )
            assert visible_mark > size[0] * size[1] * 0.03
    with Image.open(ICON_PNG) as image:
        assert image.size == (1024, 1024)
        assert image.mode == "RGBA"
