import numpy as np
import pytest
from PIL import Image

from scenelight.engine import Placement, _contrast_mid, analyze_scene, relight_sprite
from scenelight.form_maps import build_sprite_form_maps


@pytest.mark.parametrize("opacity", [3, 32, 38, 39, 255])
def test_translucent_sprite_maps_and_lighting_preserve_alpha(opacity):
    sprite = Image.new("RGBA", (48, 64), (180, 100, 60, opacity))
    maps = build_sprite_form_maps(sprite)
    assert np.isfinite(maps.metadata["contrast_mid"])
    scene = analyze_scene(Image.new("RGB", (96, 64), (90, 140, 170)), Placement())
    result = np.asarray(relight_sprite(sprite, scene))
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(result[..., 3], np.asarray(sprite)[..., 3])


def test_contrast_prefers_opaque_samples_when_available():
    luma = np.array([0.1, 0.2, 0.8, 0.9], dtype=np.float32)
    alpha = np.array([1.0, 1.0, 0.12, 0.0], dtype=np.float32)
    assert _contrast_mid(luma, alpha) == float(np.quantile(luma[:2], 0.52))


@pytest.mark.parametrize("opacity", [0, 2])
def test_invisible_sprite_still_rejected(opacity):
    sprite = Image.new("RGBA", (48, 64), (180, 100, 60, opacity))
    scene = analyze_scene(Image.new("RGB", (96, 64), "white"), Placement())
    for operation in (build_sprite_form_maps, lambda image: relight_sprite(image, scene)):
        with pytest.raises(ValueError, match="no visible pixels"):
            operation(sprite)
