init 1005 python:
    import os as _continuity_os
    _continuity_root = _continuity_os.environ.get("SCENELIGHT_CONTINUITY_AUDIT")
    if _continuity_root:
        import json as _continuity_json
        import ctypes as _continuity_ctypes
        config.save_directory = "SceneLight-Continuity-Audit"
        config.label_overrides["splashscreen"] = "scenelight_continuity_audit"
        config.label_overrides["before_main_menu"] = "scenelight_continuity_audit"
        renpy.display._sc_continuity_records = []
        class _ContinuityObserver(renpy.Displayable):
            def __init__(self):
                super(_ContinuityObserver, self).__init__()
                self.last = -1
            def render(self, width, height, st, at):
                renpy.redraw(self, 0.0)
                renderer = renpy.display._scenelight_live_renderer
                if renderer and renderer.evaluations != self.last:
                    self.last = renderer.evaluations
                    fields = _scenelight_live_fields(_scenelight_live_scene())
                    if fields:
                        record = {"time": renpy.game.interface.frame_time,
                            "evaluations": self.last, "disabled": renderer.disabled,
                            "frames": len(renderer.frames), "positions": []}
                        gl = renderer.analysis.device.gl
                        with renderer.gpu.State(gl):
                            renderer.analysis.device.bind_targets((fields["transport"].number,))
                            for x in (5, 10):
                                pixel = (_continuity_ctypes.c_ubyte * 4)()
                                gl.ReadPixels(48+x, 4, 1, 1, 0x1908, 0x1401, _continuity_ctypes.cast(pixel, _continuity_ctypes.c_void_p))
                                record["positions"].append(list(pixel))
                        renpy.display._sc_continuity_records.append(record)
                return renpy.Render(1, 1)
        def _continuity_capture(name):
            with open(_continuity_os.path.join(_continuity_root, name + ".png"), "wb") as stream:
                stream.write(renpy.screenshot_to_bytes((1280, 720)))

screen scenelight_continuity_observer():
    add _ContinuityObserver()

label scenelight_continuity_audit:
    $ quick_menu = False
    scene bg br_yellow_movie
    show natsuki 1g at t21 zorder 2
    show monika 1h at t22 zorder 2
    show screen scenelight_continuity_observer
    $ renpy.pause(1.55, hard=True)
    $ _continuity_capture("before-rank-crossing")
    $ renpy.pause(0.30, hard=True)
    $ _continuity_capture("after-rank-crossing")
    $ renpy.pause(5.0, hard=True)
    python:
        with open(_continuity_os.path.join(_continuity_root, "frames.json"), "w") as stream:
            _continuity_json.dump(renpy.display._sc_continuity_records, stream)
        renpy.display._sc_continuity_records = []
    scene bg br_nangang at AnimatedAberate
    show monika 1h at t11 zorder 2
    $ renpy.pause(8.0, hard=True)
    $ _continuity_capture("station")
    python:
        with open(_continuity_os.path.join(_continuity_root, "station-frames.json"), "w") as stream:
            _continuity_json.dump(renpy.display._sc_continuity_records, stream)
    $ renpy.quit(relaunch=False, status=0)
