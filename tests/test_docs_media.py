import runpy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

GENERATOR = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "tools/build_scene_examples.py")
)


@pytest.mark.parametrize("size", [(2643, 1821), (3840, 2160), (2160, 3840)])
@pytest.mark.parametrize("center", [(0.5, 0.5), (0.0, 0.0), (1.0, 1.0)])
def test_scene_crop_preserves_aspect_and_stays_inside_source(size, center):
    left, top, right, bottom = GENERATOR["crop_box"](size, center)
    assert 0 <= left < right <= size[0]
    assert 0 <= top < bottom <= size[1]
    assert (right - left) / (bottom - top) == pytest.approx(16 / 9)
    assert right - left == pytest.approx(size[0]) or bottom - top == pytest.approx(size[1])


def test_animation_keeps_last_frame_and_exact_duration(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for index in range(12):
        pixels = np.zeros((90, 160, 3), dtype=np.uint8)
        pixels[:, :, 0] = index * 20
        pixels[10:40, index * 8 : index * 8 + 20, 1] = 255
        Image.fromarray(pixels).save(frames / f"{index:05d}.png")
    records = GENERATOR["encode_animation"](
        frames, tmp_path / "example", 60, 12, lossless=True, size=(160, 90)
    )
    assert records["example.webp"]["frames"] == 12
    assert records["example.gif"]["frames"] == 10
    assert abs(records["example.webp"]["duration_ms"] - 200) <= 1
    assert records["example.gif"]["duration_ms"] == 200
    assert records["example.gif"]["frame_durations_ms"] == [20]
