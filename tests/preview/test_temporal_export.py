from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from scenelight.preview.exporter import (
    MP4Writer,
    composite_gif_timeline,
    export_extension,
    save_gif,
)
from scenelight.preview.temporal import (
    TemporalSceneFrame,
    interpolate_metadata,
    interpolated_scene,
    interpolated_transport,
)


def test_transport_interpolates_every_encoded_channel() -> None:
    left = np.zeros((2, 4, 4), dtype=np.uint8)
    right = np.full((2, 4, 4), 200, dtype=np.uint8)
    anchors = {0: left, 4: right}

    middle = interpolated_transport(anchors, 2)

    assert middle is not None
    assert middle.dtype == np.uint8
    assert np.all(middle == 100)
    assert interpolated_transport(anchors, -3) is left
    assert interpolated_transport(anchors, 10) is right


def test_complete_scene_interpolation_updates_textures_lights_and_probes() -> None:
    left_array = np.zeros((2, 4, 4), dtype=np.uint8)
    right_array = np.full((2, 4, 4), 200, dtype=np.uint8)
    left_metadata = {
        "local_luminance": 0.1,
        "light_transport": [
            {
                "position_radius_intensity": [0.1, 0.2, 0.4, 0.5],
                "chroma_confidence": [1.0, 0.5, 0.5, 0.8],
                "emission_enabled": [0.4, 1.0],
            }
        ],
        "probe_transport": [
            {
                "direction_luminance_enabled": [-1.0, 0.0, 0.1, 1.0],
                "chroma": [1.0, 0.5, 0.5],
            }
        ],
    }
    right_metadata = {
        "local_luminance": 0.5,
        "light_transport": [
            {
                "position_radius_intensity": [0.9, 0.6, 0.8, 1.0],
                "chroma_confidence": [0.5, 0.5, 1.0, 1.0],
                "emission_enabled": [0.8, 1.0],
            }
        ],
        "probe_transport": [
            {
                "direction_luminance_enabled": [-1.0, 0.0, 0.5, 1.0],
                "chroma": [0.5, 0.5, 1.0],
            }
        ],
    }
    anchors = {
        0: TemporalSceneFrame(left_array, left_array, left_array, left_metadata),
        4: TemporalSceneFrame(right_array, right_array, right_array, right_metadata),
    }

    middle = interpolated_scene(anchors, 2)

    assert middle is not None
    assert np.all(middle.irradiance == 100)
    assert np.all(middle.emitter == 100)
    assert np.all(middle.transport == 100)
    assert np.isclose(middle.metadata["local_luminance"], 0.3)
    light = middle.metadata["light_transport"][0]
    assert np.allclose(light["position_radius_intensity"], [0.5, 0.4, 0.6, 0.75])
    assert np.allclose(middle.metadata["probe_transport"][0]["chroma"], [0.75, 0.5, 0.75])


def test_canonical_hue_slots_interpolate_by_identity_instead_of_proximity() -> None:
    physical_left = {
        "position_radius_intensity": [0.1, 0.2, 0.4, 1.0],
        "chroma_confidence": [1.0, 1.0, 1.0, 0.8],
        "emission_enabled": [0.4, 1.0],
    }
    red_left = {
        "position_radius_intensity": [0.8, 0.2, 0.4, 0.0],
        "chroma_confidence": [2.0, 0.5, 0.5, 0.8],
        "emission_enabled": [1.0, 0.0],
    }
    physical_right = {
        "position_radius_intensity": [0.8, 0.2, 0.4, 1.0],
        "chroma_confidence": [1.0, 1.0, 1.0, 0.8],
        "emission_enabled": [0.4, 1.0],
    }
    red_right = {
        "position_radius_intensity": [0.1, 0.2, 0.4, 0.0],
        "chroma_confidence": [2.0, 0.5, 0.5, 0.8],
        "emission_enabled": [1.0, 0.0],
    }
    left = {
        "light_transport_layout": "physical-rgb-families-v1",
        "light_transport": [physical_left, red_left],
    }
    right = {
        "light_transport_layout": "physical-rgb-families-v1",
        "light_transport": [physical_right, red_right],
    }

    middle = interpolate_metadata(left, right, 0.5)

    assert middle["light_transport"][0]["position_radius_intensity"][3] == 1.0
    assert middle["light_transport"][1]["position_radius_intensity"][3] == 0.0
    assert middle["light_transport"][1]["chroma_confidence"][:3] == [2.0, 0.5, 0.5]


