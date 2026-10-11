"""Shared OpenGL analysis machinery. Standard-library-only, including on Ren'Py 7.

The host owns the current graphics context. All native resources are transient;
hosts must close this object before destroying that context. This module is also
loaded by Preview so the game and editor execute the same numerical passes.
"""

from __future__ import division

import ctypes as C
import ctypes.util
import math
import re
import sys

GLuint = C.c_uint
GLint = C.c_int
GLfloat = C.c_float
GLvoidp = C.c_void_p
GLcharp = C.c_char_p

TEXTURE_2D = 0x0DE1
TEXTURE0 = 0x84C0
RGBA = 0x1908
RGBA32F = 0x8814
RG32F = 0x8230
R32F = 0x822E
RGBA8 = 0x8058
FLOAT = 0x1406
UNSIGNED_BYTE = 0x1401
FRAMEBUFFER = 0x8D40
COLOR_ATTACHMENT0 = 0x8CE0
FRAMEBUFFER_COMPLETE = 0x8CD5
NEAREST = 0x2600
LINEAR = 0x2601
COLOR_BUFFER_BIT = 0x4000


def _resolver():
    """Use the current host's GL loader, including SDL's ANGLE selection."""
    if sys.platform == "win32":
        kernel = C.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [C.c_wchar_p]
        kernel.GetModuleHandleW.restype = GLvoidp
        for name in ("SDL2.dll", "libSDL2.dll", "SDL2-2.0.dll"):
            handle = kernel.GetModuleHandleW(name)
            if handle:
                library = C.CDLL(name, handle=handle)
                get = library.SDL_GL_GetProcAddress
                get.argtypes, get.restype = [GLcharp], GLvoidp
                return library, get, C.WINFUNCTYPE
        library = C.WinDLL("opengl32")
        get = library.wglGetProcAddress
        get.argtypes, get.restype = [GLcharp], GLvoidp
        return library, get, C.WINFUNCTYPE
    try:
        process = C.CDLL(None)
        get = process.SDL_GL_GetProcAddress
        get.argtypes, get.restype = [GLcharp], GLvoidp
        if get(b"glGetString"):
            return process, get, C.CFUNCTYPE
    except AttributeError:
        pass
    if sys.platform == "darwin":
        library = C.CDLL("/System/Library/Frameworks/OpenGL.framework/OpenGL")
        return library, lambda name: None, C.CFUNCTYPE
    name = ctypes.util.find_library("GL")
    if not name:
        try:
            library = C.CDLL(ctypes.util.find_library("GLESv2") or "libGLESv2.so")
            egl = C.CDLL(ctypes.util.find_library("EGL") or "libEGL.so")
            get = egl.eglGetProcAddress
            get.argtypes, get.restype = [GLcharp], GLvoidp
            return library, get, C.CFUNCTYPE
        except (OSError, AttributeError):
            raise RuntimeError("No OpenGL loader is available")
    library = C.CDLL(name)
    get = library.glXGetProcAddressARB
    get.argtypes, get.restype = [GLcharp], GLvoidp
    return library, get, C.CFUNCTYPE


class Driver(object):
    def __init__(self):
        self.library, self.get_proc, self.prototype = _resolver()
        signatures = {
            "GetString": (GLcharp, [GLuint]),
            "GetStringi": (GLcharp, [GLuint, GLuint]),
            "GetIntegeri_v": (None, [GLuint, GLuint, C.POINTER(GLint)]),
            "GetIntegerv": (None, [GLuint, C.POINTER(GLint)]),
            "GetFloatv": (None, [GLuint, C.POINTER(GLfloat)]),
            "IsEnabled": (C.c_ubyte, [GLuint]),
            "Enable": (None, [GLuint]),
            "Disable": (None, [GLuint]),
            "GenTextures": (None, [GLint, C.POINTER(GLuint)]),
            "DeleteTextures": (None, [GLint, C.POINTER(GLuint)]),
            "BindTexture": (None, [GLuint, GLuint]),
            "BindSampler": (None, [GLuint, GLuint]),
            "ActiveTexture": (None, [GLuint]),
            "TexParameteri": (None, [GLuint, GLuint, GLint]),
            "TexImage2D": (
                None,
                [GLuint, GLint, GLint, GLint, GLint, GLint, GLuint, GLuint, GLvoidp],
            ),
            "TexSubImage2D": (
                None,
                [GLuint, GLint, GLint, GLint, GLint, GLint, GLuint, GLuint, GLvoidp],
            ),
            "CopyTexSubImage2D": (None, [GLuint, GLint, GLint, GLint, GLint, GLint, GLint, GLint]),
            "GenFramebuffers": (None, [GLint, C.POINTER(GLuint)]),
            "DeleteFramebuffers": (None, [GLint, C.POINTER(GLuint)]),
            "BindFramebuffer": (None, [GLuint, GLuint]),
            "FramebufferTexture2D": (None, [GLuint, GLuint, GLuint, GLuint, GLint]),
            "CheckFramebufferStatus": (GLuint, [GLuint]),
            "GenVertexArrays": (None, [GLint, C.POINTER(GLuint)]),
            "DeleteVertexArrays": (None, [GLint, C.POINTER(GLuint)]),
            "BindVertexArray": (None, [GLuint]),
            "BindBuffer": (None, [GLuint, GLuint]),
            "CreateShader": (GLuint, [GLuint]),
            "ShaderSource": (None, [GLuint, GLint, C.POINTER(GLcharp), C.POINTER(GLint)]),
            "CompileShader": (None, [GLuint]),
            "GetShaderiv": (None, [GLuint, GLuint, C.POINTER(GLint)]),
            "GetShaderInfoLog": (None, [GLuint, GLint, C.POINTER(GLint), GLvoidp]),
            "DeleteShader": (None, [GLuint]),
            "CreateProgram": (GLuint, []),
            "AttachShader": (None, [GLuint, GLuint]),
            "LinkProgram": (None, [GLuint]),
            "GetProgramiv": (None, [GLuint, GLuint, C.POINTER(GLint)]),
            "GetProgramInfoLog": (None, [GLuint, GLint, C.POINTER(GLint), GLvoidp]),
            "DeleteProgram": (None, [GLuint]),
            "UseProgram": (None, [GLuint]),
            "GetUniformLocation": (GLint, [GLuint, GLcharp]),
            "Uniform1i": (None, [GLint, GLint]),
            "Uniform1f": (None, [GLint, GLfloat]),
            "Uniform2f": (None, [GLint, GLfloat, GLfloat]),
            "Uniform3f": (None, [GLint, GLfloat, GLfloat, GLfloat]),
            "Uniform4f": (None, [GLint, GLfloat, GLfloat, GLfloat, GLfloat]),
            "DrawArrays": (None, [GLuint, GLint, GLint]),
            "DrawBuffers": (None, [GLint, C.POINTER(GLuint)]),
            "Viewport": (None, [GLint, GLint, GLint, GLint]),
            "ClearColor": (None, [GLfloat, GLfloat, GLfloat, GLfloat]),
            "ClearBufferfv": (None, [GLuint, GLint, C.POINTER(GLfloat)]),
            "Clear": (None, [GLuint]),
            "ColorMask": (None, [C.c_ubyte] * 4),
            "BlendEquationSeparate": (None, [GLuint, GLuint]),
            "BlendFuncSeparate": (None, [GLuint, GLuint, GLuint, GLuint]),
            "ReadPixels": (None, [GLint, GLint, GLint, GLint, GLuint, GLuint, GLvoidp]),
            "PixelStorei": (None, [GLuint, GLint]),
            "Finish": (None, []),
            "GetError": (GLuint, []),
            "GenQueries": (None, [GLint, C.POINTER(GLuint)]),
            "DeleteQueries": (None, [GLint, C.POINTER(GLuint)]),
            "BeginQuery": (None, [GLuint, GLuint]),
            "EndQuery": (None, [GLuint]),
            "GetQueryObjectuiv": (None, [GLuint, GLuint, C.POINTER(GLuint)]),
        }
        for name, (result, args) in signatures.items():
            symbol = ("gl" + name).encode("ascii")
            address = self.get_proc(symbol)
            # Windows uses these sentinel addresses for unavailable functions.
            if address not in (None, 0, 1, 2, 3, C.c_void_p(-1).value):
                function = self.prototype(result, *args)(address)
            else:
                try:
                    function = getattr(self.library, "gl" + name)
                except AttributeError:
                    raise RuntimeError("The current graphics context lacks gl" + name)
                function.restype, function.argtypes = result, args
            setattr(self, name, function)
        version = self.GetString(0x1F02)
        if not version:
            raise RuntimeError("Live analysis needs a current graphics context")
        self.version = version.decode("ascii", "replace")
        self.shading_version = self.GetString(0x8B8C).decode("ascii", "replace")
        self.renderer = self.GetString(0x1F01).decode("ascii", "replace")
        self.es = "OpenGL ES" in self.version
        if self.es:
            address = self.get_proc(b"glTexStorage2D")
            if not address:
                raise RuntimeError("The current graphics context lacks glTexStorage2D")
            self.TexStorage2D = self.prototype(None, GLuint, GLint, GLuint, GLint, GLint)(address)
        major, minor = self.integer(0x821B), self.integer(0x821C)
        extensions = {
            self.GetStringi(0x1F03, i).decode("ascii") for i in range(self.integer(0x821D))
        }
        if self.es and "GL_EXT_float_blend" not in extensions:
            # ES rejects a draw with blending enabled on a 32-bit float target
            # without this extension. Avoid leaving an error in the host GL.
            raise RuntimeError(
                "SceneLight requires exact floating-point accumulation (GL_EXT_float_blend)"
            )
        self.compute_core = (major, minor) >= (3, 1) if self.es else (major, minor) >= (4, 3)
        self.compute_supported = self.compute_core or (
            not self.es
            and all(
                name in extensions
                for name in (
                    "GL_ARB_compute_shader",
                    "GL_ARB_shader_storage_buffer_object",
                    "GL_ARB_shader_image_load_store",
                )
            )
        )
        self.compute_active = False
        # These pre-GCN Windows drivers advertise compute, but atomic kernels
        # can stall indefinitely. The desktop raster path avoids those kernels.
        self.legacy_compute = (
            sys.platform == "win32"
            and not self.es
            and bool(re.search(r"\bRadeon HD [56]\d{3}", self.renderer))
        )
        if self.legacy_compute:
            self.compute_supported = False
        if self.compute_supported:
            optional = {
                "GenBuffers": (None, [GLint, C.POINTER(GLuint)]),
                "DeleteBuffers": (None, [GLint, C.POINTER(GLuint)]),
                "BufferData": (None, [GLuint, C.c_ssize_t, GLvoidp, GLuint]),
                "BindBufferBase": (None, [GLuint, GLuint, GLuint]),
                "BindImageTexture": (
                    None,
                    [GLuint, GLuint, GLint, C.c_ubyte, GLint, GLuint, GLuint],
                ),
                "DispatchCompute": (None, [GLuint, GLuint, GLuint]),
                "MemoryBarrier": (None, [GLuint]),
            }
            for name, (result, args) in optional.items():
                address = self.get_proc(("gl" + name).encode("ascii"))
                if address in (None, 0, 1, 2, 3, C.c_void_p(-1).value):
                    self.compute_supported = False
                    break
                setattr(self, name, self.prototype(result, *args)(address))

    def integer(self, name, count=1):
        values = (GLint * count)()
        self.GetIntegerv(name, values)
        return values[0] if count == 1 else tuple(values)

    def floating(self, name, count=1):
        values = (GLfloat * count)()
        self.GetFloatv(name, values)
        return values[0] if count == 1 else tuple(values)

    def indexed(self, name, index=0):
        value = GLint()
        self.GetIntegeri_v(name, index, C.byref(value))
        return value.value

    def generate(self, kind):
        value = GLuint()
        getattr(self, "Gen" + kind)(1, C.byref(value))
        return value.value

    def delete(self, kind, value):
        if value:
            number = GLuint(value)
            getattr(self, "Delete" + kind)(1, C.byref(number))


class State(object):
    """Restore the driver's state, including bindings cached internally by Ren'Py."""

    CAPS = (0x0BE2, 0x0B71, 0x0B44, 0x0C11, 0x0B90, 0x0BD0, 0x8C89)

    def __init__(self, gl):
        self.gl = gl

    def __enter__(self):
        gl = self.gl
        self.previous_compute = gl.compute_active
        self.compute_saved = None
        gl.compute_active = False
        if gl.compute_supported and gl.indexed(0x90D3) == 0 and gl.indexed(0x8F3A) == 0:
            self.compute_saved = (
                gl.integer(0x90D3),
                tuple(gl.indexed(k) for k in (0x8F3A, 0x8F3B, 0x8F3C, 0x8F3D, 0x8F3E, 0x906E)),
            )
            gl.compute_active = True
        self.values = {
            key: gl.integer(key)
            for key in (
                0x8CA6,
                0x8CAA,
                0x8B8D,
                0x85B5,
                0x84E0,
                0x80C9,
                0x80C8,
                0x80CB,
                0x80CA,
                0x8009,
                0x883D,
                0x88EF,
                0x88ED,
                0x0D05,
                0x0CF5,
            )
        }
        self.viewport = gl.integer(0x0BA2, 4)
        self.color_mask = gl.integer(0x0C23, 4)
        self.clear_color = gl.floating(0x0C22, 4)
        caps = self.CAPS + (() if gl.es else (0x8DB9, 0x8642))
        self.caps = {cap: bool(gl.IsEnabled(cap)) for cap in caps}
        self.textures = []
        self.samplers = []
        for unit in range(8):
            gl.ActiveTexture(TEXTURE0 + unit)
            self.textures.append(gl.integer(0x8069))
            self.samplers.append(gl.integer(0x8919))
            gl.BindSampler(unit, 0)
        pixel_names = (0x0D02, 0x0D03, 0x0D04, 0x0CF2, 0x0CF3, 0x0CF4)
        if not gl.es:
            pixel_names += (0x0D00, 0x0CF0)
        self.pixel_stores = {name: gl.integer(name) for name in pixel_names}
        for name in pixel_names:
            gl.PixelStorei(name, 0)
        for cap in caps:
            gl.Disable(cap)
        if not gl.es:
            gl.Enable(0x8642)
        gl.BindBuffer(0x88EB, 0)
        gl.BindBuffer(0x88EC, 0)
        gl.PixelStorei(0x0D05, 1)
        gl.PixelStorei(0x0CF5, 1)
        gl.ColorMask(True, True, True, True)
        return self

    def __exit__(self, *error):
        gl, v = self.gl, self.values
        if self.compute_saved is not None:
            generic, image = self.compute_saved
            gl.BindBufferBase(0x90D2, 0, 0)
            gl.BindBuffer(0x90D2, generic)
            gl.BindImageTexture(0, *image)
        gl.compute_active = self.previous_compute
        for unit, texture in enumerate(self.textures):
            gl.ActiveTexture(TEXTURE0 + unit)
            gl.BindTexture(TEXTURE_2D, texture)
            gl.BindSampler(unit, self.samplers[unit])
        gl.ActiveTexture(v[0x84E0])
        gl.BindFramebuffer(0x8CA9, v[0x8CA6])
        gl.BindFramebuffer(0x8CA8, v[0x8CAA])
        gl.UseProgram(v[0x8B8D])
        gl.BindVertexArray(v[0x85B5])
        gl.Viewport(*self.viewport)
        gl.ColorMask(*self.color_mask)
        gl.ClearColor(*self.clear_color)
        gl.BlendEquationSeparate(v[0x8009], v[0x883D])
        gl.BlendFuncSeparate(v[0x80C9], v[0x80C8], v[0x80CB], v[0x80CA])
        gl.BindBuffer(0x88EB, v[0x88ED])
        gl.BindBuffer(0x88EC, v[0x88EF])
        gl.PixelStorei(0x0D05, v[0x0D05])
        gl.PixelStorei(0x0CF5, v[0x0CF5])
        for name, value in self.pixel_stores.items():
            gl.PixelStorei(name, value)
        for cap, enabled in self.caps.items():
            (gl.Enable if enabled else gl.Disable)(cap)


QUAD_VERTEX = """
out vec2 uv;
void main() {
    uv = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
    gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}
"""


class ComputeUnavailable(RuntimeError):
    """Optional compute shaders cannot be compiled by this context."""


