from dataclasses import replace

import numpy as np
from test_gpu_lighting import renderer as renderer

from scenelight.calibration import Calibration
from scenelight.preview.gpu_view import SceneSprite
from scenelight.preview.library import Actor


def test_multiple_characters_keep_separate_settings_and_light_each_other(renderer):
    background = np.full((144, 256, 4), 18, dtype=np.uint8)
    background[..., 3] = 255
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(background)
    renderer.set_compare_mode(0)
    left = Actor(name="left", horizontal=0.3, baseline=0.9, height=0.7, strength=0)
    right = Actor(name="right", horizontal=0.7, baseline=0.9, height=0.7, strength=1)
    sprites = [
        SceneSprite(left, renderer._sprite_frame, renderer._form_artifacts),
        SceneSprite(right, renderer._sprite_frame, renderer._form_artifacts),
    ]
    try:
        renderer.set_scene_sprites(sprites, left.id)
        original = renderer.render_rgba((640, 360))
        right.calibration = Calibration(
            glow_strength=1, glow_color_mix=1, glow_red=0, glow_green=0, glow_blue=1
        )
        glowing = renderer.render_rgba((640, 360))
        np.testing.assert_array_equal(original[:, :290], glowing[:, :290])
        assert np.max(np.abs(glowing[:, 330:].astype(int) - original[:, 330:].astype(int))) > 20
        right.calibration = replace(
            right.calibration,
            emission_strength=2,
            emission_radius=1.3,
            emission_red=1,
            emission_green=0,
            emission_blue=0,
        )
        # Zero-strength receiver is intentionally unaffected by cast light.
        np.testing.assert_array_equal(glowing[:, :290], renderer.render_rgba((640, 360))[:, :290])
        left.strength = 1
        cast = renderer.render_rgba((640, 360))
        right.calibration = replace(right.calibration, emission_strength=0)
        uncast = renderer.render_rgba((640, 360))
        assert (cast[:, :290, 0].astype(int) - uncast[:, :290, 0].astype(int)).max() > 5
        right.calibration = replace(right.calibration, emission_strength=2)
        renderer.set_scene_sprites(list(reversed(sprites)), left.id)
        np.testing.assert_array_equal(cast, renderer.render_rgba((640, 360)))
        right.visible = False
        hidden = renderer.render_rgba((640, 360))
        np.testing.assert_array_equal(uncast[:, :290], hidden[:, :290])
        assert np.all(hidden[:, 330:, :3] == 18)
    finally:
        renderer.set_scene_sprites(None)
