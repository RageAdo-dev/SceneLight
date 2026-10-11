import numpy as np
from PIL import Image, ImageDraw
from test_gpu_lighting import _lamps
from test_gpu_lighting import renderer as renderer


def test_transparent_lower_canvas_does_not_draw_an_invented_floor_shadow(renderer, tmp_path):
    from scenelight.calibration import Calibration
    from scenelight.preview.artifacts import ArtifactCache

    original_source, original_form = renderer._sprite_path, renderer._form_artifacts
    sprite = Image.new("RGBA", (160, 240))
    ImageDraw.Draw(sprite).ellipse((15, 10, 145, 190), fill=(225, 190, 145, 255))
    path = tmp_path / "floating-sprite.png"
    sprite.save(path)
    cache = ArtifactCache(tmp_path / "forms")
    cache._cuda_available = False
    try:
        renderer.set_sprite(path, cache.form(path))
        renderer.set_placement(0.5, 0.95, 0.8)
        renderer.set_live_analysis_enabled(True)
        renderer.set_background_frame(_lamps(1.0))
        renderer.set_calibration(Calibration(shadow_strength=2.0))
        renderer.set_compare_mode(1)
        unlit = renderer.render_rgba((640, 360))
        renderer.set_compare_mode(0)
        lit = renderer.render_rgba((640, 360))
        # The lower quarter of this sprite is wholly transparent. Lighting may
        # shade the sprite, but must not paint a separate oval on the floor.
        np.testing.assert_array_equal(lit[312:342], unlit[312:342])
        assert np.abs(lit[100:230].astype(int) - unlit[100:230].astype(int)).max() > 10
    finally:
        renderer.set_compare_mode(0)
        renderer.set_calibration(Calibration())
        renderer.set_sprite(original_source, original_form)
        renderer.set_placement(0.65, 1.0, 0.92)
        cache.shutdown()
