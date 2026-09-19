import hashlib
import json
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from test_project import make_project

import scenelight.builder as builder_module
import scenelight.cuda_backend as cuda_backend
from scenelight.builder import build_project
from scenelight.engine import DetectedLight
from scenelight.form_maps import FORM_MAP_VERSION
from scenelight.project import SpriteSpec, discover_project


def test_stable_color_table_invalidates_the_previous_form_cache_key(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"legacy raw sprite bytes")
    spec = SpriteSpec("test", (source,))
    # Captured from the v3 fingerprint with these exact encoded source bytes.
    legacy = "443a0cec7cb6f12f7152f149d9c49e3931f2e4b2d76116b9899e6860599badae"
    current = builder_module._sprite_spec_fingerprint(spec)
    assert current != legacy
    assert builder_module._sprite_spec_fingerprint(spec) == current


def test_neutral_key_plus_strong_colored_source_uses_spatial_family_slots() -> None:
    physical = DetectedLight(
        0.132926,
        0.590472,
        (0.711002, 0.744097, 0.718009),
        1.0,
        0.776793,
        0.633167,
        0.655655,
    )
    strongest_red = DetectedLight(
        0.392930,
        0.529051,
        (0.864848, 0.703830, 0.596286),
        1.0,
        0.457433,
        0.96,
        1.0,
        True,
    )
    weaker_same_family = DetectedLight(
        0.128235,
        0.677144,
        (1.0, 0.612363, 0.650323),
        0.65,
        0.528164,
        0.635255,
        1.0,
        True,
    )
    analysis = SimpleNamespace(
        lights=(physical,),
        creative_lights=(strongest_red, weaker_same_family),
    )

    selected = builder_module._select_transport_lights(analysis)

    assert len(selected) == 4
    assert selected[0] is physical
    expected_x = (strongest_red.x + weaker_same_family.x * 0.65**2) / (1.0 + 0.65**2)
    assert selected[1].x == pytest.approx(expected_x, abs=1e-6)
    assert weaker_same_family.x < selected[1].x < strongest_red.x
    assert sum(light.creative_only and light.intensity > 0 for light in selected) == 1


def test_weak_single_color_candidate_preserves_ordinary_physical_lights() -> None:
    physical = (
        DetectedLight(0.2, 0.2, (0.73, 0.73, 0.73), 1.0, 0.4, 0.8),
        DetectedLight(0.8, 0.2, (0.78, 0.75, 0.70), 0.6, 0.3, 0.7),
    )
    weak_prop = DetectedLight(
        0.7,
        0.7,
        (0.95, 0.45, 0.42),
        1.0,
        0.08,
        0.68,
        1.0,
        True,
    )
    analysis = SimpleNamespace(lights=physical, creative_lights=(weak_prop,))

    assert builder_module._select_transport_lights(analysis) == physical


def test_scene_layout_can_force_consistent_slots_across_placement_samples() -> None:
    physical = (
        DetectedLight(0.2, 0.2, (0.73, 0.73, 0.73), 1.0, 0.4, 0.8),
        DetectedLight(0.8, 0.2, (0.78, 0.75, 0.70), 0.6, 0.3, 0.7),
    )
    weak_prop = DetectedLight(
        0.7,
        0.7,
        (0.95, 0.45, 0.42),
        1.0,
        0.08,
        0.68,
        1.0,
        True,
    )
    analysis = SimpleNamespace(lights=physical, creative_lights=(weak_prop,))

    creative_slots = builder_module._select_transport_lights(
        analysis,
        creative_layout=True,
    )
    physical_slots = builder_module._select_transport_lights(
        analysis,
        creative_layout=False,
    )

    assert len(creative_slots) == 4
    assert creative_slots[0] is physical[0]
    assert creative_slots[1].x == pytest.approx(weak_prop.x)
    assert creative_slots[1].y == pytest.approx(weak_prop.y)
    assert creative_slots[1].intensity == weak_prop.intensity
    assert creative_slots[1].creative_only
    assert physical_slots == physical


