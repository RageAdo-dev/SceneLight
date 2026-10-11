## Development-only live texture/context prototype. Never install in a release.
init 1000 python:
    import os as _live_os
    import json as _live_json
    import weakref as _live_weakref
    _live_output = _live_os.environ.get("SCENELIGHT_LIVE_TEXTURE_PROBE")

    if _live_output:
        config.save_directory = "SceneLight-Live-Texture-Probe"
        config.label_overrides["splashscreen"] = "scenelight_live_texture_probe"
        config.label_overrides["before_main_menu"] = "scenelight_live_texture_probe"
        renpy.display._scenelight_live_probe_frames = _live_weakref.WeakKeyDictionary()
        _live_rows = []
        renpy.register_shader("scenelight.live_source_probe",
            variables=_scenelight_shader_live_probe_variables,
            fragment_300=_scenelight_shader_live_probe_fragment)

        class _LiveBackgroundTap(renpy.Displayable):
            def __init__(self, child):
                super(_LiveBackgroundTap, self).__init__()
                self.child = child

            def visit(self):
                return [self.child]

            def get_placement(self):
                return self.child.get_placement()

            def set_transform_event(self, event):
                self.child.set_transform_event(event)

            def _handles_event(self, event):
                return self.child._handles_event(event)

            def _show(self):
                self.child._show()

            def render(self, width, height, st, at):
                # This is the engine's original render call, not an extra
                # DynamicDisplayable invocation or a screenshot/readback.
                rendered = renpy.render(self.child, width, height, st, at)
                canvas = renpy.Render(width, height)
                self.child.place(canvas, 0, 0, width, height, rendered)
                field = renpy.Render(16, 9)
                field.blit(renpy.render(Solid("#fff", xsize=16, ysize=9), 16, 9, st, at), (0, 0))
                field.blit(canvas, (0, 0))
                field.mesh = True
                field.add_shader("renpy.texture")
                field.add_shader("scenelight.live_source_probe")
                field.add_uniform("u_sc_probe_grid", (16.0, 9.0))
                renpy.display._scenelight_live_probe_frames[self] = (
                    renpy.game.interface.frame_time, canvas, field)
                return rendered

        _live_scene_lists = _scenelight_scene_lists_class()
        _live_original_add = _live_scene_lists.add

        def _live_tap_add(owner, *args, **kwargs):
            result = _live_original_add(owner, *args, **kwargs)
            layer = kwargs.get("layer", args[0] if args else None)
            if layer == "master":
                for index, entry in enumerate(owner.layers.get(layer, ())):
                    if entry.tag == "bg" and not isinstance(entry.displayable, _LiveBackgroundTap):
                        updated = entry.copy()
                        updated.displayable = _LiveBackgroundTap(entry.displayable)
                        owner.layers[layer][index] = updated
            return result

        _live_scene_lists.add = _live_tap_add

        class _LiveProbeView(renpy.Displayable):
            def render(self, width, height, st, at):
                renpy.redraw(self, 0.0)
                result = renpy.Render(16, 9)
                for entry in renpy.game.context().scene_lists.layers.get("master", ()):
                    if entry.tag != "bg":
                        continue
                    frame = renpy.display._scenelight_live_probe_frames.get(entry.displayable)
                    if frame is None:
                        continue
                    time, canvas, field = frame
                    result.blit(field, (0, 0))
                    _live_rows.append({
                        "frame_time": renpy.game.interface.frame_time,
                        "source_time": time,
                        "background": list(entry.name),
                        "context": id(entry.displayable),
                        "field": id(field),
                        "consumer": id(self),
                    })
                return result

        def _live_finish():
            with open(_live_os.path.join(_live_output, "live-texture-observations.json"), "w") as stream:
                _live_json.dump(_live_rows, stream)
            data = renpy.screenshot_to_bytes((1280, 720))
            with open(_live_os.path.join(_live_output, "live-texture-proof.png"), "wb") as stream:
                stream.write(data)
            renpy.quit(relaunch=False, status=0)

screen scenelight_live_probe_screen():
    add _live_probe_a zoom 8 xpos 20 ypos 20
    add _live_probe_b zoom 8 xpos 170 ypos 20

label scenelight_live_texture_probe:
    $ quick_menu = False
    $ _live_probe_a = _LiveProbeView()
    $ _live_probe_b = _LiveProbeView()
    show screen scenelight_live_probe_screen
    scene bg br_yellow_movie
    show monika 1a at t11
    $ renpy.pause(3.0, hard=True)
    scene bg br_dynamic
    $ renpy.pause(3.0, hard=True)
    scene bg br_atl_stairs at br_slow_drift
    $ renpy.pause(3.0, hard=True)
    scene bg br_pool_movie
    $ renpy.pause(3.0, hard=True)
    $ _live_finish()
