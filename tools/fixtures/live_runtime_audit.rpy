init 1003 python:
    import os as _live_audit_os
    _live_audit_output = _live_audit_os.environ.get("SCENELIGHT_LIVE_RUNTIME_AUDIT")
    if _live_audit_output:
        import json as _live_audit_json
        config.save_directory = "SceneLight-Live-Runtime-Audit"
        config.label_overrides["splashscreen"] = "scenelight_live_runtime_audit"
        config.label_overrides["before_main_menu"] = "scenelight_live_runtime_audit"
        _live_audit_records = []
        _live_audit_swaps = []
        renpy.register_shader("scenelight.audit_live_background",
            variables="uniform float u_time;\nuniform vec4 u_random;",
            fragment_300="gl_FragColor = vec4(vec3(0.12 + 0.10*sin(u_time*2.0), 0.18, 0.28 + 0.20*cos(u_time)) + u_random.rgb*0.15, 1.0);")
        class _LiveAuditObserver(renpy.Displayable):
            def render(self, width, height, st, at):
                renpy.redraw(self, 0.0)
                renderer = renpy.display._scenelight_live_renderer
                if renderer:
                    _live_audit_swaps.append((renpy.game.interface.frame_time, renderer.evaluations))
                return renpy.Render(1, 1)
        renpy.display.log.write("Live audit init: shader=%r, loadable=%r, renderer=%r" % (
            _SCENELIGHT_SHADER_AVAILABLE, renpy.loadable("scenelight_runtime/live_gpu.txt"),
            renpy.display._scenelight_live_renderer))

        def _live_audit_capture(name):
            renderer = renpy.display._scenelight_live_renderer
            scene = _scenelight_live_scene()
            _live_audit_records.append({"name": name,
                "shader_available": _SCENELIGHT_SHADER_AVAILABLE,
                "init_error": renpy.display._scenelight_live_error,
                "loadable": renpy.loadable("scenelight_runtime/live_gpu.txt"),
                "renderer": renderer is not None,
                "disabled": renderer.disabled if renderer else None,
                "evaluations": renderer.evaluations if renderer else 0,
                "live_fields": bool(_scenelight_live_fields(scene)),
                "frame_cache": len(renderer.frames) if renderer else 0,
                "background_cache": len(renderer.backgrounds) if renderer else 0,
                "background_placement": [list(entry.displayable.child.get_placement())
                    for entry in renpy.game.context().scene_lists.layers.get("master", ())
                    if isinstance(entry.displayable, _SceneLightBackground) and entry.tag == "bg"],
                "background_offsets": [[float(value) for value in renderer.backgrounds[entry.displayable.binding][4]]
                    for entry in renpy.game.context().scene_lists.layers.get("master", ())
                    if renderer and isinstance(entry.displayable, _SceneLightBackground)
                    and entry.tag == "bg" and renderer.frame(entry.displayable) is not None],
                "version": renderer.analysis.device.gl.version if renderer and renderer.analysis else None})
            with open(_live_audit_os.path.join(_live_audit_output, name + ".png"), "wb") as stream:
                stream.write(renpy.screenshot_to_bytes((1280, 720)))
            with open(_live_audit_os.path.join(_live_audit_output, "report.json"), "w") as stream:
                _live_audit_json.dump(_live_audit_records, stream, indent=2, default=str)
            with open(_live_audit_os.path.join(_live_audit_output, name + "-frames.json"), "w") as stream:
                _live_audit_json.dump(_live_audit_swaps, stream)

image bg scenelight_live_sixty = Movie(play="scenelight-live-sixty.mp4", size=(1280, 720))

image bg scenelight_live_shader = Transform(Solid("#fff"), mesh=True, shader="scenelight.audit_live_background")

screen scenelight_live_audit_observer():
    add _LiveAuditObserver()

transform scenelight_live_audit_drift:
    xpos 0.10
    xanchor 0.0
    linear 4.0 xpos 0.20

label scenelight_live_runtime_audit:
    $ quick_menu = False
    scene bg br_yellow_movie
    show monika 1a at t11
    $ renpy.pause(2.0, hard=True)
    $ _live_audit_capture("yellow")
    scene bg br_pool_movie
    show monika 1a at t11
    with dissolve
    $ renpy.pause(2.0, hard=True)
    $ _live_audit_capture("pool")
    scene bg br_dynamic
    show monika 1a at t11
    $ renpy.pause(2.0, hard=True)
    $ _live_audit_capture("dynamic")
    scene bg scenelight_live_sixty
    show monika 1a at t11
    show screen scenelight_live_audit_observer
    $ renpy.pause(1.0, hard=True)
    $ _live_audit_swaps[:] = []
    $ renpy.pause(5.0, hard=True)
    $ _live_audit_capture("sixty")
    scene bg scenelight_live_shader
    show monika 1a at t11
    $ _live_audit_swaps[:] = []
    $ renpy.pause(2.0, hard=True)
    $ _live_audit_capture("shader")
    scene bg br_pool at scenelight_live_audit_drift
    show monika 1a at t11
    $ renpy.pause(0.4, hard=True)
    $ _live_audit_capture("drift-before")
    show bg br_red
    $ renpy.pause(0.4, hard=True)
    $ _live_audit_capture("drift-after")
    $ renpy.quit(relaunch=False, status=0)
