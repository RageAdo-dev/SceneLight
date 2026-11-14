from types import SimpleNamespace

import pytest

from scenelight.project_watch import ProjectWatch, source_metadata
from scenelight.setup_gui import SceneLightSetup


def test_existing_player_copy_detects_changes_after_reopening(tmp_path, monkeypatch):
    import json

    from scenelight import __version__, setup_gui

    project = tmp_path / "source"
    (project / "game").mkdir(parents=True)
    (project / "game/script.rpy").write_text("label start:\n    return\n")
    monkeypatch.setenv("SCENELIGHT_MANAGED_ROOT", str(tmp_path / "copies"))
    managed = setup_gui.managed_project_root(project)
    managed.mkdir(parents=True)
    (managed / "Game.exe").write_bytes(b"fixture launcher")
    (managed / ".scenelight_install.json").write_text(
        json.dumps({"scenelight_version": __version__, "source_state": source_metadata(project)})
    )
    assert not setup_gui.inspect_project_installation(project).refresh_required
    (project / "game/new.png").write_bytes(b"new art")
    inspection = setup_gui.inspect_project_installation(project)
    assert inspection.managed_install_ready
    assert inspection.refresh_required
    assert not inspection.release_replacement_available


def test_inspection_reports_a_source_read_failure(tmp_path, monkeypatch):
    from scenelight import setup_gui

    (tmp_path / "game").mkdir()
    (tmp_path / "game/script.rpy").write_text("label start:\n    return\n")

    def fail(root):
        raise PermissionError("file is being replaced")

    monkeypatch.setattr(setup_gui, "source_metadata", fail)
    assert "file is being replaced" in setup_gui.inspect_project_installation(tmp_path).error


