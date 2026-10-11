"""Selective glow runs on original alpha-aware artwork, once per target."""

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image, ImageDraw
from test_gpu_lighting import renderer as renderer

from scenelight.calibration import Calibration, ColorGlowRule
from scenelight.preview.artifacts import ArtifactCache
from scenelight.preview.gpu_view import SceneSprite
from scenelight.preview.library import Actor


@pytest.fixture
def color_sprite(renderer, tmp_path):
    old_path, old_form = renderer._sprite_path, renderer._form_artifacts
    sprite = Image.new("RGBA", (160, 240), (255, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    for rect, color in [
        ((15, 20, 65, 75), (145, 12, 12, 255)),
        ((95, 20, 145, 75), (12, 22, 145, 255)),
        ((15, 115, 65, 170), (60, 4, 4, 255)),
        ((95, 115, 145, 170), (145, 80, 12, 255)),
    ]:
        draw.rectangle(rect, fill=color)
    path = tmp_path / "colors.png"
    sprite.save(path)
    cache = ArtifactCache(tmp_path / "cache")
    cache._cuda_available = False
    renderer.set_scene_sprites(None)
    renderer.set_sprite(path, cache.form(path))
    background = np.full((144, 256, 4), 18, np.uint8)
    background[..., 3] = 255
    renderer.set_background_frame(background)
    renderer.set_live_analysis_enabled(True)
    renderer.set_placement(0.5, 0.9, 0.8)
    renderer.set_calibration(Calibration())
    renderer.set_strength(0)
    renderer.set_compare_mode(0)
    renderer.set_sprite_emitters(())
    yield renderer, cache
    renderer.set_scene_sprites(None)
    renderer.set_sprite(old_path, old_form)
    renderer.set_calibration(Calibration())
    renderer.set_strength(1)
    renderer.set_compare_mode(0)
    renderer.set_placement(0.65, 1.0, 0.92)
    cache.shutdown()


def _patch(frame, x, y):
    # Sprite UV translated to screen with its measured alpha center at x=320.
    sx, sy = round(224 + x * 1.2), round(36 + y * 1.2)
    return frame[sy - 8 : sy + 8, sx - 8 : sx + 8, :3].astype(float)


def test_hue_range_multiple_rules_original_colors_and_disabled_identity(color_sprite):
    renderer, _cache = color_sprite
    baseline = renderer.render_rgba((640, 360))
    red = ColorGlowRule(color=(1, 0, 0), radius=0, tolerance=0.08, softness=0.02)
    renderer.set_calibration(Calibration(glow_rules=(red,)))
    narrow = renderer.render_rgba((640, 360))
    for x, y in ((40, 45), (40, 140)):
        assert (_patch(narrow, x, y) - _patch(baseline, x, y)).mean() > 8
    for x, y in ((120, 45), (120, 140)):
        assert np.abs(_patch(narrow, x, y) - _patch(baseline, x, y)).max() <= 1
    renderer.set_calibration(Calibration(glow_rules=(replace(red, tolerance=0.5),)))
    wide = renderer.render_rgba((640, 360))
    assert (_patch(wide, 120, 140) - _patch(narrow, 120, 140)).mean() > 10
    blue = ColorGlowRule(color=(0, 0, 1), radius=0, tolerance=0.1)
    renderer.set_calibration(Calibration(glow_rules=(red, blue)))
    both = renderer.render_rgba((640, 360))
    assert (_patch(both, 120, 45) - _patch(narrow, 120, 45)).mean() > 8
    renderer.set_calibration(Calibration(glow_rules=(blue, red)))
    np.testing.assert_allclose(both, renderer.render_rgba((640, 360)), atol=1)
    # Only the last of nineteen active rules matches blue: no fixed rule cap.
    green = replace(red, color=(0, 1, 0), tolerance=0)
    renderer.set_calibration(Calibration(glow_rules=(green,) * 18 + (blue,)))
    many = renderer.render_rgba((640, 360))
    assert (_patch(many, 120, 45) - _patch(baseline, 120, 45)).mean() > 8
    renderer.set_compare_mode(1)
    original = renderer.render_rgba((640, 360))
    renderer.set_calibration(Calibration())
    np.testing.assert_array_equal(original, renderer.render_rgba((640, 360)))
    renderer.set_compare_mode(0)
    for rule in (replace(red, strength=0), replace(red, enabled=False)):
        renderer.set_calibration(Calibration(glow_rules=(rule,)))
        np.testing.assert_array_equal(baseline, renderer.render_rgba((640, 360)))


def test_matching_uses_artwork_before_global_tint_and_not_transparent_rgb(color_sprite):
    renderer, _cache = color_sprite
    tinted = Calibration(
        glow_strength=0.6, glow_color_mix=1, glow_red=0, glow_green=1, glow_blue=0, glow_radius=0
    )
    renderer.set_calibration(tinted)
    baseline = renderer.render_rgba((640, 360))
    renderer.set_calibration(replace(tinted, glow_rules=(ColorGlowRule(radius=0),)))
    red_only = renderer.render_rgba((640, 360))
    assert (_patch(red_only, 40, 45) - _patch(baseline, 40, 45)).mean() > 5
    assert np.abs(_patch(red_only, 120, 45) - _patch(baseline, 120, 45)).max() <= 1
    # Source transparent pixels deliberately contain pure red. They do not emit.
    np.testing.assert_array_equal(red_only[280:320, 230:410], baseline[280:320, 230:410])


def test_multiple_targets_and_different_sizes_reuse_buffers_after_warmup(color_sprite, monkeypatch):
    from OpenGL import GL

    renderer, cache = color_sprite
    source = renderer._sprite_frame
    small = Image.fromarray(source).resize((80, 120))
    small_path = cache.root.parent / "small.png"
    small.save(small_path)
    small_artifacts = cache.form(small_path)
    left = Actor(name="left", horizontal=0.25, baseline=0.9, height=0.6, strength=0)
    right = Actor(name="right", horizontal=0.75, baseline=0.9, height=0.6, strength=0)
    sprites = [
        SceneSprite(left, source, renderer._form_artifacts),
        SceneSprite(right, np.array(small), small_artifacts),
    ]
    renderer.set_scene_sprites(sprites, left.id)
    baseline = renderer.render_rgba((640, 360))
    left.calibration = Calibration(glow_rules=(ColorGlowRule(radius=1.5),))
    one = renderer.render_rgba((640, 360))
    np.testing.assert_array_equal(baseline[:, 330:], one[:, 330:])
    assert np.max(np.abs(baseline[:, :310].astype(int) - one[:, :310].astype(int))) > 20
    right.calibration = Calibration(glow_rules=(ColorGlowRule(color=(0, 0, 1)),))
    both = renderer.render_rgba((640, 360))
    assert np.max(np.abs(both[:, 330:].astype(int) - baseline[:, 330:].astype(int))) > 20
    calls = []
    allocate = GL.glGenTextures
    monkeypatch.setattr(GL, "glGenTextures", lambda *args: (calls.append(args), allocate(*args))[1])
    for _ in range(3):
        np.testing.assert_array_equal(both, renderer.render_rgba((640, 360)))
    # render_rgba's destination texture is the only allocation each frame.
    assert calls == [(1,), (1,), (1,)]
    renderer.set_scene_sprites(list(reversed(sprites)), left.id)
    np.testing.assert_array_equal(both, renderer.render_rgba((640, 360)))


def test_small_color_detail_has_smooth_halo_without_displaced_copies(color_sprite):
    renderer, cache = color_sprite
    image = Image.new("RGBA", (160, 240))
    ImageDraw.Draw(image).ellipse((75, 115, 85, 125), fill=(180, 12, 12, 255))
    path = cache.root.parent / "gem.png"
    image.save(path)
    renderer.set_sprite(path, cache.form(path))
    renderer.set_calibration(Calibration())
    baseline = renderer.render_rgba((640, 360))
    renderer.set_calibration(Calibration(glow_rules=(ColorGlowRule(strength=2, radius=2),)))
    glow = renderer.render_rgba((640, 360))
    added = glow[..., 0].astype(int) - baseline[..., 0].astype(int)
    # At right of gem the halo falls smoothly away, with no second peak.
    line = added[180, 329:350]
    assert line.max() > 1
    assert np.all(np.diff(line) <= 1), line
    assert np.count_nonzero(added[150:210, 285:355]) > 100
    assert added[:130].max() == 0 and added[230:].max() == 0


@pytest.mark.parametrize("selective", [False, True])
def test_gpu_glow_keeps_increasing_above_two_up_to_ten(color_sprite, selective):
    renderer, _cache = color_sprite
    frames = []
    for strength in (2, 6, 10):
        calibration = (
            Calibration(glow_rules=(ColorGlowRule(strength=strength, radius=0),))
            if selective
            else Calibration(glow_strength=strength, glow_radius=0)
        )
        renderer.set_calibration(calibration)
        frames.append(renderer.render_rgba((640, 360)))
    for before, after in zip(frames, frames[1:]):
        assert (_patch(after, 40, 140) - _patch(before, 40, 140)).mean() > 2
    if selective:
        np.testing.assert_array_equal(_patch(frames[0], 120, 45), _patch(frames[-1], 120, 45))
