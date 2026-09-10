## Development-only test of the shared GL device inside the real engine.
init 1002 python:
    import os as _device_os
    _device_output = _device_os.environ.get("SCENELIGHT_GPU_DEVICE_AUDIT")
    if _device_output:
        import types as _device_types
        import sys as _device_sys
        import json as _device_json
        import traceback as _device_traceback
        config.save_directory = "SceneLight-GPU-Device-Audit"
        config.label_overrides["splashscreen"] = "scenelight_gpu_device_audit"
        config.label_overrides["before_main_menu"] = "scenelight_gpu_device_audit"
        _device_name = "scenelight_gpu_device_audit"
        if _device_sys.version_info[0] < 3:
            _device_name = _device_name.encode("ascii")
        _device_module = _device_types.ModuleType(_device_name)
        with open(_device_os.path.join(config.gamedir, "zz_live_gpu_module.py"), "rb") as _device_stream:
            eval(compile(_device_stream.read(), "zz_live_gpu_module.py", "exec", 0, True), _device_module.__dict__)

        class _SceneLightDeviceAudit(renpy.Displayable):
            complete = False
            def render(self, width, height, st, at):
                if not self.complete:
                    self.complete = True
                    report = {}
                    device = None
                    try:
                        driver = _device_module.Driver()
                        report["host_gl_error_before_device"] = driver.GetError()
                        device = _device_module.Device(driver)
                        gl = device.gl
                        C = _device_module.C
                        report["version"] = gl.version
                        report["renpy"] = renpy.version_string
                        expected = (gl.integer(0x0BA2, 4), gl.integer(0x8B8D), gl.integer(0x8CA6))
                        with _device_module.State(gl):
                            target = device.target("precision", 8, 1)
                            program = device.program("precision", """
                                in vec2 uv; out vec4 color;
                                void main() { color=vec4(0.0000123, 1.125, -0.25, 1.0); }
                            """)
                            device.draw(program, target, 8, 1)
                            pixels = (C.c_float * 32)()
                            gl.ReadPixels(0, 0, 8, 1, 0x1908, 0x1406, C.cast(pixels, C.c_void_p))
                            reference = (0.0000123, 1.125, -0.25, 1.0)
                            report["float_max_error"] = max(abs(pixels[i]-reference[i%4]) for i in range(32))
                            program = device.program("scatter", """
                                out vec4 color; void main() { color=vec4(1.0); }
                            """, """
                                void main() {
                                    float x=float(gl_VertexID % 8);
                                    gl_Position=vec4((x+0.5)/8.0*2.0-1.0, 0.0, 0.0, 1.0);
                                    gl_PointSize=1.0;
                                }
                            """)
                            device.draw(program, target, 8, 1, points=8000, blend=True)
                            gl.ReadPixels(0, 0, 8, 1, 0x1908, 0x1406, C.cast(pixels, C.c_void_p))
                            report["accumulation_exact"] = all(value == 1000 for value in pixels)
                            report["gl_error"] = gl.GetError()
                        observed = (gl.integer(0x0BA2, 4), gl.integer(0x8B8D), gl.integer(0x8CA6))
                        report["state_restored"] = observed == expected
                    except Exception:
                        report["error"] = _device_traceback.format_exc()
                    finally:
                        if device is not None:
                            device.close()
                    with open(_device_output, "w") as stream:
                        _device_json.dump(report, stream, indent=2)
                return renpy.render(Solid("#182030"), width, height, st, at)

label scenelight_gpu_device_audit:
    $ quick_menu = False
    scene expression _SceneLightDeviceAudit()
    $ renpy.pause(0.5, hard=True)
    $ renpy.quit(relaunch=False, status=0)