def test_transport_layout_metadata_is_derived_from_encoded_planes() -> None:
    transport = np.zeros((26, 2, 3, 4), dtype=np.uint8)
    transport[..., 3] = 255
    assert builder_module._transport_light_layout(transport) == "physical-components-v1"

    transport[8, ..., 2] = 255
    strip = np.concatenate([transport[plane] for plane in range(26)], axis=1)

    assert builder_module._transport_light_layout(transport) == "physical-rgb-families-v1"
    assert builder_module._transport_light_layout(strip) == "physical-rgb-families-v1"

    transport[2, ..., 2] = 255
    transport[2, ..., 1] = 127
    strip = np.concatenate(transport, axis=1)
    assert builder_module._transport_light_layout(transport) == "continuous-light-slots-v2"
    assert builder_module._transport_light_layout(strip) == "continuous-light-slots-v2"


def test_near_tied_hue_sectors_contribute_without_winner_switches():
    key = DetectedLight(0.5, 0.1, (0.73, 0.73, 0.73), 1.0, 0.2, 0.8)
    left = DetectedLight(0.1, 0.3, (0.98, 0.53, 0.51), 1.0, 0.2, 0.96, 1.0, True)
    right = replace(left, x=0.9, intensity=0.999)
    a = SimpleNamespace(lights=(key,), creative_lights=(left, right))
    b = SimpleNamespace(
        lights=(key,),
        creative_lights=(replace(left, intensity=0.999), replace(right, intensity=1.0)),
    )
    first = builder_module._select_transport_lights(a, creative_layout=True)
    second = builder_module._select_transport_lights(b, creative_layout=True)
    assert 0.49 < first[1].x < 0.51
    assert abs(first[1].x - second[1].x) < 0.002
    reverse = builder_module._select_transport_lights(
        SimpleNamespace(lights=(key,), creative_lights=tuple(reversed(a.creative_lights))),
        creative_layout=True,
    )
    assert reverse[1].x == pytest.approx(first[1].x, abs=1e-6)


def test_transport_blends_light_hypotheses_across_confidence_boundaries():
    from scenelight.engine import analyze_scene

    scene = analyze_scene(Image.new("RGB", (64, 36), (90, 90, 90)))
    key = DetectedLight(0.15, 0.15, (0.7353569,) * 3, 1.0, 0.2, 0.8)
    fill = replace(key, x=0.85, intensity=0.6)
    red = DetectedLight(0.75, 0.6, (1.0, 0.53, 0.51), 1.0, 0.15, 0.8, 1.0, True)

    def encode(confidence):
        analysis = replace(
            scene, lights=(key, fill), creative_lights=(replace(red, confidence=confidence),)
        )
        return builder_module._encode_transport_analyses(
            ((row, column, analysis) for row in range(2) for column in range(2)), (2, 2)
        )

    mixes = []
    for confidence in np.linspace(0.72, 0.90, 25):
        left, right = encode(confidence - 0.00001), encode(confidence + 0.00001)
        assert np.abs(left.astype(int) - right.astype(int)).max() <= 1
        assert np.all(left[2, ..., 2] == 191)
        mixes.append(int(left[2, 0, 0, 1]))
    assert mixes[0] == 0 and mixes[-1] == 255
    assert len(set(mixes)) >= 6
    assert all(a <= b for a, b in zip(mixes, mixes[1:]))


def test_form_worker_limit_uses_live_memory_without_changing_quality() -> None:
    assert (
        builder_module._memory_safe_form_workers(
            16,
            806,
            available_memory_bytes=2 * builder_module.GIB,
        )
        == 6
    )
    assert (
        builder_module._memory_safe_form_workers(
            16,
            806,
            available_memory_bytes=4 * builder_module.GIB,
        )
        == 12
    )
    assert (
        builder_module._memory_safe_form_workers(
            16,
            806,
            available_memory_bytes=64 * builder_module.GIB,
        )
        == 16
    )


