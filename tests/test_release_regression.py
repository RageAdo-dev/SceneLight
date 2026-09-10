"""Repeatable release checks for author edits, ownership and animated media."""

from __future__ import annotations

import json
import os
import random

import numpy as np
import pytest
from PIL import Image, ImageSequence
from test_developer import _projects

from scenelight.capture import _capture_content_signature
from scenelight.developer import (
    EMBED_ROOT,
    developer_status,
    embed_from_managed,
    preflight_refresh_destination,
    refresh_embedded_from_managed,
    remove_embedded,
)
from scenelight.preview.media import MediaClip
from scenelight.project import ProjectDiscovery
from scenelight.sidecar import sync_project, visual_sources_changed

VISUAL_FILES = (
    "scene.rpy",
    "scene.rpym",
    "archive.rpa",
    "pose.png",
    "pose.webp",
    "background.jpg",
    "animation.gif",
    "animation.apng",
    "background.avif",
    "vector.svg",
    "movie.mp4",
    "movie.webm",
    "scenelight_effects/rain.json",
)


@pytest.mark.parametrize("name", VISUAL_FILES)
@pytest.mark.parametrize("operation", ("add", "edit", "delete", "rename"))
def test_author_edit_matrix_preserves_install_and_user_files(
    tmp_path, monkeypatch, name, operation
):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "private" / "projects"))
    project, managed = _projects(tmp_path)
    asset = project / "game" / name
    asset.parent.mkdir(parents=True, exist_ok=True)
    if operation != "add":
        asset.write_bytes(b"original authored bytes")
    save = project / "game" / "saves" / "progress.save"
    save.parent.mkdir()
    save.write_bytes(b"player save canary")
    embed_from_managed(project, managed)
    assert not developer_status(project).refresh_required

    if operation == "add":
        asset.write_bytes(b"new authored bytes")
    elif operation == "edit":
        asset.write_bytes(b"edited authored bytes, not a runtime edit")
    elif operation == "delete":
        asset.unlink()
    else:
        asset.rename(asset.with_name("renamed-" + asset.name))
    status = developer_status(project)
    assert status.clean
    assert status.refresh_required, (name, operation)
    assert "game/" + name in status.changed_sources
    authored = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
        and EMBED_ROOT not in p.relative_to(project).parents
        and p.name != ".scenelight_developer_install.json"
    }

    refresh_embedded_from_managed(project, managed)
    assert developer_status(project).clean
    assert not developer_status(project).refresh_required
    remove_embedded(project)
    assert all((project / name).read_bytes() == data for name, data in authored.items())
    assert save.read_bytes() == b"player save canary"


@pytest.mark.parametrize("name", VISUAL_FILES)
def test_managed_copy_visual_edits_trigger_rebuild(tmp_path, monkeypatch, name):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "private" / "projects"))
    project, _ = _projects(tmp_path)
    first = sync_project(project)
    assert not sync_project(project).changed
    source = project / "game" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"new authored source")
    result = sync_project(project)
    assert result.managed == first.managed
    assert visual_sources_changed(result), name
    assert (result.managed / "game" / name).read_bytes() == source.read_bytes()
    assert not sync_project(project).changed


@pytest.mark.parametrize("mode", ("managed", "developer"))
def test_same_size_timestamp_preserving_edit_is_not_missed(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "private" / "projects"))
    project, managed = _projects(tmp_path)
    asset = project / "game" / "pose.png"
    asset.write_bytes(b"first artwork")
    if mode == "managed":
        sync_project(project)
    else:
        embed_from_managed(project, managed)
    stamp = asset.stat()
    asset.write_bytes(b"other artwork")
    os.utime(asset, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert asset.stat().st_size == stamp.st_size
    if mode == "managed":
        result = sync_project(project)
        assert "game/pose.png" in result.copied
        assert (result.managed / "game" / "pose.png").read_bytes() == b"other artwork"
    else:
        assert "game/pose.png" in developer_status(project).changed_sources


@pytest.mark.parametrize("seed", (1729, 2718, 31415, 65537))
def test_seeded_source_edit_sequences_preserve_save_and_runtime(tmp_path, monkeypatch, seed):
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "private" / "projects"))
    project, _ = _projects(tmp_path)
    result = sync_project(project)
    runtime = result.managed / "game" / "scenelight_runtime" / "owned.bin"
    save = result.managed / "game" / "saves" / "canary.save"
    for path in (runtime, save):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve me")
    rng = random.Random(seed)
    for step in range(40):
        path = project / "game" / ("pose-%d.png" % rng.randrange(8))
        if path.exists() and rng.random() < 0.3:
            path.unlink()
        else:
            path.write_bytes(("revision-%d-%d" % (seed, step)).encode())
        result = sync_project(project)
        for index in range(8):
            source = project / "game" / ("pose-%d.png" % index)
            copied = result.managed / "game" / source.name
            assert copied.exists() == source.exists()
            if source.exists():
                assert copied.read_bytes() == source.read_bytes()
        assert save.read_bytes() == runtime.read_bytes() == b"preserve me"
        assert not sync_project(project).changed


