"""Ren'Py texture ownership for the shared scene analyzer (Python 2 compatible).

All instances live on renpy.display, outside the save and rollback stores.
Displayables retain only serializable frame references. Scratch targets are shared
by the renderer; completed fields are ordinary, engine-owned RGBA8 textures.
"""

from __future__ import division

import ctypes
import inspect
import sys
import traceback
import weakref


class TextureUploadState(object):
    """Preserve only the state touched when refreshing existing RGBA textures."""

    def __init__(self, gpu, gl):
        self.gpu, self.gl = gpu, gl

    def __enter__(self):
        gl = self.gl
        self.active = gl.integer(0x84E0)
        gl.ActiveTexture(self.gpu.TEXTURE0)
        self.texture = gl.integer(0x8069)
        self.buffer = gl.integer(0x88EF)
        self.unpack = [(key, gl.integer(key)) for key in (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)]
        gl.BindBuffer(0x88EC, 0)
        for key, _value in self.unpack:
            gl.PixelStorei(key, 4 if key == 0x0CF5 else 0)
        return self

    def __exit__(self, *args):
        gl = self.gl
        for key, value in self.unpack:
            gl.PixelStorei(key, value)
        gl.BindBuffer(0x88EC, self.buffer)
        gl.BindTexture(self.gpu.TEXTURE_2D, self.texture)
        gl.ActiveTexture(self.active)
        return False