def test_large_form_maps_match_preview_at_original_resolution(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    source = game / "images" / "hero.png"
    output = game / "scenelight_runtime" / "sprite_form"
    output.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    Image.new("RGBA", (1024, 768), (80, 120, 180, 255)).save(source)
    paths = {
        name: output / f"hero_{name}.png" for name in ("normal_noise", "height_ao_edge", "response")
    }

    _key, entry = builder_module._render_form_entry(
        game,
        "hero idle",
        SpriteSpec("hero idle", (source,)),
        paths,
        "source-fingerprint",
    )

    assert entry is not None
    assert entry["source_size"] == [1024, 768]
    assert entry["map_size"] == [1024, 768]
    with Image.open(source) as source_image:
        assert (
            entry["source_sha256"]
            == hashlib.sha256(source_image.convert("RGBA").tobytes()).hexdigest()
        )
    expected_sizes = {
        "normal_noise": (1024, 768),
        "height_ao_edge": (1024, 768),
        "response": (64, 64),
    }
    from scenelight.preview.artifacts import ArtifactCache

    preview = ArtifactCache(tmp_path / "preview-cache").form(source)
    for name, expected_size in expected_sizes.items():
        with Image.open(paths[name]) as generated:
            assert generated.size == expected_size
            with Image.open(preview.image(name)) as preview_map:
                np.testing.assert_array_equal(np.asarray(generated), np.asarray(preview_map))
    for name, value in preview.metadata.items():
        assert entry[name] == value


def test_full_resolution_forms_reduce_worker_count_for_large_sources() -> None:
    available = 4 * builder_module.GIB
    small = builder_module._memory_safe_form_workers(16, 100, available_memory_bytes=available)
    large = builder_module._memory_safe_form_workers(
        16, 100, available_memory_bytes=available, largest_sprite_pixels=2048 * 2048
    )
    assert small == 12
    assert large == 3


def test_form_memory_budget_uses_composite_canvas_and_caches_image_headers(tmp_path, monkeypatch):
    source = tmp_path / "sprite.png"
    Image.new("RGBA", (800, 1200)).save(source)
    sizes = {}
    assert builder_module._form_pixel_count(SpriteSpec("single", (source,)), sizes) == 800 * 1200
    monkeypatch.setattr(Image, "open", lambda *args: pytest.fail("Header should be cached"))
    assert builder_module._form_pixel_count(SpriteSpec("alias", (source,)), sizes) == 800 * 1200
    composed = SpriteSpec("layered", (source,), positions=((0, 0),), canvas_size=(2000, 3000))
    assert builder_module._form_pixel_count(composed, sizes) == 2000 * 3000


def test_previous_512px_maps_are_rebuilt_then_full_resolution_maps_are_reused(
    tmp_path, monkeypatch
):
    project = make_project(tmp_path / "project")
    source = project / "game/images/nova.png"
    Image.new("RGBA", (600, 900), (80, 120, 180, 255)).save(source)
    discovery = discover_project(project)
    output = project / "game/scenelight_runtime"
    before = builder_module._build_form_maps(discovery, output, 1)
    legacy = json.loads(json.dumps(before))
    legacy["version"] = 8
    entry = legacy["sprites"]["nova idle"]
    entry["version"] = 8
    entry["map_size"] = [341, 512]
    for name in ("normal_noise", "height_ao_edge"):
        Image.new("RGB", (341, 512)).save(project / "game" / entry[name])
    (output / "sprite_form_manifest.json").write_text(json.dumps(legacy))

    rebuilt = builder_module._build_form_maps(discovery, output, 1)
    assert rebuilt["version"] == FORM_MAP_VERSION == 9
    assert rebuilt["sprites"]["nova idle"]["map_size"] == [600, 900]
    for name in ("normal_noise", "height_ao_edge"):
        with Image.open(project / "game" / entry[name]) as image:
            assert image.size == (600, 900)
    monkeypatch.setattr(
        builder_module,
        "_render_form_entry",
        lambda *args: pytest.fail("Current maps should be reused"),
    )
    assert builder_module._build_form_maps(discovery, output, 1)["sprites"] == rebuilt["sprites"]


def test_broken_form_process_pool_retries_exact_jobs_with_fewer_workers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    additions: list[str] = []
    for index, color in enumerate(((20, 40, 60), (80, 100, 120), (140, 160, 180))):
        path = project / "game" / "images" / f"extra_{index}.png"
        Image.new("RGBA", (12, 16), (*color, 255)).save(path)
        additions.append(f'image nova extra{index} = "images/extra_{index}.png"')
    script.write_text(
        script.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(additions)
        + "\nlabel extra_forms:\n"
        + "\n".join(f"    show nova extra{index}" for index in range(3))
        + "\n    return\n",
        encoding="utf-8",
    )
    discovery = discover_project(project)

    class _FakeFuture:
        def __init__(self, attempt, function, args):
            self.attempt = attempt
            self.function = function
            self.args = args

        def result(self):
            if self.attempt == 0:
                raise BrokenProcessPool("simulated low-memory worker termination")
            return self.function(*self.args)

        def cancel(self):
            return True

    attempts: list[int] = []
    worker_counts: list[int] = []

    class _FakeExecutor:
        def __init__(self, max_workers):
            self.attempt = len(attempts)
            attempts.append(self.attempt)
            worker_counts.append(max_workers)

        def submit(self, function, *args):
            return _FakeFuture(self.attempt, function, args)

        def shutdown(self, *, wait, cancel_futures):
            assert wait is True
            assert cancel_futures is True

    monkeypatch.setattr(builder_module, "ProcessPoolExecutor", _FakeExecutor)
    monkeypatch.setattr(builder_module, "as_completed", lambda futures: list(futures))
    monkeypatch.setattr(
        builder_module,
        "_memory_safe_form_workers",
        lambda requested, _jobs, **_kwargs: requested,
    )

    payload = builder_module._build_form_maps(
        discovery,
        project / "game" / "scenelight_runtime",
        worker_count=4,
    )

    assert worker_counts == [4, 2]
    assert len(payload["sprites"]) == 4
    baseline = builder_module._build_form_maps(
        discovery,
        project / "game" / "scenelight_runtime_baseline",
        worker_count=1,
    )
    for key, entry in payload["sprites"].items():
        for map_name in ("normal_noise", "height_ao_edge", "response"):
            generated = project / "game" / entry[map_name]
            expected = project / "game" / baseline["sprites"][key][map_name]
            assert generated.read_bytes() == expected.read_bytes()


def test_builds_complete_generic_runtime_data(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    discovery = discover_project(project)
    result = build_project(
        discovery,
        grid_size=(2, 2),
        workers=1,
        analyzer_backend="cpu",
    )
    assert result.scene_count == 1
    assert result.sprite_count == 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    forms = json.loads(
        (result.output_root / "sprite_form_manifest.json").read_text(encoding="utf-8")
    )
    effects = json.loads((result.output_root / "effect_packs.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 8
    assert manifest["strength"] == 1.0
    assert manifest["calibration"]["auto_strength"] == 0.88
    assert manifest["scenes"]["lab"]["calibration"] == manifest["calibration"]
    assert manifest["transport_atlas"]["grid_size"] == [2, 2]
    assert manifest["character_tags"] == ["nova"]
    assert list(manifest["scenes"]) == ["lab"]
    assert list(forms["sprites"]) == ["nova idle"]
    assert effects == {"version": 1, "packs": [], "effects": {}}
    assert not any(
        path.suffix.lower() in {".jpg", ".jpeg"} for path in result.output_root.rglob("*")
    )


def test_temporal_backgrounds_publish_a_runtime_timeline(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    discovery = discover_project(project)
    alternate = project / "game" / "images" / "lab-alternate.png"
    Image.new("RGB", (48, 27), (210, 60, 30)).save(alternate)
    discovery.scenes["lab::t00125"] = alternate
    discovery.scene_sequences["lab"] = [
        (0, "lab"),
        (125, "lab::t00125"),
        (250, "lab"),
    ]

    result = build_project(
        discovery,
        grid_size=(2, 2),
        workers=1,
        analyzer_backend="cpu",
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["scene_sequences"]["lab"] == {
        "mode": "visible-source",
        "sample_window_ms": 375,
        "sources": {},
        "frames": [[0, "lab"], [125, "lab::t00125"], [250, "lab"]],
    }


def test_runtime_capture_skips_persist_in_form_manifest(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    discovery = discover_project(project)
    discovery.skipped_sprites.append(
        {
            "sprite": "broken unsupported",
            "stage": "runtime-capture",
            "error": "RuntimeError: intentional failure",
        }
    )

    payload = builder_module._build_form_maps(
        discovery,
        project / "game" / "scenelight_runtime",
        worker_count=1,
    )

    assert payload["skipped"] == discovery.skipped_sprites


def test_accelerated_transport_retains_exact_cpu_fallback(monkeypatch) -> None:
    expected = np.zeros((26, 9, 16, 4), dtype=np.uint8)
    calls: list[tuple[str, str, tuple[int, int]]] = []

    def fake_cpu(scene_name: str, path_text: str, grid_size=(16, 9), **_kwargs):
        calls.append((scene_name, path_text, grid_size))
        return scene_name, expected

    monkeypatch.setattr(cuda_backend, "cuda_available", lambda: False)
    monkeypatch.setattr(builder_module, "_transport_maps", fake_cpu)

    name, transport = builder_module._transport_maps_accelerated(
        "generic_scene",
        "background.png",
    )

    assert name == "generic_scene"
    assert transport is expected
    assert calls == [("generic_scene", "background.png", (16, 9))]


def test_identical_sprite_forms_share_lossless_content_addressed_maps(
    tmp_path: Path, monkeypatch
) -> None:
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + """
image nova duplicate = "images/nova.png"

label duplicate_test:
    show nova duplicate
    return
""",
        encoding="utf-8",
    )

    original_fingerprint = builder_module._sprite_spec_fingerprint
    fingerprint_calls = 0

    def count_fingerprint(spec, layer_digests=None, resolved_layers=None):
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        return original_fingerprint(spec, layer_digests, resolved_layers)

    monkeypatch.setattr(builder_module, "_sprite_spec_fingerprint", count_fingerprint)
    result = build_project(
        discover_project(project),
        grid_size=(2, 2),
        workers=2,
        analyzer_backend="cpu",
    )
    forms = json.loads(
        (result.output_root / "sprite_form_manifest.json").read_text(encoding="utf-8")
    )["sprites"]

    assert forms["nova idle"] == forms["nova duplicate"]
    assert forms["nova idle"]["source_sha256"] == forms["nova duplicate"]["source_sha256"]
    assert fingerprint_calls == 1


def test_fully_transparent_registered_forms_are_skipped(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    transparent = project / "game" / "images" / "transparent.png"
    Image.new("RGBA", (12, 16), (255, 0, 255, 0)).save(transparent)
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + """
image nova placeholder = "images/transparent.png"

label transparent_form_test:
    show nova placeholder
    return
""",
        encoding="utf-8",
    )

    result = build_project(
        discover_project(project),
        grid_size=(2, 2),
        workers=2,
        analyzer_backend="cpu",
    )
    forms = json.loads(
        (result.output_root / "sprite_form_manifest.json").read_text(encoding="utf-8")
    )["sprites"]

    assert result.sprite_count == 1
    assert list(forms) == ["nova idle"]


def test_one_broken_surface_map_is_reported_without_aborting_other_forms(
    tmp_path: Path, monkeypatch
) -> None:
    project = make_project(tmp_path / "project")
    broken = project / "game" / "images" / "broken.png"
    Image.new("RGBA", (12, 16), (231, 17, 29, 255)).save(broken)
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + '\nimage nova broken = "images/broken.png"\n'
        + "label broken_form_test:\n    show nova broken\n    return\n",
        encoding="utf-8",
    )
    original = builder_module.build_sprite_form_maps

    def fail_selected_sprite(image, **kwargs):
        if image.getpixel((0, 0))[:3] == (231, 17, 29):
            raise ValueError("simulated malformed sprite")
        return original(image, **kwargs)

    monkeypatch.setattr(builder_module, "build_sprite_form_maps", fail_selected_sprite)

    result = build_project(
        discover_project(project),
        grid_size=(2, 2),
        workers=1,
        analyzer_backend="cpu",
    )
    manifest = json.loads(
        (result.output_root / "sprite_form_manifest.json").read_text(encoding="utf-8")
    )

    assert list(manifest["sprites"]) == ["nova idle"]
    assert manifest["skipped"] == [
        {
            "sprite": "nova broken",
            "stage": "surface-map",
            "error": "ValueError: simulated malformed sprite",
        }
    ]


def test_temporal_atlases_grow_horizontally_and_reject_unsafe_allocations():
    from scenelight.builder import _atlas_layout

    assert _atlas_layout(140, (16, 9)) == (4, 36)
    assert _atlas_layout(300, (16, 9)) == (7, 43)
    with pytest.raises(ValueError, match="No installed runtime was replaced"):
        _atlas_layout(405, (16, 9))