def test_editing_owned_runtime_refuses_update_and_removal(tmp_path):
    project, managed = _projects(tmp_path)
    embed_from_managed(project, managed)
    target = project / EMBED_ROOT / "bootstrap.rpy"
    target.write_text("# a developer's intentional local edit\n", encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(RuntimeError):
        preflight_refresh_destination(project)
    with pytest.raises(RuntimeError):
        remove_embedded(project)
    assert target.read_bytes() == before


@pytest.mark.parametrize("disposal", (1, 2, 3))
@pytest.mark.parametrize("optimize", (False, True))
def test_actual_gif_frames_alpha_and_variable_timing(tmp_path, disposal, optimize):
    frames = []
    for index in range(4):
        rgba = np.zeros((20, 32, 4), dtype=np.uint8)
        rgba[2:18, 2 + index * 4 : 10 + index * 4] = (50 + index * 50, 100, 200, 255)
        frames.append(Image.fromarray(rgba))
    source = tmp_path / "actual animation.gif"
    frames[0].save(
        source,
        save_all=True,
        append_images=frames[1:],
        duration=(30, 70, 110, 190),
        loop=0,
        disposal=disposal,
        optimize=optimize,
    )
    with Image.open(source) as image:
        expected = [
            np.asarray(frame.convert("RGBA")).copy() for frame in ImageSequence.Iterator(image)
        ]
    for _ in range(2):
        clip = MediaClip(source, tmp_path / "cache")
        try:
            assert clip.frame_count == 4
            assert clip.durations_ms == (30, 70, 110, 190)
            for index, pixels in enumerate(expected):
                assert np.array_equal(clip.frame_by_index(index).rgba, pixels)
            assert [clip.index_at(t) for t in (0, 29, 30, 99, 100, 209, 210, 399, 400)] == [
                0,
                0,
                1,
                1,
                2,
                2,
                3,
                3,
                0,
            ]
        finally:
            clip.close()


def test_apng_poster_is_not_an_animation_frame(tmp_path):
    poster = Image.new("RGBA", (32, 20), "red")
    frames = [Image.new("RGBA", poster.size, color) for color in ("blue", "green")]
    source = tmp_path / "poster.apng"
    poster.save(
        source,
        format="PNG",
        save_all=True,
        append_images=frames,
        default_image=True,
        duration=(40, 80),
        loop=0,
    )
    clip = MediaClip(source, tmp_path / "cache")
    try:
        assert clip.frame_count == 2
        assert clip.durations_ms == (40, 80)
        assert np.array_equal(clip.frame_by_index(0).rgba, np.asarray(frames[0]))
        assert np.array_equal(clip.frame_by_index(1).rgba, np.asarray(frames[1]))
    finally:
        clip.close()


@pytest.mark.parametrize(
    "broken",
    (
        {"durations_ms": []},
        {"durations_ms": [10]},
        {"durations_ms": [40, "invalid"]},
        {"size": [0, 0]},
        {"frames": ["../outside.png", "../outside.png"]},
    ),
)
def test_invalid_animation_cache_metadata_is_rebuilt(tmp_path, broken):
    source = tmp_path / "animation.gif"
    first = Image.new("RGBA", (20, 20), "red")
    first.save(
        source,
        save_all=True,
        append_images=[Image.new("RGBA", first.size, "blue")],
        duration=(40, 80),
        loop=0,
    )
    clip = MediaClip(source, tmp_path / "cache")
    marker = clip.frame_paths[0].parent / "media.json"
    clip.close()
    payload = json.loads(marker.read_text())
    payload.update(broken)
    marker.write_text(json.dumps(payload))
    reopened = MediaClip(source, tmp_path / "cache")
    try:
        assert reopened.frame_count == 2
        assert reopened.durations_ms == (40, 80)
        assert reopened.size == (20, 20)
        assert reopened.index_at(45) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("name", VISUAL_FILES[:-1])
def test_capture_cache_tracks_bytes_not_only_file_metadata(tmp_path, name):
    game = tmp_path / "game"
    game.mkdir()
    asset = game / name
    asset.write_bytes(b"first artwork")
    discovery = ProjectDiscovery(
        project_root=tmp_path, game_root=game, scenes={}, sprites={}, character_tags=[]
    )
    before = _capture_content_signature(discovery)
    timestamp = asset.stat().st_mtime_ns
    asset.write_bytes(b"other artwork")
    os.utime(asset, ns=(timestamp, timestamp))
    assert _capture_content_signature(discovery) != before
