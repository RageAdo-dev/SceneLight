import numpy as np
import pytest
from PIL import Image

from scenelight.engine import _pseudo_surface
from scenelight.form_maps import build_sprite_form_maps


def test_surface_direction_does_not_flatten_at_higher_resolution():
    samples = []
    for size in (256, 512, 960):
        alpha = np.zeros((size, size), np.float32)
        alpha[size // 8 : 7 * size // 8, size // 4 : 3 * size // 4] = 1
        paint = np.full((size, size, 3), 0.6, np.float32)
        _, nx, ny, nz = _pseudo_surface(alpha, paint, 0.72)
        points = [(size // 2, round(size * x)) for x in (0.32, 0.4, 0.6, 0.68)]
        samples.append(np.array([[nx[y, x], ny[y, x], nz[y, x]] for y, x in points]))
    # Resizing the same artwork must not change the inferred surface angles.
    for normals in samples[1:]:
        np.testing.assert_allclose(normals, samples[0], atol=0.025)


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


def test_painted_color_boundary_cannot_become_a_deep_surface_crease():
    size = 512
    alpha = np.zeros((size, size), np.float32)
    alpha[32:480, 64:448] = 1
    paint = np.full((size, size, 3), 0.4, np.float32)
    striped = paint.copy()
    striped[:, 240:272] = 0.98
    _, *base = _pseudo_surface(alpha, paint, 0.72)
    _, *detail = _pseudo_surface(alpha, striped, 0.72)
    change = np.linalg.norm(np.stack(detail) - np.stack(base), axis=0)
    # The printed stripe may add shallow relief, not a near-sideways normal.
    assert 0.1 < change.max() < 0.30


def test_fine_painted_relief_survives_without_spreading_across_the_surface():
    size = 256
    alpha = np.zeros((size, size), dtype=np.float32)
    alpha[16:240, 32:224] = 1
    srgb = np.full((size, size, 3), 0.6, dtype=np.float32)
    y, x = np.mgrid[:size, :size]
    radius_squared = (x - 96) ** 2 + (y - 128) ** 2
    highlight = np.exp(-radius_squared / (2 * 4**2)).astype(np.float32)
    detailed = srgb + 0.25 * highlight[..., None]

    height, *normal = _pseudo_surface(alpha, srgb, 0.72)
    detail_height, *detail_normal = _pseudo_surface(alpha, detailed, 0.72)
    change = np.linalg.norm(np.stack(detail_normal) - np.stack(normal), axis=0)

    # A small painted feature must affect local relief without becoming a
    # broad blob. Filtering the complete height at silhouette scale fails this.
    assert change.max() > 0.1
    assert np.max(np.abs(detail_height - height)) > 0.03
    assert change[radius_squared > 32**2].max() < 0.001


def test_narrow_painted_ribbon_stays_flatter_than_painted_volume():
    size = 512
    alpha = np.zeros((size, size), dtype=np.float32)
    alpha[32:480, 64:448] = 1
    flat = np.full((size, size, 3), 0.55, dtype=np.float32)
    base = np.stack(_pseudo_surface(alpha, flat, 0.72)[1:])

    ribbon_paint = flat.copy()
    ribbon_paint[:, 254:258] = 0.85
    volume_paint = flat.copy()
    volume_paint[:, 226:286] = 0.85
    ribbon = np.stack(_pseudo_surface(alpha, ribbon_paint, 0.72)[1:])
    volume = np.stack(_pseudo_surface(alpha, volume_paint, 0.72)[1:])

    ribbon_effect = np.linalg.norm(ribbon - base, axis=0).max()
    volume_effect = np.linalg.norm(volume - base, axis=0).max()
    # A strand-wide painted stripe must read as albedo rather than as a ridge,
    # while broad painted volume still shapes the surface.
    assert volume_effect > 0.15
    assert ribbon_effect < 0.6 * volume_effect
