init 1004 python:
    import os as _memory_os
    _memory_output = _memory_os.environ.get("SCENELIGHT_MEMORY_AUDIT")
    if _memory_output:
        import json as _memory_json
        import gc as _memory_gc
        import ctypes as _memory_ctypes
        import time as _memory_time
        class _MemoryCounters(_memory_ctypes.Structure):
            _fields_ = [("cb", _memory_ctypes.c_ulong), ("faults", _memory_ctypes.c_ulong)] + [(name, _memory_ctypes.c_size_t) for name in (
                "peak_working", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "commit", "peak_commit", "private")]
        _memory_ctypes.windll.kernel32.GetCurrentProcess.restype = _memory_ctypes.c_void_p
        _memory_ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [_memory_ctypes.c_void_p, _memory_ctypes.c_void_p, _memory_ctypes.c_ulong]
        config.save_directory = "SceneLight-Memory-Audit"
        config.label_overrides["splashscreen"] = "scenelight_memory_audit"
        config.label_overrides["before_main_menu"] = "scenelight_memory_audit"
        class _MemoryObserver(renpy.Displayable):
            def __init__(self):
                super(_MemoryObserver, self).__init__()
                self.started = _memory_time.time()
                self.last = 0
            def render(self, width, height, st, at):
                renpy.redraw(self, 0.0)
                now = _memory_time.time()
                if now - self.last >= 1:
                    self.last = now
                    counters = _MemoryCounters()
                    counters.cb = _memory_ctypes.sizeof(counters)
                    _memory_ctypes.windll.psapi.GetProcessMemoryInfo(_memory_ctypes.windll.kernel32.GetCurrentProcess(), _memory_ctypes.byref(counters), counters.cb)
                    renderer = renpy.display._scenelight_live_renderer
                    loader = renpy.display.draw.texture_loader
                    record = {"seconds": now-self.started, "private_mib": counters.private/1048576.0,
                        "textures": loader.get_texture_size(), "gc_count": _memory_gc.get_count(), "garbage": len(_memory_gc.garbage),
                        "evaluations": renderer.evaluations, "frames": len(renderer.frames), "backgrounds": len(renderer.backgrounds),
                        "frozen": len(renderer.frozen_canvases), "disabled": renderer.disabled}
                    if renderer.analysis:
                        device = renderer.analysis.device
                        record.update(targets=len(device.targets), programs=len(device.programs), buffers=len(device.buffers))
                    with open(_memory_output, "a") as stream:
                        stream.write(_memory_json.dumps(record) + "\n")
                    if counters.private > 3 * 1024**3:
                        renpy.quit(relaunch=False, status=2)
                return renpy.Render(1, 1)

label scenelight_memory_audit:
    $ quick_menu = False
    scene bg br_yellow_movie
    show monika 1a at t11
    show screen scenelight_memory_observer
    $ renpy.pause(float(_memory_os.environ.get("SCENELIGHT_MEMORY_SECONDS", "180")), hard=True)
    $ renpy.quit(relaunch=False, status=0)

screen scenelight_memory_observer():
    add _MemoryObserver()
