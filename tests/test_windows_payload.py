import importlib.util
from pathlib import Path

import pytest


def _policy():
    path = Path(__file__).resolve().parents[1] / "tools/windows_payload.py"
    spec = importlib.util.spec_from_file_location("windows_payload", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "profile,kept,excluded",
    [
        (
            "desktop",
            [
                "python.exe",
                "pythonw.exe",
                "python311.dll",
                "LICENSE.txt",
                "python311._pth",
                "Lib/ensurepip/_bundled/pip.whl",
                "DLLs/_tkinter.pyd",
                "tcl/tk8.6/tk.tcl",
                "Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
                "Lib/site-packages/PySide6/opengl32sw.dll",
                "Lib/site-packages/cv2/cv2.pyd",
                "Lib/site-packages/numpy/_core/_multiarray_umath.pyd",
                "Lib/site-packages/numpy.testing/__init__.py",
                "Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe",
                "Lib/site-packages/psutil-6.1.1.dist-info/licenses/LICENSE",
                "Lib/site-packages/cupy/_core/include/cupy/complex.cuh",
                "Lib/site-packages/cupy/_core/include/cupy/jitify.hpp",
            ],
            [
                "Lib/SPIRV-Tools.lib",
                "Lib/cmake/tool.cmake",
                "Lib/idlelib/idle.py",
                "Lib/test/test_codecs.py",
                "Lib/site-packages/numpy/tests/test_core.py",
                "Lib/site-packages/PySide6/include/QtCore.h",
                "Lib/site-packages/PySide6/QtCore.pyi",
                "Lib/site-packages/PySide6/designer.exe",
                "Lib/site-packages/PySide6/typesystems/types.xml",
                "Lib/site-packages/cv2/__pycache__/__init__.pyc",
            ],
        ),
        (
            "compatibility",
            [
                "renpy.exe",
                "renpy-32.exe",
                "renpy.py",
                "LICENSE.txt",
                "renpy/__init__.py",
                "renpy/common/00start.rpyc",
                "renpy/common/DejaVuSans.ttf",
                "lib/python2.7/os.pyo",
                "lib/py2-windows-x86_64/librenpython.dll",
                "lib/py2-windows-i686/python.exe",
                "module/libhydrogen/LICENSE",
            ],
            [
                "renpy.app/Contents/MacOS/librenpython.dylib",
                "lib/py2-mac-universal/librenpython.dylib",
                "lib/py2-linux-x86_64/librenpython.so",
                "lib/py2-linux-i686/librenpython.so",
                "tutorial/game/script.rpyc",
                "the_question/game/script.rpyc",
                "launcher/game/script.rpyc",
                "doc/index.html",
                "sdk-fonts/SourceHanSansLite.ttf",
            ],
        ),
        (
            "docs",
            [
                "INSTALL.md",
                "media/CREDITS.md",
                "media/RENPY_ART_LICENSE.txt",
                "media/lighting-comparison.png",
                "media/surface-maps.png",
                "media/scenelight-banner.svg",
                "media/preview-workspace.png",
                "media/preview-glow.png",
                "media/preview-export.png",
                "media/ingame-inspector.png",
            ],
            [
                "EFFECT_PACKS.md",
                "media/moving-light.gif",
                "media/waterfall-example.mp4",
                "media/waterfall-example.webp",
                "media/forest-example.png",
            ],
        ),
        (
            "examples",
            ["renpy/scenelight_author_example.rpy", "synthetic/make_fixture.py"],
            ["effect-packs/environmental_atmosphere.json", "effect-packs/horror_signals.json"],
        ),
    ],
)
def test_copy_keeps_runtime_and_license_files_without_changing_the_source(
    tmp_path, profile, kept, excluded
):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    before = {}
    for name in kept + excluded:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        before[name] = path.read_bytes()
    _policy().copy_payload(source, destination, profile)
    assert all((destination / name).read_bytes() == before[name] for name in kept)
    assert all(not (destination / name).exists() for name in excluded)
    assert all((source / name).read_bytes() == data for name, data in before.items())


