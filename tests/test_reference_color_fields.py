"""Compare accelerated hue support against the dense reference calculation."""

import cv2
import numpy as np

from scenelight.engine import (
    _linear_to_srgb,
    _prepare_creative_color_fields,
    _srgb_to_linear,
)


def test_sparse_hue_fields_are_bit_identical_at_boundaries_and_random_colors():
    rng = np.random.default_rng(20260908)
    display = rng.random((160, 320, 3), dtype=np.float32)
    hue = np.linspace(0, 359.99997, 6400, dtype=np.float32)
    hsv_boundary = np.stack((hue, np.ones_like(hue), np.ones_like(hue)), axis=-1)
    display[:20] = cv2.cvtColor(hsv_boundary.reshape(20, 320, 3), cv2.COLOR_HSV2RGB)
    linear = _srgb_to_linear(display)
    roundtrip = np.clip(_linear_to_srgb(linear), 0, 1).astype(np.float32)
    hsv = cv2.cvtColor(roundtrip, cv2.COLOR_RGB2HSV)
    saturation, saturated, actual = _prepare_creative_color_fields(linear)
    np.testing.assert_array_equal(saturation, hsv[..., 1])
    np.testing.assert_array_equal(saturated, hsv[..., 1] >= 0.24)
    for sector, membership in enumerate(actual):
        expected = np.clip(
            1.0
            - np.abs((hsv[..., 0] - (sector * 30.0 + 15.0) + 180.0) % 360.0 - 180.0)
            / (30.0 * 0.72),
            0.0,
            1.0,
        )
        np.testing.assert_array_equal(membership, expected)
