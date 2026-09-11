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


def test_repacked_form_maps_preserve_every_approved_logical_texel() -> None:
    # These are hashes captured immediately before the optional-effects
    # implementation. Rain and glitch are runtime-only, so the approved
    # physical form textures must remain byte-identical.
    expected = {
        "opaque": {
            "normal_noise": "f31a4a00857470e9707a78822c6199cfff53ba2950893eda8c3dd584542595df",
            "height_ao_edge": "05792c02e4064a466b50f410848e9840548935c2cad2a9c3bb995b73ba8fa611",
            "response": "9ab5910c74bd5e9ba8cace49e6cd38aa9ab35e23a4ab381df7e787415a44f3dd",
        },
        "sprite": {
            "normal_noise": "85d42d5260d709e86fbaded5375ee53c99ca5056662bb605d5a7a352e88db726",
            "height_ao_edge": "39be341a0f5ea304ec32d8c74c4dcc341442de2f20f6625e05b31064f440a065",
            "response": "a7e66718d4af9b26facf7b04049dc8ce60f4bce748eee52bffe7e98cd3ee13cc",
        },
    }
    assert FORM_MAP_VERSION == 3
    for mode, hashes in expected.items():
        maps = build_sprite_form_maps(_pre_effect_fixture(mode))
        normal = np.asarray(maps.normal_noise.convert("RGB"), dtype=np.uint8)
        auxiliary = np.asarray(maps.height_ao_edge.convert("RGB"), dtype=np.uint8)
        # v2 groups smooth normal/edge bytes and height/AO/noise bytes into two
        # RGB files. Reconstructing v1's logical shader channels must remain
        # byte-identical, as must the directional response texture.
        logical_normal = np.dstack((normal[..., :2], auxiliary[..., 2]))
        logical = {
            "normal_noise": logical_normal.tobytes(),
            "height_ao_edge": np.dstack((auxiliary[..., :2], normal[..., 2])).tobytes(),
            "response": maps.response.convert("RGB").tobytes(),
        }
        for name, expected_hash in hashes.items():
            assert hashlib.sha256(logical[name]).hexdigest() == expected_hash