class Renderer(object):
    def __init__(self, gpu, api, config):
        self.gpu, self.api, self.config = gpu, api, config
        self.loader = None
        self.analysis = None
        self.disabled = False
        self.backgrounds = weakref.WeakKeyDictionary()
        self.frames = weakref.WeakKeyDictionary()
        self.frozen_canvases = weakref.WeakKeyDictionary()
        self.evaluations = 0
        self.cleanup_checked = False
        self.prepared = None
        self.prepared_frames = 0
        self.last_analysis_time = None
        self.prepared_pool = []
        self.prepared_releases = {}
        self.texture_transform = None

    def _context(self):
        draw = self.api.display.draw
        loader = getattr(draw, "texture_loader", None)
        if loader is None:
            return None
        if loader is not self.loader:
            # A destroyed GL context already owns reclamation of its objects.
            # Never delete old numeric GL names in a replacement context.
            self.loader = loader
            self.analysis = None
            self.disabled = False
            self.backgrounds.clear()
            self.frames.clear()
            self.frozen_canvases.clear()
            self.cleanup_checked = False
            self.last_analysis_time = None
            self.prepared_pool[:] = []
            self.prepared_releases.clear()
            # Newer Ren'Py renderers require a model-to-texture MatrixStack.
            # Inspect the bound method once per context; do not catch TypeError
            # from texture loading itself, which could hide an engine failure.
            self.texture_transform = None
            try:
                arguments = inspect.getfullargspec(draw.load_all_textures).args
            except (AttributeError, TypeError, ValueError):
                arguments = ()  # Python 2 / older Cython renderer.
            if "reverse" in arguments:
                from renpy.display.matrix import MatrixStack

                self.texture_transform = MatrixStack([1, 0, 0, 1])
        if self.disabled:
            return None
        if self.analysis is None:
            self.analysis = self.gpu.Analysis()
        return draw

    def capture(self, background, rendered, width, height, frame_factory):
        """Analyze the actual child render, including its final placement."""
        try:
            draw = self._context()
            if draw is None:
                return
            placement = tuple(background.child.get_placement())
            binding = getattr(background, "binding", background)
            previous = self.backgrounds.get(binding)
            animated = self._animated_shader(rendered)
            clock = self.api.game.interface.frame_time if animated else None
            signature = (rendered, placement, width, height, clock)
            if previous is not None and previous[0] == signature:
                return
            canvas = self.api.Render(width, height)
            offset = background.child.place(canvas, 0, 0, width, height, rendered)
            canvas.xclipping = canvas.yclipping = True
            prepared = (
                self.prepared.frame(background, rendered, width, height)
                if self.prepared is not None and not animated and offset in (None, (0, 0))
                else None
            )
            if prepared is not None:
                signature = (prepared[0], placement, width, height, None)
                if previous is not None and previous[0] == signature:
                    return
                self._capture_prepared(draw, binding, signature, prepared[1], frame_factory)
                return
            # Ren'Py maintains an FBO cache alongside the real GL binding.
            # Restore both when entering its texture loader from a displayable.
            saved_fbo = draw.current_fbo
            gl = self.analysis.device.gl
            try:
                with self.gpu.State(gl):
                    if not self.cleanup_checked:
                        self._check_texture_cleanup(draw)
                        self.cleanup_checked = True
                    if self.texture_transform is None:
                        draw.load_all_textures(canvas)
                    else:
                        draw.load_all_textures(canvas, self.texture_transform)
                    source = draw.render_to_texture(
                        canvas, properties={"drawable_resolution": animated, "mipmap": False}
                    )
                    old_fields = self.frames.get(previous[1], {}) if previous is not None else {}
                    history_keys = ("_history_lights", "_history_image")
                    history = (
                        tuple(old_fields[key].number for key in history_keys)
                        if all(key in old_fields for key in history_keys)
                        else ()
                    )
                    outputs = self.analysis.evaluate(
                        source.number,
                        (source.texture_width, source.texture_height),
                        previous=history,
                    )
                    self.last_analysis_time = self.api.game.interface.frame_time
                    fields = {}
                    for name, size in (
                        ("irradiance", (160, 90)),
                        ("emitter", (160, 90)),
                        ("wrap", (160, 90)),
                        ("transport", (416, 10)),
                        ("_history_lights", (12, 3)),
                        ("_history_image", (32, 18)),
                    ):
                        if name not in outputs:
                            continue
                        target = draw.render_to_texture(
                            self.api.Render(*size),
                            properties={"drawable_resolution": False, "mipmap": False},
                        )
                        self.analysis.device.bind_targets((outputs[name],))
                        gl.ActiveTexture(self.gpu.TEXTURE0)
                        gl.BindTexture(self.gpu.TEXTURE_2D, target.number)
                        gl.CopyTexSubImage2D(self.gpu.TEXTURE_2D, 0, 0, 0, 0, 0, *size)
                        fields[name] = target
            finally:
                draw.current_fbo = saved_fbo
            frame = frame_factory()
            self.frames[frame] = fields
            self.backgrounds[binding] = (
                signature,
                frame,
                animated,
                canvas if animated else None,
                offset or (0, 0),
            )
            self.evaluations += 1
        except Exception:
            self.disabled = True
            self.api.display.log.write(
                "SceneLight live analysis unavailable; using cached lighting.\n"
                + traceback.format_exc()
            )

    def _capture_prepared(self, draw, binding, signature, raw_fields, frame_factory):
        # A completed movie needs no analysis scratch textures or CL buffers.
        # Wait until live evaluation is idle so overlapping transitions retain
        # their analyzer rather than repeatedly destroying and rebuilding it.
        now = self.api.game.interface.frame_time
        if self.last_analysis_time is not None and now - self.last_analysis_time > 0.5:
            self.analysis.device.close()
            self.analysis = self.gpu.Analysis()
            self.last_analysis_time = None
        saved_fbo = draw.current_fbo
        gl = self.analysis.device.gl
        fields = self.prepared_pool.pop() if self.prepared_pool else {}
        state = TextureUploadState(self.gpu, gl) if fields else self.gpu.State(gl)
        try:
            with state:
                if not self.cleanup_checked:
                    self._check_texture_cleanup(draw)
                    self.cleanup_checked = True
                for name, size in (
                    ("irradiance", (160, 90)),
                    ("emitter", (160, 90)),
                    ("wrap", (160, 90)),
                    ("transport", (416, 10)),
                ):
                    target = fields.get(name)
                    if target is None:
                        target = draw.render_to_texture(
                            self.api.Render(*size),
                            properties={"drawable_resolution": False, "mipmap": False},
                        )
                    gl.ActiveTexture(self.gpu.TEXTURE0)
                    gl.BindTexture(self.gpu.TEXTURE_2D, target.number)
                    gl.TexSubImage2D(
                        self.gpu.TEXTURE_2D,
                        0,
                        0,
                        0,
                        size[0],
                        size[1],
                        self.gpu.RGBA,
                        self.gpu.UNSIGNED_BYTE,
                        ctypes.cast(ctypes.c_char_p(raw_fields[name]), ctypes.c_void_p),
                    )
                    fields[name] = target
        finally:
            draw.current_fbo = saved_fbo
        frame = frame_factory()
        self.frames[frame] = fields
        self.backgrounds[binding] = (signature, frame, False, None, (0, 0))
        owner = weakref.ref(self)
        key = id(frame)

        def released(_reference):
            renderer = owner()
            if renderer is not None:
                renderer.prepared_releases.pop(key, None)
                if len(renderer.prepared_pool) < 2:
                    renderer.prepared_pool.append(fields)

        self.prepared_releases[key] = weakref.ref(frame, released)
        self.prepared_frames += 1

    def _check_texture_cleanup(self, draw):
        loader = draw.texture_loader
        if not hasattr(loader, "get_texture_size"):
            return
        before = loader.get_texture_size()[0]
        temporary = self.api.Render(2, 2)
        draw.render_to_texture(
            temporary, properties={"drawable_resolution": False, "mipmap": False}
        )
        temporary.cached_texture = None
        if loader.get_texture_size()[0] > before:
            raise RuntimeError(
                "This Ren'Py runtime leaks graphics textures (including movie frames). "
                "Select a corrected Ren'Py 8 runtime, or SceneLight's verified Ren'Py 7 "
                "compatibility runtime for Python 2 games. Live analysis has been stopped "
                "to avoid amplifying the engine leak."
            )

    def frame(self, background):
        if self.disabled:
            return None
        previous = self.backgrounds.get(getattr(background, "binding", background))
        return previous[1] if previous is not None else None

    def animated(self, background):
        previous = self.backgrounds.get(getattr(background, "binding", background))
        return bool(previous is not None and previous[2] and not self.disabled)

    def canvas(self, background):
        previous = self.backgrounds.get(getattr(background, "binding", background))
        if previous is None or self.disabled or previous[3] is None:
            return None
        return previous[3], previous[4]

    def pin_canvas(self, background, reference):
        captured = self.canvas(background)
        if captured is None:
            return False
        canvas = captured[0]
        texture = getattr(canvas, "cached_texture", None)
        if texture is None:
            return False
        self.frozen_canvases[reference] = (texture, canvas.get_size())
        return True

    def frozen_canvas(self, reference):
        return self.frozen_canvases.get(reference) if reference is not None else None

    @staticmethod
    def _animated_shader(rendered):
        # u_time/u_random are supplied at draw time without changing Render
        # identity. Inspect the actual render tree, never displayable callbacks.
        module = sys.modules.get("renpy.gl2.gl2shadercache")
        parts = getattr(module, "shader_part", {})
        pending, seen = [rendered], set()
        while pending and len(seen) < 4096:
            node = pending.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for name in getattr(node, "shaders", ()) or ():
                part = parts.get(name)
                if part is None:
                    if not name.startswith("renpy."):
                        return True
                else:
                    uniforms = getattr(part, "uniforms", None)
                    if uniforms is None:
                        # Ren'Py 7.7/8.2 records declarations as three-tuples;
                        # newer versions expose the names in ``uniforms``.
                        uniforms = (
                            declaration[2]
                            for declarations in (
                                getattr(part, "vertex_variables", ()),
                                getattr(part, "fragment_variables", ()),
                            )
                            for declaration in declarations
                            if declaration[0] == "uniform"
                        )
                    if any(uniform in ("u_time", "u_random") for uniform in uniforms):
                        return True
            pending.extend(child[0] for child in (getattr(node, "children", ()) or ()))
        return bool(pending)

    def fields(self, frame):
        return self.frames.get(frame) if frame is not None else None
