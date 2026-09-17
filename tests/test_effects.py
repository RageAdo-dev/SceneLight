import hashlib

import numpy as np
from PIL import Image, ImageDraw

from scenelight.form_maps import _SRGB_U8_TO_LINEAR, FORM_MAP_VERSION, build_sprite_form_maps


def test_integer_srgb_lookup_preserves_every_approved_float32_value() -> None:
    assert _SRGB_U8_TO_LINEAR.dtype == np.float32
    assert not _SRGB_U8_TO_LINEAR.flags.writeable
    assert hashlib.sha256(_SRGB_U8_TO_LINEAR.astype("<f4").tobytes()).hexdigest() == (
        "305f395a99e83b5e2f75b6de7c72acc42af192eab6e377a18d6b209beead7c04"
    )


def _pre_effect_fixture(mode: str) -> Image.Image:
    image = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if mode == "opaque":
        draw.rectangle((8, 6, 87, 123), fill=(153, 97, 210, 255))
        draw.ellipse((22, 24, 42, 38), fill=(245, 235, 220, 255))
        draw.ellipse((54, 24, 74, 38), fill=(245, 235, 220, 255))
    else:
        draw.ellipse((24, 8, 72, 58), fill=(210, 151, 134, 255))
        draw.rectangle((32, 50, 64, 118), fill=(80, 110, 170, 255))
        draw.ellipse((34, 28, 42, 36), fill=(30, 180, 220, 255))
        draw.ellipse((54, 28, 62, 36), fill=(30, 180, 220, 255))
    return image


def test_form_maps_preserve_the_reviewed_smooth_surface_texels() -> None:
    # v7 removes painted line art and strand-scale edges from the inferred
    # surface; height, occlusion and grain stay unchanged.
    # Keep this reviewed surface stable across packing and optional-FX changes.
    expected = {
        "opaque": {
            "normal_noise": "96386a8abe804f0b09b881378c867c0be094a26f82fa067e8b409077d579e47d",
            "height_ao_edge": "dab731c09395ffa639c43cd0725f6eb8f47154870a123c58d1cfdf18e94a15e3",
            "response": "07cb1a72fe6c0b9e51fe0982a0d75fb6560b871807bc14013f083a99d59d12ce",
        },
        "sprite": {
            "normal_noise": "8bebb5783d74630fb7d1033dd0b2a47cc27a5d50dd27f79692d027bafc72c28e",
            "height_ao_edge": "84239543ad6486c6473ec47c4ded598134d3d76bb939930f11d3bf6b200dc6e9",
            "response": "ddcada65d4c2afd1aa051da1caf066f1d511083bd963c52e2cc83b027ba83f8f",
        },
    }
    assert FORM_MAP_VERSION == 7
    for mode, hashes in expected.items():
        maps = build_sprite_form_maps(_pre_effect_fixture(mode))
        normal = np.asarray(maps.normal_noise.convert("RGB"), dtype=np.uint8)
        auxiliary = np.asarray(maps.height_ao_edge.convert("RGB"), dtype=np.uint8)
        # Compare logical channels so PNG compression and physical channel
        # packing cannot hide a change to the reviewed surface or grain.
        logical_normal = np.dstack((normal[..., :2], auxiliary[..., 2]))
        logical = {
            "normal_noise": logical_normal.tobytes(),
            "height_ao_edge": np.dstack((auxiliary[..., :2], normal[..., 2])).tobytes(),
            "response": maps.response.convert("RGB").tobytes(),
        }
        for name, expected_hash in hashes.items():
            assert hashlib.sha256(logical[name]).hexdigest() == expected_hash