def test_source_metadata_covers_edits_additions_removals_and_ignores_generated(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    source = game / "script.rpy"
    source.write_text("scene lake")
    baseline = source_metadata(tmp_path)
    for name in [
        "saves/1.save",
        "cache/compiled.json",
        "scenelight_runtime/code.rpy",
        "script.rpyc",
    ]:
        path = game / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("ignored")
    assert source_metadata(tmp_path) == baseline
    source.write_text("scene room\nshow hero")
    assert source_metadata(tmp_path) != baseline
    sprite = game / "new.png"
    sprite.write_bytes(b"new artwork")
    assert "game/new.png" in source_metadata(tmp_path)
    sprite.unlink()
    assert "game/new.png" not in source_metadata(tmp_path)
    (tmp_path / "scenelight.json").write_text("{}")
    assert "scenelight.json" in source_metadata(tmp_path)


def test_watch_debounces_and_tracks_subsequent_changes():
    watch = ProjectWatch({"a": (1, 1)})
    assert not watch.observe({"a": (2, 2)})
    assert not watch.observe({"b": (3, 3)})
    assert watch.observe({"b": (3, 3)})
    assert not watch.observe({"b": (3, 3)})
    assert not watch.observe({})
    assert watch.observe({})


@pytest.mark.parametrize(
    "running,checking,generation", [(True, False, 3), (False, True, 3), (False, False, 2)]
)
def test_watch_discards_busy_and_stale_results(running, checking, generation):
    app = SimpleNamespace(
        _watch_busy=True, _project_generation=3, _running=running, _project_checking=checking
    )
    SceneLightSetup._finish_project_sources(app, generation, {})
    assert not app._watch_busy


@pytest.mark.parametrize("developer", [False, True])
def test_stable_changes_invalidate_scan_in_both_modes(developer):
    events = []
    app = SimpleNamespace(
        developer_mode=developer,
        _project_generation=3,
        _running=False,
        _project_checking=False,
        _watch_busy=True,
        _source_watch=ProjectWatch({}),
        _scan_ok=True,
        _review_completed_for="project",
        _character_review_pending_for="project",
        _last_scan_payload={"characters": ["old"]},
        _close_character_review_window=lambda: events.append("closed"),
        preview_var=SimpleNamespace(set=lambda text: events.append(text)),
        _append_log=lambda text: events.append(text),
        _begin_project_inspection=lambda: events.append("inspect"),
    )
    SceneLightSetup._finish_project_sources(app, 3, {"new.png": (12, 34)})
    assert app._scan_ok
    SceneLightSetup._finish_project_sources(app, 3, {"new.png": (12, 34)})
    assert not app._scan_ok
    assert app._last_scan_payload == {}
    assert events[-1] == "inspect"


def test_live_watch_finds_preserved_times_and_ignores_runtime_writes(tmp_path):
    import os

    from scenelight.project_watch import LiveSources

    game = tmp_path / "game"
    game.mkdir()
    art = game / "hero.png"
    art.write_bytes(b"old")
    stat = art.stat()
    runtime = game / "scenelight_runtime"
    runtime.mkdir()
    monitor = LiveSources()
    initial = monitor.snapshot(tmp_path)
    assert not monitor.watch.observe(initial)
    assert monitor.watch.observe(initial)
    art.write_bytes(b"new")
    os.utime(art, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    (runtime / "form.png").write_bytes(b"generated")
    changed = monitor.snapshot(tmp_path)
    assert set(changed) == {"game/hero.png"}
    assert changed != initial
    assert not monitor.watch.observe(changed)
    assert monitor.watch.observe(monitor.snapshot(tmp_path))
    assert not monitor.watch.observe(monitor.snapshot(tmp_path))


def test_only_committed_updates_for_this_playtest_request_one_reload(tmp_path, monkeypatch):
    from scenelight.project_watch import notify_playtest
    from scenelight.runtime import live_edit

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    clock = [10.0]
    monkeypatch.setattr(live_edit.time, "monotonic", lambda: clock[0])
    project = tmp_path / "mod"
    notify_playtest(project)
    reloaded = []
    ready = [False]
    poll = live_edit.subscribe(str(project), lambda: reloaded.append(True), lambda: ready[0])
    poll()
    notify_playtest(tmp_path / "other")
    clock[0] += 2
    poll()
    assert not reloaded
    notify_playtest(project)
    clock[0] += 2
    poll()
    assert not reloaded
    ready[0] = True
    clock[0] += 2
    poll()
    clock[0] += 2
    poll()
    assert reloaded == [True]


@pytest.mark.parametrize(
    ("developer", "installed", "older", "expected_on"),
    [
        (True, True, False, True),
        (False, True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_live_updates_default_for_current_developer_installations(
    tmp_path, monkeypatch, developer, installed, older, expected_on
):
    from unittest.mock import Mock

    from scenelight.project_watch import LiveSources

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    root = tmp_path / "game-project"
    app = Mock()
    app._live_project = None
    app._live_sources = None
    app._project_generation = 2
    app.project_var.get.return_value = str(root)
    app.developer_mode = developer
    app._closing = app._running = False
    app._dependency_state.ready = True
    monkeypatch.setattr("scenelight.setup_gui.ArtworkPreview", Mock())
    app._artwork_preview = None
    app._watch_live_edits = lambda enabled: SceneLightSetup._watch_live_edits(app, enabled)
    app._sync_live_project = lambda project: SceneLightSetup._sync_live_project(app, project)
    from scenelight import __version__
    from scenelight.setup_gui import ProjectInspection, ProjectSelection

    status = SimpleNamespace(
        installed=installed,
        clean=True,
        refresh_required=True,
        installed_version="0.9.0" if older else __version__,
        installed_content_sha256=None,
    )
    inspection = ProjectInspection(ProjectSelection(root, True, "ready"), developer_status=status)
    SceneLightSetup._finish_project_inspection(app, 2, str(root), inspection)
    assert isinstance(app._live_sources, LiveSources) == expected_on
    assert app._start_operation.called == expected_on


def test_live_edit_choice_survives_setup_reopening_and_stays_with_the_project(
    tmp_path, monkeypatch
):
    from unittest.mock import Mock

    from scenelight.project_watch import live_updates_enabled

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    a, b = tmp_path / "first", tmp_path / "second"
    monkeypatch.setattr("scenelight.setup_gui.ArtworkPreview", Mock())

    def setup():
        instance = SimpleNamespace(
            _live_project=None, _artwork_preview=None, _events=Mock(), live_edit_var=Mock()
        )
        instance._watch_live_edits = lambda enabled: SceneLightSetup._watch_live_edits(
            instance, enabled
        )
        return instance

    app = setup()
    SceneLightSetup._sync_live_project(app, a)
    assert app._live_sources is not None
    watcher = app._live_sources
    SceneLightSetup._sync_live_project(app, a)
    assert app._live_sources is watcher
    SceneLightSetup._set_live_edit(app, False)
    assert not live_updates_enabled(a)
    SceneLightSetup._sync_live_project(app, b)
    assert app._live_sources is not None
    reopened = setup()
    SceneLightSetup._sync_live_project(reopened, a)
    assert reopened._live_sources is None
    SceneLightSetup._set_live_edit(reopened, True)
    assert live_updates_enabled(a)
    SceneLightSetup._sync_live_project(reopened, None)
    assert reopened._live_sources is None


@pytest.mark.parametrize("broken_managed_copy", [False, True])
def test_live_updates_wait_for_installation_issues_to_be_resolved(tmp_path, broken_managed_copy):
    from scenelight import __version__
    from scenelight.setup_gui import ProjectInspection, ProjectSelection

    status = SimpleNamespace(
        installed=True, clean=True, installed_version=__version__, installed_content_sha256=None
    )
    inspection = ProjectInspection(
        ProjectSelection(tmp_path, True, "ready"),
        developer_status=status,
        error=None if broken_managed_copy else "Could not inspect the project",
        managed_install_present=broken_managed_copy,
    )
    assert not inspection.live_update_ready


def test_artwork_preview_handles_incomplete_saves_and_atomic_replacements(tmp_path, monkeypatch):
    import os
    import time
    from io import BytesIO
    from unittest.mock import Mock

    from PIL import Image

    from scenelight.artwork_preview import ArtworkPreview
    from scenelight.runtime import live_edit

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    game = tmp_path / "game"
    game.mkdir()
    runtime = game / "scenelight_runtime"
    runtime.mkdir()
    sprite = game / "hero.png"
    encoded = BytesIO()
    Image.new("RGB", (32, 32), "red").save(encoded, format="PNG")
    data = encoded.getvalue()
    watcher = ArtworkPreview(tmp_path, Mock())
    watcher.start()
    try:
        assert watcher.ready.wait(5)
        sprite.write_bytes(data[:10])
        (runtime / "generated.png").write_bytes(data)
        time.sleep(0.35)
        assert not watcher.signal.exists()
        editor = game / "drawing.tmp"
        editor.write_bytes(data)
        os.replace(editor, sprite)
        (game / "room.png").write_bytes(data)

        def received():
            end = time.monotonic() + 7
            while time.monotonic() < end:
                revision, names = live_edit._artwork_changes(str(watcher.signal), None)
                if set(names) == {"hero.png", "room.png"}:
                    return revision
                time.sleep(0.04)
            raise AssertionError("Saved artwork did not reach the playtest mailbox")

        revision = received()
        assert live_edit._artwork_changes(str(watcher.signal), revision) == (revision, [])
        watcher.report.assert_not_called()
    finally:
        watcher.stop()
        watcher.join(4)
    assert not watcher.is_alive()


def test_artwork_preview_keeps_story_running_until_lighting_commits(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from scenelight.artwork_preview import ArtworkPreview
    from scenelight.project_watch import notify_playtest
    from scenelight.runtime import live_edit

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    clock = [10.0]
    monkeypatch.setattr(live_edit.time, "monotonic", lambda: clock[0])
    watcher = ArtworkPreview(tmp_path, Mock())
    watcher._publish(["old.png"])
    preview, reload_game = Mock(), Mock()
    available = [False]
    poll = live_edit.subscribe(str(tmp_path), reload_game, lambda: available[0], preview)
    watcher._publish(["hero.png"])
    watcher._publish(["room.png", "hero.png"])
    poll()
    preview.assert_not_called()
    available[0] = True
    clock[0] += 1
    poll()
    clock[0] += 1
    poll()
    preview.assert_called_once_with(["hero.png", "room.png"])
    reload_game.assert_not_called()
    notify_playtest(tmp_path)
    clock[0] += 1
    poll()
    reload_game.assert_called_once_with()


def test_visible_form_uses_latest_save_and_matches_installed_textures(tmp_path, monkeypatch):
    import hashlib
    import time
    from io import BytesIO
    from pathlib import Path
    from unittest.mock import Mock

    from PIL import Image, ImageDraw

    from scenelight.artwork_preview import ArtworkPreview
    from scenelight.form_maps import build_sprite_form_maps
    from scenelight.project import SpriteSpec
    from scenelight.runtime.live_edit import VisibleForms

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    game = tmp_path / "game"
    game.mkdir()
    (tmp_path / "scenelight.json").write_text(
        '{"character_selection":"manual","character_tags":["hero"]}'
    )
    (game / "script.rpy").write_text(
        'image hero happy = "hero.png"\nlabel start:\n    show hero happy\n    return\n'
    )
    hero = game / "hero.png"
    Image.new("RGBA", (48, 64), "blue").save(hero)
    watcher = ArtworkPreview(tmp_path, Mock())
    watcher.start()

    def wait_for(check):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            if check():
                return
            time.sleep(0.025)
        raise AssertionError("Visible sprite lighting did not finish")

    try:
        assert watcher.ready.wait(5)
        forms = VisibleForms(str(tmp_path))
        forms.connect((watcher.session + "0" * 16).encode())

        def request():
            forms.request(
                "hero happy", ["hero.png"], lambda name: Path(name).write_bytes(hero.read_bytes())
            )
            assert forms.status.startswith("Updating lighting")

        request()
        first = forms.pending["hero happy"]
        body = Image.new("RGBA", (48, 64), (0, 0, 0, 0))
        ImageDraw.Draw(body).ellipse((3, 9, 24, 55), fill=(220, 90, 50, 255))
        body.save(hero)
        request()
        assert forms.pending["hero happy"] != first
        wait_for(lambda: forms.poll(lambda data, name: data))
        assert forms.status.startswith("Lighting ready")
        metadata, *textures = forms.bindings["hero happy"]
        exact = build_sprite_form_maps(SpriteSpec("hero happy", (hero,)).compose())
        assert metadata == exact.metadata
        for data, expected in zip(
            textures, (exact.normal_noise, exact.height_ao_edge, exact.response), strict=True
        ):
            assert Image.open(BytesIO(data)).tobytes() == expected.tobytes()
        assert metadata["source_sha256"] == hashlib.sha256(body.tobytes()).hexdigest()

        with (game / "script.rpy").open("a") as script:
            script.write("\ninit python:\n    variable = 4\n")
        watcher.changed(game / "script.rpy")
        request()
        wait_for(lambda: forms.poll(lambda data, name: data))
        assert "pending" in forms.status and forms.bindings["hero happy"] is None
        watcher.project_updated()
        request()
        wait_for(lambda: forms.poll(lambda data, name: data))
        assert forms.status.startswith("Lighting ready")
    finally:
        watcher.stop()
        watcher.join(5)
    assert not watcher.is_alive()


def test_early_script_reload_only_accepts_supported_additions():
    from scenelight.script_preview import sprite_script_changes

    before = b'label start:\n    "Hello"\n    return\n'
    after = before.replace(
        b"    return", b'    show guest smile at right\n    "Welcome"\n    return'
    )
    after += b'define g = Character("Guest", image="guest")\nimage guest smile = "art/guest.png"\n'
    assert sprite_script_changes(before, after) == (
        {"guest smile": "art/guest.png"},
        {"guest"},
        {"guest"},
    )
    assert sprite_script_changes(before, after.replace(b"art/guest.png", b"../guest.png")) is None
    assert (
        sprite_script_changes(
            before, after.replace(b"    return", b"    $ counter += 1\n    return")
        )
        is None
    )
    assert sprite_script_changes(before, after.replace(b'"Hello"', b"jump finish")) is None


def test_layered_expression_replacement_uses_the_show_at_its_script_location():
    from scenelight.script_preview import sprite_script_changes

    before = b'label visit:\n    show ryan happy at left\n    "Hello"\n    show ryan sad at left\n'
    after = before.replace(b"ryan sad", b"ryan happy")
    assert sprite_script_changes(before, after) == ({}, set(), {"ryan"})
    for replacement in (
        b"show ida happy at left",
        b"show ryan happy at right",
        b"show expression make_sprite()",
        b"hide ryan",
        b"show ryan happy onlayer overlay",
    ):
        assert (
            sprite_script_changes(before, after.replace(b"show ryan happy at left", replacement))
            is None
        )
    assert sprite_script_changes(before, after.replace(b'"Hello"', b"$ play_sound()")) is None
    assert sprite_script_changes(before, after.replace(b"    show", b"        show")) is None


def test_script_preview_binds_verified_art_and_ignores_superseded_saves(tmp_path, monkeypatch):
    import hashlib
    import json
    import time

    from PIL import Image

    from scenelight.artwork_preview import ArtworkPreview
    from scenelight.runtime.live_edit import VisibleForms, script_matches

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    game = tmp_path / "game"
    runtime = game / "scenelight_runtime"
    runtime.mkdir(parents=True)
    config = runtime / "manifest.json"
    config.write_text(json.dumps({"character_tags": [], "auto_include_new_characters": True}))
    script = game / "story.rpy"
    original = b'label start:\n    "Hello"\n    return\n'
    script.write_bytes(original)
    watcher = ArtworkPreview(tmp_path, lambda text: None)
    watcher.start()
    try:
        assert watcher.ready.wait(10)

        def packet(state, previous=None):
            stop = time.monotonic() + 8
            while time.monotonic() < stop:
                try:
                    rev, body = watcher.signal.with_suffix(".script").read_bytes().split(b"\n", 1)
                    data = json.loads(body)
                    if rev != previous and data["state"] == state:
                        return rev, data
                except (ValueError, OSError):
                    pass
                time.sleep(0.03)
            raise AssertionError(state)

        art = game / "guest.png"
        changed = (
            original
            + b'define g = Character("Guest", image="guest")\nimage guest smile = "guest.png"\n'
        )
        script.write_bytes(changed)
        packet("waiting")
        Image.new("RGBA", (48, 96), "#ae1960").save(art)
        rev, data = packet("preview")
        digest = hashlib.sha256(art.read_bytes()).hexdigest()
        assert data["entries"] == {"guest smile": ["guest.png", digest]}
        assert script_matches(str(game), data["scripts"])
        forms = VisibleForms(str(tmp_path))
        assert not forms.install_script_maps(
            (rev.decode(), data["entries"]), lambda *args: False, lambda *args: None
        )
        assert forms.install_script_maps(
            (rev.decode(), data["entries"]), lambda *args: True, lambda raw, name: raw
        ) == {"guest"}
        assert forms.bindings["guest smile"][0]["source_size"] == [48, 96]
        script.write_bytes(original)
        _, reverted = packet("preview", rev)
        assert not reverted["entries"] and script_matches(str(game), reverted["scripts"])
        assert not script_matches(str(game), data["scripts"])
        config.write_text(
            json.dumps(
                {
                    "character_tags": [],
                    "auto_include_new_characters": True,
                    "excluded_character_tags": ["guest"],
                }
            )
        )
        script.write_bytes(changed)
        packet("pending")
    finally:
        watcher.stop()
        watcher.join(10)
    assert not watcher.is_alive()


def test_layered_preview_tracks_the_changed_pose_and_its_new_artwork():
    from scenelight.script_preview import layered_changes, sprite_script_changes

    original = b'layeredimage hero turned:\n    group outfit:\n        attribute plain default "art/plain.png"\nlabel room:\n    "Hello"\n'
    updated = original.replace(
        b"label room:", b'        attribute coat:\n            "art/coat.png"\nlabel room:'
    ).replace(b'    "Hello"', b'    show hero turned coat at left\n    "Hello"')
    old, new, tags, files = layered_changes(original, updated)
    assert tags == {"hero"} and files == {"art/coat.png"}
    assert sprite_script_changes(old, new) == ({}, set(), {"hero"})
    assert layered_changes(original, updated.replace(b"art/coat.png", b"../coat.png")) is None
    assert layered_changes(original, updated.replace(b'"art/coat.png"', b"$ recalculate()")) is None
    assert (
        layered_changes(
            original, updated.replace(b"layeredimage hero turned:", b"layeredimage other:")
        )
        is None
    )


def test_verified_sprite_commit_handles_reordered_forms_and_checks_script_and_scene(tmp_path):
    import hashlib
    import json

    from scenelight.runtime.live_edit import _NewerSave, loaded_bytecode, sprite_commit

    game = tmp_path / "game"
    runtime = game / "scenelight_runtime"
    runtime.mkdir(parents=True)

    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    artwork = game / "coat.png"
    artwork.write_bytes(b"new art")
    story = game / "story.rpy"
    story.write_text("show hero coat")
    scripts = {"story.rpy": sha(story.read_bytes())}
    tag = ["hero"]
    settings = {"scenes": {"room": 1}, "character_tags": tag}
    entry = {
        "normal_noise": "normal.png",
        "height_ao_edge": "height.png",
        "response": "response.png",
    }
    previous = {"sprites": {"hero grin coat": entry}, "version": 9}
    current = {"sprites": {"hero coat grin": entry}, "version": 9}
    files = {}

    def store_index(name, value):
        raw = json.dumps(value).encode()
        (runtime / name).write_bytes(raw)
        files["game/scenelight_runtime/" + name] = sha(raw)

    store_index("manifest.json", settings)
    store_index("sprite_form_manifest.json", current)
    old = {"files": {}, "source_state": {}}
    new = {
        "files": files,
        "source_state": {
            "game/story.rpy": [14, 1, scripts["story.rpy"]],
            "game/coat.png": [7, 1, sha(artwork.read_bytes())],
        },
    }

    def patch(applied=scripts, compiled=None):
        return sprite_commit(
            str(tmp_path), old, new, settings, previous, applied, tag, compiled=compiled
        )

    assert patch()[2] == {"hero grin coat": None, "hero coat grin": entry}
    with pytest.raises(ValueError, match="scripts have not loaded"):
        patch({})
    bytecode = story.with_suffix(".rpyc")
    bytecode.write_bytes(b"already loaded")
    loaded = loaded_bytecode(str(tmp_path), old, scripts)
    new["source_state"]["game/story.rpyc"] = [0, 0, "compiler fingerprint"]
    assert patch(compiled=loaded)[2]["hero coat grin"] == entry
    bytecode.write_bytes(b"another script")
    with pytest.raises(ValueError, match="Compiled script differs"):
        patch(compiled=loaded)
    del new["source_state"]["game/story.rpyc"]
    artwork.write_bytes(b"newer save")
    with pytest.raises(_NewerSave):
        patch()
    artwork.write_bytes(b"new art")
    store_index("manifest.json", dict(settings, strength=0.4))
    with pytest.raises(ValueError, match="Scene lighting parameters changed"):
        patch()
    files["game/scenelight_runtime/bootstrap.rpy"] = sha(b"new runtime")
    with pytest.raises(ValueError, match="runtime files changed"):
        patch()
