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
    # v4 smooths the inferred height ridges before normal reconstruction.
    # Keep this reviewed surface stable across packing and optional-FX changes.
    expected = {
        "opaque": {
            "normal_noise": "a7d09d9f121700fe164b03581279e182db92cc75af205b2d7c7be2d4d8426eea",
            "height_ao_edge": "c362e890dd1ac50dfd93199b95ae4216d9f055cca6d5267b7aa8a7ac6f384d13",
            "response": "d17bc4082a8941719be73b5b6822c392d06bc5164116c16e36691c5711de35ba",
        },
        "sprite": {
            "normal_noise": "76d3751e6aa1683c1bf07fdad4eb88b829ddfa78a476204e41afd63ed181c13f",
            "height_ao_edge": "194cc97568f0ec4d264b9a522748c49928e449093896a0b2d511216b8d38ee37",
            "response": "d6b22ba76ef0d8b2da451f79d7a0b635b180b06f547419303710b493be4df3ff",
        },
    }
    assert FORM_MAP_VERSION == 4
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
