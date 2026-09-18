"""Exercise alias exposure with the production fragment shader on real GL."""

from dataclasses import replace

import numpy as np
import pytest
import test_gpu_lighting

renderer = test_gpu_lighting.renderer


@pytest.mark.parametrize("authored_grade", [0.0, 1.0])
def test_nonowner_additive_lighting_retains_dark_scene_exposure(
    renderer, monkeypatch, authored_grade
):
    from scenelight.calibration import Calibration
    from scenelight.engine import _srgb_to_linear

    original_uniform = renderer._uniform
    reference_scale = 1.0

    def uniform(name, value):
        if name in ("u_sc_exposure_owner", "u_sc_exposure_bias_owner"):
            value = 0.0
        elif name == "u_sc_exposure_auto":
            # An inner ungraded alias already exposed the incoming art.
            value = 1.0
        elif name == "u_sc_exposure_bias":
            value = -1.0
        elif name == "u_sc_authored_grade":
            value = authored_grade
        elif name == "u_sc_reference_mid":
            value *= reference_scale
        original_uniform(name, value)

    monkeypatch.setattr(renderer, "_uniform", uniform)
    calibration = Calibration(
        auto_strength=0.25,
        exposure_bias=2.0,
        contrast_match=0.0,
        saturation_match=0.0,
        highlight_rolloff=0.0,
        grain_match=0.0,
        wrap_strength=0.0,
        specular_strength=0.0,
        rim_strength=0.0,
    )
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(test_gpu_lighting._lamps(1.0))
    energies = []
    try:
        for reference_scale in (1.0, 40.0):
            renderer.set_calibration(calibration)
            without = _srgb_to_linear(renderer.render_rgba((640, 360))[..., :3] / 255.0)
            renderer.set_calibration(replace(calibration, specular_strength=2.0, rim_strength=2.0))
            with_highlights = _srgb_to_linear(renderer.render_rgba((640, 360))[..., :3] / 255.0)
            energies.append(float(np.maximum(with_highlights - without, 0.0).sum()))
        assert energies[0] > 0.01, energies
        assert 0.0 < energies[1] < energies[0] * 0.2, energies
    finally:
        renderer.set_calibration(Calibration())


def test_inherited_bias_scales_new_highlights_independently_of_outer_bias(renderer, monkeypatch):
    from scenelight.calibration import Calibration
    from scenelight.engine import _srgb_to_linear

    original_uniform = renderer._uniform
    inherited_bias = 0.0

    def uniform(name, value):
        if name in ("u_sc_exposure_owner", "u_sc_exposure_bias_owner"):
            value = 0.0
        elif name == "u_sc_exposure_auto":
            value = 1.0
        elif name == "u_sc_exposure_bias":
            value = inherited_bias
        original_uniform(name, value)

    monkeypatch.setattr(renderer, "_uniform", uniform)
    calibration = Calibration(
        exposure_bias=2.0,
        contrast_match=0.0,
        saturation_match=0.0,
        highlight_rolloff=0.0,
        grain_match=0.0,
        wrap_strength=0.0,
        specular_strength=0.0,
        rim_strength=0.0,
    )
    renderer.set_live_analysis_enabled(True)
    renderer.set_background_frame(test_gpu_lighting._lamps(1.0))
    energies = []
    try:
        for inherited_bias in (0.0, -2.0):
            renderer.set_calibration(calibration)
            without = _srgb_to_linear(renderer.render_rgba((640, 360))[..., :3] / 255.0)
            renderer.set_calibration(replace(calibration, specular_strength=2.0, rim_strength=2.0))
            with_highlights = _srgb_to_linear(renderer.render_rgba((640, 360))[..., :3] / 255.0)
            energies.append(float(np.maximum(with_highlights - without, 0.0).sum()))
        assert energies[0] > 0.01, energies
        assert energies[1] / energies[0] == pytest.approx(0.25, abs=0.03), energies
    finally:
        renderer.set_calibration(Calibration())