class Device(object):
    """Persistent targets and programs; no per-frame allocation or host readback."""

    def __init__(self, gl=None):
        self.gl = gl or Driver()
        self.programs, self.locations, self.targets = {}, {}, {}
        self._uniform_values = {}
        self._attachments = [None] * 4
        self._draw_count = None
        self._validated = set()
        self.buffers = {}
        self.opencl = None
        self.opencl_exceptions = ()
        self.opencl_error = None
        with State(self.gl):
            self.fbo = self.gl.generate("Framebuffers")
            self.vao = self.gl.generate("VertexArrays")
            self.query = self.gl.generate("Queries")
        try:
            self.validate()
        except Exception:
            self.close()
            raise
        if getattr(self.gl, "legacy_compute", False):
            try:
                module = sys.modules.get("_scenelight_live_opencl")
                if module is None:
                    from scenelight.runtime import live_opencl as module
                self.opencl_exceptions = (module.Unavailable,)
                self.opencl = module.Backend(self)
            except Exception as error:
                self.opencl_error = str(error)

    def validate(self):
        """Check the actual float-rendering and accumulation path once."""
        gl = self.gl
        with State(gl):
            target = self.target("capability", 8, 1)
            program = self.program(
                "capability_float",
                "out vec4 color;void main(){color=vec4(0.0000123,1.125123,-0.250123,1.0);}",
            )
            self.draw(program, target, 8, 1)
            values = (GLfloat * 32)()
            gl.ReadPixels(0, 0, 8, 1, RGBA, FLOAT, C.cast(values, GLvoidp))
            expected = (0.0000123, 1.125123, -0.250123, 1.0)
            if any(abs(values[i] - expected[i % 4]) > 1e-7 for i in range(32)):
                raise RuntimeError(
                    "SceneLight requires full-precision floating-point render targets"
                )
            sampled = self.target("capability_sampled", 8, 1)
            sample_program = self.program(
                "capability_sampled",
                "uniform sampler2D source;out vec4 color;"
                "vec4 sample_value(sampler2D image){return texelFetch(image,ivec2(gl_FragCoord.xy),0);}"
                "void main(){color=sample_value(source);}",
            )
            self.draw(sample_program, sampled, 8, 1, textures=(("source", target),))
            gl.ReadPixels(0, 0, 8, 1, RGBA, FLOAT, C.cast(values, GLvoidp))
            if any(abs(values[i] - expected[i % 4]) > 1e-7 for i in range(32)):
                raise RuntimeError(
                    "SceneLight requires full-precision floating-point texture sampling"
                )
            program = self.program(
                "capability_sum",
                "out vec4 color;void main(){color=vec4(1.0);}",
                """
                void main(){gl_Position=vec4((float(gl_VertexID%8)+0.5)/8.0*2.0-1.0,0.0,0.0,1.0);gl_PointSize=1.0;}
            """,
            )
            self.draw(program, target, 8, 1, points=8192, blend=True)
            gl.ReadPixels(0, 0, 8, 1, RGBA, FLOAT, C.cast(values, GLvoidp))
            if any(value != 1024.0 for value in values):
                raise RuntimeError("SceneLight requires exact floating-point accumulation")

    def program(self, name, fragment, vertex=QUAD_VERTEX, geometry=None):
        key = (vertex, fragment, geometry)
        if key in self.programs:
            return self.programs[key]
        gl = self.gl
        prefix = (
            "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"
            if gl.es
            else "#version 330 core\n"
        )
        shaders = []
        program = 0
        try:
            stages = ((0x8B31, vertex), (0x8B30, fragment))
            if geometry is not None:
                stages += ((0x8DD9, geometry),)
            for kind, code in stages:
                shader = gl.CreateShader(kind)
                shaders.append(shader)
                source = GLcharp((prefix + code).encode("utf-8"))
                gl.ShaderSource(shader, 1, C.byref(source), None)
                gl.CompileShader(shader)
                ok = GLint()
                gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
                if not ok.value:
                    message = C.create_string_buffer(16384)
                    gl.GetShaderInfoLog(shader, len(message), None, message)
                    raise RuntimeError(name + ": " + message.value.decode("utf-8", "replace"))
            program = gl.CreateProgram()
            for shader in shaders:
                gl.AttachShader(program, shader)
            gl.LinkProgram(program)
            ok = GLint()
            gl.GetProgramiv(program, 0x8B82, C.byref(ok))
            if not ok.value:
                message = C.create_string_buffer(16384)
                gl.GetProgramInfoLog(program, len(message), None, message)
                raise RuntimeError(name + ": " + message.value.decode("utf-8", "replace"))
            self.programs[key] = program
            return program
        except BaseException:
            if program:
                gl.DeleteProgram(program)
            raise
        finally:
            for shader in shaders:
                gl.DeleteShader(shader)

    def target(self, name, width, height, storage=RGBA32F, linear=False):
        shape = (int(width), int(height), storage, bool(linear))
        prior = self.targets.get(name)
        if prior and prior[1:] == shape:
            return prior[0]
        gl = self.gl
        if prior:
            if self.opencl is not None:
                self.opencl.release_texture(prior[0])
            gl.delete("Textures", prior[0])
            # GL can reuse a deleted numeric name. Deletion detaches the old
            # object from every FBO, even when its replacement gets that name.
            self._attachments = [
                None if value == prior[0] else value for value in self._attachments
            ]
        texture = gl.generate("Textures")
        self._validated.clear()
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, texture)
        for parameter, value in (
            (0x2800, LINEAR if linear else NEAREST),
            (0x2801, LINEAR if linear else NEAREST),
            (0x2802, 0x812F),
            (0x2803, 0x812F),
            (0x813D, 0),
        ):
            gl.TexParameteri(TEXTURE_2D, parameter, value)
        if storage == R32F:
            # Scalar fields historically replicated their value into RGBA.
            # Preserve every sampler channel while storing one 32-bit float.
            for parameter in (0x8E42, 0x8E43, 0x8E44, 0x8E45):
                gl.TexParameteri(TEXTURE_2D, parameter, 0x1903)
        if gl.es:
            # ES image load/store requires immutable texture storage.
            gl.TexStorage2D(TEXTURE_2D, 1, storage, width, height)
        else:
            gl.TexImage2D(
                TEXTURE_2D,
                0,
                storage,
                width,
                height,
                0,
                0x8227 if storage == RG32F else 0x1903 if storage == R32F else RGBA,
                FLOAT if storage in (RGBA32F, RG32F, R32F) else UNSIGNED_BYTE,
                None,
            )
        self.targets[name] = (texture,) + shape
        return texture

    def uniform(self, program, name, value, integer=False):
        key = (program, name)
        location = self.locations.get(key)
        if location is None:
            location = self.gl.GetUniformLocation(program, name.encode("ascii"))
            self.locations[key] = location
        if location < 0:
            return
        normalized = (bool(integer), tuple(value) if isinstance(value, (tuple, list)) else value)
        if self._uniform_values.get(key) == normalized:
            return
        if integer:
            self.gl.Uniform1i(location, value)
        elif isinstance(value, (tuple, list)):
            getattr(self.gl, "Uniform%df" % len(value))(location, *value)
        else:
            self.gl.Uniform1f(location, value)
        self._uniform_values[key] = normalized

    def bind_targets(self, targets):
        gl = self.gl
        gl.BindFramebuffer(FRAMEBUFFER, self.fbo)
        for index in range(4):
            texture = targets[index] if index < len(targets) else 0
            if self._attachments[index] != texture:
                gl.FramebufferTexture2D(
                    FRAMEBUFFER, COLOR_ATTACHMENT0 + index, TEXTURE_2D, texture, 0
                )
                self._attachments[index] = texture
        if self._draw_count != len(targets):
            gl.DrawBuffers(
                len(targets),
                (GLuint * len(targets))(*[COLOR_ATTACHMENT0 + i for i in range(len(targets))]),
            )
            self._draw_count = len(targets)

    def draw(
        self,
        program,
        target,
        width,
        height,
        textures=(),
        uniforms=(),
        points=None,
        blend=False,
        extra_targets=(),
    ):
        gl = self.gl
        self.bind_targets((target,) + tuple(extra_targets))
        attachments = tuple(self._attachments)
        if attachments not in self._validated:
            if gl.CheckFramebufferStatus(FRAMEBUFFER) != FRAMEBUFFER_COMPLETE:
                raise RuntimeError("This renderer cannot draw the requested analysis texture")
            self._validated.add(attachments)
        gl.Viewport(0, 0, width, height)
        gl.BindVertexArray(self.vao)
        gl.UseProgram(program)
        for unit, (name, texture) in enumerate(textures):
            gl.ActiveTexture(TEXTURE0 + unit)
            gl.BindTexture(TEXTURE_2D, texture)
            self.uniform(program, name, unit, integer=True)
        for name, value in uniforms:
            self.uniform(program, name, value)
        if blend:
            clear = 1e30 if blend == "min" else 0.0
            for index in range(1 + len(extra_targets)):
                gl.ClearBufferfv(0x1800, index, (GLfloat * 4)(clear, clear, clear, clear))
            gl.Enable(0x0BE2)
            equation = 0x8007 if blend == "min" else 0x8006
            gl.BlendEquationSeparate(equation, equation)
            gl.BlendFuncSeparate(1, 1, 1, 1)
        else:
            gl.Disable(0x0BE2)
        gl.DrawArrays(0 if points is not None else 5, 0, points if points is not None else 4)

    def close(self):
        gl = self.gl
        if self.opencl is not None:
            self.opencl.close()
            self.opencl = None
        with State(gl):
            for texture in self.targets.values():
                gl.delete("Textures", texture[0])
            for program in self.programs.values():
                gl.DeleteProgram(program)
            gl.delete("Framebuffers", self.fbo)
            gl.delete("VertexArrays", self.vao)
            gl.delete("Queries", self.query)
            for buffer, _size in self.buffers.values():
                gl.delete("Buffers", buffer)
        self.targets.clear()
        self.programs.clear()
        self.locations.clear()
        self._uniform_values.clear()
        self.buffers.clear()
        self.fbo = self.vao = self.query = 0

    def compute_program(self, name, code):
        key = ("compute", code)
        if key in self.programs:
            return self.programs[key]
        gl = self.gl
        if gl.es:
            prefix = (
                "#version 310 es\nprecision highp float;\nprecision highp int;\n"
                "precision highp sampler2D;\nprecision highp image2D;\n"
            )
        elif gl.compute_core or gl.shading_version.startswith(("4.3", "4.4", "4.5", "4.6")):
            prefix = "#version 430 core\n"
        else:
            prefix = "#version 330 core\n#extension GL_ARB_compute_shader : require\n#extension GL_ARB_shader_storage_buffer_object : require\n#extension GL_ARB_shader_image_load_store : require\n"
        # ES requires an image binding in the declaration. Older desktop GLSL
        # uses the default unit zero without requiring the 420pack extension.
        prefix += "#define sl_binding_zero " + ("binding=0," if gl.es else "") + "\n"
        shader = gl.CreateShader(0x91B9)
        program = 0
        try:
            source = GLcharp((prefix + code).encode("utf-8"))
            gl.ShaderSource(shader, 1, C.byref(source), None)
            gl.CompileShader(shader)
            ok = GLint()
            gl.GetShaderiv(shader, 0x8B81, C.byref(ok))
            if not ok.value:
                message = C.create_string_buffer(16384)
                gl.GetShaderInfoLog(shader, len(message), None, message)
                raise ComputeUnavailable(name + ": " + message.value.decode("utf-8", "replace"))
            program = gl.CreateProgram()
            gl.AttachShader(program, shader)
            gl.LinkProgram(program)
            gl.GetProgramiv(program, 0x8B82, C.byref(ok))
            if not ok.value:
                raise ComputeUnavailable(name + ": compute program did not link")
            self.programs[key] = program
            return program
        except BaseException:
            if program:
                gl.DeleteProgram(program)
            raise
        finally:
            gl.DeleteShader(shader)


COMMON = """
uniform sampler2D t0;
uniform sampler2D t1;
uniform sampler2D t2;
uniform sampler2D t3;
uniform sampler2D t4;
uniform sampler2D t5;
uniform sampler2D t6;
uniform sampler2D t7;
in vec2 uv;
out vec4 color;
const float EPS = 0.000001;
vec3 linear_rgb(vec3 c) {
    return mix(c/12.92, pow((c+0.055)/1.055, vec3(2.4)), step(vec3(0.04045),c));
}
vec3 display_rgb(vec3 c) {
    return mix(c*12.92, 1.055*pow(max(c,vec3(0.0)), vec3(1.0/2.4))-0.055,
               step(vec3(0.0031308), c));
}
float luma(vec3 c) { return dot(c,vec3(0.2126,0.7152,0.0722)); }
float reflect_index(float p, float n) {
    if(n<=1.0) return 0.0;
    float x=mod(p,2.0*(n-1.0));
    return min(x,2.0*(n-1.0)-x);
}
vec4 reflected(sampler2D source, ivec2 p) {
    ivec2 n=textureSize(source,0);
    return texelFetch(source,ivec2(reflect_index(float(p.x),float(n.x)),
                                  reflect_index(float(p.y),float(n.y))),0);
}
vec3 chroma(vec3 c, float maximum) {
    return clamp(c/(luma(c)+EPS),vec3(0.45),vec3(maximum));
}
vec3 display_chroma(vec3 c) {
    return clamp(display_rgb(clamp(c/(luma(c)+EPS),vec3(0.45),vec3(2.4))*0.5),0.0,1.0);
}
vec4 q8(vec4 v) {
    vec4 scaled=clamp(v,0.0,1.0)*255.0, integral=floor(scaled);
    return mix(floor(scaled+0.5),integral+mod(integral,2.0),vec4(equal(scaled-integral,vec4(0.5))))/255.0;
}
"""

LANCZOS = (
    COMMON
    + """
uniform vec2 output_size;
uniform float axis;
uniform float make_linear;
float sinc(float x) { return abs(x)<0.000001 ? 1.0 : sin(3.141592653589793*x)/(3.141592653589793*x); }
void main() {
    ivec2 p=ivec2(gl_FragCoord.xy);
    ivec2 input_size=textureSize(t0,0);
    float input_length=axis<0.5 ? float(input_size.x) : float(input_size.y);
    float output_length=axis<0.5 ? output_size.x : output_size.y;
    float center=((axis<0.5 ? float(p.x) : float(p.y))+0.5)*input_length/output_length;
    float scale=max(input_length/output_length,1.0);
    int first=max(0,int(center-scale*3.0+0.5));
    int last=min(int(input_length),int(center+scale*3.0+0.5));
    vec4 total=vec4(0.0); float weight_sum=0.0;
    for(int i=first;i<last;i++) {
        float distance=(float(i)-center+0.5)/scale;
        float weight=abs(distance)<3.0 ? sinc(distance)*sinc(distance/3.0) : 0.0;
        total+=texelFetch(t0,axis<0.5 ? ivec2(i,p.y) : ivec2(p.x,i),0)*weight;
        weight_sum+=weight;
    }
    color=floor(clamp(total/max(weight_sum,EPS),0.0,1.0)*255.0+0.5)/255.0;
    if(make_linear>0.5) {
        vec3 c=linear_rgb(color.rgb);
        color=vec4(c,luma(c));
    }
}
"""
)

AREA = (
    COMMON
    + """
uniform vec2 output_size;
uniform float axis;
uniform float make_linear;
void main() {
    ivec2 p=ivec2(gl_FragCoord.xy);
    ivec2 n=textureSize(t0,0);
    float scale=(axis<0.5 ? float(n.x)/output_size.x : float(n.y)/output_size.y);
    float first=(axis<0.5 ? float(p.x) : float(p.y))*scale;
    float last=first+scale;
    vec4 total=vec4(0.0);
    for(int i=int(floor(first));i<int(ceil(last));i++) {
        float weight=max(0.0,min(float(i+1),last)-max(float(i),first));
        total+=texelFetch(t0,axis<0.5 ? ivec2(i,p.y) : ivec2(p.x,i),0)*weight;
    }
    color=total/scale;
    if(make_linear>0.5) {
        vec3 c=linear_rgb(color.rgb);
        color=vec4(c,luma(c));
    }
}
"""
)

REDUCE = (
    COMMON
    + """
uniform float operation;
void main() {
    ivec2 origin=ivec2(gl_FragCoord.xy)*4;
    ivec2 size=textureSize(t0,0);
    vec4 result=vec4(operation>1.5 ? 1e30 : 0.0);
    for(int y=0;y<4;y++) for(int x=0;x<4;x++) {
        ivec2 p=origin+ivec2(x,y);
        if(p.x>=size.x || p.y>=size.y) continue;
        vec4 v=texelFetch(t0,p,0);
        if(operation<0.5) result+=v;
        else if(operation<1.5) result=max(result,v);
        else result=min(result,v);
    }
    color=result;
}
"""
)


AREA_UPSCALE = (
    COMMON
    + """
uniform vec2 output_size;
uniform float axis;
uniform float make_linear;
void main(){
    ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);
    vec2 geometry=texelFetch(t1,ivec2(axis<0.5 ? p.x : p.y,0),0).rg;
    int first=int(geometry.r);
    float fraction=geometry.g;
    ivec2 a=axis<0.5 ? ivec2(first,p.y) : ivec2(p.x,first);
    ivec2 b=a+(axis<0.5 ? ivec2(1,0) : ivec2(0,1));
    color=mix(texelFetch(t0,clamp(a,ivec2(0),size-1),0),texelFetch(t0,clamp(b,ivec2(0),size-1),0),fraction);
    if(make_linear>0.5){vec3 c=linear_rgb(color.rgb);color=vec4(c,luma(c));}
}
"""
)

HISTOGRAM_VERTEX = """
uniform sampler2D t0;
uniform sampler2D t1;
uniform sampler2D t2;
uniform float channel;
uniform float fine;
uniform float positive;
uniform float unit_range;
void main() {
    ivec2 size=textureSize(t0,0);
    ivec2 p=ivec2(gl_VertexID % size.x,gl_VertexID / size.x);
    float value=texelFetch(t0,p,0)[int(channel)];
    float maximum=unit_range>0.5 ? 1.0 : texelFetch(t2,ivec2(0),0)[int(channel)];
    float scaled=clamp(value/max(maximum,1e-20),0.0,1.0)*1024.0;
    int coarse_bin=min(int(scaled),1023);
    int bin=coarse_bin;
    int row=0;
    bool valid=positive<0.5 || value>0.000001;
    if(fine>0.5) {
        row=-1;
        for(int i=0;i<8;i++) {
            if(row<0 && int(texelFetch(t1,ivec2(i,0),0).r)==coarse_bin) row=i;
        }
        valid=valid && row>=0;
        bin=min(int((scaled-float(coarse_bin))*1024.0),1023);
    }
    gl_Position=valid ? vec4((float(bin)+0.5)/1024.0*2.0-1.0,
        (float(row)+0.5)/(fine>0.5 ? 8.0 : 1.0)*2.0-1.0,0.0,1.0) : vec4(3.0,3.0,0.0,1.0);
    gl_PointSize=1.0;
}
"""

HISTOGRAM_FRAGMENT = "out vec4 color; void main() { color=vec4(1.0,0.0,0.0,0.0); }"

QUANTILE_COARSE = (
    COMMON
    + """
uniform vec4 quantiles;
void main() {
    int index=int(gl_FragCoord.x);
    float count=0.0;
    for(int bin=0;bin<1024;bin++) count+=texelFetch(t0,ivec2(bin,0),0).r;
    float position=max(count-1.0,0.0)*quantiles[index/2];
    float rank=index%2==0 ? floor(position) : ceil(position);
    float cumulative=0.0;
    int chosen=1023;
    float local_rank=0.0;
    for(int bin=0;bin<1024;bin++) {
        float n=texelFetch(t0,ivec2(bin,0),0).r;
        if(cumulative+n>rank) { chosen=bin; local_rank=rank-cumulative; break; }
        cumulative+=n;
    }
    color=vec4(float(chosen),local_rank,count,fract(position));
}
"""
)

QUANTILE_FINE = (
    COMMON
    + """
uniform float channel;
uniform float unit_range;
float selected(int index) {
    vec4 info=texelFetch(t1,ivec2(index,0),0);
    if(info.b<0.5) return 0.0;
    int row=index;
    for(int i=0;i<8;i++) {
        if(i<row && texelFetch(t1,ivec2(i,0),0).r==info.r) row=i;
    }
    float cumulative=0.0;
    int chosen=1023;
    for(int bin=0;bin<1024;bin++) {
        cumulative+=texelFetch(t0,ivec2(bin,row),0).r;
        if(cumulative>info.g) { chosen=bin; break; }
    }
    float maximum=unit_range>0.5 ? 1.0 : texelFetch(t2,ivec2(0),0)[int(channel)];
    return min((info.r*1024.0+float(chosen)+0.5)/1048576.0,1.0)*maximum;
}
void main() {
    int index=int(gl_FragCoord.x)*2;
    vec4 info=texelFetch(t1,ivec2(index,0),0);
    color=vec4(mix(selected(index),selected(index+1),info.a), info.b, 0.0, 1.0);
}
"""
)


