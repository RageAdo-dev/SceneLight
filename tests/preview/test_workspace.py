import time

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QMessageBox
from test_gpu_lighting import renderer as renderer

from scenelight import diagnostics
from scenelight.calibration import Calibration
from scenelight.preview import ui
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.library import Actor


def test_window_selects_characters_without_overwriting_their_lighting(
    renderer, tmp_path, monkeypatch
):
    # The shared fixture checks for a real GL 3.3 context and skips unsupported hosts.
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "userdata" / "projects"))
    monkeypatch.setattr(diagnostics, "_session", None)
    monkeypatch.setattr(ui, "ArtifactCache", lambda: ArtifactCache(tmp_path / "analysis"))
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _parent, title, message: errors.append((title, message))
    )
    source = tmp_path / "sprite.png"
    image = Image.new("RGBA", (100, 160))
    ImageDraw.Draw(image).ellipse((15, 10, 85, 145), fill=(180, 150, 120, 255))
    image.save(source)
    background = tmp_path / "room.png"
    Image.new("RGB", (640, 360), (25, 30, 40)).save(background)
    app = QApplication.instance()
    window = ui.MainWindow()
    window._cache._cuda_available = False
    try:
        window.show()
        app.processEvents()
        window._load_background(background)
        first = window._add_actor(source, Actor(name="First", horizontal=0.3))
        second = window._add_actor(source, Actor(name="Second", horizontal=0.7, strength=1.3))
        deadline = time.monotonic() + 20
        while not all(window._actor_forms[actor.id] for actor in window._actors):
            app.processEvents()
            assert not errors, errors
            assert time.monotonic() < deadline, "Surface preparation did not finish"
            time.sleep(0.01)
        window._select_actor(first.id)
        window._exact_strength.setValue(0.47)
        window._set_calibration(Calibration(glow_strength=0.8, glow_color_mix=0.35))
        window._select_actor(second.id)
        assert window._exact_strength.value() == 1.3
        assert window._calibration.glow_color_mix == 0
        assert first.strength == 0.47
        assert first.calibration.glow_color_mix == 0.35
        window._actor_visible.setChecked(False)
        assert not second.visible and first.visible
        assert len(window._view._scene_sprites) == 2
        window._view.render_rgba((320, 180))
        window._remove_actor()
        assert window._active_actor == first.id
        assert len(window._view._scene_sprites) == 1
        assert window._exact_strength.value() == 0.47
        assert not errors, errors
    finally:
        window.close()
        app.processEvents()
