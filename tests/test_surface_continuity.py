import numpy as np
import pytest
from PIL import Image

from scenelight.engine import _pseudo_surface
from scenelight.form_maps import build_sprite_form_maps


@pytest.mark.parametrize("size", [256, 512])
def test_flat_paint_has_no_silhouette_medial_crease(size):
    alpha = np.zeros((size, size), dtype=np.float32)
    alpha[size // 8 : 7 * size // 8, size // 4 : 3 * size // 4] = 1
    srgb = np.full((size, size, 3), 0.6, dtype=np.float32)
    height, nx, ny, nz = _pseudo_surface(alpha, srgb, 0.72)

    # Equidistant edges used to create a narrow roof ridge through flat paint.
    # A broad surface crosses its center smoothly but still slopes both ways.
    row = nx[size // 2, size // 4 : 3 * size // 4]
    assert np.max(np.abs(np.diff(row))) < 0.02
    assert row.min() < -0.15 and row.max() > 0.15
    assert np.max(height) > 0.6
    assert np.allclose(nx * nx + ny * ny + nz * nz, 1.0, atol=1e-5)
    assert np.all(height[alpha == 0] == 0)


def test_surface_preparation_keeps_source_pixels_and_transparency():
    rng = np.random.default_rng(642)
    rgba = rng.integers(0, 256, size=(80, 64, 4), dtype=np.uint8)
    sprite = Image.fromarray(rgba)
    before = sprite.tobytes()
    maps = build_sprite_form_maps(sprite)
    assert sprite.tobytes() == before
    assert maps.metadata["map_size"] == [64, 80]
    assert maps.normal_noise.size == sprite.size