def test_transport_layout_change_crossfades_secondary_identities_through_primary() -> None:
    pixels = np.zeros((2, 26 * 4, 4), dtype=np.uint8)
    left_transport = pixels.copy()
    right_transport = pixels.copy()
    left_transport[:, 8 * 4 : 9 * 4, :3] = 200
    right_transport[:, 8 * 4 : 9 * 4, :3] = 120
    physical = {
        "position_radius_intensity": [0.2, 0.3, 0.4, 1.0],
        "chroma_confidence": [1.0, 1.0, 1.0, 0.8],
        "emission_enabled": [0.4, 1.0],
    }
    creative = {
        "position_radius_intensity": [0.8, 0.3, 0.4, 0.0],
        "chroma_confidence": [2.0, 0.5, 0.5, 0.8],
        "emission_enabled": [1.0, 0.0],
    }
    left = TemporalSceneFrame(
        pixels,
        pixels,
        left_transport,
        {
            "light_transport_layout": "physical-components-v1",
            "light_transport": [physical, physical],
        },
    )
    right = TemporalSceneFrame(
        pixels + 200,
        pixels + 200,
        right_transport,
        {
            "light_transport_layout": "physical-rgb-families-v1",
            "light_transport": [physical, creative],
        },
    )

    first_half = interpolated_scene({0: left, 4: right}, 1)
    midpoint = interpolated_scene({0: left, 4: right}, 2)
    second_half = interpolated_scene({0: left, 4: right}, 3)

    assert first_half is not None
    assert midpoint is not None
    assert second_half is not None
    assert np.all(first_half.irradiance == 50)
    assert np.all(midpoint.irradiance == 100)
    assert np.all(second_half.irradiance == 150)
    assert first_half.metadata["light_transport"][1]["position_radius_intensity"][3] == 0.5
    assert midpoint.metadata["lights"] == 1
    assert second_half.metadata["light_transport"][1]["emission_enabled"][0] == 0.5
    assert np.all(first_half.transport[:, 8 * 4 : 9 * 4, :3] == 100)
    assert np.all(midpoint.transport[:, 8 * 4 : 9 * 4, :3] == 0)
    assert np.all(second_half.transport[:, 8 * 4 : 9 * 4, :3] == 60)


def test_export_format_follows_background_kind_and_gif_keeps_timing(
    tmp_path: Path,
) -> None:
    assert export_extension("static") == ".png"
    assert export_extension("animated-image") == ".gif"
    assert export_extension("video") == ".mp4"
    assert export_extension("static", "animated-image") == ".gif"

    frames = [
        np.full((24, 32, 4), (240, 20, 20, 255), dtype=np.uint8),
        np.full((24, 32, 4), (20, 40, 230, 255), dtype=np.uint8),
    ]
    destination = tmp_path / "composite.gif"
    save_gif(destination, frames, (70, 130))

    with Image.open(destination) as image:
        assert image.n_frames == 2
        image.seek(0)
        assert image.info["duration"] == 70
        image.seek(1)
        assert image.info["duration"] == 130


def test_combined_gif_timeline_preserves_both_animation_cycles() -> None:
    background = SimpleNamespace(
        kind="animated-image",
        duration_ms=200,
        cumulative_ms=(100, 200),
    )
    sprite = SimpleNamespace(
        kind="animated-image",
        duration_ms=300,
        cumulative_ms=(150, 300),
    )

    timestamps, durations = composite_gif_timeline(background, sprite)

    assert timestamps == (0, 100, 150, 200, 300, 400, 450, 500)
    assert durations == (100, 50, 50, 100, 100, 50, 50, 100)
    assert sum(durations) == 600


def test_mp4_writer_streams_gpu_frames_to_a_decodable_video(tmp_path: Path) -> None:
    source = tmp_path / "source.avi"
    source_writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (64, 36),
    )
    assert source_writer.isOpened()
    for value in (20, 80, 160):
        source_writer.write(np.full((36, 64, 3), (value, 40, 220), dtype=np.uint8))
    source_writer.release()

    destination = tmp_path / "composite.mp4"
    with MP4Writer(destination, source, (64, 36), 5.0) as writer:
        for value in (30, 100, 210):
            writer.write(np.full((36, 64, 4), (value, 60, 180, 255), dtype=np.uint8))

    capture = cv2.VideoCapture(str(destination))
    try:
        assert capture.isOpened()
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 3
        assert int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) == 64
        assert int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 36
        ok, decoded = capture.read()
        assert ok
        assert decoded is not None
    finally:
        capture.release()