def test_docs_replace_excluded_media_with_online_links_and_keep_source_unchanged(tmp_path):
    source, package = tmp_path / "source", tmp_path / "package"
    (source / "docs/media").mkdir(parents=True)
    package.mkdir()
    readme = "# SceneLight for Ren’Py\n![Demo](docs/media/demo.gif)\n![Diagram](docs/media/surface-maps.png)\n"
    guide = "[Video](media/demo.mp4)\n![Demo](media/demo.webp)\n[Guide](INSTALL.md)\n"
    (source / "README.md").write_text(readme, encoding="utf-8")
    (package / "README.md").write_text(readme, encoding="utf-8")
    (source / "docs/HOW_IT_WORKS.md").write_text(guide)
    for name in ["demo.gif", "demo.mp4", "demo.webp", "surface-maps.png"]:
        (source / "docs/media" / name).write_bytes(b"media")
    _policy().package_docs(source, package)
    assert (source / "README.md").read_text(encoding="utf-8") == readme
    assert (source / "docs/HOW_IT_WORKS.md").read_text() == guide
    packaged = (package / "README.md").read_text(encoding="utf-8")
    assert "[Demo (online example)](https://github.com/" in packaged
    assert "![Diagram](docs/media/surface-maps.png)" in packaged
    assert not (package / "docs/media/demo.gif").exists()
    packaged_guide = (package / "docs/HOW_IT_WORKS.md").read_text(encoding="utf-8")
    assert "[Video](https://github.com/" in packaged_guide
    assert "[Guide](INSTALL.md)" in packaged_guide


def test_existing_destinations_and_overlapping_trees_are_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    policy = _policy()
    with pytest.raises(ValueError):
        policy.copy_payload(source, source / "nested", "desktop")
    with pytest.raises(ValueError):
        policy.copy_payload(source, source, "desktop")
    with pytest.raises(ValueError):
        policy.copy_payload(policy.filesystem_path(source), source / "nested", "desktop")
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("existing")
    with pytest.raises(FileExistsError):
        policy.copy_payload(source, destination, "desktop")
    assert marker.read_text() == "existing"


def test_windows_release_uses_filters_for_fresh_and_reused_runtimes():
    root = Path(__file__).resolve().parents[1]
    builder = (root / "tools/build_release_zip.ps1").read_text()
    bundler = (root / "tools/bundle_runtime.py").read_text()
    assert 'windows_payload.py") desktop $desktopSource $desktopDestination' in builder
    assert (
        'windows_payload.py") compatibility $resolvedCompatibilityRuntime $compatibilityDestination'
        in builder
    )
    assert 'windows_payload.py") docs $root $packageRoot' in builder
    assert 'windows_payload.py") examples' in builder
    assert "from windows_payload import copy_payload, filesystem_path, keep" in bundler
    assert "copy_payload(" in bundler and '"Lib/site-packages"' in bundler


def test_fresh_bundle_filters_interpreter_and_installed_dependencies(tmp_path, monkeypatch):
    tools = Path(__file__).resolve().parents[1] / "tools"
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location("bundle_runtime", tools / "bundle_runtime.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    base = tmp_path / "python"
    for name in [
        "python.exe",
        "pythonw.exe",
        "LICENSE.txt",
        "python311.dll",
        "DLLs/_tkinter.pyd",
        "Lib/os.py",
        "Lib/extra.lib",
        "Lib/test/test_os.py",
        "tcl/tk8.6/tk.tcl",
    ]:
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    monkeypatch.setattr(module.sys, "base_prefix", str(base))
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.sys, "version_info", (3, 11, 9))

    def install(command, *, check):
        assert check and "--only-binary=:all:" in command
        target = Path(command[command.index("--target") + 1])
        for name in [
            "numpy/__init__.py",
            "numpy/_core/kernel.pyd",
            "numpy/tests/test_core.py",
            "numpy/_core/include/numpy/array.h",
            "numpy-2.1.3.dist-info/licenses/LICENSE",
        ]:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"wheel")

    monkeypatch.setattr(module.subprocess, "run", install)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("numpy==2.1.3\n")
    destination = tmp_path / "bundled"
    module.bundle(destination, requirements)
    assert (destination / "Lib/os.py").exists()
    assert (destination / "Lib/site-packages/numpy/_core/kernel.pyd").exists()
    assert (destination / "Lib/site-packages/numpy-2.1.3.dist-info/licenses/LICENSE").exists()
    assert not (destination / "Lib/extra.lib").exists()
    assert not (destination / "Lib/test").exists()
    assert not (destination / "Lib/site-packages/numpy/tests").exists()
    assert not (destination / "Lib/site-packages/numpy/_core/include").exists()
    assert "../src" in (destination / "python311._pth").read_text()
    assert (destination / "scenelight-runtime.json").exists()


def test_copy_handles_deep_runtime_asset_paths(tmp_path):
    policy = _policy()
    source, destination = tmp_path / "source", tmp_path / "destination"
    relative = Path("Lib/site-packages/PySide6/qml") / ("nested" * 12) / ("asset" * 30 + ".png")
    original = policy.filesystem_path(source / relative)
    original.parent.mkdir(parents=True)
    original.write_bytes(b"runtime asset")
    policy.copy_payload(source, destination, "desktop")
    assert policy.filesystem_path(destination / relative).read_bytes() == b"runtime asset"
