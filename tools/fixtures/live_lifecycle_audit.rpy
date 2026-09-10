init 1004 python:
    import os as _life_os
    _life_root = _life_os.environ.get("SCENELIGHT_LIVE_LIFECYCLE_AUDIT")
    if _life_root:
        import json as _life_json
        config.save_directory = "SceneLight-Live-Lifecycle-Audit"
        # Ren'Py normally skips timed pauses while replaying a rollback/load.
        # The audit must allow an actual interaction before reading live fields.
        config.pause_after_rollback = True
        config.label_overrides["splashscreen"] = "scenelight_live_lifecycle_audit"
        config.label_overrides["before_main_menu"] = "scenelight_live_lifecycle_audit"
        renpy.display._sc_lifecycle_trace = []
        def _life_trace_install():
            renderer = renpy.display._scenelight_live_renderer
            original = renderer.capture
            def capture(background, *args):
                renpy.display._sc_lifecycle_trace.append((background.scene_key, id(background), id(background.binding)))
                return original(background, *args)
            renderer.capture = capture
        _life_trace_install()

        def _life_marker(name):
            return _life_os.path.join(_life_root, name + ".once")

        def _life_legacy_background():
            owner = renpy.game.context().scene_lists
            for index, entry in enumerate(owner.layers.get("master", ())):
                if isinstance(entry.displayable, _SceneLightBackground):
                    restored = entry.copy()
                    restored.displayable = entry.displayable.child
                    owner.layers["master"][index] = restored

        def _life_capture(name):
            if _life_os.path.exists(_life_os.path.join(_life_root, name + ".json")):
                return
            scene = _scenelight_live_scene()
            renderer = renpy.display._scenelight_live_renderer
            result = {"scene": SCENELIGHT_STABLE_SCENE_KEY,
                "live": bool(_scenelight_live_fields(scene)),
                "disabled": renderer.disabled if renderer else None,
                "evaluations": renderer.evaluations if renderer else 0,
                "backgrounds": len(renderer.backgrounds) if renderer else 0,
                "frames": len(renderer.frames) if renderer else 0,
                "cache_keys": [id(key) for key in renderer.backgrounds] if renderer else [],
                "captures": renpy.display._sc_lifecycle_trace,
                "entries": [(str(entry.name), type(entry.displayable).__name__,
                    bool(renderer.frame(entry.displayable)) if renderer else False,
                    id(getattr(entry.displayable, "binding", None)))
                    for entry in renpy.game.context().scene_lists.layers.get("master", ())]}
            with open(_life_os.path.join(_life_root, name + ".json"), "w") as stream:
                _life_json.dump(result, stream)
            with open(_life_os.path.join(_life_root, name + ".png"), "wb") as stream:
                stream.write(renpy.screenshot_to_bytes((1280, 720)))

label scenelight_live_lifecycle_audit:
    $ quick_menu = False
    $ renpy.set_physical_size((1280, 720))
    scene bg br_red
    show monika 1a at t11
    $ renpy.pause(1.5, hard=True)
    $ _life_capture("before-save")
    $ _life_legacy_background()
    $ renpy.save("scenelight-live-audit")
    if not _life_os.path.exists(_life_marker("load")):
        $ open(_life_marker("load"), "w").close()
        scene bg br_pool
        show monika 1a at t11
        $ renpy.pause(0.5, hard=True)
        $ renpy.load("scenelight-live-audit")
    $ renpy.pause(1.0, hard=True)
    $ _life_capture("after-load")
    $ renpy.checkpoint()
    if _life_os.path.exists(_life_marker("rollback")):
        jump scenelight_live_after_rollback
    scene bg br_pool
    show monika 1a at t11
    $ renpy.pause(0.5, hard=True)
    $ open(_life_marker("rollback"), "w").close()
    $ renpy.rollback(force=True, checkpoints=1)
    $ raise RuntimeError("Rollback returned without restoring the checkpoint")

label scenelight_live_after_rollback:
    $ renpy.pause(1.0, hard=True)
    $ _life_capture("after-rollback")
    $ renpy.quit(relaunch=False, status=0)
