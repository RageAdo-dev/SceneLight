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
    # v6 normalizes slope units; height, occlusion and grain stay unchanged.
    # Keep this reviewed surface stable across packing and optional-FX changes.
    expected = {
        "opaque": {
            "normal_noise": "d05a82d21d315c9c8ca8c8286c40026109ca4e31f448ec477966c35cd4710f73",
            "height_ao_edge": "93dbb612dc5b151e37848507c4fd8a0bfc01204d5b272400da74a2f470102e4b",
            "response": "0de2c34e2d4cdbfee235ba2e308acbe64a798cd95cc0fd4027d6d4a513911c87",
        },
        "sprite": {
            "normal_noise": "8f7af25c01314a3dbd1d3ce58291721bfc2f2239ad1e75598eba29c10db07786",
            "height_ao_edge": "138c4c998c0ab1b7dead4e33e117cd3d1d854c7e23ee931dd4fdd8f7416f7231",
            "response": "5bd0747e424d719ab43343e50c9774a07b92eb849f469e56a180a035f05f4e09",
        },
    }
    assert FORM_MAP_VERSION == 8
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