class Analysis(object):
    """Reference-model scene passes evaluated from the current background texture."""

    def __init__(self, device=None):
        self.device = device or Device()
        self.width = self.height = 0
        self.fields = {}
        self._fft_kernels = {}
        self._twiddles = {}
        self._probe_shape = None
        self._annular_ready = False
        self._label_iterations = {}
        self._area_tables = {}
        self._meter_shape = None
        self._meter_basis = None

    def run(
        self, name, source, width, height, inputs=(), uniforms=(), storage=RGBA32F, linear=False
    ):
        device = self.device
        program = device.program(name, source)
        target = device.target(name, width, height, storage, linear)
        device.draw(
            program,
            target,
            width,
            height,
            tuple(("t%d" % index, texture) for index, texture in enumerate(inputs)),
            uniforms,
        )
        self.fields[name] = (target, width, height)
        return target

    def resize(self, name, texture, source_size, target_size, linear=False, area=False):
        width, height = target_size
        shader = AREA if area else LANCZOS
        if area and (width > source_size[0] or height > source_size[1]):
            # OpenCV's INTER_AREA switches both axes to its two-tap area
            # emulation when either axis enlarges (including mixed scaling).
            shader = AREA_UPSCALE
        x_inputs = (
            (texture, self.area_geometry(source_size[0], width))
            if shader is AREA_UPSCALE
            else (texture,)
        )
        first = self.run(
            name + "_x",
            shader,
            width,
            source_size[1],
            x_inputs,
            (("output_size", (width, source_size[1])), ("axis", 0.0), ("make_linear", 0.0)),
        )
        return self.run(
            name,
            shader,
            width,
            height,
            (first, self.area_geometry(source_size[1], height))
            if shader is AREA_UPSCALE
            else (first,),
            (("output_size", (width, height)), ("axis", 1.0), ("make_linear", float(linear))),
        )

    def area_geometry(self, source, target):
        """Match OpenCV's double-precision area-emulation coordinate table.

        Its reciprocal scale and float-cast fractional part matter at exact
        pixel boundaries. Geometry is computed only when dimensions change;
        every frame's pixels remain on the graphics device.
        """
        key = (source, target)
        if key in self._area_tables:
            return self._area_tables[key]
        inverse = float(target) / source
        scale = 1.0 / inverse
        values = []
        for coordinate in range(target):
            first = int(math.floor(coordinate * scale))
            fraction = C.c_float(coordinate + 1 - (first + 1) * inverse).value
            fraction = max(0.0, fraction)
            fraction -= math.floor(fraction)
            coefficient = fraction * 2048.0
            base = math.floor(coefficient)
            rounded = base + (
                int(base) % 2 if coefficient - base == 0.5 else int(coefficient - base > 0.5)
            )
            values.extend((first, rounded / 2048.0, 0.0, 1.0))
        texture = self.device.target("area_geometry_%d_%d" % key, target, 1)
        array = (GLfloat * len(values))(*values)
        gl = self.device.gl
        gl.BindTexture(TEXTURE_2D, texture)
        gl.TexSubImage2D(TEXTURE_2D, 0, 0, 0, target, 1, RGBA, FLOAT, C.cast(array, GLvoidp))
        self._area_tables[key] = texture
        return texture

    def reduce(self, name, texture, size, operation=0.0):
        width, height = size
        index = 0
        while width > 1 or height > 1:
            width, height = (width + 3) // 4, (height + 3) // 4
            texture = self.run(
                name + "_%d" % index, REDUCE, width, height, (texture,), (("operation", operation),)
            )
            index += 1
        return texture

    def quantiles(self, name, texture, size, channel, values, positive=False, unit_range=False):
        device = self.device
        maximum = self.reduce(name + "_max", texture, size, 1.0) if not unit_range else texture
        if device.opencl is not None:
            target = device.opencl.quantiles(
                name, texture, maximum, size, channel, values, positive, unit_range
            )
            self.fields[name] = (target, len(values), 1)
            return target
        shader = device.program("histogram", HISTOGRAM_FRAGMENT, HISTOGRAM_VERTEX)
        coarse = device.target(name + "_hist", 1024, 1)
        common = (
            ("channel", float(channel)),
            ("positive", float(positive)),
            ("unit_range", float(unit_range)),
        )
        if device.gl.compute_active:
            self.compute_histogram(coarse, texture, size, maximum, texture, common, False)
        else:
            device.draw(
                shader,
                coarse,
                1024,
                1,
                (("t0", texture), ("t2", maximum)),
                common + (("fine", 0.0),),
                points=size[0] * size[1],
                blend=True,
            )
        if device.gl.compute_active:
            parameters = self.compute_quantile_parameters(name + "_coarse", coarse, 1, values)
        else:
            parameters = self.run(
                name + "_coarse", QUANTILE_COARSE, 8, 1, (coarse,), (("quantiles", values),)
            )
        fine = device.target(name + "_fine_hist", 1024, 8)
        if device.gl.compute_active:
            self.compute_histogram(fine, texture, size, maximum, parameters, common, True)
        else:
            device.draw(
                shader,
                fine,
                1024,
                8,
                (("t0", texture), ("t1", parameters), ("t2", maximum)),
                common + (("fine", 1.0),),
                points=size[0] * size[1],
                blend=True,
            )
        if device.gl.compute_active:
            selected = self.compute_quantile_values(name + "_values", fine, parameters, 1, 8)
            return self.run(
                name,
                COMMON
                + """
                uniform float channel; uniform float unit_range;
                void main(){int index=int(gl_FragCoord.x)*2;
                    vec4 info=texelFetch(t1,ivec2(index,0),0);
                    float maximum=unit_range>0.5 ? 1.0 : texelFetch(t2,ivec2(0),0)[int(channel)];
                    float a=texelFetch(t0,ivec2(index,0),0).r*maximum;
                    float b=texelFetch(t0,ivec2(index+1,0),0).r*maximum;
                    color=vec4(mix(a,b,info.a),info.b,0.0,1.0);}
                """,
                4,
                1,
                (selected, parameters, maximum),
                common,
            )
        return self.run(name, QUANTILE_FINE, 4, 1, (fine, parameters, maximum), common)

    def compute_quantile_parameters(self, name, histogram, groups, quantiles):
        """Select exact histogram ranks with a parallel integer prefix sum."""
        device, gl = self.device, self.device.gl
        ranks = len(quantiles) * 2
        target = device.target(name, groups * ranks, 1)
        program = device.compute_program(
            "quantile_parameters",
            self._quantile_prefix_shader()
            + """
            uniform vec4 quantiles; uniform int ranks;
            void main(){
                uint group=gl_WorkGroupID.x,thread=gl_LocalInvocationID.x;
                prefix(int(group));
                uint count=blocks[127],before=thread==0u ? 0u : blocks[thread-1u];
                for(int k=0;k<ranks;k++){
                    float position=max(float(count)-1.0,0.0)*quantiles[k/2];
                    uint rank=uint(k%2==0 ? floor(position) : ceil(position));
                    if(count==0u){
                        if(thread==0u)imageStore(destination,ivec2(int(group)*ranks+k,0),vec4(1023.0,0.0,0.0,fract(position)));
                    }else if(before<=rank && blocks[thread]>rank){
                        uint cumulative=before;
                        for(uint i=0u;i<8u;i++){
                            uint n=values[i];
                            if(cumulative+n>rank){
                                imageStore(destination,ivec2(int(group)*ranks+k,0),vec4(float(thread*8u+i),float(rank-cumulative),float(count),fract(position)));
                                break;
                            }
                            cumulative+=n;
                        }
                    }
                }
            }
            """,
        )
        gl.UseProgram(program)
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, histogram)
        device.uniform(program, "histogram", 0, integer=True)
        device.uniform(program, "quantiles", tuple(quantiles) + (0.0,) * (4 - len(quantiles)))
        device.uniform(program, "ranks", ranks, integer=True)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
        gl.DispatchCompute(groups, 1, 1)
        gl.MemoryBarrier(0x2428)
        return target

    @staticmethod
    def _quantile_prefix_shader():
        return """
            layout(local_size_x=128) in;
            uniform sampler2D histogram;
            layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
            shared uint blocks[128];
            uint values[8];
            void prefix(int row){
                uint thread=gl_LocalInvocationID.x,total=0u;
                for(uint i=0u;i<8u;i++){
                    values[i]=uint(texelFetch(histogram,ivec2(int(thread*8u+i),row),0).r);
                    total+=values[i];
                }
                blocks[thread]=total;barrier();
                for(uint offset=1u;offset<128u;offset*=2u){
                    uint preceding=thread>=offset ? blocks[thread-offset] : 0u;
                    barrier();blocks[thread]+=preceding;barrier();
                }
            }
        """

    def compute_quantile_values(self, name, histogram, parameters, groups, ranks):
        device, gl = self.device, self.device.gl
        target = device.target(name, groups * ranks, 1)
        program = device.compute_program(
            "quantile_values",
            self._quantile_prefix_shader()
            + """
            uniform sampler2D parameters; uniform int ranks;
            void main(){
                int index=int(gl_WorkGroupID.x),row=index;
                uint thread=gl_LocalInvocationID.x;
                vec4 info=texelFetch(parameters,ivec2(index,0),0);
                if(info.b<0.5){
                    if(thread==0u)imageStore(destination,ivec2(index,0),vec4(0.0));return;
                }
                for(int i=0;i<ranks;i++){
                    int other=index/ranks*ranks+i;
                    if(other<row && texelFetch(parameters,ivec2(other,0),0).r==info.r)row=other;
                }
                prefix(row);
                uint rank=uint(info.g),before=thread==0u ? 0u : blocks[thread-1u];
                if(before<=rank && blocks[thread]>rank){
                    uint cumulative=before;
                    for(uint i=0u;i<8u;i++){
                        cumulative+=values[i];
                        if(cumulative>rank){
                            float chosen=float(thread*8u+i);
                            float value=min((info.r*1024.0+chosen+0.5)/1048576.0,1.0);
                            imageStore(destination,ivec2(index,0),vec4(value));break;
                        }
                    }
                }
            }
            """,
        )
        gl.UseProgram(program)
        for index, (uniform, texture) in enumerate(
            (("histogram", histogram), ("parameters", parameters))
        ):
            gl.ActiveTexture(TEXTURE0 + index)
            gl.BindTexture(TEXTURE_2D, texture)
            device.uniform(program, uniform, index, integer=True)
        device.uniform(program, "ranks", ranks, integer=True)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
        gl.DispatchCompute(groups * ranks, 1, 1)
        gl.MemoryBarrier(0x2428)
        return target

    def compute_histogram(self, target, source, size, maximum, parameters, common, fine):
        """Count the same radix bins without serializing point blending.

        Each workgroup combines 512 samples in a 4 KiB shared histogram.
        Integer counts are exact at the analyzer's maximum image size. Fine
        rows retain the raster path's first-matching-coarse-bin ownership.
        """
        device, gl = self.device, self.device.gl
        key = "quantile_histogram"
        previous = device.buffers.get(key)
        if previous is None:
            buffer = gl.generate("Buffers")
            gl.BindBuffer(0x90D2, buffer)
            gl.BufferData(0x90D2, 8192 * 4, None, 0x88E8)
            device.buffers[key] = (buffer, 8192 * 4)
        else:
            buffer = previous[0]
        gl.BindBufferBase(0x90D2, 0, buffer)
        header = """
            layout(local_size_x=128) in;
            layout(sl_binding_zero std430) buffer Histogram { uint bins[]; };
        """
        clear = device.compute_program(
            "clear_quantile_histogram", header + "void main(){bins[gl_GlobalInvocationID.x]=0u;}"
        )
        gl.UseProgram(clear)
        rows = 8 if fine else 1
        gl.DispatchCompute(rows * 8, 1, 1)
        gl.MemoryBarrier(0x2000)
        program = device.compute_program(
            "quantile_histogram",
            header
            + """
            uniform sampler2D t0; uniform sampler2D t1; uniform sampler2D t2;
            uniform float channel; uniform float positive; uniform float unit_range;
            uniform float fine;
            shared uint local_bins[1024];
            void main(){
                uint row=gl_WorkGroupID.z,thread=gl_LocalInvocationID.x;
                int chosen=fine>0.5 ? int(texelFetch(t1,ivec2(row,0),0).r) : 0;
                if(fine>0.5)for(uint prior=0u;prior<row;prior++)
                    if(int(texelFetch(t1,ivec2(prior,0),0).r)==chosen)return;
                for(uint bin=thread;bin<1024u;bin+=128u)local_bins[bin]=0u;
                barrier();
                ivec2 size=textureSize(t0,0);
                float maximum=unit_range>0.5 ? 1.0 : texelFetch(t2,ivec2(0),0)[int(channel)];
                for(uint sample_index=0u;sample_index<4u;sample_index++){
                    uint index=gl_WorkGroupID.x*512u+thread+sample_index*128u;
                    if(index>=uint(size.x*size.y))continue;
                    float value=texelFetch(t0,ivec2(int(index)%size.x,int(index)/size.x),0)[int(channel)];
                    if(positive>0.5 && value<=0.000001)continue;
                    float scaled=clamp(value/max(maximum,1e-20),0.0,1.0)*1024.0;
                    int coarse_bin=min(int(scaled),1023),bin=coarse_bin;
                    if(fine>0.5){
                        if(coarse_bin!=chosen)continue;
                        bin=min(int((scaled-float(coarse_bin))*1024.0),1023);
                    }
                    atomicAdd(local_bins[bin],1u);
                }
                barrier();
                for(uint bin=thread;bin<1024u;bin+=128u){
                    uint count=local_bins[bin];
                    if(count>0u)atomicAdd(bins[row*1024u+bin],count);
                }
            }
            """,
        )
        gl.UseProgram(program)
        for index, texture in enumerate((source, parameters, maximum)):
            gl.ActiveTexture(TEXTURE0 + index)
            gl.BindTexture(TEXTURE_2D, texture)
            device.uniform(program, "t%d" % index, index, integer=True)
        for name, value in common + (("fine", float(fine)),):
            device.uniform(program, name, value)
        gl.DispatchCompute((size[0] * size[1] + 511) // 512, 1, rows)
        gl.MemoryBarrier(0x2000)
        copy = device.compute_program(
            "copy_quantile_histogram",
            header
            + """
            layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
            void main(){uint i=gl_GlobalInvocationID.x;
                imageStore(destination,ivec2(int(i)%1024,int(i)/1024),vec4(float(bins[i]),0.0,0.0,0.0));}
            """,
        )
        gl.UseProgram(copy)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
        gl.DispatchCompute(rows * 8, 1, 1)
        gl.MemoryBarrier(0x2428)

    def gaussian(self, name, texture, size, sigma, channel=-1, scalar=False):
        if sigma > 8.0 and channel in (-1, 0):
            return self.gaussian_fft(name, texture, size, sigma)
        # OpenCV's automatically-sized CV_32F kernel uses four standard
        # deviations. Values are calculated once; every frame reuses the program.
        radius = int(round(sigma * 8.0 + 1.0)) // 2
        weights = [math.exp(-0.5 * (offset / sigma) ** 2) for offset in range(-radius, radius + 1)]
        denominator = sum(weights)
        weights = [value / denominator for value in weights]
        scalar_output = scalar or channel >= 0
        for axis in (0, 1):
            terms = []
            for offset, weight in zip(range(-radius, radius + 1), weights):
                sample = "reflected(t0,p+ivec2(%d,%d))" % (
                    offset if axis == 0 else 0,
                    offset if axis == 1 else 0,
                )
                if scalar_output:
                    sample += "." + "rgba"[max(channel, 0)]
                terms.append("total+=%s*%.12g;" % (sample, weight))
            shader = (
                COMMON
                + "void main(){ ivec2 p=ivec2(gl_FragCoord.xy);"
                + ("float total=0.0;" if scalar_output else "vec4 total=vec4(0.0);")
                + "\n".join(terms)
                + ("color=vec4(total);}" if scalar_output else "color=total;}")
            )
            texture = self.run(
                name + "_%d" % axis,
                shader,
                size[0],
                size[1],
                (texture,),
                storage=R32F if scalar or channel >= 0 else RGBA32F,
            )
        return texture

    def prepare(self, texture, source_size):
        scale = min(640.0 / max(source_size), 1.0)
        width = max(1, int(round(source_size[0] * scale)))
        height = max(1, int(round(source_size[1] * scale)))
        self.width, self.height = width, height
        size = (width, height)
        linear = self.resize("linear", texture, source_size, size, True, area=True)
        quantiles = self.quantiles(
            "luma_quantiles", linear, size, 3, (0.995, 0.86, 0.97, 0.55), unit_range=True
        )
        clipped = self.run(
            "clipped",
            COMMON
            + """
            void main() { color=vec4(min(texelFetch(t0,ivec2(gl_FragCoord.xy),0).a,
                                         texelFetch(t1,ivec2(0),0).r)); }
        """,
            width,
            height,
            (linear, quantiles),
            storage=R32F,
        )
        blur_radius = max(9, (min(height, width) // 18) | 1)
        local_base = self.gaussian(
            "local_base", clipped, size, max(3.0, blur_radius / 3.0), scalar=True
        )
        saliency = self.run(
            "saliency_raw",
            COMMON
            + """
            void main() {
                ivec2 p=ivec2(gl_FragCoord.xy);
                float v=texelFetch(t0,p,0).r;
                float residual=max(v-texelFetch(t1,p,0).r,0.0);
                float bright=max(v-texelFetch(t2,ivec2(1,0),0).r,0.0);
                color=vec4(residual*1.4+bright*0.7);
            }
        """,
            width,
            height,
            (clipped, local_base, quantiles),
            storage=R32F,
        )
        saliency = self.gaussian(
            "saliency", saliency, size, max(1.2, min(height, width) / 180.0), scalar=True
        )
        threshold = self.quantiles(
            "saliency_quantiles", saliency, size, 0, (0.86, 0.86, 0.86, 0.86)
        )
        weights = self.run(
            "source_weights",
            COMMON
            + """
            void main() { color=vec4(pow(max(texelFetch(t0,ivec2(gl_FragCoord.xy),0).r
                -texelFetch(t1,ivec2(0),0).r,0.0),1.25)); }
        """,
            width,
            height,
            (saliency, threshold),
            storage=R32F,
        )
        residual = self.gaussian("texture_blur", linear, size, 1.2, 3)
        residual = self.run(
            "texture_residual",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                color=vec4(abs(texelFetch(t0,p,0).a-texelFetch(t1,p,0).r)); }
        """,
            width,
            height,
            (linear, residual),
            storage=R32F,
        )
        return {
            "linear": linear,
            "clipped": clipped,
            "source_weights": weights,
            "texture_residual": residual,
            "quantiles": quantiles,
        }

    def read_scalar(self, texture, channel=0):
        """Read a convergence/control scalar; no image analysis is performed on CPU."""
        gl = self.device.gl
        self.device.bind_targets((texture,))
        result = (GLfloat * 4)()
        gl.ReadPixels(0, 0, 1, 1, RGBA, FLOAT, C.cast(result, GLvoidp))
        return result[channel]

    def control_flag(self, texture, channel=0):
        # Occlusion query results avoid staging a floating-point framebuffer
        # through the driver's image-readback path for a one-bit decision.
        device = self.device
        gl = device.gl
        program = device.program(
            "control_flag",
            COMMON
            + """
            uniform float channel;
            void main(){if(texelFetch(t0,ivec2(0),0)[int(channel)]<0.5) discard; color=vec4(1.0);}
        """,
        )
        target = device.target("control_flag", 1, 1, RGBA8)
        gl.BeginQuery(0x8C2F, device.query)
        try:
            device.draw(program, target, 1, 1, (("t0", texture),), (("channel", float(channel)),))
        finally:
            gl.EndQuery(0x8C2F)
        result = GLuint()
        gl.GetQueryObjectuiv(device.query, 0x8866, C.byref(result))
        return bool(result.value)

    def copy_scalar(self, destination, index, source):
        gl = self.device.gl
        self.device.bind_targets((source,))
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, destination)
        gl.CopyTexSubImage2D(TEXTURE_2D, 0, index, 0, 0, 0, 1, 1)

    def component_labels(self, name, weights):
        width, height = self.width, self.height
        size = (width, height)
        cut = self.quantiles(
            name + "_cut", weights, size, 0, (0.16, 0.16, 0.16, 0.16), positive=True
        )
        maximum = self.reduce(name + "_max", weights, size, 1.0)
        mask = self.run(
            name + "_binary",
            COMMON
            + """
            void main() {
                float peak=texelFetch(t2,ivec2(0),0).r;
                float cutoff=max(peak*0.035,texelFetch(t1,ivec2(0),0).r);
                color=vec4(peak>EPS && texelFetch(t0,ivec2(gl_FragCoord.xy),0).r>=cutoff ? 1.0 : 0.0);
            }
        """,
            width,
            height,
            (weights, cut, maximum),
        )
        for dilation in (True, False):
            body = """
                void main() {
                    ivec2 p=ivec2(gl_FragCoord.xy), size=textureSize(t0,0);
                    float result=INITIAL;
                    for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
                        ivec2 q=p+ivec2(x,y);
                        if(q.x<0 || q.y<0 || q.x>=size.x || q.y>=size.y) continue;
                        result=OPERATION(result,texelFetch(t0,q,0).r);
                    }
                    color=vec4(result);
                }
            """.replace("INITIAL", "0.0" if dilation else "1.0").replace(
                "OPERATION", "max" if dilation else "min"
            )
            mask = self.run(
                name + ("_dilated" if dilation else "_closed"),
                COMMON + body,
                width,
                height,
                (mask,),
            )
        if self.device.opencl is not None or self.device.gl.compute_active:
            labels = (
                self.device.opencl.labels(name, mask, size)
                if self.device.opencl is not None
                else self.compute_labels(name, mask)
            )
            self.fields[name + "_labels"] = (labels, width, height)
            self.fields[name + "_iterations"] = 0
            return labels
        labels = self.run(
            name + "_initial",
            COMMON
            + """
            void main() {
                ivec2 p=ivec2(gl_FragCoord.xy), size=textureSize(t0,0);
                float id=texelFetch(t0,p,0).r>0.5 ? float(p.y*size.x+p.x+1) : 0.0;
                color=vec4(id,1.0,0.0,1.0);
            }
        """,
            width,
            height,
            (mask,),
        )
        propagation = (
            COMMON
            + """
            void main() {
                ivec2 p=ivec2(gl_FragCoord.xy), size=textureSize(t0,0);
                float initial=texelFetch(t0,p,0).r;
                if(initial<0.5) { color=vec4(0.0); return; }
                float best=initial;
                for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
                    ivec2 q=p+ivec2(x,y);
                    if(q.x<0 || q.y<0 || q.x>=size.x || q.y>=size.y) continue;
                    float neighbor=texelFetch(t0,q,0).r;
                    if(neighbor>0.0) best=min(best,neighbor);
                }
                int root=int(best)-1;
                best=min(best,texelFetch(t0,ivec2(root%size.x,root/size.x),0).r);
                color=vec4(best,best!=initial ? 1.0 : 0.0,0.0,1.0);
            }
        """
        )
        iterations = 0
        batch_size = self._label_iterations.get((name, width, height), 8)
        while iterations < width * height + 16:
            for index in range(batch_size):
                labels = self.run(
                    name + "_labels%d" % (index % 2), propagation, width, height, (labels,)
                )
            iterations += batch_size
            changed = self.reduce(name + "_changed", labels, size, 1.0)
            if not self.control_flag(changed, 1):
                self.fields[name + "_labels"] = (labels, width, height)
                self.fields[name + "_iterations"] = iterations
                self._label_iterations[(name, width, height)] = iterations
                return labels
            batch_size = 16
        raise RuntimeError("GPU source labels did not converge")

    def compute_labels(self, name, mask):
        """Atomic union/find produces the same 8-connected minimum-root labels."""
        device = self.device
        gl = device.gl
        count = self.width * self.height
        previous = device.buffers.get(name)
        if previous is None:
            buffer = gl.generate("Buffers")
        else:
            buffer = previous[0]
        gl.BindBuffer(0x90D2, buffer)
        if previous is None or previous[1] != count * 4:
            gl.BufferData(0x90D2, count * 4, None, 0x88E8)
            device.buffers[name] = (buffer, count * 4)
        gl.BindBufferBase(0x90D2, 0, buffer)
        target = device.target(name + "_computed_labels", self.width, self.height)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
        header = """
            layout(local_size_x=128) in;
            layout(sl_binding_zero std430) coherent buffer Parents { uint parent[]; };
            uniform sampler2D mask;
            uint root(uint p){
                uint q=atomicAdd(parent[p],0u);
                while(q!=p){
                    uint next=atomicAdd(parent[q],0u);
                    atomicMin(parent[p],next);p=q;q=next;
                }
                return p;
            }
            void join(uint a,uint b){
                while(true){
                    a=root(a);b=root(b);if(a==b)return;
                    uint high=max(a,b),low=min(a,b);
                    uint old=atomicMin(parent[high],low);
                    if(old==high)return;
                    a=old;b=low;
                }
            }
        """
        bodies = (
            """void main(){uint i=gl_GlobalInvocationID.x;ivec2 size=textureSize(mask,0);
                if(i>=uint(size.x*size.y))return;ivec2 p=ivec2(int(i)%size.x,int(i)/size.x);
                parent[i]=texelFetch(mask,p,0).r>0.5 ? i : 0xffffffffu;}""",
            """void main(){uint i=gl_GlobalInvocationID.x;ivec2 size=textureSize(mask,0);
                if(i>=uint(size.x*size.y) || atomicAdd(parent[i],0u)==0xffffffffu)return;
                ivec2 p=ivec2(int(i)%size.x,int(i)/size.x);
                ivec2 steps[4]=ivec2[4](ivec2(1,0),ivec2(-1,1),ivec2(0,1),ivec2(1,1));
                for(int k=0;k<4;k++){ivec2 q=p+steps[k];
                    if(q.x<0 || q.x>=size.x || q.y>=size.y)continue;
                    uint j=uint(q.y*size.x+q.x);
                    if(atomicAdd(parent[j],0u)!=0xffffffffu)join(i,j);
                }}""",
            """layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
                void main(){uint i=gl_GlobalInvocationID.x;ivec2 size=textureSize(mask,0);
                if(i>=uint(size.x*size.y))return;ivec2 p=ivec2(int(i)%size.x,int(i)/size.x);
                float label=atomicAdd(parent[i],0u)==0xffffffffu ? 0.0 : float(root(i)+1u);
                imageStore(destination,p,vec4(label,0.0,0.0,1.0));}""",
        )
        for index, body in enumerate(bodies):
            program = device.compute_program("components_%d" % index, header + body)
            gl.UseProgram(program)
            gl.ActiveTexture(TEXTURE0)
            gl.BindTexture(TEXTURE_2D, mask)
            device.uniform(program, "mask", 0, integer=True)
            gl.DispatchCompute((count + 127) // 128, 1, 1)
            gl.MemoryBarrier(0x2000 if index < 2 else 0x2428)
        return target

    def component_statistics(self, name, labels, weights, linear, residual):
        device = self.device
        vertex = """
            uniform sampler2D t0,t1,t2,t3,t4;
            uniform float statistic;
            flat out vec4 value;
            void main() {
                ivec2 size=textureSize(t0,0);
                ivec2 p=ivec2(gl_VertexID%size.x,gl_VertexID/size.x);
                int root=int(texelFetch(t0,p,0).r)-1;
                if(root<0){value=vec4(0.0);gl_Position=vec4(3.0,3.0,0.0,1.0);gl_PointSize=1.0;return;}
                float w=texelFetch(t1,p,0).r;
                vec2 coordinate=vec2(p)/vec2(size);
                vec4 linear=texelFetch(t2,p,0);
                if(statistic<0.5) value=vec4(w,coordinate*w,dot(coordinate,coordinate)*w);
                else if(statistic<1.5) value=vec4(linear.rgb*w,1.0);
                else if(statistic<2.5) {
                    vec4 moments=root<0 ? vec4(0.0) : texelFetch(t4,ivec2(root%size.x,root/size.x),0);
                    vec2 center=moments.gb/(moments.r+0.000001);
                    value=vec4(texelFetch(t3,p,0).r,dot(coordinate-center,coordinate-center)*w,0.0,0.0);
                }
                else value=vec4(vec2(p),-vec2(p));
                gl_Position=root<0 ? vec4(3.0,3.0,0.0,1.0) :
                    vec4((vec2(root%size.x,root/size.x)+0.5)/vec2(size)*2.0-1.0,0.0,1.0);
                gl_PointSize=1.0;
            }
        """
        fragment = "flat in vec4 value; out vec4 color; void main(){color=value;}"
        program = device.program("component_statistics", fragment, vertex)
        result = [device.target(name + "_stat%d" % i, self.width, self.height) for i in range(2)]
        paired = device.program(
            "component_statistics_pair",
            """
            flat in vec4 value_a,value_b;
            layout(location=0) out vec4 a;layout(location=1) out vec4 b;
            void main(){a=value_a;b=value_b;}
            """,
            """
            uniform sampler2D t0,t1,t2;
            flat out vec4 value_a,value_b;
            void main(){ivec2 size=textureSize(t0,0);
                ivec2 p=ivec2(gl_VertexID%size.x,gl_VertexID/size.x);
                int root=int(texelFetch(t0,p,0).r)-1;
                if(root<0){value_a=vec4(0.0);value_b=vec4(0.0);gl_Position=vec4(3.0,3.0,0.0,1.0);gl_PointSize=1.0;return;}
                float w=texelFetch(t1,p,0).r;
                vec2 coordinate=vec2(p)/vec2(size);
                value_a=vec4(w,coordinate*w,dot(coordinate,coordinate)*w);
                value_b=vec4(texelFetch(t2,p,0).rgb*w,1.0);
                gl_Position=root<0 ? vec4(3.0,3.0,0.0,1.0) :
                    vec4((vec2(root%size.x,root/size.x)+0.5)/vec2(size)*2.0-1.0,0.0,1.0);
                gl_PointSize=1.0;}
            """,
        )
        device.draw(
            paired,
            result[0],
            self.width,
            self.height,
            (("t0", labels), ("t1", weights), ("t2", linear)),
            points=self.width * self.height,
            blend=True,
            extra_targets=(result[1],),
        )
        for index in range(2, 4):
            target = device.target(name + "_stat%d" % index, self.width, self.height)
            device.draw(
                program,
                target,
                self.width,
                self.height,
                (
                    ("t0", labels),
                    ("t1", weights),
                    ("t2", linear),
                    ("t3", residual),
                    ("t4", result[0] if result else labels),
                ),
                (("statistic", float(index)),),
                points=self.width * self.height,
                blend="min" if index == 3 else True,
            )
            result.append(target)
        total = self.reduce(name + "_energy", weights, (self.width, self.height))
        candidates = self.run(
            name + "_candidates",
            COMMON
            + """
            void main() {
                ivec2 p=ivec2(gl_FragCoord.xy), size=textureSize(t0,0);
                float energy=texelFetch(t0,p,0).r;
                float area=texelFetch(t1,p,0).a;
                float minimum=max(4.0,floor(float(size.x*size.y)*0.000035));
                if(area<minimum || energy<texelFetch(t2,ivec2(0),0).r*0.009) energy=0.0;
                color=vec4(energy,float(p.y*size.x+p.x+1),area,0.0);
            }
        """,
            self.width,
            self.height,
            (result[0], result[1], total),
        )
        return result, candidates, total

    def candidate_batch(self, name, candidates, count=8):
        selector = self.device.target(name + "_selected", count, 1)
        reduction = (
            COMMON
            + """
            void main() {
                ivec2 origin=ivec2(gl_FragCoord.xy)*4, size=textureSize(t0,0);
                vec4 best=vec4(0.0);
                for(int y=0;y<4;y++) for(int x=0;x<4;x++) {
                    ivec2 p=origin+ivec2(x,y);
                    if(p.x>=size.x || p.y>=size.y) continue;
                    vec4 v=texelFetch(t0,p,0);
                    if(v.r>best.r || (v.r==best.r && v.g<best.g)) best=v;
                }
                color=best;
            }
        """
        )
        for index in range(count):
            w, h = self.width, self.height
            best = candidates
            step = 0
            while w > 1 or h > 1:
                w, h = (w + 3) // 4, (h + 3) // 4
                best = self.run(name + "_rank%d" % step, reduction, w, h, (best,))
                step += 1
            self.copy_scalar(selector, index, best)
            candidates = self.run(
                name + "_remaining%d" % (index % 2),
                COMMON
                + """
                void main() {
                    color=texelFetch(t0,ivec2(gl_FragCoord.xy),0);
                    if(color.g==texelFetch(t1,ivec2(0),0).g) color.r=0.0;
                }
            """,
                self.width,
                self.height,
                (candidates, best),
            )
        return selector, candidates

    def compact_candidates(self, name, candidates):
        """At most 111 disjoint components can each contain >=0.9% of total energy."""
        if self.device.opencl is not None:
            return self.device.opencl.sort_candidates(
                name, candidates, size=(self.width, self.height)
            )
        if self.device.gl.compute_active:
            return self.compute_compact_candidates(name, candidates)
        w, h = self.width, self.height
        scan = self.run(
            name + "_valid",
            COMMON
            + """
            void main(){ color=vec4(texelFetch(t0,ivec2(gl_FragCoord.xy),0).r>0.0 ? 1.0 : 0.0); }
        """,
            w,
            h,
            (candidates,),
        )
        shader = (
            COMMON
            + """
            uniform vec2 stride;
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy), q=p-ivec2(stride);
                color=texelFetch(t0,p,0);
                if(q.x>=0 && q.y>=0) color+=texelFetch(t0,q,0); }
        """
        )
        step, index = 1, 0
        while step < w:
            scan = self.run(
                name + "_scanx%d" % (index % 2), shader, w, h, (scan,), (("stride", (step, 0)),)
            )
            step *= 2
            index += 1
        rows = self.run(
            name + "_rows",
            COMMON
            + """
            void main(){ color=texelFetch(t0,ivec2(textureSize(t0,0).x-1,int(gl_FragCoord.y)),0); }
        """,
            1,
            h,
            (scan,),
        )
        step, index = 1, 0
        while step < h:
            rows = self.run(
                name + "_scany%d" % (index % 2), shader, 1, h, (rows,), (("stride", (0, step)),)
            )
            step *= 2
            index += 1
        vertex = """
            uniform sampler2D t0,t1,t2;
            flat out vec4 value;
            void main(){ ivec2 size=textureSize(t0,0);
                ivec2 p=ivec2(gl_VertexID%size.x,gl_VertexID/size.x);
                value=texelFetch(t0,p,0);
                float index=texelFetch(t1,p,0).r-1.0;
                if(p.y>0) index+=texelFetch(t2,ivec2(0,p.y-1),0).r;
                gl_Position=value.r>0.0 ? vec4((index+0.5)/128.0*2.0-1.0,0.0,0.0,1.0) : vec4(3.0,3.0,0.0,1.0);
                gl_PointSize=1.0; }
        """
        device = self.device
        target = device.target(name + "_compact", 128, 1)
        program = device.program(
            "compact_candidates",
            "flat in vec4 value; out vec4 color; void main(){color=value;}",
            vertex,
        )
        device.draw(
            program,
            target,
            128,
            1,
            (("t0", candidates), ("t1", scan), ("t2", rows)),
            points=w * h,
            blend=True,
        )
        return self.sort_candidates(name, target)

    def sort_candidates(self, name, target, root_channel="g"):
        if self.device.opencl is not None:
            return self.device.opencl.sort_candidates(name, target, root_channel)
        if self.device.gl.compute_active:
            return self.compute_sort_candidates(name, target, root_channel)
        shader = (
            COMMON
            + """
            uniform float stage, step;
            void main(){ int i=int(gl_FragCoord.x), j=i^int(step);
                vec4 a=texelFetch(t0,ivec2(i,0),0), b=texelFetch(t0,ivec2(j,0),0);
                bool better=a.r>b.r || (a.r==b.r && a.ROOT<b.ROOT);
                bool want=((i&int(stage))==0)==((i&int(step))==0);
                color=better==want ? a : b; }
        """.replace("ROOT", root_channel)
        )
        stage, index = 2, 0
        while stage <= 128:
            step = stage // 2
            while step:
                target = self.run(
                    name + "_sort%d" % (index % 2),
                    shader,
                    128,
                    1,
                    (target,),
                    (("stage", float(stage)), ("step", float(step))),
                )
                index += 1
                step //= 2
            stage *= 2
        return target

    def compute_compact_candidates(self, name, candidates):
        device, gl = self.device, self.device.gl
        key = "compact_candidates"
        previous = device.buffers.get(key)
        if previous is None:
            buffer = gl.generate("Buffers")
            gl.BindBuffer(0x90D2, buffer)
            gl.BufferData(0x90D2, 16 + 128 * 16, None, 0x88E8)
            device.buffers[key] = (buffer, 16 + 128 * 16)
        else:
            buffer = previous[0]
        gl.BindBufferBase(0x90D2, 0, buffer)
        header = "layout(sl_binding_zero std430) buffer Candidates { uint count; uint pad[3]; vec4 values[]; };\n"
        program = device.compute_program(
            "compact_clear", header + "layout(local_size_x=1) in;void main(){count=0u;}"
        )
        gl.UseProgram(program)
        gl.DispatchCompute(1, 1, 1)
        gl.MemoryBarrier(0x2000)
        program = device.compute_program(
            "compact_append",
            header
            + """
            layout(local_size_x=128) in; uniform sampler2D source;
            void main(){ivec2 size=textureSize(source,0);uint i=gl_GlobalInvocationID.x;
                if(i>=uint(size.x*size.y))return;
                vec4 value=texelFetch(source,ivec2(int(i)%size.x,int(i)/size.x),0);
                if(value.r>0.0){uint slot=atomicAdd(count,1u);if(slot<128u)values[slot]=value;}}
        """,
        )
        gl.UseProgram(program)
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, candidates)
        device.uniform(program, "source", 0, integer=True)
        gl.DispatchCompute((self.width * self.height + 127) // 128, 1, 1)
        gl.MemoryBarrier(0x2000)
        return self.compute_sort_candidates(name, candidates, "g", header)

    def compute_sort_candidates(self, name, source, root_channel, buffer_header=""):
        device, gl = self.device, self.device.gl
        initial = (
            "i<int(count) ? values[i] : vec4(0.0)"
            if buffer_header
            else "texelFetch(source,ivec2(i,0),0)"
        )
        code = (
            buffer_header
            + """
            layout(local_size_x=128) in;
            uniform sampler2D source;
            layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
            shared vec4 items[128];
            void main(){int i=int(gl_LocalInvocationID.x);items[i]=INITIAL;barrier();
                for(int stage=2;stage<=128;stage*=2)for(int step=stage/2;step>0;step/=2){
                    int j=i^step;vec4 a=items[i],b=items[j];
                    bool better=a.r>b.r || (a.r==b.r && a.ROOT<b.ROOT);
                    bool want=((i&stage)==0)==((i&step)==0);
                    barrier();items[i]=better==want ? a : b;barrier();
                }
                imageStore(destination,ivec2(i,0),items[i]);}
        """
        )
        program = device.compute_program(
            "candidate_sort", code.replace("INITIAL", initial).replace("ROOT", root_channel)
        )
        target = device.target(name + "_compute_sorted", 128, 1)
        gl.UseProgram(program)
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, source)
        device.uniform(program, "source", 0, integer=True)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
        gl.DispatchCompute(1, 1, 1)
        gl.MemoryBarrier(0x2428)
        return target

    def compute_component_quantiles(self, name, labels, selection, linear):
        """Parallel exact ring membership, with no frame-dependent CPU query.

        A tile shares neighboring component IDs. A 128-bit membership set makes
        overlapping rings count each pixel once per component, including holes
        and touching components. Histograms retain the reference 20-bit radix.
        """
        device = self.device
        gl = device.gl
        width, height = self.width, self.height
        pad = max(5, (min(width, height) // 46) | 1) // 2
        side = 8 + 2 * pad
        vertex = """
            uniform sampler2D t0; uniform vec2 size;
            flat out vec4 value;
            void main(){vec4 candidate=texelFetch(t0,ivec2(gl_VertexID,0),0);
                int root=int(candidate.g)-1;
                vec2 p=vec2(root%int(size.x),root/int(size.x));
                gl_Position=candidate.r>0.0 ? vec4((p+0.5)/size*2.0-1.0,0.0,1.0) : vec4(3.0,3.0,0.0,1.0);
                gl_PointSize=1.0;value=vec4(float(gl_VertexID+1));}
        """
        slots = device.target(name + "_slots", width, height)
        program = device.program(
            "component_slots", "flat in vec4 value;out vec4 color;void main(){color=value;}", vertex
        )
        device.draw(
            program,
            slots,
            width,
            height,
            (("t0", selection),),
            (("size", (width, height)),),
            points=128,
            blend=True,
        )
        parameters = selection
        histograms = []
        for fine in (False, True):
            rows = 1024 if fine else 256
            count = 1024 * rows
            key = "component_histogram_" + str(rows)
            prior = device.buffers.get(key)
            if prior is None:
                buffer = gl.generate("Buffers")
                gl.BindBuffer(0x90D2, buffer)
                gl.BufferData(0x90D2, count * 4, None, 0x88E8)
                device.buffers[key] = (buffer, count * 4)
            else:
                buffer = prior[0]
            gl.BindBufferBase(0x90D2, 0, buffer)
            header = "layout(sl_binding_zero std430) buffer Histogram { uint bins[]; };\n"
            clear = device.compute_program(
                "clear_" + key,
                header
                + """
                layout(local_size_x=128) in;
                void main(){uint i=gl_GlobalInvocationID.x;if(i<COUNTu)bins[i]=0u;}
            """.replace("COUNT", str(count)),
            )
            gl.UseProgram(clear)
            gl.DispatchCompute((count + 127) // 128, 1, 1)
            gl.MemoryBarrier(0x2000)
            membership = (
                header
                + """
                layout(local_size_x=8,local_size_y=8) in;
                uniform sampler2D t0,t1,t2,t3;
                shared uint tile[SIDE*SIDE];
                void add_value(uint group,float value){
                    uint bin=min(uint(value),1023u),row=group;
                    if(FINE){
                        int selected=-1;
                        for(int i=0;i<4;i++)if(selected<0 && uint(texelFetch(t3,ivec2(int(group)*4+i,0),0).r)==bin)selected=int(group)*4+i;
                        if(selected<0)return;
                        row=uint(selected);bin=min(uint((value-float(bin))*1024.0),1023u);
                    }
                    atomicAdd(bins[row*1024u+bin],1u);
                }
                void main(){ivec2 size=textureSize(t0,0);
                    ivec2 origin=ivec2(gl_WorkGroupID.xy)*8-ivec2(PAD);
                    for(int i=int(gl_LocalInvocationIndex);i<SIDE*SIDE;i+=64){
                        ivec2 p=origin+ivec2(i%SIDE,i/SIDE);uint slot=0u;
                        if(p.x>=0 && p.y>=0 && p.x<size.x && p.y<size.y){
                            int root=int(texelFetch(t0,p,0).r)-1;
                            if(root>=0)slot=uint(texelFetch(t1,ivec2(root%size.x,root/size.x),0).r);
                        }
                        tile[i]=slot;
                    }
                    barrier();
                    ivec2 p=ivec2(gl_GlobalInvocationID.xy);
                    if(p.x>=size.x || p.y>=size.y)return;
                    ivec2 local=ivec2(gl_LocalInvocationID.xy)+ivec2(PAD);
                    uint own=tile[local.y*SIDE+local.x];
                    float value=clamp(texelFetch(t2,p,0).a,0.0,1.0)*1024.0;
                    if(own>0u)add_value(own-1u,value);
                    uvec4 seen=uvec4(0u);
                    for(int y=-PAD;y<=PAD;y++)for(int x=-PAD;x<=PAD;x++){
                        uint slot=tile[(local.y+y)*SIDE+local.x+x];
                        if(slot==0u || slot==own)continue;
                        uint group=slot-1u,word=group/32u,bit=1u<<(group%32u);
                        if((seen[word]&bit)!=0u)continue;
                        seen[word]|=bit;add_value(128u+group,value);
                    }
                }
            """.replace("SIDE", str(side))
                .replace("PAD", str(pad))
                .replace("FINE", "true" if fine else "false")
            )
            program = device.compute_program("component_membership", membership)
            gl.UseProgram(program)
            for index, texture in enumerate((labels, slots, linear, parameters)):
                gl.ActiveTexture(TEXTURE0 + index)
                gl.BindTexture(TEXTURE_2D, texture)
                device.uniform(program, "t%d" % index, index, integer=True)
            gl.DispatchCompute((width + 7) // 8, (height + 7) // 8, 1)
            gl.MemoryBarrier(0x2000)
            target = device.target(key, 1024, rows)
            gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
            program = device.compute_program(
                "copy_" + key,
                header
                + """
                layout(local_size_x=128) in;
                layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
                void main(){uint i=gl_GlobalInvocationID.x;if(i>=COUNTu)return;
                    imageStore(destination,ivec2(int(i)%1024,int(i)/1024),vec4(float(bins[i])));}
            """.replace("COUNT", str(count)),
            )
            gl.UseProgram(program)
            gl.DispatchCompute((count + 127) // 128, 1, 1)
            gl.MemoryBarrier(0x2428)
            histograms.append(target)
            if not fine:
                parameters = self.compute_quantile_parameters(
                    name + "_all_parameters", target, 256, (0.5, 0.9)
                )
        selected = self.compute_quantile_values(
            name + "_selected_values", histograms[1], parameters, 256, 4
        )
        return self.run(
            name + "_all_quantiles",
            COMMON
            + """
            float selected(int index){return texelFetch(t0,ivec2(index,0),0).r;}
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);int index=(p.y*128+p.x)*4;
                vec4 a=texelFetch(t1,ivec2(index,0),0),b=texelFetch(t1,ivec2(index+2,0),0);
                color=vec4(mix(selected(index),selected(index+1),a.a),
                    mix(selected(index+2),selected(index+3),b.a),a.b,1.0);}
        """,
            128,
            2,
            (selected, parameters),
        )

    def raster_component_quantiles(self, name, labels, selection, linear):
        """Gather all component/ring samples once, without compute atomics.

        Geometry emits only actual memberships. Integer-valued float blending
        preserves exact counts, including overlapping rings and duplicate bins.
        """
        device = self.device
        width, height = self.width, self.height
        pad = max(5, (min(width, height) // 46) | 1) // 2
        vertex = """
            uniform sampler2D t0; uniform vec2 size;
            flat out vec4 value;
            void main(){vec4 candidate=texelFetch(t0,ivec2(gl_VertexID,0),0);
                int root=int(candidate.g)-1;
                vec2 p=vec2(root%int(size.x),root/int(size.x));
                gl_Position=candidate.r>0.0 ? vec4((p+0.5)/size*2.0-1.0,0.0,1.0) : vec4(3.0,3.0,0.0,1.0);
                gl_PointSize=1.0;value=vec4(float(gl_VertexID+1));}
        """
        slots = device.target(name + "_raster_slots", width, height, R32F)
        program = device.program(
            "raster_component_slots",
            "flat in vec4 value;out vec4 color;void main(){color=value;}",
            vertex,
        )
        device.draw(
            program,
            slots,
            width,
            height,
            (("t0", selection),),
            (("size", (width, height)),),
            points=128,
            blend=True,
        )
        pixel_slots = self.run(
            name + "_pixel_slots",
            COMMON
            + """
            void main(){ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);
                int root=int(texelFetch(t0,p,0).r)-1;
                color=vec4(root<0 ? 0.0 : texelFetch(t1,ivec2(root%size.x,root/size.x),0).r);}
            """,
            width,
            height,
            (labels, slots),
            storage=R32F,
        )
        neighborhoods = []
        for half in range(2):
            horizontal = self.run(
                name + "_membership_horizontal%d" % half,
                COMMON
                + """
                uniform float half_index;
                void main(){ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);uvec4 bits=uvec4(0u);
                    for(int x=-PAD;x<=PAD;x++){
                        if(p.x+x<0 || p.x+x>=size.x)continue;
                        int group=int(texelFetch(t0,p+ivec2(x,0),0).r)-1-int(half_index)*64;
                        if(group>=0 && group<64)bits[group/16]|=1u<<uint(group%16);
                    }
                    color=vec4(bits);}
                """.replace("PAD", str(pad)),
                width,
                height,
                (pixel_slots,),
                (("half_index", float(half)),),
            )
            neighborhoods.append(
                self.run(
                    name + "_membership_vertical%d" % half,
                    COMMON
                    + """
                void main(){ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);uvec4 bits=uvec4(0u);
                    for(int y=-PAD;y<=PAD;y++){
                        if(p.y+y>=0 && p.y+y<size.y)bits|=uvec4(texelFetch(t0,p+ivec2(0,y),0));
                    }
                    color=vec4(bits);}
                """.replace("PAD", str(pad)),
                    width,
                    height,
                    (horizontal,),
                )
            )
        geometry = """
            layout(points) in;
            layout(points,max_vertices=MAXIMUM) out;
            flat in int sample_id[];
            uniform sampler2D t0,t1,t2,t3,t4,t5;
            uniform float fine;
            void add_value(uint group,float value){
                int bin=min(int(value),1023),row=int(group);
                if(fine>0.5){
                    row=-1;
                    for(int i=0;i<4;i++)if(row<0 && int(texelFetch(t3,ivec2(int(group)*4+i,0),0).r)==bin)
                        row=int(group)*4+i;
                    if(row<0)return;
                    bin=min(int((value-float(bin))*1024.0),1023);
                }
                gl_Position=vec4((float(bin)+0.5)/1024.0*2.0-1.0,
                    (float(row)+0.5)/(fine>0.5 ? 1024.0 : 256.0)*2.0-1.0,0.0,1.0);
                gl_PointSize=1.0;EmitVertex();EndPrimitive();
            }
            void main(){
                ivec2 size=textureSize(t0,0),p=ivec2(sample_id[0]%size.x,sample_id[0]/size.x);
                uint own=uint(texelFetch(t1,p,0).r);float value=clamp(texelFetch(t2,p,0).a,0.0,1.0)*1024.0;
                if(own>0u)add_value(own-1u,value);
                uvec4 near0=uvec4(texelFetch(t4,p,0)),near1=uvec4(texelFetch(t5,p,0));
                if(own>0u){uint group=own-1u;
                    if(group<64u)near0[group/16u]&=~(1u<<(group%16u));
                    else near1[(group-64u)/16u]&=~(1u<<(group%16u));
                }
                for(uint word=0u;word<8u;word++){
                    uint bits=word<4u ? near0[word] : near1[word-4u];
                    if(bits==0u)continue;
                    for(uint bit=0u;bit<16u;bit++)if((bits&(1u<<bit))!=0u)
                        add_value(128u+word*16u+bit,value);
                }
            }
        """.replace("PAD", str(pad)).replace("MAXIMUM", str((2 * pad + 1) ** 2 + 1))
        program = device.program(
            "raster_membership_histogram",
            HISTOGRAM_FRAGMENT,
            "flat out int sample_id;void main(){sample_id=gl_VertexID;gl_Position=vec4(0.0);}",
            geometry=geometry,
        )
        coarse = device.target(name + "_raster_hist", 1024, 256, R32F)
        inputs = (
            ("t0", labels),
            ("t1", pixel_slots),
            ("t2", linear),
            ("t4", neighborhoods[0]),
            ("t5", neighborhoods[1]),
        )
        device.draw(
            program, coarse, 1024, 256, inputs, (("fine", 0.0),), points=width * height, blend=True
        )
        parameters = self.run(
            name + "_raster_parameters",
            COMMON
            + """
            void main(){int index=int(gl_FragCoord.x),group=index/4;
                float count=0.0;for(int i=0;i<1024;i++)count+=texelFetch(t0,ivec2(i,group),0).r;
                float position=max(count-1.0,0.0)*(index%4<2 ? 0.5 : 0.9);
                float rank=index%2==0 ? floor(position) : ceil(position);
                float cumulative=0.0,local_rank=0.0;int chosen=1023;
                for(int i=0;i<1024;i++){
                    float n=texelFetch(t0,ivec2(i,group),0).r;
                    if(cumulative+n>rank){chosen=i;local_rank=rank-cumulative;break;}
                    cumulative+=n;
                }
                color=vec4(float(chosen),local_rank,count,fract(position));}
            """,
            1024,
            1,
            (coarse,),
        )
        fine = device.target(name + "_raster_fine_hist", 1024, 1024, R32F)
        device.draw(
            program,
            fine,
            1024,
            1024,
            inputs + (("t3", parameters),),
            (("fine", 1.0),),
            points=width * height,
            blend=True,
        )
        return self.run(
            name + "_raster_quantiles",
            COMMON
            + """
            float selected(int index){
                vec4 info=texelFetch(t1,ivec2(index,0),0);
                if(info.b<0.5)return 0.0;
                int row=index;
                for(int i=0;i<4;i++){
                    int other=index/4*4+i;
                    if(other<row && texelFetch(t1,ivec2(other,0),0).r==info.r)row=other;
                }
                float cumulative=0.0;int chosen=1023;
                for(int i=0;i<1024;i++){
                    cumulative+=texelFetch(t0,ivec2(i,row),0).r;
                    if(cumulative>info.g){chosen=i;break;}
                }
                return min((info.r*1024.0+float(chosen)+0.5)/1048576.0,1.0);
            }
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);int index=(p.y*128+p.x)*4;
                vec4 a=texelFetch(t1,ivec2(index,0),0),b=texelFetch(t1,ivec2(index+2,0),0);
                color=vec4(mix(selected(index),selected(index+1),a.a),
                    mix(selected(index+2),selected(index+3),b.a),a.b,1.0);}
            """,
            128,
            2,
            (fine, parameters),
        )

    def component_quantiles(self, name, labels, selection, linear, bounds, ring=False):
        """Exact component/ring membership, with a 20-bit luminance radix histogram."""
        pad = max(5, (min(self.width, self.height) // 46) | 1) // 2
        vertex = """
            uniform sampler2D t0,t1,t2,t3,t4;
            uniform float fine;
            void main(){
                ivec2 size=textureSize(t0,0);
                int sample_index=RING ? gl_VertexID/8 : gl_VertexID;
                ivec2 p=ivec2(sample_index%size.x,sample_index/size.x);
                int own=int(texelFetch(t0,p,0).r);
                int group=RING ? gl_VertexID%8 : -1;
                if(!RING && own>0) for(int i=0;i<8;i++) {
                    vec4 candidate=texelFetch(t1,ivec2(i,0),0);
                    if(candidate.r>0.0 && int(candidate.g)==own) group=i;
                }
                bool valid=group>=0;
                if(RING) {
                    vec4 candidate=texelFetch(t1,ivec2(group,0),0);
                    int root=int(candidate.g);
                    valid=candidate.r>0.0 && root>0 && own!=root;
                    if(valid) {
                        vec4 box=texelFetch(t3,ivec2((root-1)%size.x,(root-1)/size.x),0);
                        valid=p.x>=int(box.x)-PAD && p.x<=int(-box.z)+PAD && p.y>=int(box.y)-PAD && p.y<=int(-box.w)+PAD;
                    }
                    if(valid) {
                        valid=false;
                        for(int y=-PAD;y<=PAD;y++) for(int x=-PAD;x<=PAD;x++) {
                            ivec2 q=p+ivec2(x,y);
                            if(q.x<0 || q.y<0 || q.x>=size.x || q.y>=size.y) continue;
                            if(int(texelFetch(t0,q,0).r)==root) valid=true;
                        }
                    }
                }
                float value=clamp(texelFetch(t2,p,0).a,0.0,1.0)*1024.0;
                int coarse_bin=min(int(value),1023), bin=coarse_bin, row=group;
                if(fine>0.5 && valid) {
                    row=-1;
                    for(int i=0;i<4;i++) {
                        if(row<0 && int(texelFetch(t4,ivec2(group*4+i,0),0).r)==coarse_bin) row=group*4+i;
                    }
                    valid=row>=0;
                    bin=min(int((value-float(coarse_bin))*1024.0),1023);
                }
                gl_Position=valid ? vec4((float(bin)+0.5)/1024.0*2.0-1.0,
                    (float(row)+0.5)/(fine>0.5 ? 32.0 : 8.0)*2.0-1.0,0.0,1.0) : vec4(3.0,3.0,0.0,1.0);
                gl_PointSize=1.0;
            }
        """.replace("RING", "true" if ring else "false").replace("PAD", str(pad))
        device = self.device
        program = device.program(name + "_histogram", HISTOGRAM_FRAGMENT, vertex)
        coarse = device.target(name + "_hist", 1024, 8)
        inputs = (("t0", labels), ("t1", selection), ("t2", linear), ("t3", bounds))
        points = self.width * self.height * (8 if ring else 1)
        device.draw(program, coarse, 1024, 8, inputs, (("fine", 0.0),), points=points, blend=True)
        parameters = self.run(
            name + "_parameters",
            COMMON
            + """
            void main(){ int index=int(gl_FragCoord.x), group=index/4;
                float count=0.0;
                for(int i=0;i<1024;i++) count+=texelFetch(t0,ivec2(i,group),0).r;
                float position=max(count-1.0,0.0)*(index%4<2 ? 0.5 : 0.9);
                float rank=index%2==0 ? floor(position) : ceil(position);
                float cumulative=0.0, local_rank=0.0; int chosen=1023;
                for(int i=0;i<1024;i++) {
                    float n=texelFetch(t0,ivec2(i,group),0).r;
                    if(cumulative+n>rank){ chosen=i; local_rank=rank-cumulative; break; }
                    cumulative+=n;
                }
                color=vec4(float(chosen),local_rank,count,fract(position));
            }
        """,
            32,
            1,
            (coarse,),
        )
        fine = device.target(name + "_fine_hist", 1024, 32)
        device.draw(
            program,
            fine,
            1024,
            32,
            inputs + (("t4", parameters),),
            (("fine", 1.0),),
            points=points,
            blend=True,
        )
        return self.run(
            name,
            COMMON
            + """
            float selected(int index){
                vec4 info=texelFetch(t1,ivec2(index,0),0);
                if(info.b<0.5) return 0.0;
                int row=index;
                for(int i=0;i<4;i++) {
                    int other=index/4*4+i;
                    if(other<row && texelFetch(t1,ivec2(other,0),0).r==info.r) row=other;
                }
                float cumulative=0.0; int chosen=1023;
                for(int i=0;i<1024;i++) {
                    cumulative+=texelFetch(t0,ivec2(i,row),0).r;
                    if(cumulative>info.g){chosen=i;break;}
                }
                return min((info.r*1024.0+float(chosen)+0.5)/1048576.0,1.0);
            }
            void main(){ int index=int(gl_FragCoord.x)*4;
                vec4 first=texelFetch(t1,ivec2(index,0),0);
                vec4 second=texelFetch(t1,ivec2(index+2,0),0);
                color=vec4(mix(selected(index),selected(index+1),first.a),
                    mix(selected(index+2),selected(index+3),second.a),first.b,1.0);
            }
        """,
            8,
            1,
            (fine, parameters),
        )

    def physical_components(self, name, weights, linear, residual):
        # Integrate a partition of unity instead of segmenting bright blobs.
        # Fixed slots preserve direction when a bright region splits or merges.
        rows = self.run(
            name + "_basis_rows",
            COMMON
            + """
            void main(){
                ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);
                int slot=p.x%4,kind=p.x/4;
                vec4 sum=vec4(0.0);
                for(int x=0;x<size.x;x++){
                    ivec2 q=ivec2(x,p.y);
                    vec2 uv=vec2(q)/max(vec2(size-1),vec2(1.0));
                    float wx=slot%2==0 ? 1.0-uv.x : uv.x;
                    float wy=slot<2 ? 1.0-uv.y : uv.y;
                    float weight=texelFetch(t0,q,0).r*wx*wy;
                    sum+=kind==0 ? vec4(weight,uv*weight,dot(uv,uv)*weight)
                        : vec4(texelFetch(t1,q,0).rgb*weight,0.0);
                }
                color=sum;
            }
            """,
            8,
            self.height,
            (weights, linear),
        )
        moments = self.run(
            name + "_basis_moments",
            COMMON
            + """
            void main(){
                vec4 sum=vec4(0.0);int x=int(gl_FragCoord.x);
                for(int y=0;y<textureSize(t0,0).y;y++)sum+=texelFetch(t0,ivec2(x,y),0);
                color=sum;
            }
            """,
            8,
            1,
            (rows,),
        )
        lights = self.run(
            name,
            COMMON
            + """
            void main(){
                ivec2 p=ivec2(gl_FragCoord.xy);
                float maximum=0.0,total=0.0;
                for(int i=0;i<4;i++){float e=texelFetch(t0,ivec2(i,0),0).r;maximum=max(maximum,e);total+=e;}
                if(p.x>=4 || total<=EPS){color=vec4(0.0);return;}
                vec4 m=texelFetch(t0,ivec2(p.x,0),0);
                vec2 center=m.gb/(m.r+EPS);
                float variance=max(m.a/(m.r+EPS)-dot(center,center),0.0);
                float radius=clamp(sqrt(variance)*3.2,0.055,1.0);
                vec3 c=display_chroma(texelFetch(t0,ivec2(p.x+4,0),0).rgb/(m.r+EPS));
                color=p.y==0 ? vec4(center,radius,sqrt(m.r/(maximum+EPS)))
                    : (p.y==1 ? vec4(c,0.35+0.60*(1.0-radius))
                    : vec4(1.0-smoothstep(0.10,0.45,radius),1.0,0.0,1.0));
            }
            """,
            6,
            3,
            (moments,),
        )
        total = self.reduce(name + "_basis_total", weights, (self.width, self.height))
        return lights, total

    def creative_components(self, name, linear):
        hsv = self.run(
            name + "_hsv",
            COMMON
            + """
            void main(){
                ivec2 p=ivec2(gl_FragCoord.xy);
                vec3 c=clamp(display_rgb(texelFetch(t0,p,0).rgb),0.0,1.0);
                float maximum=max(c.r,max(c.g,c.b)), minimum=min(c.r,min(c.g,c.b));
                float delta=maximum-minimum;
                float saturation=delta/(maximum+0.00000011920928955078125);
                float hue=maximum==c.r ? c.g-c.b : (maximum==c.g ? c.b-c.r+2.0*delta : c.r-c.g+4.0*delta);
                hue*=60.0/(delta+0.00000011920928955078125);
                if(hue<0.0) hue+=360.0;
                float w=texelFetch(t0,p,0).a;
                float energy=saturation>=0.24 ? w*(0.30+0.70*saturation) : 0.0;
                color=vec4(hue,saturation,energy,0.0);
            }
        """,
            self.width,
            self.height,
            (linear,),
        )
        total = self.reduce(name + "_energy", hsv, (self.width, self.height))
        statistics = []
        for index in range(3):
            rows = self.run(
                name + "_stat_rows%d" % index,
                COMMON
                + """
                uniform float statistic;
                void main(){
                    ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);
                    float sector_center=float(p.x)*30.0+15.0;
                    vec4 sum=vec4(0.0);
                    vec4 moments=texelFetch(t2,ivec2(p.x,0),0);
                    vec2 center=moments.gb/(moments.r+0.000001);
                    for(int x=0;x<size.x;x++){
                        ivec2 sample_position=ivec2(x,p.y);
                        vec4 hsv=texelFetch(t0,sample_position,0);
                        float membership=clamp(1.0-abs(mod(hsv.r-sector_center+180.0,360.0)-180.0)/21.6,0.0,1.0);
                        float weight=hsv.b*membership;
                        if(weight<=0.0)continue;
                        vec2 coordinate=vec2(sample_position)/vec2(size);
                        if(statistic<0.5)sum+=vec4(weight,coordinate*weight,dot(coordinate,coordinate)*weight);
                        else if(statistic<1.5)sum+=vec4(texelFetch(t1,sample_position,0).rgb*weight,0.0);
                        else sum+=vec4(dot(coordinate-center,coordinate-center)*weight,0.0,0.0,0.0);
                    }
                    color=sum;
                }
                """,
                12,
                self.height,
                (hsv, linear, statistics[0] if statistics else linear),
                (("statistic", float(index)),),
            )
            statistics.append(
                self.run(
                    name + "_stat%d" % index,
                    COMMON
                    + """
                void main(){
                    vec4 sum=vec4(0.0);
                    for(int y=0;y<textureSize(t0,0).y;y++)sum+=texelFetch(t0,ivec2(int(gl_FragCoord.x),y),0);
                    color=sum;
                }
                """,
                    12,
                    1,
                    (rows,),
                )
            )
        return self.run(
            name + "_lights",
            COMMON
            + """
            uniform vec2 source_size;
            void main(){
                float total=texelFetch(t3,ivec2(0),0).b+EPS;
                float energy[12]; vec3 colors[12];
                float maximum=0.0;
                for(int i=0;i<12;i++){
                    energy[i]=texelFetch(t0,ivec2(i,0),0).r;
                    if(energy[i]<total*0.012) energy[i]=0.0;
                    maximum=max(maximum,energy[i]);
                    colors[i]=display_chroma(texelFetch(t1,ivec2(i,0),0).rgb/(energy[i]+EPS));
                }
                int slot=int(gl_FragCoord.x), row=int(gl_FragCoord.y);
                if(slot>=3) {color=vec4(0.0);return;}
                vec4 geometry[3];vec3 rgb[3];float support[3];
                for(int k=0;k<3;k++){geometry[k]=vec4(0.0);rgb[k]=vec3(0.0);support[k]=0.0;}
                for(int i=0;i<12;i++){
                    float e=energy[i];if(e<=0.0)continue;
                    vec3 c=colors[i];float hi=max(c.r,max(c.g,c.b)),lo=min(c.r,min(c.g,c.b)),delta=hi-lo;
                    float h=delta<=0.0 ? 0.0 : (hi==c.r ? (c.g-c.b)/delta : (hi==c.g ? (c.b-c.r)/delta+2.0 : (c.r-c.g)/delta+4.0));
                    int family=int(floor(mod(h/6.0,1.0)*3.0+0.5))%3;
                    vec4 moments=texelFetch(t0,ivec2(i,0),0);
                    vec2 center=clamp(moments.gb/(e+EPS)*source_size/max(source_size-1.0,vec2(1.0)),0.0,1.0);
                    float radius=clamp(sqrt(max(texelFetch(t2,ivec2(i,0),0).r/(e+EPS),0.0))*3.2,0.055,0.72);
                    float intensity=clamp(sqrt(e/(maximum+EPS)),0.0,1.0)*smoothstep(0.012,0.06,e/total);
                    float confidence=clamp(0.62+e/total*0.85,0.0,0.96);
                    float weight=intensity*intensity;
                    support[family]+=weight;geometry[family]+=vec4(center,radius,confidence)*weight;
                    rgb[family]+=linear_rgb(c)*weight;
                }
                if(support[slot]<=0.0){color=vec4(0.0);return;}
                vec4 g=geometry[slot]/support[slot];
                vec3 c=display_chroma(rgb[slot]/support[slot]);
                float intensity=sqrt(support[slot]/max(support[0],max(support[1],support[2])));
                color=row==0 ? vec4(g.xyz,intensity) : (row==1 ? vec4(c,g.w) : vec4(1.0));
            }
        """,
            6,
            3,
            tuple(statistics) + (total,),
            (("source_size", (self.width, self.height)),),
        )

    def supported_creative_components(self, name, creative, physical):
        return self.run(
            name,
            COMMON
            + """
            void main(){color=texelFetch(t1,ivec2(0,2),0).a>0.5
                ? texelFetch(t0,ivec2(gl_FragCoord.xy),0) : vec4(0.0);}
            """,
            6,
            3,
            (creative, physical),
        )

    def fft_twiddles(self, n, inverse):
        key = (n, inverse)
        if key not in self._twiddles:
            self._twiddles[key] = self.run(
                "fft_twiddle_%d_%d" % key,
                COMMON
                + """
                uniform float sign;
                void main(){ivec2 p=ivec2(gl_FragCoord.xy);
                    float stage=exp2(float(p.y+1));
                    float angle=sign*6.283185307179586*float(p.x)/stage;
                    color=vec4(cos(angle),sin(angle),0.0,0.0);}
                """,
                n // 2,
                n.bit_length() - 1,
                uniforms=(("sign", 1.0 if inverse else -1.0),),
                storage=RG32F,
            )
        return self._twiddles[key]

    def gaussian_fft(self, name, texture, size, sigma):
        radius = int(round(sigma * 8.0 + 1.0)) // 2
        weights = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-radius, radius + 1)]
        total = sum(weights)
        weights = [v / total for v in weights]
        for axis in (0, 1):
            length = size[axis]
            n = 1
            bits = 0
            while n < length + 2 * radius:
                n *= 2
                bits += 1
            shape = (n, size[1]) if axis == 0 else (size[0], n)
            key = (sigma, n)
            kernel = self._fft_kernels.get(key)
            if kernel is None:
                values = []
                for k in range(n):
                    v = weights[radius] + 2.0 * sum(
                        weights[radius + j] * math.cos(2.0 * math.pi * k * j / n)
                        for j in range(1, radius + 1)
                    )
                    values.extend((v, 0.0, 0.0, 1.0))
                kernel = self.device.target("fft_kernel_%s_%d" % (sigma, n), n, 1)
                gl = self.device.gl
                gl.BindTexture(TEXTURE_2D, kernel)
                array = (GLfloat * len(values))(*values)
                gl.TexSubImage2D(TEXTURE_2D, 0, 0, 0, n, 1, RGBA, FLOAT, C.cast(array, GLvoidp))
                self._fft_kernels[key] = kernel
            if self.device.opencl is not None and n * 8 <= self.device.opencl.local_memory:
                texture = self.device.opencl.gaussian_axis(
                    name + "_fft_crop%d" % axis,
                    texture,
                    kernel,
                    size,
                    axis,
                    n,
                    radius,
                    (self.fft_twiddles(n, False), self.fft_twiddles(n, True)),
                )
                continue
            if self.device.gl.compute_active and n <= 2048:
                texture = self.compute_gaussian_axis(
                    name + "_fft_crop%d" % axis, texture, kernel, size, axis, n, radius
                )
                continue
            permutation = (
                COMMON
                + """
                uniform float axis,bits,radius,length,inverse;
                void main(){
                    ivec2 p=ivec2(gl_FragCoord.xy);
                    int index=axis<0.5 ? p.x : p.y;
                    int reversed=0;
                    for(int i=0;i<int(bits);i++){ reversed=(reversed<<1)|(index&1);index>>=1; }
                    ivec2 q=axis<0.5 ? ivec2(reversed,p.y) : ivec2(p.x,reversed);
                    if(inverse>0.5) color=texelFetch(t0,q,0)*texelFetch(t1,ivec2(reversed,0),0).r;
                    else {
                        if(reversed>=int(length+2.0*radius)){color=vec4(0.0);return;}
                        if(axis<0.5) q.x-=int(radius);else q.y-=int(radius);
                        color=vec4(reflected(t0,q).r,0.0,0.0,0.0);
                    }
                }
            """
            )
            butterfly = (
                COMMON
                + """
                uniform float axis,stage,sign,phase;
                void main(){
                    ivec2 p=ivec2(gl_FragCoord.xy);int index=axis<0.5 ? p.x : p.y;
                    int m=int(stage), half_m=m/2, lane=index&(half_m-1);
                    int base=(index&~(m-1))+lane;
                    ivec2 a=axis<0.5 ? ivec2(base,p.y) : ivec2(p.x,base);
                    ivec2 b=axis<0.5 ? ivec2(base+half_m,p.y) : ivec2(p.x,base+half_m);
                    vec2 first=texelFetch(t0,a,0).rg, second=texelFetch(t0,b,0).rg;
                    vec2 twiddle=texelFetch(t1,ivec2(lane,int(phase)),0).rg;
                    vec2 product=vec2(second.x*twiddle.x-second.y*twiddle.y,second.x*twiddle.y+second.y*twiddle.x);
                    color=vec4(first+((index&half_m)==0 ? product : -product),0.0,0.0);
                }
            """
            )
            for inverse in (False, True):
                twiddles = self.fft_twiddles(n, inverse)
                texture = self.run(
                    name + "_fft_permutation%d" % axis,
                    permutation,
                    shape[0],
                    shape[1],
                    (texture, kernel),
                    (
                        ("axis", float(axis)),
                        ("bits", float(bits)),
                        ("radius", float(radius)),
                        ("length", float(length)),
                        ("inverse", float(inverse)),
                    ),
                    storage=RG32F,
                )
                stage, index = 2, 0
                while stage <= n:
                    texture = self.run(
                        name + "_fft%d_%d" % (axis, index % 2),
                        butterfly,
                        shape[0],
                        shape[1],
                        (texture, twiddles),
                        (
                            ("axis", float(axis)),
                            ("stage", float(stage)),
                            ("phase", float(index)),
                            ("sign", 1.0 if inverse else -1.0),
                        ),
                        storage=RG32F,
                    )
                    stage *= 2
                    index += 1
            texture = self.run(
                name + "_fft_crop%d" % axis,
                COMMON
                + """
                uniform float axis,radius,normalization;
                void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                    p+=axis<0.5 ? ivec2(int(radius),0) : ivec2(0,int(radius));
                    color=vec4(texelFetch(t0,p,0).r/normalization); }
            """,
                size[0],
                size[1],
                (texture,),
                (("axis", float(axis)), ("radius", float(radius)), ("normalization", float(n))),
                storage=R32F,
            )
        return texture

    @staticmethod
    def _shared_fft_shader(n, vector=False):
        kind = "vec4" if vector else "vec2"
        multiply = "vec4(product(b.rg,t),product(b.ba,t))" if vector else "product(b,t)"
        return (
            """
            layout(local_size_x=128) in;
            uniform sampler2D source;
            uniform int axis;
            layout(sl_binding_zero rgba32f) writeonly uniform image2D destination;
            shared KIND data[N];
            int reversed(int index){int result=0;
                for(int bit=0;bit<BITS;bit++){result=(result<<1)|(index&1);index>>=1;}
                return result;}
            vec2 product(vec2 a,vec2 b){return vec2(a.x*b.x-a.y*b.y,a.x*b.y+a.y*b.x);}
            ivec2 coordinate(int index){int row=int(gl_WorkGroupID.x);
                return axis==0 ? ivec2(index,row) : ivec2(row,index);}
            void fft(float sign){
                for(int stage=2;stage<=N;stage*=2){
                    int h=stage/2;
                    for(int pair=int(gl_LocalInvocationID.x);pair<N/2;pair+=128){
                        int lane=pair%h,base=pair/h*stage+lane;
                        KIND a=data[base],b=data[base+h];
                        float angle=sign*6.283185307179586*float(lane)/float(stage);
                        vec2 t=vec2(cos(angle),sin(angle));
                        KIND multiplied=MULTIPLY;
                        data[base]=a+multiplied;data[base+h]=a+(-multiplied);
                    }
                    barrier();
                }
            }
        """.replace("KIND", kind)
            .replace("MULTIPLY", multiply)
            .replace("BITS", str(int(round(math.log(n, 2)))))
            .replace("N", str(n))
        )

    def compute_gaussian_axis(self, name, texture, kernel, size, axis, n, radius):
        device, gl = self.device, self.device.gl
        target = device.target(name, *size, storage=R32F)
        program = device.compute_program(
            "shared_gaussian_fft_%d" % n,
            self._shared_fft_shader(n).replace(
                "layout(sl_binding_zero rgba32f)", "layout(sl_binding_zero r32f)"
            )
            + """
            uniform sampler2D kernel; uniform int radius;
            float reflect_index(float p,float n){if(n<=1.0)return 0.0;
                float x=mod(p,2.0*(n-1.0));return min(x,2.0*(n-1.0)-x);}
            void main(){
                ivec2 size=textureSize(source,0);int length=axis==0 ? size.x : size.y;
                int thread=int(gl_LocalInvocationID.x);
                for(int index=thread;index<N;index+=128){
                    int r=reversed(index);
                    if(r>=length+2*radius)data[index]=vec2(0.0);
                    else {
                        int p=int(reflect_index(float(r-radius),float(length)));
                        data[index]=vec2(texelFetch(source,coordinate(p),0).r,0.0);
                    }
                }
                barrier();fft(-1.0);
                for(int index=thread;index<N;index+=128)data[index]*=texelFetch(kernel,ivec2(index,0),0).r;
                barrier();
                for(int index=thread;index<N;index+=128){int r=reversed(index);
                    if(r>index){vec2 temporary=data[index];data[index]=data[r];data[r]=temporary;}}
                barrier();fft(1.0);
                for(int index=thread;index<length;index+=128)
                    imageStore(destination,coordinate(index),vec4(data[index+radius].r/float(N)));
            }
            """.replace("N", str(n)),
        )
        gl.UseProgram(program)
        for unit, (uniform, value) in enumerate((("source", texture), ("kernel", kernel))):
            gl.ActiveTexture(TEXTURE0 + unit)
            gl.BindTexture(TEXTURE_2D, value)
            device.uniform(program, uniform, unit, integer=True)
        device.uniform(program, "axis", axis, integer=True)
        device.uniform(program, "radius", radius, integer=True)
        gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, R32F)
        gl.DispatchCompute(size[1 - axis], 1, 1)
        gl.MemoryBarrier(0x2428)
        return target

    def gradient(self, name, clipped, height):
        sigma = max(8.0, min(self.width, self.height) * max(height, 0.12) * 0.16)
        blurred = self.gaussian(name + "_blur", clipped, (self.width, self.height), sigma)
        return self.run(
            name,
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                float gx=reflected(t0,p+ivec2(1,-1)).r+2.0*reflected(t0,p+ivec2(1,0)).r+reflected(t0,p+ivec2(1,1)).r
                        -reflected(t0,p+ivec2(-1,-1)).r-2.0*reflected(t0,p+ivec2(-1,0)).r-reflected(t0,p+ivec2(-1,1)).r;
                float gy=reflected(t0,p+ivec2(-1,1)).r+2.0*reflected(t0,p+ivec2(0,1)).r+reflected(t0,p+ivec2(1,1)).r
                        -reflected(t0,p+ivec2(-1,-1)).r-2.0*reflected(t0,p+ivec2(0,-1)).r-reflected(t0,p+ivec2(1,-1)).r;
                color=vec4(gx,gy,0.0,0.0); }
        """,
            self.width,
            self.height,
            (blurred,),
        )

    def draw_mrt(self, name, source, size, inputs=(), uniforms=()):
        targets = tuple(self.device.target(name + "_%d" % i, size[0], size[1]) for i in range(4))
        program = self.device.program(name, source)
        self.device.draw(
            program,
            targets[0],
            size[0],
            size[1],
            tuple(("t%d" % i, v) for i, v in enumerate(inputs)),
            uniforms,
            extra_targets=targets[1:],
        )
        return targets

    def meter_geometry(self, size):
        if self._meter_shape != size:
            width, height = size
            x = self.run(
                "meter_geometry_x",
                COMMON
                + """
                uniform vec2 size;
                void main(){ivec2 p=ivec2(gl_FragCoord.xy);float h=p.y==16 ? 0.78 : 0.92;
                    float char_h=max(4.0,floor(size.y*h)),char_w=max(4.0,floor(char_h*0.54));
                    float cx=floor((p.y==16 ? 0.5 : float(p.y)/15.0)*size.x);
                    float delta=(float(p.x)-cx)/max(char_w*0.86,1.0);float squared=delta*delta;
                    color=vec4(exp(-squared*1.8),squared,0.0,0.0);}
                """,
                width,
                17,
                uniforms=(("size", size),),
            )
            y = self.run(
                "meter_geometry_y",
                COMMON
                + """
                uniform vec2 size;
                void main(){ivec2 p=ivec2(gl_FragCoord.xy);float h=p.y==9 ? 0.78 : 0.92;
                    float baseline=p.y==9 ? 0.99 : 0.84*float(p.y)/8.0+h*0.48;
                    baseline=clamp(baseline,0.1,1.25);
                    float char_h=max(4.0,floor(size.y*h)),cy=floor(baseline*size.y)-char_h*0.48;
                    float delta=(float(p.x)-cy)/max(char_h*0.66,1.0);float squared=delta*delta;
                    float subject_y=clamp(baseline-h*0.48,0.0,1.0);
                    float upper=clamp((subject_y-float(p.x)/max(size.y-1.0,1.0))*2.2+0.35,0.15,1.0);
                    color=vec4(exp(0.9-squared*1.8),squared,upper,0.0);}
                """,
                height,
                10,
                uniforms=(("size", size),),
            )
            self._meter_basis, self._meter_shape = (x, y), size
        return self._meter_basis

    def meters(self, prepared):
        width, height = self.width, self.height
        gradient = self.gradient("gradient", prepared["clipped"], 0.92)
        camera_gradient = self.gradient("camera_gradient", prepared["clipped"], 0.78)
        features = self.run(
            "meter_features",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                vec4 linear=texelFetch(t0,p,0);
                float clipped=min(linear.a,texelFetch(t2,ivec2(0),0).r);
                vec3 srgb=display_rgb(linear.rgb);
                float maximum=max(srgb.r,max(srgb.g,srgb.b)), minimum=min(srgb.r,min(srgb.g,srgb.b));
                color=vec4(log(clipped+0.008),clipped*clipped,(maximum-minimum)/(maximum+EPS),texelFetch(t1,p,0).r); }
        """,
            width,
            height,
            (prepared["linear"], prepared["source_weights"], prepared["quantiles"]),
        )
        common = COMMON.replace(
            "out vec4 color;",
            "layout(location=0) out vec4 a;\nlayout(location=1) out vec4 b;\nlayout(location=2) out vec4 c;\nlayout(location=3) out vec4 d;",
        )
        shader = (
            common
            + """
            void main(){
                int placement=int(gl_FragCoord.x), chunk=int(gl_FragCoord.y);
                ivec2 size=textureSize(t0,0);
                float character_height=placement==144 ? 0.78 : 0.92;
                float center_x=placement==144 ? 0.5 : float(placement%16)/15.0;
                float baseline=placement==144 ? 0.99 : 0.84*float(placement/16)/8.0+character_height*0.48;
                baseline=clamp(baseline,0.1,1.25);
                float char_h=max(4.0,floor(float(size.y)*character_height));
                float char_w=max(4.0,floor(char_h*0.54));
                float cx=floor(center_x*float(size.x)), bottom=floor(baseline*float(size.y));
                float cy=bottom-char_h*0.48;
                float rx=max(char_w*0.86,1.0), ry=max(char_h*0.66,1.0);
                float subject_y=clamp(baseline-character_height*0.48,0.0,1.0);
                a=vec4(0.0);b=vec4(0.0);c=vec4(0.0);d=vec4(0.0);
                float clip_hi=texelFetch(t4,ivec2(0),0).r;
                for(int j=0;j<256;j++) {
                    int index=chunk*256+j;
                    if(index>=size.x*size.y) break;
                    ivec2 p=ivec2(index%size.x,index/size.x);
                    vec2 gx=texelFetch(t5,ivec2(p.x,placement==144 ? 16 : placement%16),0).rg;
                    vec3 gy=texelFetch(t6,ivec2(p.y,placement==144 ? 9 : placement/16),0).rgb;
                    float distance=gx.g+gy.g;
                    float weight=distance<=0.5 ? (distance<0.28 ? 0.18 : 1.0) : gx.r*gy.r;
                    vec4 linear=texelFetch(t0,p,0), features=texelFetch(t1,p,0);
                    float clipped=min(linear.a,clip_hi);
                    vec2 gradient=placement==144 ? texelFetch(t3,p,0).rg : texelFetch(t2,p,0).rg;
                    float upper=gy.b;
                    a+=vec4(linear.rgb,1.0)*weight;
                    b+=vec4(clipped,features.rgb)*weight;
                    c+=vec4(gradient,features.a,0.0)*weight;
                    d+=vec4(linear.rgb,1.0)*(weight*upper);
                }
            }
        """
        )
        rows = (width * height + 255) // 256
        inputs = (prepared["linear"], features, gradient, camera_gradient, prepared["quantiles"])
        inputs += self.meter_geometry((width, height))
        values = (
            self.device.opencl.meters("meter_partial", (width, height), inputs)
            if self.device.opencl is not None
            else self.draw_mrt("meter_partial", shader, (145, rows), inputs)
        )
        shader = (
            common
            + """
            void main(){ ivec2 origin=ivec2(int(gl_FragCoord.x),int(gl_FragCoord.y)*16);
                int rows=textureSize(t0,0).y;
                a=vec4(0.0);b=vec4(0.0);c=vec4(0.0);d=vec4(0.0);
                for(int y=0;y<16;y++) {
                    ivec2 p=origin+ivec2(0,y);if(p.y>=rows) break;
                    a+=texelFetch(t0,p,0);b+=texelFetch(t1,p,0);c+=texelFetch(t2,p,0);d+=texelFetch(t3,p,0);
                }
            }
        """
        )
        index = 0
        while rows > 1:
            rows = (rows + 15) // 16
            values = self.draw_mrt("meter_reduce%d" % index, shader, (145, rows), values)
            index += 1
        self.fields["meters"] = values
        self.fields["gradient"] = (gradient, width, height)
        return values

    def upload(self, name, size, values):
        texture = self.device.target(name, size[0], size[1])
        gl = self.device.gl
        gl.ActiveTexture(TEXTURE0)
        gl.BindTexture(TEXTURE_2D, texture)
        array = (GLfloat * len(values))(*values)
        gl.TexSubImage2D(TEXTURE_2D, 0, 0, 0, size[0], size[1], RGBA, FLOAT, C.cast(array, GLvoidp))
        return texture

    def probes(self, linear):
        width, height = self.width, self.height
        if self._probe_shape != (width, height):
            directions = (
                (-1, 0),
                (-0.7071, -0.7071),
                (0, -1),
                (0.7071, -0.7071),
                (1, 0),
                (0.7071, 0.7071),
                (0, 1),
                (-0.7071, 0.7071),
            )
            ys = {}
            y_values = []
            geometry = []
            for i in range(145):
                char_h = 0.78 if i == 144 else 0.92
                x = 0.5 if i == 144 else (i % 16) / 15.0
                baseline = 0.99 if i == 144 else min(0.84 * (i // 16) / 8.0 + char_h * 0.48, 1.25)
                y = min(max(baseline - char_h * 0.48, 0.0), 1.0)
                rx = min(max(char_h * 0.42, 0.12), 0.46)
                ry = min(max(char_h * 0.34, 0.10), 0.38)
                sx = max(width * min(max(char_h * 0.105, 0.035), 0.12), 2.0)
                sy = max(height * min(max(char_h * 0.105, 0.035), 0.12), 2.0)
                for dx, dy in directions:
                    tx = min(max(x + dx * rx, 0.0), 1.0) * max(width - 1, 1)
                    ty = min(max(y + dy * ry, 0.0), 1.0) * max(height - 1, 1)
                    key = (ty, sy)
                    if key not in ys:
                        ys[key] = len(ys)
                        y_values.extend((ty, sy, 0.0, 1.0))
                    geometry.extend((tx, sx, float(ys[key]), 0.0))
            self._probe_count = len(ys)
            self._probe_geometry = self.upload("probe_geometry", (8, 145), geometry)
            self._probe_y_geometry = self.upload("probe_y_geometry", (1, len(ys)), y_values)
            self._probe_y_weights = self.run(
                "probe_y_weights",
                COMMON
                + """
                void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                    vec4 geometry=texelFetch(t0,ivec2(0,p.y),0);
                    float distance=(float(p.x)-geometry.r)/geometry.g;
                    color=vec4(exp(-0.5*distance*distance)); }
            """,
                height,
                len(ys),
                (self._probe_y_geometry,),
            )
            self._probe_shape = (width, height)
        vertical = self.run(
            "probe_vertical",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);int height=textureSize(t0,0).y;
                vec4 sum=vec4(0.0);
                for(int y=0;y<height;y++) {
                    float weight=texelFetch(t1,ivec2(y,p.y),0).r;
                    sum+=vec4(texelFetch(t0,ivec2(p.x,y),0).rgb,1.0)*weight;
                }
                color=sum;
            }
        """,
            width,
            self._probe_count,
            (linear, self._probe_y_weights),
        )
        return self.run(
            "probes",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);vec4 geometry=texelFetch(t1,p,0);
                int width=textureSize(t0,0).x;
                vec4 sum=vec4(0.0);
                for(int x=0;x<width;x++) {
                    float distance=(float(x)-geometry.r)/geometry.g;
                    float weight=exp(-0.5*distance*distance);
                    sum+=texelFetch(t0,ivec2(x,int(geometry.b)),0)*weight;
                }
                vec3 sample_value=sum.rgb/(sum.a+EPS);
                color=vec4(display_chroma(sample_value),clamp(luma(sample_value),0.0,1.0));
            }
        """,
            8,
            145,
            (vertical, self._probe_geometry),
        )

    def global_statistics(self, prepared):
        w, h = self.width, self.height
        blurred = self.gaussian("grain_blur", prepared["linear"], (w, h), 1.1, 3)
        first = self.run(
            "global_features",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                float raw=texelFetch(t0,p,0).a;
                float clipped=min(raw,texelFetch(t2,ivec2(0),0).r);
                float highpass=raw-texelFetch(t1,p,0).r;
                color=vec4(clipped,clipped*clipped,highpass,highpass*highpass);
            }
        """,
            w,
            h,
            (prepared["linear"], blurred, prepared["quantiles"]),
        )
        laplacian = self.run(
            "laplacian",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                float lap=reflected(t0,p+ivec2(1,0)).a+reflected(t0,p+ivec2(-1,0)).a
                    +reflected(t0,p+ivec2(0,1)).a+reflected(t0,p+ivec2(0,-1)).a-4.0*texelFetch(t0,p,0).a;
                color=vec4(lap*lap); }
        """,
            w,
            h,
            (prepared["linear"],),
        )
        first = self.reduce("global_sum", first, (w, h))
        laplacian = self.reduce("laplacian_sum", laplacian, (w, h))
        return self.run(
            "global_statistics",
            COMMON
            + """
            uniform float count;
            void main(){
                vec4 sums=texelFetch(t0,ivec2(0),0)/count;
                float contrast=sqrt(max(sums.g-sums.r*sums.r,0.0))/(sums.r+0.035);
                float guard=smoothstep(0.18,0.245,sums.r)*(1.0-smoothstep(0.46,0.50,contrast));
                float grain=clamp(sqrt(max(sums.a-sums.b*sums.b,0.0))/0.055,0.0,1.0);
                float sharpness=clamp(sqrt(texelFetch(t1,ivec2(0),0).r/count)/0.18,0.0,1.0);
                float q97=texelFetch(t2,ivec2(2,0),0).r;
                float separation=(q97-texelFetch(t2,ivec2(3,0),0).r)/(q97+0.04);
                color=gl_FragCoord.x<1.0 ? vec4(sums.r,min(contrast,2.0),guard,separation) : vec4(grain,sharpness,0.0,0.0);
            }
        """,
            2,
            1,
            (first, laplacian, prepared["quantiles"]),
            (("count", float(w * h)),),
        )

    def join_lights(self, name, first, second):
        return self.run(
            name,
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy);
                color=p.x<6 ? texelFetch(t0,p,0) : texelFetch(t1,p-ivec2(6,0),0); }
        """,
            12,
            3,
            (first, second),
        )

    def synthesize(self, meters, physical, creative, global_stats, base_total):
        shader = (
            COMMON
            + """
            struct Light { vec4 position; vec4 color; float emission; bool creative; };
            Light raw_light(sampler2D source,int index,int offset) {
                Light v; v.position=texelFetch(source,ivec2(index+offset,0),0);
                v.color=texelFetch(source,ivec2(index+offset,1),0);
                v.emission=texelFetch(source,ivec2(index+offset,2),0).r;v.creative=false;return v;
            }
            Light disabled() {
                Light v;v.position=vec4(0.5,0.2,1.0,0.0);v.color=vec4(0.7353569,0.7353569,0.7353569,0.0);
                v.emission=0.0;v.creative=false;return v;
            }
            void main(){
                int index=int(gl_FragCoord.x), row=int(gl_FragCoord.y), offset=index==144 ? 6 : 0;
                float char_height=index==144 ? 0.78 : 0.92;
                float sx=index==144 ? 0.5 : float(index%16)/15.0;
                float baseline=index==144 ? 0.99 : min(0.84*float(index/16)/8.0+char_height*0.48,1.25);
                float sy=clamp(baseline-char_height*0.48,0.0,1.0);
                vec4 sums=texelFetch(t0,ivec2(index,0),0);
                float denominator=sums.a+EPS;
                vec4 local=texelFetch(t1,ivec2(index,0),0)/denominator;
                vec4 extra=texelFetch(t2,ivec2(index,0),0)/denominator;
                vec4 upper=texelFetch(t3,ivec2(index,0),0);
                vec4 global=texelFetch(t6,ivec2(0),0);
                vec3 ambient_linear=sums.rgb/denominator;
                float mean=local.r, adaptation=max(exp(local.g)-0.008,0.0);
                float contrast=sqrt(max(local.b-mean*mean,0.0))/(mean+0.035);
                float saturation=local.a;
                float source_total=0.58*texelFetch(t7,ivec2(0),0).r+0.42*extra.b*sums.a;
                Light components[6];int physical_count=0;
                for(int i=0;i<6;i++){
                    components[i]=raw_light(t4,i,offset);
                    if(texelFetch(t4,ivec2(i+offset,2),0).a>0.5) physical_count++;
                }
                int emitters[6];int emitter_count=0;float support[6];
                for(int i=0;i<6;i++){
                    support[i]=0.0;
                    if(i>=physical_count) continue;
                    Light v=components[i];
                    float lower=smoothstep(sy-0.06,sy+0.02,v.position.y);
                    float daylight=smoothstep(0.12,0.20,adaptation);
                    float broad_reflection=smoothstep(0.06,0.11,v.position.z);
                    if(physical_count>=2) broad_reflection=max(broad_reflection,1.0-smoothstep(0.54,0.70,v.emission));
                    // Reflected illumination retains direction; emission only
                    // controls point-source falloff in the surface shader.
                    support[i]=1.0-lower*daylight*broad_reflection;
                    emitters[emitter_count]=i;emitter_count++;
                }
                bool broad=emitter_count==0;
                vec2 position=vec2(0.5,0.2);vec3 light_linear=vec3(1.0,0.96,0.9);
                float radius=1.0,confidence=0.0;
                if(source_total>EPS){
                    if(!broad){
                        Light dominant=components[emitters[0]];
                        position=dominant.position.xy;radius=dominant.position.z;
                        light_linear=linear_rgb(dominant.color.rgb);
                    } else {position=vec2(sx,clamp(sy-0.42,0.04,0.42));light_linear=upper.rgb/(upper.a+EPS);}
                    confidence=clamp(0.68*global.a+0.32*(1.0-radius),0.0,1.0);
                    if(!broad) confidence=max(confidence,components[emitters[0]].color.a);
                    float magnitude=length(extra.rg);
                    float gradient_confidence=clamp(magnitude/(mean+0.025)*28.0,0.0,1.0);
                    if(gradient_confidence>0.015){
                        vec2 gradient_position=clamp(vec2(sx,sy)+extra.rg/(magnitude+EPS)*0.52,0.0,1.0);
                        if(broad) gradient_position.y=min(gradient_position.y,sy-0.12);
                        float blend=(broad ? 0.72 : 0.42)*gradient_confidence;
                        position=mix(position,gradient_position,blend);
                        confidence=max(confidence,gradient_confidence*0.72);
                    }
                    if(broad){position.y=min(position.y,sy-0.12);confidence=min(confidence,0.58);}
                    else if(radius>0.8 && confidence<0.32 && position.y>sy-0.1){
                        float prior=clamp((0.32-confidence)/0.32*1.1,0.0,0.84);
                        position.y=mix(position.y,clamp(sy-0.42,0.04,0.42),prior);
                    }
                }
                float primary_support=broad ? 0.0 : support[emitters[0]];
                if(!broad && primary_support<1.0 && source_total>EPS){
                    vec2 diffuse_position=vec2(sx,clamp(sy-0.42,0.04,0.42));
                    float diffuse_confidence=clamp(0.68*global.a,0.0,1.0);
                    float magnitude=length(extra.rg);
                    float gradient_confidence=clamp(magnitude/(mean+0.025)*28.0,0.0,1.0);
                    if(gradient_confidence>0.015){
                        vec2 gradient_position=clamp(vec2(sx,sy)+extra.rg/(magnitude+EPS)*0.52,0.0,1.0);
                        gradient_position.y=min(gradient_position.y,sy-0.12);
                        diffuse_position=mix(diffuse_position,gradient_position,0.72*gradient_confidence);
                        diffuse_confidence=max(diffuse_confidence,gradient_confidence*0.72);
                    }
                    diffuse_position.y=min(diffuse_position.y,sy-0.12);
                    position=mix(diffuse_position,position,primary_support);
                    light_linear=mix(upper.rgb/(upper.a+EPS),light_linear,primary_support);
                    radius=mix(1.0,radius,primary_support);
                    confidence=mix(min(diffuse_confidence,0.58),confidence,primary_support);
                }
                vec3 ambient_chroma=chroma(ambient_linear,2.2);
                vec3 light_chroma=chroma(light_linear,2.4);
                vec3 shadow_chroma=clamp(ambient_chroma*vec3(0.91,0.96,1.07),0.45,2.2);
                vec3 ambient_display=clamp(display_rgb(ambient_chroma*0.5),0.0,1.0);
                vec3 light_display=clamp(display_rgb(light_chroma*0.5),0.0,1.0);
                vec3 shadow_display=clamp(display_rgb(shadow_chroma*0.5),0.0,1.0);
                Light lights[4];for(int i=0;i<4;i++) lights[i]=disabled();
                lights[0].position=vec4(position,radius,broad ? 1.0 : components[emitters[0]].position.a);lights[0].color=vec4(light_display,confidence);
                lights[0].emission=broad ? 0.0 : components[emitters[0]].emission*primary_support;
                int count=1;
                for(int i=1;i<6;i++){
                    if(i>=emitter_count) break;
                    Light v=components[emitters[i]];
                    v.position.a*=support[emitters[i]];
                    if(count<4){lights[count]=v;count++;}
                    if(count>=4) break;
                }
                Light families[3];
                for(int i=0;i<3;i++){families[i]=disabled();families[i].creative=true;}
                for(int i=0;i<3;i++){
                    if(texelFetch(t5,ivec2(i+offset,2),0).a<0.5) continue;
                    Light v=raw_light(t5,i,offset);v.creative=true;
                    int family=i;
                    if(v.position.a*v.color.a>families[family].position.a*families[family].color.a) families[family]=v;
                }
                float creative_evidence=0.0;
                vec3 primary_chroma=chroma(linear_rgb(light_display),2.4);
                for(int i=0;i<3;i++){
                    Light a=families[i];vec3 ac=chroma(linear_rgb(a.color.rgb),2.4);
                    if(a.position.a<=0.0 || a.color.a<=0.0)continue;
                    if(confidence>0.0){
                        float single=(1.0-smoothstep(0.22,0.40,length(primary_chroma-1.0)))
                            *smoothstep(0.45,0.80,length(primary_chroma-ac))
                            *smoothstep(0.10,0.24,length(position-a.position.xy))
                            *smoothstep(0.72,0.90,a.position.a)*smoothstep(0.72,0.90,a.color.a);
                        creative_evidence=max(creative_evidence,single);
                    }
                    for(int j=0;j<3;j++)if(j>i){
                        Light b=families[j];vec3 bc=chroma(linear_rgb(b.color.rgb),2.4);
                        float pair=smoothstep(0.55,0.95,length(ac-bc))
                            *smoothstep(0.04,0.24,length(a.position.xy-b.position.xy))
                            *smoothstep(0.0,0.85,min(a.position.a,b.position.a))
                            *smoothstep(0.0,0.82,min(a.color.a,b.color.a));
                        creative_evidence=max(creative_evidence,pair);
                    }
                }
                float nominal=clamp(0.82*(adaptation+0.65*max(mean-adaptation,0.0)*(1.0-smoothstep(0.025,0.12,adaptation))),0.0,0.58);
                float exposure=clamp(nominal/0.221169,0.0001,2.15)*pow(2.0,-0.42*global.b);
                float target=clamp(exposure*0.221169,0.0,0.58);
                float chroma_guard=smoothstep(0.30,0.46,mean)*smoothstep(0.62,0.90,radius)*
                    (1.0-smoothstep(0.34,0.60,confidence))*(1.0-smoothstep(0.12,0.35,lights[0].emission));
                if(row==0) color=vec4(clamp(mean,0.0,1.0),clamp(adaptation,0.0,1.0),clamp(contrast,0.0,2.0),clamp(saturation,0.0,1.0));
                else if(row==1) color=vec4(ambient_display,confidence);
                else if(row==2) color=vec4(shadow_display,radius);
                else if(row<24){
                    Light v=row<15 ? lights[(row-3)/3] : families[(row-15)/3];
                    int plane=(row-3)%3;
                    color=plane==0 ? v.position : (plane==1 ? v.color : vec4(v.emission,1.0,v.creative ? 1.0 : 0.0,1.0));
                }
                else if(row==24) color=vec4(creative_evidence,float(count),source_total,broad ? 1.0 : 0.0);
                else color=vec4(target,chroma_guard,global.b,confidence);
            }
        """
        )
        return self.run(
            "scene_state",
            shader,
            145,
            26,
            tuple(meters) + (physical, creative, global_stats, base_total),
        )

    def transport(self, state, probes):
        layout = self.run(
            "transport_layout",
            COMMON
            + """
            void main(){ float evidence=0.0;for(int i=0;i<144;i++) evidence=max(evidence,texelFetch(t0,ivec2(i,24),0).r);
                color=vec4(smoothstep(0.0,0.25,evidence)); }
        """,
            1,
            1,
            (state,),
        )
        return self.run(
            "transport",
            COMMON
            + """
            void main(){
                int plane=int(gl_FragCoord.x)/16, index=int(gl_FragCoord.y)*16+int(gl_FragCoord.x)%16;
                vec3 value=vec3(0.0);
                if(plane==0){vec4 v=texelFetch(t0,ivec2(index,0),0);value=vec3(v.b/2.0,v.a,v.r);}
                else if(plane==1) value=chroma(linear_rgb(texelFetch(t0,ivec2(index,1),0).rgb),2.4)/2.4;
                else if(plane==2) value=vec3(sqrt(texelFetch(t0,ivec2(index,25),0).r/0.58),texelFetch(t2,ivec2(0),0).r,0.75);
                else if(plane<15){
                    int slot=(plane-3)/3, kind=(plane-3)%3;
                    int row=3+slot*3;
                    vec4 position=texelFetch(t0,ivec2(index,row),0), c=texelFetch(t0,ivec2(index,row+1),0);
                    float emission=texelFetch(t0,ivec2(index,row+2),0).r;
                    value=kind==0 ? position.xyz : (kind==1 ? chroma(linear_rgb(c.rgb),2.4)/2.4 : vec3(position.a,c.a,emission));
                    if(slot>0){
                        int optional_row=15+(slot-1)*3;
                        vec4 optional_position=texelFetch(t0,ivec2(index,optional_row),0);
                        vec4 optional_color=texelFetch(t0,ivec2(index,optional_row+1),0);
                        vec3 optional_value=kind==0 ? optional_position.xyz : (kind==1 ? chroma(linear_rgb(optional_color.rgb),2.4)/2.4 : vec3(0.0,optional_color.a,optional_position.a));
                        value=mix(value,optional_value,texelFetch(t2,ivec2(0),0).r);
                    }
                } else if(plane<23) value=chroma(linear_rgb(texelFetch(t1,ivec2(plane-15,index),0).rgb),2.4)/2.4;
                else for(int channel=0;channel<3;channel++) {
                    int probe=(plane-23)*3+channel;
                    if(probe<8) value[channel]=texelFetch(t1,ivec2(probe,index),0).a;
                }
                vec3 scaled=clamp(value,0.0,1.0)*255.0, integral=floor(scaled);
                vec3 rounded=floor(scaled+0.5);
                rounded=mix(rounded,integral+mod(integral,2.0),vec3(equal(scaled-integral,vec3(0.5))));
                color=vec4(rounded/255.0,1.0);
            }
        """,
            416,
            9,
            (state, probes, layout),
            storage=RGBA8,
        )

    def stabilize_light_order(self, physical, image, previous):
        """Keep emitter identities when scores are nearly tied, without filtering light values."""
        difference = self.run(
            "continuity_difference",
            COMMON
            + """
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);
                vec3 a=texelFetch(t0,p,0).rgb,b=texelFetch(t1,p,0).rgb;
                color=vec4(dot(abs(a-b),vec3(1.0/3.0)),dot(a+b,vec3(1.0/6.0)),0.0,0.0);}
            """,
            32,
            18,
            (image, previous[1]),
        )
        change = self.reduce("continuity_change", difference, (32, 18))
        return self.run(
            "continuous_physical",
            COMMON
            + """
            void main(){
                ivec2 p=ivec2(gl_FragCoord.xy);int offset=p.x/6*6,rank=p.x%6;
                vec2 change=texelFetch(t2,ivec2(0),0).rg/576.0;
                // A cut or a substantial flash uses the new scene immediately.
                if(change.r>0.01 && change.r>max(change.g,0.03)*0.35){
                    color=texelFetch(t0,p,0);return;
                }
                bool used[6];for(int i=0;i<6;i++)used[i]=false;
                int selected=0;
                for(int slot=0;slot<=rank;slot++){
                    int best=-1;
                    for(int i=0;i<6;i++)if(!used[i] && best<0)best=i;
                    vec4 strongest=texelFetch(t0,ivec2(offset+best,0),0);
                    vec4 old=texelFetch(t1,ivec2(offset+slot,0),0);
                    vec4 old_color=texelFetch(t1,ivec2(offset+slot,1),0);
                    int matched=-1;float distance=1e30;
                    if(old.a>0.0 && old_color.a>0.0){
                        for(int i=0;i<6;i++){
                            if(used[i])continue;
                            vec4 candidate=texelFetch(t0,ivec2(offset+i,0),0);
                            vec4 c=texelFetch(t0,ivec2(offset+i,1),0);
                            float d=length(candidate.xy-old.xy);
                            // Intensities are sqrt(score/best_score): 0.95
                            // represents roughly a ten-percent score margin.
                            if(candidate.a>=strongest.a*0.95 && c.a>0.0 &&
                               d<clamp(old.z*0.5,0.035,0.12) &&
                               length(c.rgb-old_color.rgb)<0.20 && d<distance){
                                matched=i;distance=d;
                            }
                        }
                    }
                    selected=matched>=0 ? matched : best;used[selected]=true;
                }
                color=texelFetch(t0,ivec2(offset+selected,p.y),0);
            }
            """,
            12,
            3,
            (physical, previous[0], change),
        )

    def solve(self, texture, source_size, previous=None):
        prepared = self.prepare(texture, source_size)
        physical, total = self.physical_components(
            "physical", prepared["source_weights"], prepared["linear"], prepared["texture_residual"]
        )
        creative = self.creative_components("creative", prepared["linear"])
        camera_weights = self.run(
            "camera_weights",
            COMMON
            + """
            void main(){ ivec2 p=ivec2(gl_FragCoord.xy),size=textureSize(t0,0);
                float char_h=max(4.0,floor(float(size.y)*0.78)),char_w=max(4.0,floor(char_h*0.54));
                vec2 center=vec2(floor(float(size.x)*0.5),floor(float(size.y)*0.99)-char_h*0.48);
                vec2 delta=(vec2(p)-center)/vec2(max(char_w*0.86,1.0),max(char_h*0.66,1.0));
                float distance=dot(delta,delta);
                float weight=exp(-max(distance-0.5,0.0)*1.8)*(distance<0.28 ? 0.18 : 1.0);
                color=texelFetch(t0,p,0)*(0.58+0.42*weight); }
        """,
            self.width,
            self.height,
            (prepared["source_weights"],),
            storage=R32F,
        )
        camera_physical, _ = self.physical_components(
            "camera_physical", camera_weights, prepared["linear"], prepared["texture_residual"]
        )
        # Hue radiance is scene-wide, so the global and camera solutions share
        # one reduction. Only their component-availability masks differ.
        camera_creative = self.supported_creative_components(
            "camera_creative", creative, camera_physical
        )
        creative = self.supported_creative_components("global_creative", creative, physical)
        physical = self.join_lights("joined_physical", physical, camera_physical)
        creative = self.join_lights("joined_creative", creative, camera_creative)
        history_image = None
        if previous is not None:
            small = self.resize(
                "continuity_area",
                prepared["linear"],
                (self.width, self.height),
                (32, 18),
                area=True,
            )
            history_image = self.run(
                "continuity_image",
                COMMON + "void main(){color=q8(texelFetch(t0,ivec2(gl_FragCoord.xy),0));}",
                32,
                18,
                (small,),
                storage=RGBA8,
            )
        meters = self.meters(prepared)
        probes = self.probes(prepared["linear"])
        global_stats = self.global_statistics(prepared)
        state = self.synthesize(meters, physical, creative, global_stats, total)
        transport = self.transport(state, probes)
        return {
            "transport": transport,
            "state": state,
            "probes": probes,
            "global_stats": global_stats,
            "prepared": prepared,
            "history_lights": physical,
            "history_image": history_image,
        }

    def fft2d(self, name, texture, size, inverse=False):
        # Callers retain only the kernel spectrum. Serial transforms can share
        # one permutation target and two butterfly targets across both axes.
        scratch = "complex_fft_%d_%d" % size
        for axis in (0, 1):
            n = size[axis]
            bits = int(round(math.log(n, 2)))
            if (
                self.device.opencl is not None
                and 2 <= n
                and n * 16 <= self.device.opencl.local_memory
            ):
                texture = self.device.opencl.fft_axis(
                    scratch + "_opencl%d" % axis,
                    texture,
                    size,
                    axis,
                    inverse,
                    self.fft_twiddles(n, inverse),
                )
                continue
            if self.device.gl.compute_active and 2 <= n <= 1024:
                device, gl = self.device, self.device.gl
                target = device.target(scratch + "_compute%d" % axis, *size)
                program = device.compute_program(
                    "shared_complex_fft_%d" % n,
                    self._shared_fft_shader(n, True)
                    + """
                    uniform float sign; uniform float normalization;
                    void main(){int thread=int(gl_LocalInvocationID.x);
                        for(int index=thread;index<N;index+=128)
                            data[index]=texelFetch(source,coordinate(reversed(index)),0);
                        barrier();fft(sign);
                        for(int index=thread;index<N;index+=128)
                            imageStore(destination,coordinate(index),data[index]/normalization);
                    }
                    """.replace("N", str(n)),
                )
                gl.UseProgram(program)
                gl.ActiveTexture(TEXTURE0)
                gl.BindTexture(TEXTURE_2D, texture)
                device.uniform(program, "source", 0, integer=True)
                device.uniform(program, "axis", axis, integer=True)
                device.uniform(program, "sign", 1.0 if inverse else -1.0)
                device.uniform(program, "normalization", float(n) if inverse else 1.0)
                gl.BindImageTexture(0, target, 0, False, 0, 0x88B9, RGBA32F)
                gl.DispatchCompute(size[1 - axis], 1, 1)
                gl.MemoryBarrier(0x2428)
                texture = target
                continue
            permutation = (
                COMMON
                + """
                uniform float axis,bits;
                void main(){ ivec2 p=ivec2(gl_FragCoord.xy);int i=axis<0.5 ? p.x : p.y;
                    int j=0;for(int b=0;b<int(bits);b++){j=(j<<1)|(i&1);i>>=1;}
                    color=texelFetch(t0,axis<0.5 ? ivec2(j,p.y) : ivec2(p.x,j),0); }
            """
            )
            texture = self.run(
                scratch + "_permutation",
                permutation,
                size[0],
                size[1],
                (texture,),
                (("axis", float(axis)), ("bits", float(bits))),
            )
            butterfly = (
                COMMON
                + """
                uniform float axis,stage,sign,normalization,phase;
                vec2 product(vec2 a,vec2 b){return vec2(a.x*b.x-a.y*b.y,a.x*b.y+a.y*b.x);}
                void main(){ ivec2 p=ivec2(gl_FragCoord.xy);int i=axis<0.5 ? p.x : p.y;
                    int m=int(stage),h=m/2,lane=i&(h-1),base=(i&~(m-1))+lane;
                    ivec2 ap=axis<0.5 ? ivec2(base,p.y) : ivec2(p.x,base);
                    ivec2 bp=axis<0.5 ? ivec2(base+h,p.y) : ivec2(p.x,base+h);
                    vec4 a=texelFetch(t0,ap,0),b=texelFetch(t0,bp,0);
                    vec2 t=texelFetch(t1,ivec2(lane,int(phase)),0).rg;vec4 multiplied=vec4(product(b.rg,t),product(b.ba,t));
                    color=(a+((i&h)==0 ? multiplied : -multiplied))/normalization;
                }
            """
            )
            stage, index = 2, 0
            twiddles = self.fft_twiddles(n, inverse)
            while stage <= n:
                texture = self.run(
                    scratch + "_%d" % (index % 2),
                    butterfly,
                    size[0],
                    size[1],
                    (texture, twiddles),
                    (
                        ("axis", float(axis)),
                        ("stage", float(stage)),
                        ("phase", float(index)),
                        ("sign", 1.0 if inverse else -1.0),
                        ("normalization", float(n) if inverse and stage == n else 1.0),
                    ),
                )
                stage *= 2
                index += 1
        return texture

    def annular_geometry(self):
        if self._annular_ready:
            return
        rx = 90 * 0.88 * 0.54 * 0.86
        ry = 90 * 0.88 * 0.66
        ex = min(159, int(math.ceil(rx * 2.5)))
        ey = min(89, int(math.ceil(ry * 2.5)))
        self._annular_extent = (ex, ey)
        shader = (
            COMMON
            + """
            uniform vec2 radius,extent;
            uniform float padded;
            void main(){ vec2 p=floor(gl_FragCoord.xy);
                if(padded>0.5){
                    vec2 size=vec2(512.0);p=mix(p,p-size,step(size-extent,p));
                    if(abs(p.x)>extent.x || abs(p.y)>extent.y){color=vec4(0.0);return;}
                }else p-=extent;
                float distance=dot(p/radius,p/radius);
                float weight=exp(-max(distance-0.5,0.0)*1.8)*(distance<0.28 ? 0.18 : 1.0);
                color=padded>0.5 ? vec4(weight,0.0,weight,0.0) : vec4(weight);
            }
        """
        )
        kernel = self.run(
            "annular_kernel",
            shader,
            512,
            512,
            uniforms=(("radius", (rx, ry)), ("extent", (ex, ey)), ("padded", 1.0)),
        )
        spectrum = self.fft2d("annular_kernel_transform", kernel, (512, 512))
        self._annular_spectrum = self.run(
            "annular_kernel_spectrum",
            COMMON + "void main(){color=texelFetch(t0,ivec2(gl_FragCoord.xy),0);}",
            512,
            512,
            (spectrum,),
        )
        kernel = self.run(
            "annular_spatial_kernel",
            shader,
            2 * ex + 1,
            2 * ey + 1,
            uniforms=(("radius", (rx, ry)), ("extent", (ex, ey)), ("padded", 0.0)),
        )
        prefix = (
            COMMON
            + """
            uniform vec2 stride;
            void main(){ivec2 p=ivec2(gl_FragCoord.xy),q=p-ivec2(stride);color=texelFetch(t0,p,0);
                if(q.x>=0 && q.y>=0) color+=texelFetch(t0,q,0);}
        """
        )
        for axis, n in ((0, 2 * ex + 1), (1, 2 * ey + 1)):
            step, index = 1, 0
            while step < n:
                kernel = self.run(
                    "annular_prefix%d_%d" % (axis, index % 2),
                    prefix,
                    2 * ex + 1,
                    2 * ey + 1,
                    (kernel,),
                    (("stride", (step, 0) if axis == 0 else (0, step)),),
                )
                step *= 2
                index += 1
        self._annular_denominator = self.run(
            "annular_denominator",
            COMMON
            + """
            uniform vec2 extent;
            float value(ivec2 p){return p.x<0 || p.y<0 ? 0.0 : texelFetch(t0,p,0).r;}
            void main(){ivec2 p=ivec2(gl_FragCoord.xy),e=ivec2(extent);
                ivec2 lo=max(-e,-p)+e,hi=min(e,ivec2(159,89)-p)+e;
                color=vec4(value(hi)-value(ivec2(lo.x-1,hi.y))-value(ivec2(hi.x,lo.y-1))+value(lo-1));}
        """,
            160,
            90,
            (kernel,),
            (("extent", (ex, ey)),),
        )
        self._annular_ready = True

    def scene_images(self, texture, source_size, state, global_stats):
        self.annular_geometry()
        small = self.resize("small_linear", texture, source_size, (160, 90), True)
        quantiles = self.quantiles(
            "small_quantiles", small, (160, 90), 3, (0.995, 0.995, 0.995, 0.995), unit_range=True
        )
        signal = self.run(
            "annular_signal",
            COMMON
            + """
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);
                if(p.x>=160 || p.y>=90){color=vec4(0.0);return;}
                vec4 v=texelFetch(t0,p,0);float clipped=min(v.a,texelFetch(t1,ivec2(0),0).r);
                // Remove the fixed log offset before packing two real
                // signals into one complex FFT. Black stays exactly zero.
                color=vec4(v.rgb,log((clipped+0.008)/0.008));}
        """,
            512,
            512,
            (small, quantiles),
        )
        spectrum = self.fft2d("annular_signal_transform", signal, (512, 512))
        multiplied = self.run(
            "annular_multiply",
            COMMON
            + """
            vec2 product(vec2 a,vec2 b){return vec2(a.x*b.x-a.y*b.y,a.x*b.y+a.y*b.x);}
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);vec4 a=texelFetch(t0,p,0);vec2 b=texelFetch(t1,p,0).rg;
                color=vec4(product(a.rg,b),product(a.ba,b));}
        """,
            512,
            512,
            (spectrum, self._annular_spectrum),
        )
        filtered = self.fft2d("annular_inverse", multiplied, (512, 512), True)
        irradiance = self.run(
            "irradiance",
            COMMON
            + """
            void main(){ivec2 p=ivec2(gl_FragCoord.xy);vec4 value=texelFetch(t0,p,0)/(texelFetch(t1,p,0).r+EPS);
                vec3 ambient=chroma(max(value.rgb,vec3(0.0)),2.4);
                float adaptation=max(exp(value.a)*0.008-0.008,0.0);
                float nominal=clamp(0.82*(adaptation+0.65*max(dot(value.rgb,vec3(0.2126,0.7152,0.0722))-adaptation,0.0)*(1.0-smoothstep(0.025,0.12,adaptation))),0.0,0.58);
                float exposure=clamp(nominal/0.221169,0.0001,2.15)*pow(2.0,-0.42*texelFetch(t2,ivec2(0),0).b);
                float target=clamp(exposure*0.221169,0.0,0.58);
                color=q8(vec4(ambient/2.4,target/0.58));}
        """,
            160,
            90,
            (filtered, self._annular_denominator, global_stats),
            storage=RGBA8,
        )
        emitter_field = self.run(
            "emitter_field",
            COMMON
            + """
            void main(){vec2 p=floor(gl_FragCoord.xy)/vec2(159.0,89.0);
                int count=int(texelFetch(t0,ivec2(144,24),0).g);
                float field=0.0;vec3 weighted=vec3(0.0);
                for(int i=0;i<4;i++){
                    if(i>=count)break;
                    vec4 light=texelFetch(t0,ivec2(144,3+i*3),0),c=texelFetch(t0,ivec2(144,4+i*3),0);
                    float radius=clamp(light.z*0.52,0.10,0.72);
                    vec2 delta=(p-light.xy)/radius;
                    float contribution=exp(-0.5*dot(delta,delta))*light.a*(0.42+0.58*c.a);
                    field+=contribution;weighted+=contribution*chroma(linear_rgb(c.rgb),2.4);
                }
                float sky=0.10+0.16*(1.0-p.y);field+=sky;
                weighted+=sky*chroma(linear_rgb(texelFetch(t0,ivec2(144,4),0).rgb),2.4);
                color=vec4(weighted,field);}
        """,
            160,
            90,
            (state,),
        )
        maximum = self.quantiles(
            "emitter_quantiles", emitter_field, (160, 90), 3, (0.995, 0.995, 0.995, 0.995)
        )
        emitter = self.run(
            "emitter",
            COMMON
            + """
            void main(){vec4 v=texelFetch(t0,ivec2(gl_FragCoord.xy),0);
                color=q8(vec4(clamp(v.rgb/(v.a+EPS),0.45,2.4)/2.4,clamp(v.a/(texelFetch(t1,ivec2(0),0).r+EPS),0.0,1.0)));}
        """,
            160,
            90,
            (emitter_field, maximum),
            storage=RGBA8,
        )
        return irradiance, emitter

    def wrap(self, texture, source_size, preview=False):
        if preview:
            value = self.resize("preview_wrap_area", texture, source_size, (160, 90), area=True)
            value = self.run(
                "preview_wrap_quantized",
                COMMON + "void main(){color=q8(texelFetch(t0,ivec2(gl_FragCoord.xy),0));}",
                160,
                90,
                (value,),
            )
            value = self.gaussian("preview_wrap_blur", value, (160, 90), 2.25)
            return self.run(
                "wrap",
                COMMON
                + "void main(){color=vec4(q8(texelFetch(t0,ivec2(gl_FragCoord.xy),0)).rgb,1.0);}",
                160,
                90,
                (value,),
                storage=RGBA8,
            )
        value = self.resize("wrap_linear", texture, source_size, (1280, 720), True)
        sigma = 18.0
        radius = 72
        stride = 8
        kernel = [math.exp(-0.5 * (j / sigma) ** 2) for j in range(-radius, radius + 1)]
        total = sum(kernel)
        kernel = [v / total for v in kernel]
        combined = [
            sum(kernel[j - t + radius] for t in range(stride) if 0 <= j - t + radius < len(kernel))
            / stride
            for j in range(-radius, radius + stride)
        ]
        for axis, size in ((0, (160, 720)), (1, (160, 90))):
            terms = []
            for j, weight in zip(range(-radius, radius + stride), combined):
                terms.append(
                    "total+=reflected(t0,origin+ivec2(%d,%d))*%.12g;"
                    % (j if axis == 0 else 0, j if axis == 1 else 0, weight)
                )
            shader = (
                COMMON
                + "void main(){ivec2 p=ivec2(gl_FragCoord.xy);ivec2 origin=p*ivec2(%d,%d);vec4 total=vec4(0.0);"
                % (stride if axis == 0 else 1, stride if axis == 1 else 1)
                + "\n".join(terms)
                + "color=total;}"
            )
            value = self.run("wrap_filter%d" % axis, shader, size[0], size[1], (value,))
        return self.run(
            "wrap",
            COMMON
            + "void main(){color=vec4(q8(vec4(display_rgb(max(texelFetch(t0,ivec2(gl_FragCoord.xy),0).rgb,vec3(0.0))),1.0)).rgb,1.0);}",
            160,
            90,
            (value,),
            storage=RGBA8,
        )

    def evaluate(self, texture, source_size, preview=False, animated=False, previous=None):
        """Produce all frame-dependent shader inputs from the displayed texture."""
        try:
            return self._evaluate(texture, source_size, preview, animated, previous)
        except ComputeUnavailable:
            # Compute accelerates component labeling/histograms. The raster
            # implementation implements the same model on older GL contexts.
            self.device.gl.compute_supported = False
            return self._evaluate(texture, source_size, preview, animated, previous)
        except self.device.opencl_exceptions as error:
            self.device.opencl_error = str(error)
            self.device.opencl.close()
            self.device.opencl = None
            return self._evaluate(texture, source_size, preview, animated, previous)

    def _evaluate(self, texture, source_size, preview, animated, previous=None):
        with State(self.device.gl):
            solved = self.solve(texture, source_size, previous)
            irradiance, emitter = self.scene_images(
                texture, source_size, solved["state"], solved["global_stats"]
            )
            wrap = self.wrap(texture, source_size, preview)
            # Ren'Py premultiplies PNG atlases; the Preview uploads their
            # straight bytes. Preserve that host contract at the final boundary.
            final = []
            for name, source in (("irradiance", irradiance), ("emitter", emitter), ("wrap", wrap)):
                final.append(
                    self.run(
                        "sampled_" + name,
                        COMMON
                        + """
                    uniform float premultiplied;
                    void main(){color=texelFetch(t0,ivec2(gl_FragCoord.xy),0);
                        if(premultiplied>0.5) color=vec4(q8(vec4(color.rgb*color.a,1.0)).rgb,color.a);}
                """,
                        160,
                        90,
                        (source,),
                        (("premultiplied", 0.0 if preview or name == "wrap" else 1.0),),
                        storage=RGBA8,
                        linear=True,
                    )
                )
            transport = self.run(
                "sampled_transport",
                COMMON
                + """
                void main(){ivec2 p=ivec2(gl_FragCoord.xy);
                    if(p.y<9) color=texelFetch(t0,p,0);
                    else {
                        float v=p.x<2 ? texelFetch(t1,ivec2(1,0),0)[p.x] : 0.0;
                        float bits=min(floor(clamp(v,0.0,1.0)*16777215.0+0.5),16777215.0);
                        color=vec4(floor(bits/65536.0),mod(floor(bits/256.0),256.0),mod(bits,256.0),255.0)/255.0;
                    }}
            """,
                416,
                10,
                (solved["transport"], solved["global_stats"]),
                storage=RGBA8,
                linear=True,
            )
            result = {
                "irradiance": final[0],
                "emitter": final[1],
                "wrap": final[2],
                "transport": transport,
            }
            if previous is not None:
                for name, size in (("history_lights", (12, 3)), ("history_image", (32, 18))):
                    result["_" + name] = self.run(
                        name + "_snapshot",
                        COMMON + "void main(){color=q8(texelFetch(t0,ivec2(gl_FragCoord.xy),0));}",
                        size[0],
                        size[1],
                        (solved[name],),
                        storage=RGBA8,
                    )
            return result
