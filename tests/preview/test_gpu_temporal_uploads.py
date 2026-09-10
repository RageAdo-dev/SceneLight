from types import SimpleNamespace as NS

import numpy as np

from scenelight.preview.gpu_view import SceneLightGPUView


def test_changing_phase_reuses_textures_but_new_endpoints_upload():
    uploads, updates = [], []
    view = NS(
        _scene_blend=None,
        _initialized=True,
        makeCurrent=lambda: None,
        doneCurrent=lambda: None,
        update=lambda: updates.append(True),
        _replace_texture=lambda name, pixels: uploads.append((name, pixels.copy())),
    )

    def frame(value):
        return NS(
            **{
                k: np.full((2, 3, 4), value, np.uint8)
                for k in ("irradiance", "emitter", "transport")
            }
        )

    left, right, following = frame(1), frame(2), frame(3)
    set_blend = SceneLightGPUView.set_live_scene_blend
    for amount in (0.0, 0.1, 0.5, 0.9):
        set_blend(view, NS(left=left, right=right, amount=amount, metadata={"phase": amount}))
    assert len(uploads) == 3
    assert [name for name, _ in uploads] == ["irradiance", "emitter", "transport_pair"]
    assert all(pixels.shape == (2, 6, 4) for _, pixels in uploads)
    assert view._live_scene_metadata == {"phase": 0.9}
    set_blend(view, NS(left=right, right=following, amount=0.0, metadata={}))
    assert len(uploads) == 6
    assert len(updates) == 5
