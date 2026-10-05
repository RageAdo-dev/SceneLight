from dataclasses import replace

import numpy as np
from test_gpu_lighting import renderer as renderer

from scenelight.calibration import Calibration


def test_background_color_adjustment_selects_light_not_sprite_paint(renderer):
    renderer.set_live_analysis_enabled(True)
    renderer.set_strength(1)
    renderer.set_placement(0.5, 1, 0.92)
    background = np.full((144, 256, 4), 255, np.uint8)
    background[..., :3] = (85, 135, 205)
    renderer.set_background_frame(background)
    base = Calibration.from_mapping({"light_color": "#4080FF"})
    output = {}
    try:
        for amount in (0, -1, 1):
            renderer.set_calibration(replace(base, light_color_amount=amount))
            output[amount] = renderer.render_rgba((640, 360))
        # The background is not recolored by a sprite-light control.
        np.testing.assert_array_equal(output[0][:, :150], output[-1][:, :150])
        patch = np.s_[190:260, 310:330, :3]
        blue_cast = {
            k: float(v[patch][..., 2].mean() - v[patch][..., 0].mean()) for k, v in output.items()
        }
        assert blue_cast[-1] < blue_cast[0] - 2, blue_cast
        assert blue_cast[1] > blue_cast[0] + 1, blue_cast
        renderer.set_calibration(
            replace(base, light_color_amount=0, light_color_red=1, light_color_blue=0)
        )
        np.testing.assert_array_equal(output[0], renderer.render_rgba((640, 360)))
        renderer.set_strength(0)
        renderer.set_calibration(base)
        original = renderer.render_rgba((640, 360))
        renderer.set_calibration(replace(base, light_color_amount=-1))
        np.testing.assert_array_equal(original, renderer.render_rgba((640, 360)))
        # A red target should not suppress a blue environment cast.
        renderer.set_strength(1)
        renderer.set_calibration(
            Calibration.from_mapping(
                {"light_color": "#FF0000", "light_color_amount": -1, "light_color_tolerance": 0.05}
            )
        )
        red_filter = renderer.render_rgba((640, 360))
        assert np.abs(red_filter[patch].astype(float) - output[0][patch]).mean() < 1
    finally:
        renderer.set_calibration(Calibration())
        renderer.set_strength(1)
        renderer.set_placement(0.65, 1, 0.92)
