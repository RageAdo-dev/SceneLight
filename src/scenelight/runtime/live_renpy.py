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
        self.retired_source_frame_time = None
        self.drawable = None
        # Every engine texture we asked for since the last drawable change.
        # Ren'Py's render caches can outlive our own containers, so the caches
        # are not enough to find them again at reset time.
        self.created_textures = []

    def _drawable_changed(self):
        # Ren'Py keeps the texture loader across a window resize and only swaps
        # the drawable underneath it, so the loader alone cannot tell us that
        # captured textures went stale: lighting captured against the old
        # drawable samples the wrong memory once the window changes size.
        # Every cache lookup has to check, because the frozen-canvas path
        # returns a captured render before any analysis runs. A stale entry
        # there composes the previous drawable's background at its old size,
        # which shows up as a scaled background leaving an unpainted band.
        draw = self.api.display.draw
        loader = getattr(draw, "texture_loader", None)
        if loader is None:
            return False
        drawable = (
            getattr(draw, "drawable_size", None),
            getattr(draw, "drawable_viewport", None),
        )
        new_context = loader is not self.loader
        if not new_context and drawable == self.drawable:
            return False
        if not new_context and self.analysis is not None:
            self.analysis.device.close()
        # A destroyed GL context already owns reclamation of its objects.
        # Never delete old numeric GL names in a replacement context.
        self.loader = loader
        self.drawable = drawable
        self.analysis = None
        self._detach_textures()
        if new_context:
            # Only a replacement GL context starts over. A resize must not
            # resurrect a renderer that stopped itself to protect the game.
            self.disabled = False
        self.backgrounds.clear()
        self.frames.clear()
        self.frozen_canvases.clear()
        self.cleanup_checked = False
        self.last_analysis_time = None
        self.prepared_pool[:] = []
        self.prepared_releases.clear()
        self.retired_source_frame_time = None
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
        return True

    @staticmethod
    def _detach_texture(texture):
        """Retire one engine texture so its finalizer cannot free a live name.

        Only real GL textures are touched, and the test has to use public
        attributes only: ``GLTexture`` exposes ``number`` and ``loaded``, while
        ``loader`` is a private Cython attribute Python cannot see. Keying off
        ``loader`` silently matched nothing. Ren'Py's ``Render`` also carries a
        ``loaded`` flag but no ``number``, and a render belongs to the game's
        own displayable tree: its state has to stay as the engine left it.
        """
        if texture is None:
            return
        if not (hasattr(texture, "number") and hasattr(texture, "loaded")):
            return
        try:
            texture.loaded = False
        except (AttributeError, TypeError):
            pass

    def _detach_textures(self):
        """Make our engine textures inert before the loader forgets them.

        Ren'Py reuses a single ``TextureLoader`` and re-runs
        ``TextureLoader.init()`` on every window resize. That call deletes
        every allocated GL name and then empties ``allocated``, while the
        Python textures that owned those names stay alive. Our lighting
        fields live outside the per-frame render tree, so nothing else drops
        them at resize time. When one is finally collected,
        ``GLTexture.__del__`` appends its now-stale number to the *current*
        ``free_list``; the next ``cleanup()`` then calls ``glDeleteTextures``
        on a name the renderer has since handed to a live texture. That is
        what paints the sprite as an opaque black quad after a drag. Clearing
        ``loaded`` first makes those finalizers no-ops.
        """
        candidates = list(self.created_textures)
        for fields in list(self.frames.values()):
            candidates.extend(fields.values())
        for fields in self.prepared_pool:
            candidates.extend(fields.values())
        for texture, _size in list(self.frozen_canvases.values()):
            candidates.append(texture)
        for signature, _frame, _animated, canvas, _offset in list(self.backgrounds.values()):
            candidates.append(signature[0] if signature else None)
            candidates.append(getattr(canvas, "cached_texture", None))
        self.created_textures[:] = []
        self.frames.clear()
        self.prepared_pool[:] = []
        self.frozen_canvases.clear()
        for texture in candidates:
            self._detach_texture(texture)

    def _own_texture(self, texture):
        """Remember one engine texture until the current drawable is replaced.

        Our own containers are not enough to find these again at reset time:
        a field set that already left ``frames`` is still reachable from the
        engine's render cache, and that cache releases it long after we did.
        """
        if texture is None:
            return
        self.created_textures.append(texture)
        if len(self.created_textures) > 512:
            self._prune_owned_textures()

    def _prune_owned_textures(self):
        """Drop entries nothing but this list still refers to.

        Releasing one here is safe: no GL context has been replaced since it
        was created, so its finalizer hands the loader a name the loader still
        tracks. Only textures a render cache is keeping alive have to stay, and
        those are exactly what the sweep at the next reset is for.
        """
        self.created_textures[:] = [
            texture for texture in self.created_textures if sys.getrefcount(texture) > 3
        ]

    def _context(self):
        draw = self.api.display.draw
        if getattr(draw, "texture_loader", None) is None:
            return None
        self._drawable_changed()
        if self.disabled:
            return None
        if self.analysis is None:
            self.analysis = self.gpu.Analysis()
        return draw

    def _release_retired_sources(self):
        now = self.api.game.interface.frame_time
        if now == self.retired_source_frame_time:
            return
        self.retired_source_frame_time = now
        for binding, previous in list(self.backgrounds.items()):
            signature, frame, animated, canvas, offset = previous
            retired_source = getattr(signature[0], "killed", False)
            retired_canvas = getattr(canvas, "killed", False)
            if retired_source or retired_canvas:
                # Ren'Py deliberately leaves texture-only children on killed
                # Renders (image-cache tiles use them). Rollback can retain our
                # binding, but must not retain that retired source graph.
                # Small completed lighting fields remain available to snapshots.
                self.backgrounds[binding] = (
                    (None,) + signature[1:] if retired_source else signature,
                    frame,
                    animated,
                    None if retired_canvas else canvas,
                    offset,
                )

    def snapshot(self, rendered):
        """Resolve mesh samplers before allocating a transition snapshot."""
        draw = self._context()
        if draw is None:
            return None
        saved_fbo = draw.current_fbo
        try:
            with self.gpu.State(self.analysis.device.gl):
                if self.texture_transform is None:
                    draw.load_all_textures(rendered)
                else:
                    draw.load_all_textures(rendered, self.texture_transform)
                return draw.render_to_texture(rendered)
        finally:
            draw.current_fbo = saved_fbo

    def capture(self, background, rendered, width, height, frame_factory):
        """Analyze the actual child render, including its final placement."""
        try:
            draw = self._context()
            if draw is None:
                return
            self._release_retired_sources()
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
                    self._own_texture(source)
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
                        self._own_texture(target)
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
                        self._own_texture(target)
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
        self._drawable_changed()
        if self.disabled:
            return None
        previous = self.backgrounds.get(getattr(background, "binding", background))
        return previous[1] if previous is not None else None

    def animated(self, background):
        self._drawable_changed()
        previous = self.backgrounds.get(getattr(background, "binding", background))
        return bool(previous is not None and previous[2] and not self.disabled)

    def canvas(self, background):
        self._drawable_changed()
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
        self._drawable_changed()
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
        # The sprite shader asks for its fields on every draw, so this is the
        # hottest lookup in the runtime. It still has to run the drawable check:
        # returning a field set captured before the window changed hands the
        # shader textures the new drawable has already reallocated.
        self._drawable_changed()
        return self.frames.get(frame) if frame is not None else None
