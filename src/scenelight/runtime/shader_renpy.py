"""Capability and link checks for the optional vertex shader (Python 2 compatible)."""

import ctypes as C


def validate_program(gl, vertex, fragment, log=None):
    """Check the engine's assembled sources, releasing even failed GL objects.

    Ren'Py 7's compiler does not delete shaders when compilation fails. Perform
    the optional compilation here first so an unsupported optimization cannot
    leak those objects or prevent a game from starting.
    """
    shaders, program = [], 0
    try:
        for kind, code in ((0x8B31, vertex), (0x8B30, fragment)):
            shader = gl.CreateShader(kind)
            shaders.append(shader)
            source = C.c_char_p(code.encode("utf-8"))
            gl.ShaderSource(shader, 1, C.byref(source), None)
            gl.CompileShader(shader)
            ok = C.c_int()
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            if not ok.value:
                if log is not None:
                    message = C.create_string_buffer(4096)
                    gl.GetShaderInfoLog(shader, len(message), None, message)
                    log("SceneLight optional shader: " + message.value.decode("utf-8", "replace"))
                return False
        program = gl.CreateProgram()
        for shader in shaders:
            gl.AttachShader(program, shader)
        gl.LinkProgram(program)
        ok = C.c_int()
        gl.GetProgramiv(program, 0x8B82, C.byref(ok))
        if not ok.value and log is not None:
            message = C.create_string_buffer(4096)
            gl.GetProgramInfoLog(program, len(message), None, message)
            log("SceneLight optional shader link: " + message.value.decode("utf-8", "replace"))
        return bool(ok.value)
    finally:
        if program:
            gl.DeleteProgram(program)
        for shader in shaders:
            gl.DeleteShader(shader)


def assembled_sources(cache_module, names, default_shader, gles):
    included = set(name for name in names if not name.startswith("-"))
    included.difference_update(name[1:] for name in names if name.startswith("-"))
    if "renpy.ftl" not in included:
        included.add(default_shader)
    parts = [cache_module.shader_part[name] for name in sorted(included)]
    sources = []
    for stage in ("vertex", "fragment"):
        variables, bodies, functions = set(), [], []
        for part in parts:
            variables.update(getattr(part, stage + "_variables"))
            bodies.extend(getattr(part, stage + "_parts"))
            functions.append(getattr(part, stage + "_functions"))
        sources.append(cache_module.source(variables, bodies, functions, stage == "fragment", gles))
    return tuple(sources)


def install(cache_module, gpu, stages, config, log):
    """Only intercept SceneLight's optional part; cache decisions per GL context."""
    cache_class = cache_module.ShaderCache
    if getattr(cache_class.get, "_scenelight_vertex_policy", False):
        return
    original = cache_class.get

    def get(cache, names):
        if stages.OPTIMIZED not in names:
            return original(cache, names)
        if getattr(config, "shader_part_filter", None) is not None:
            # A game's filter can replace arbitrary parts after our preflight.
            # Let the engine invoke it once, with SceneLight's public part name,
            # preserving its existing behavior rather than guessing its output.
            fallback = tuple(
                stages.ORIGINAL if name == stages.OPTIMIZED else name for name in names
            )
            return original(cache, fallback)
        if names in cache.cache:
            return original(cache, names)
        if "-" + stages.ORIGINAL in names or "-" + stages.OPTIMIZED in names:
            # Preserve the original public part's exclusion semantics, including
            # on devices which select the fallback implementation.
            without = tuple(name for name in names if name != stages.OPTIMIZED)
            program = original(cache, without)
            cache.cache[names] = program
            return program
        selected = tuple(name for name in names if name != stages.ORIGINAL)
        if not hasattr(cache, "_scenelight_vertex_gl"):
            cache._scenelight_vertex_gl = None
            try:
                if not cache.gles:
                    gl = gpu.Driver()
                    if stages.supported(gl.integer(0x8B4B), gl.integer(0x8B4C)):
                        cache._scenelight_vertex_gl = gl
                    else:
                        log(
                            "SceneLight vertex limits: %s varying components, %s vertex samplers."
                            % (gl.integer(0x8B4B), gl.integer(0x8B4C))
                        )
            except Exception as error:
                log("SceneLight optional vertex APIs unavailable: " + str(error))
        gl = cache._scenelight_vertex_gl
        eligible = False
        if gl is not None:
            try:
                sources = assembled_sources(
                    cache_module, selected, config.default_shader, cache.gles
                )
                eligible = validate_program(gl, sources[0], sources[1], log)
            except Exception as error:
                log("SceneLight optional vertex check failed: " + str(error))
                eligible = False
        if eligible:
            program = original(cache, selected)
            cache.cache[names] = program
            log("SceneLight uses vertex sampling for this renderer/shader combination.")
            return program
        fallback = tuple(stages.ORIGINAL if name == stages.OPTIMIZED else name for name in names)
        program = original(cache, fallback)
        cache.cache[names] = program
        log("SceneLight retained its original shader for this renderer/shader combination.")
        return program

    get._scenelight_vertex_policy = True
    cache_class.get = get
