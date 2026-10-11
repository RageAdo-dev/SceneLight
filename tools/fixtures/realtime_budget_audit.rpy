## Development-only performance probe. Use in an isolated game copy.
## Measures render scheduling and CPU submission, not GPU execution time.
init 999 python:
    import json as _rt_json
    import os as _rt_os
    import time as _rt_time

    _rt_root = _rt_os.environ.get("SCENELIGHT_REALTIME_AUDIT")
    if _rt_root:
        config.save_directory = "SceneLight-Realtime-Design-Audit"
        config.label_overrides["splashscreen"] = "scenelight_realtime_budget_audit"
        config.label_overrides["before_main_menu"] = "scenelight_realtime_budget_audit"
        _rt_frames = []
        _rt_renders = []
        _rt_freezes = []
        _rt_phase = "startup"
        _rt_names = {id(value): key for key, value in SCENELIGHT_SCENES.items()}
        _rt_original_render = SceneLightSprite.render
        _rt_original_flatten = _scenelight_flatten_lit_side

        def _rt_sprite_render(self, width, height, st, at):
            started = _rt_time.time()
            result = _rt_original_render(self, width, height, st, at)
            elapsed = (_rt_time.time() - started) * 1000.0
            scene = self._sc_last_rendered_scene
            _rt_renders.append({
                "phase": _rt_phase,
                "frame_time": renpy.game.interface.frame_time,
                "cpu_ms": elapsed,
                "scene": _rt_names.get(id(scene)),
                "lighting_present": scene is not None,
                "blend": scene.get("_sc_blend", 0.0) if scene else None,
                "scene_uv": scene.get("uv") if scene else None,
                "next_uv": scene.get("_sc_next_uv") if scene else None,
                "frozen": self._sc_snapshot_frozen,
            })
            return result

        def _rt_flatten(displayable, *args):
            result = _rt_original_flatten(displayable, *args)
            _rt_freezes.append({
                "phase": _rt_phase,
                "frame_time": renpy.game.interface.frame_time,
                "type": result.__class__.__name__,
            })
            return result

        SceneLightSprite.render = _rt_sprite_render
        _scenelight_flatten_lit_side = _rt_flatten

    class _RealtimeBudgetObserver(renpy.Displayable):
        def render(self, width, height, st, at):
            renpy.redraw(self, 0.0)
            _rt_frames.append({
                "phase": _rt_phase,
                "frame_time": renpy.game.interface.frame_time,
                "wall_time": _rt_time.time(),
            })
            return renpy.Render(1, 1)

    def _rt_finish():
        payload = {
            "renpy": renpy.version_string,
            "renderer": renpy.get_renderer_info(),
            "physical_size": renpy.get_physical_size(),
            "frames": _rt_frames,
            "sprite_renders": _rt_renders,
            "transition_sides": _rt_freezes,
            "scope": "Render scheduling and CPU submission; no GPU query or presentation timestamps.",
        }
        with open(_rt_os.path.join(_rt_root, "game-observations.json"), "w") as stream:
            _rt_json.dump(payload, stream, indent=2, default=str)
        renpy.quit(relaunch=False, status=0)

screen scenelight_realtime_budget_observer():
    zorder 1000
    add _rt_observer

label scenelight_realtime_budget_audit:
    $ quick_menu = False
    $ renpy.set_physical_size((1920, 1080))
    $ renpy.pause(0.25, hard=True)
    $ _rt_observer = _RealtimeBudgetObserver()
    show screen scenelight_realtime_budget_observer
    scene bg br_yellow_movie
    show monika 1a at t11
    $ renpy.pause(1.5, hard=True)
    $ scenelight_set_enabled(False)
    $ _rt_phase = "yellow-unlit"
    $ renpy.pause(5.0, hard=True)
    $ scenelight_set_enabled(True)
    $ _rt_phase = "yellow-lit"
    $ renpy.pause(5.0, hard=True)
    $ _rt_phase = "vhs-lit"
    scene bg br_real_vhs_movie
    show monika 1a at t11
    $ renpy.pause(5.0, hard=True)
    $ _rt_phase = "expression-dissolve"
    show monika 1b at t11
    with Dissolve(1.5)
    $ _rt_phase = "after-dissolve"
    $ renpy.pause(3.0, hard=True)
    $ _rt_finish()
