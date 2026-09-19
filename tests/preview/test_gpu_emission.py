import numpy as np
from test_gpu_lighting import renderer as renderer

from scenelight.calibration import Calibration


def test_glow_and_incoming_light_are_independent_and_disabled_pixels_match(renderer):
    background = np.full((144, 256, 4), 18, dtype=np.uint8)
    background[..., 3] = 255
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(background)
    renderer.set_placement(0.5, 0.95, 0.8)
    renderer.set_calibration(Calibration())
    renderer.set_sprite_emitters(())
    renderer.set_compare_mode(0)
    try:
        baseline = renderer.render_rgba((640, 360))
        renderer.set_calibration(Calibration(glow_strength=1.0, glow_radius=2.0))
        glowing = renderer.render_rgba((640, 360))
        assert np.mean(glowing[90:150, 300:340, :3]) > np.mean(baseline[90:150, 300:340, :3]) + 10
        # Alpha-defined silhouette: new halo pixels surround the sprite, not
        # an invented ellipse below its feet or the whole rectangle.
        empty = np.all(baseline[..., :3] == 18, axis=-1)
        halo = np.any(glowing[..., :3] != baseline[..., :3], axis=-1) & empty
        assert np.count_nonzero(halo) > 100
        assert np.count_nonzero(halo[:, :180]) == 0
        renderer.set_compare_mode(1)
        original_glow = renderer.render_rgba((640, 360))
        empty = np.all(original_glow[..., :3] == 18, axis=-1)
        renderer.set_calibration(Calibration())
        np.testing.assert_array_equal(original_glow, renderer.render_rgba((640, 360)))
        renderer.set_compare_mode(0)
        renderer.set_sprite_emitters((((0.34, 0.45, 0.7, 2.0), (1.0, 0.12, 0.0)),))
        cast = renderer.render_rgba((640, 360))
        delta = cast[..., :3].astype(float) - baseline[..., :3]
        assert delta[..., 0].max() > 10
        assert delta[..., 0].sum() > delta[..., 2].sum() + 1000
        np.testing.assert_array_equal(cast[empty], baseline[empty])
        renderer.set_sprite_emitters(())
        np.testing.assert_array_equal(baseline, renderer.render_rgba((640, 360)))
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_sprite_emitters(())
        renderer.set_compare_mode(0)
        renderer.set_placement(0.65, 1.0, 0.92)
