# SceneLight raw-asset resolver. This is inert during normal gameplay.
init -999 python:
    import hashlib
    import json
    import math
    import os
    import struct
    import sys
    import time
    import traceback
    import zlib

    try:
        import cPickle as _scenelight_pickle
    except ImportError:
        import pickle as _scenelight_pickle

    try:
        import pygame_sdl2 as _scenelight_pygame
    except ImportError:
        try:
            import pygame as _scenelight_pygame
        except ImportError:
            _scenelight_pygame = None

    try:
        _scenelight_string_types = (basestring,)
    except NameError:
        _scenelight_string_types = (str,)

    _scenelight_inventory_wait_started = [None]
    _scenelight_component_cache = {}
    _scenelight_shared_component_root = [None]
    _scenelight_deferred_composites = [None]
    _scenelight_deferred_composite_stream = [None]
    _scenelight_deferred_composite_count = [0]
    _scenelight_deferred_form_paths = [None]
    _scenelight_deferred_form_stream = [None]
    _scenelight_deferred_form_count = [0]

    def _scenelight_probe_texture_cleanup():
        # Exercise the compiled runtime, rather than trusting its version or
        # bundled source. Some Ren'Py 7 binaries omit Texture's finalizer.
        # Clearing our temporary Render's cache releases its only owner; the
        # loader's byte count falls immediately, before deferred GL deletion.
        draw = renpy.display.draw
        loader = getattr(draw, "texture_loader", None)
        if loader is None or not hasattr(loader, "get_texture_size"):
            return None
        before = loader.get_texture_size()[0]
        temporary = renpy.Render(2, 2)
        draw.render_to_texture(temporary, properties={"drawable_resolution": False, "mipmap": False})
        temporary.cached_texture = None
        return loader.get_texture_size()[0] <= before

    def _scenelight_atomic_replace(source, destination):
        # A separate SceneLight process polls this tiny checkpoint. Windows can
        # momentarily reject replace/remove while that reader is closing its
        # handle, especially in older Ren'Py 7/Python 2 runtimes. Keep the
        # atomic protocol and retry only the known sharing/access race.
        for attempt in range(80):
            try:
                replace = getattr(os, "replace", None)
                if replace is not None:
                    replace(source, destination)
                    return
                if os.path.exists(destination):
                    os.remove(destination)
                os.rename(source, destination)
                return
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32) or attempt == 79:
                    raise
                time.sleep(0.01)

    def _scenelight_checkpoint_temporary(marker):
        # A readable sprite filename plus `.surface-checkpoint.tmp` can cross
        # legacy Windows MAX_PATH inside a long managed-project root. Keep the
        # temporary marker in the same directory for atomic replace, but give it
        # a compact content-derived name independent of the sprite spelling.
        digest = hashlib.sha256(marker.encode("utf-8")).hexdigest()[:16]
        return os.path.join(os.path.dirname(marker), ".slcp-%s.tmp" % digest)

    def _scenelight_capture_temporary(filename, purpose, suffix):
        # Pixel and source-copy publication has the same MAX_PATH constraint as
        # marker publication. Preserve any format-significant suffix (notably
        # `.png`) without extending the user-derived sprite filename.
        identity = "%s\0%s" % (purpose, filename)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return os.path.join(
            os.path.dirname(filename),
            ".sl-%s-%s%s" % (purpose, digest, suffix),
        )

    def _scenelight_log(message):
        sys.stdout.write(message + "\n")
        sys.stdout.flush()

    def _scenelight_load_capture_plan(filename, signature, sprite_names):
        if not signature or not os.path.isfile(filename):
            return None
        try:
            stream = open(filename, "r")
            try:
                payload = json.load(stream)
            finally:
                stream.close()
            if payload.get("version") != 3 or payload.get("signature") != signature:
                return None
            if payload.get("sprite_names") != sorted(sprite_names):
                return None
            raw_planned = payload.get("planned_forms")
            raw_requests = payload.get("request_forms")
            if not isinstance(raw_planned, list) or not isinstance(raw_requests, dict):
                return None
            planned = set()
            for value in raw_planned:
                if not isinstance(value, _scenelight_string_types):
                    return None
                normalized = " ".join(value.lower().split())
                if normalized:
                    planned.add(normalized)
            requests = {}
            for requested_name, raw_forms in raw_requests.items():
                if (
                    not isinstance(requested_name, _scenelight_string_types)
                    or not isinstance(raw_forms, list)
                ):
                    return None
                normalized_request = " ".join(requested_name.lower().split())
                forms = set()
                for value in raw_forms:
                    if not isinstance(value, _scenelight_string_types):
                        return None
                    normalized = " ".join(value.lower().split())
                    if normalized:
                        forms.add(normalized)
                requests[normalized_request] = forms
            if not planned or not requests:
                return None
            return planned, requests
        except Exception:
            return None

    def _scenelight_save_capture_plan(
        filename,
        signature,
        sprite_names,
        planned_forms,
        request_forms,
    ):
        if not signature:
            return
        payload = {
            "version": 3,
            "signature": signature,
            "sprite_names": sorted(sprite_names),
            "planned_forms": sorted(planned_forms),
            "request_forms": dict(
                (name, sorted(forms)) for name, forms in sorted(request_forms.items())
            ),
        }
        temporary = filename + ".tmp"
        stream = open(temporary, "w")
        try:
            json.dump(payload, stream, separators=(",", ":"))
            stream.write("\n")
        finally:
            stream.close()
        _scenelight_atomic_replace(temporary, filename)

    def _scenelight_displayable_signature(displayable):
        """Identify a fully resolved static LayeredImage tree before rasterization."""
        displayable_type = displayable.__class__
        if (
            getattr(displayable_type, "__module__", "") != "renpy.display.layout"
            or getattr(displayable_type, "__name__", "") != "Flatten"
        ):
            return None
        try:
            serialized = _scenelight_pickle.dumps(displayable, protocol=2)
        except Exception:
            return None
        return hashlib.sha256(serialized).hexdigest()

    def _scenelight_load_structure_index(filename, output_relative):
        if not os.path.isfile(filename):
            return {}
        try:
            stream = open(filename, "r")
            try:
                payload = json.load(stream)
            finally:
                stream.close()
            forms = payload.get("forms")
            if payload.get("version") != 1 or not callable(getattr(forms, "items", None)):
                return {}
            prefix = output_relative.replace(os.sep, "/").rstrip("/") + "/sprite_"
            result = {}
            for signature, relative in forms.items():
                if (
                    not isinstance(signature, _scenelight_string_types)
                    or len(signature) != 64
                    or not isinstance(relative, _scenelight_string_types)
                    or not relative.startswith(prefix)
                ):
                    continue
                absolute = os.path.join(config.basedir, relative.replace("/", os.sep))
                composite_job = _scenelight_composite_job_path(relative)
                if (
                    (not os.path.isfile(absolute) or os.path.getsize(absolute) <= 32)
                    and not os.path.isfile(composite_job)
                ):
                    continue
                if not (
                    os.path.isfile(absolute + ".surface-checkpoint")
                    or os.path.isfile(absolute + ".surface-normalized")
                    or os.path.isfile(absolute + ".composite-normalized")
                    or os.path.isfile(composite_job)
                    or relative in (_scenelight_deferred_composites[0] or {})
                ):
                    continue
                result[signature] = relative
            return result
        except Exception:
            return {}

    def _scenelight_save_structure_index(filename, structures):
        temporary = filename + ".tmp"
        stream = open(temporary, "w")
        try:
            json.dump(
                {"version": 1, "forms": structures},
                stream,
                separators=(",", ":"),
                sort_keys=True,
            )
            stream.write("\n")
        finally:
            stream.close()
        _scenelight_atomic_replace(temporary, filename)

    def _scenelight_save_surface_image_atomic(surface, filename):
        temporary = _scenelight_capture_temporary(filename, "surface", ".png")
        try:
            renpy.display.scale.image_save_unscaled(surface, temporary)
            _scenelight_atomic_replace(temporary, filename)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def _scenelight_save_surface_fast(surface, filename):
        """Write a lossless low-CPU checkpoint for host-side normalization."""
        if _scenelight_pygame is None:
            _scenelight_save_surface_image_atomic(surface, filename)
            return
        temporary = _scenelight_capture_temporary(filename, "rgba", ".tmp")
        try:
            width, height = surface.get_size()
            raw = _scenelight_pygame.image.tostring(surface, "RGBA", False)
            destination = open(temporary, "wb")
            try:
                destination.write(b"SCENELIGHT_RGBA1")
                destination.write(struct.pack("<III", width, height, len(raw)))
                destination.write(zlib.compress(raw, 1))
            finally:
                destination.close()
            _scenelight_atomic_replace(temporary, filename)
        except Exception:
            if os.path.exists(temporary):
                os.remove(temporary)
            _scenelight_save_surface_image_atomic(surface, filename)

    def _scenelight_mark_surface_checkpoint(filename):
        marker = filename + ".surface-checkpoint"
        normalized_marker = filename + ".surface-normalized"
        temporary = _scenelight_checkpoint_temporary(marker)
        if os.path.exists(normalized_marker):
            os.remove(normalized_marker)
        stream = open(temporary, "w")
        try:
            stream.write("raw\n")
        finally:
            stream.close()
        _scenelight_atomic_replace(temporary, marker)

    def _scenelight_mark_scene_checkpoint(filename):
        marker = filename + ".scene-checkpoint"
        temporary = _scenelight_checkpoint_temporary(marker)
        stream = open(temporary, "w")
        try:
            stream.write("renderer\n")
        finally:
            stream.close()
        _scenelight_atomic_replace(temporary, marker)

    def _scenelight_plain_png_source(displayable):
        image_module = getattr(renpy.display, "im", None)
        image_type = getattr(image_module, "Image", None)
        if image_type is None or not isinstance(displayable, image_type):
            return None
        source_name = getattr(displayable, "filename", "")
        oversample = getattr(displayable, "get_oversample", lambda: 1)()
        if (
            isinstance(source_name, _scenelight_string_types)
            and source_name.lower().endswith(".png")
            and not getattr(displayable, "is_svg", False)
            and float(oversample) == 1.0
        ):
            return source_name
        return None

    def _scenelight_copy_source_png(source_name, relative):
        filename = os.path.join(config.basedir, relative)
        parent = os.path.dirname(filename)
        if not os.path.isdir(parent):
            try:
                os.makedirs(parent)
            except OSError:
                if not os.path.isdir(parent):
                    raise
        if os.path.isfile(filename):
            return
        temporary = _scenelight_capture_temporary(
            filename,
            "copy-%d" % os.getpid(),
            ".tmp",
        )
        source_file = None
        destination_file = None
        try:
            source_file = renpy.loader.load(source_name, directory="images")
            destination_file = open(temporary, "wb")
            while True:
                block = source_file.read(1024 * 1024)
                if not block:
                    break
                destination_file.write(block)
            destination_file.close()
            destination_file = None
            source_file.close()
            source_file = None
            _scenelight_atomic_replace(temporary, filename)
        finally:
            if destination_file is not None:
                destination_file.close()
            if source_file is not None:
                source_file.close()
            if os.path.exists(temporary):
                os.remove(temporary)

    def _scenelight_export_composite(displayable, relative):
        """Describe exact static PNG composition for parallel host assembly."""
        image_module = getattr(renpy.display, "im", None)
        composite_type = getattr(image_module, "Composite", None)
        component_relative_root = _scenelight_shared_component_root[0] or os.path.join(
            os.path.dirname(relative),
            "components",
        )
        layers = []
        layer_sizes = []

        def add_source(source_name, offset_x, offset_y):
            cached_source = _scenelight_component_cache.get(source_name)
            if cached_source is None:
                digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:20]
                component_relative = os.path.join(
                    component_relative_root,
                    "component_%s.png" % digest,
                )
                _scenelight_copy_source_png(source_name, component_relative)
                component_absolute = os.path.join(config.basedir, component_relative)
                source_stream = open(component_absolute, "rb")
                try:
                    header = source_stream.read(24)
                finally:
                    source_stream.close()
                if (
                    len(header) != 24
                    or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                ):
                    return False
                source_width, source_height = struct.unpack(">II", header[16:24])
                if (
                    source_width < 1
                    or source_height < 1
                    or source_width > 16384
                    or source_height > 16384
                ):
                    return False
                cached_source = (
                    component_relative,
                    int(source_width),
                    int(source_height),
                )
                _scenelight_component_cache[source_name] = cached_source
            component_relative, source_width, source_height = cached_source
            layers.append({
                "source": component_relative.replace(os.sep, "/"),
                "position": [int(offset_x), int(offset_y)],
            })
            layer_sizes.append((source_width, source_height))
            return True

        def collect(item, offset_x, offset_y):
            source_name = _scenelight_plain_png_source(item)
            if source_name is not None:
                return add_source(source_name, offset_x, offset_y)

            if not isinstance(item, composite_type):
                return False
            positions = tuple(getattr(item, "positions", ()))
            images = tuple(getattr(item, "images", ()))
            if len(positions) != len(images):
                return False
            start = len(layers)
            for position, child in zip(positions, images):
                if len(position) != 2:
                    del layers[start:]
                    return False
                child_x, child_y = position
                if int(child_x) != child_x or int(child_y) != child_y:
                    del layers[start:]
                    return False
                if not collect(child, offset_x + int(child_x), offset_y + int(child_y)):
                    del layers[start:]
                    return False
            return True

        if composite_type is not None and isinstance(displayable, composite_type):
            size = getattr(displayable, "size", None)
            if not size or len(size) != 2:
                return None
            width, height = int(size[0]), int(size[1])
            if width < 1 or height < 1 or width > 16384 or height > 16384:
                return None
            if not collect(displayable, 0, 0) or not layers:
                return None
            return {"size": [width, height], "layers": layers}

        # A resolved LayeredImage is normally Flatten(Fixed(...)). The fixed
        # children are already concrete PNGs and simple placement transforms,
        # so exporting that conservative subset avoids thousands of unstable
        # software-renderer passes. Unsupported layout, animation, shader,
        # crop, color, or geometry state deliberately falls back to Ren'Py.
        layout_module = getattr(renpy.display, "layout", None)
        transform_module = getattr(renpy.display, "transform", None)
        flatten_type = getattr(layout_module, "Flatten", None)
        multibox_type = getattr(layout_module, "MultiBox", None)
        null_type = getattr(layout_module, "Null", None)
        transform_type = getattr(transform_module, "Transform", None)
        if transform_type is not None and isinstance(displayable, transform_type):
            state = getattr(displayable, "state", None)
            matrixcolor = getattr(state, "matrixcolor", None) if state is not None else None
            matrixcolor_type = matrixcolor.__class__ if matrixcolor is not None else None
            placement = displayable.get_placement()
            transform_arguments = getattr(displayable, "arguments", None)
            safe_tint_arguments = transform_arguments is None
            if (
                not safe_tint_arguments
                and callable(getattr(transform_arguments, "values", None))
            ):
                safe_tint_arguments = True
                for argument_group in transform_arguments.values():
                    if not callable(getattr(argument_group, "items", None)):
                        safe_tint_arguments = False
                        break
                    for key, value in argument_group.items():
                        if key != "matrixcolor" or not (
                            value is matrixcolor or value == matrixcolor
                        ):
                            safe_tint_arguments = False
                            break
                    if not safe_tint_arguments:
                        break
            tint_defaults = {
                "additive": 0.0,
                "alpha": 1.0,
                "blend": None,
                "blur": None,
                "corner1": None,
                "corner2": None,
                "crop": None,
                "fit": None,
                "matrixtransform": None,
                "maxsize": None,
                "mesh": False,
                "mesh_pad": None,
                "nearest": None,
                "orientation": None,
                "perspective": None,
                "point_to": None,
                "rotate": None,
                "shader": None,
                "transform_anchor": False,
                "xpan": None,
                "xrotate": None,
                "xsize": None,
                "xtile": 1,
                "xzoom": 1.0,
                "ypan": None,
                "yrotate": None,
                "ysize": None,
                "ytile": 1,
                "yzoom": 1.0,
                "zoom": 1.0,
                "zpos": 0.0,
                "zrotate": None,
                "zzoom": False,
            }
            safe_tint_wrapper = (
                state is not None
                and matrixcolor_type is not None
                and getattr(matrixcolor_type, "__module__", "") == "store"
                and getattr(matrixcolor_type, "__name__", "") == "TintMatrix"
                and getattr(displayable, "function", None) is None
                and safe_tint_arguments
                and getattr(displayable, "forward", None) is None
                and getattr(displayable, "reverse", None) is None
                and placement
                and len(placement) == 7
                and all(value in (None, 0, 0.0) for value in placement[:6])
                and all(
                    getattr(state, key, expected) == expected
                    for key, expected in tint_defaults.items()
                )
                and all(
                    not ((key.startswith("u_") or key.startswith("gl_")) and value is not None)
                    for key, value in getattr(state, "__dict__", {}).items()
                )
            )
            if not safe_tint_wrapper:
                return None
            # SceneLight's established alpha-preserving SWDraw capture ignores
            # a top-level TintMatrix while resolving the same child pixels and
            # alpha. Unwrapping only this exact static wrapper reproduces that
            # output byte-for-byte and avoids one fallback render per variant.
            displayable = getattr(displayable, "child", None)
        if (
            flatten_type is None
            or multibox_type is None
            or null_type is None
            or transform_type is None
            or not isinstance(displayable, flatten_type)
        ):
            return None
        fixed = getattr(displayable, "child", None)
        if not isinstance(fixed, multibox_type):
            return None
        style = getattr(fixed, "style", None)
        if (
            getattr(fixed, "default_layout", None) != "fixed"
            or getattr(fixed, "adjust_times", False)
            or getattr(fixed, "scene_list", None) is not None
            or getattr(fixed, "layers", None) is not None
            or getattr(fixed, "layer_name", None) is not None
            or getattr(style, "box_layout", None) not in (None, "fixed")
            or bool(getattr(style, "order_reverse", False))
            or not bool(getattr(style, "xfit", False))
            or not bool(getattr(style, "yfit", False))
            or getattr(style, "fit_first", None) not in (None, False)
            or getattr(style, "xminimum", None) not in (None, 0)
            or getattr(style, "yminimum", None) not in (None, 0)
        ):
            return None
        if any(value not in (None, 0) for value in getattr(fixed, "start_times", ())):
            return None
        if any(value not in (None, 0) for value in getattr(fixed, "anim_times", ())):
            return None

        def simple_position(item):
            try:
                placement = item.get_placement()
            except Exception:
                return None
            if not placement or len(placement) != 7:
                return None
            xpos, ypos, xanchor, yanchor, xoffset, yoffset, subpixel = placement
            if (
                xpos not in (None, 0, 0.0)
                or ypos not in (None, 0, 0.0)
                or xanchor not in (None, 0, 0.0)
                or yanchor not in (None, 0, 0.0)
                or not isinstance(xoffset, (int, float))
                or not isinstance(yoffset, (int, float))
                or xoffset != xoffset
                or yoffset != yoffset
                or abs(xoffset) > 16384
                or abs(yoffset) > 16384
            ):
                return None
            if subpixel:
                # Ren'Py 7/8's software compositor floors the half-pixel
                # offsets used by common LayeredImage pose systems. Other
                # fractional placements retain the renderer fallback until
                # they have an exact cross-version rasterization contract.
                if xoffset != int(xoffset) and abs(xoffset + 0.5) > 0.000001:
                    return None
                if yoffset != int(yoffset) and abs(yoffset + 0.5) > 0.000001:
                    return None
                return int(math.floor(xoffset)), int(math.floor(yoffset))
            if xoffset != int(xoffset) or yoffset != int(yoffset):
                return None
            return int(xoffset), int(yoffset)

        def static_transform_is_identity(item):
            if not isinstance(item, transform_type):
                return False
            if (
                getattr(item, "function", None) is not None
                or getattr(item, "arguments", None) is not None
                or getattr(item, "forward", None) is not None
                or getattr(item, "reverse", None) is not None
            ):
                return False
            state = getattr(item, "state", None)
            if state is None:
                return False
            required_defaults = {
                "additive": 0.0,
                "alpha": 1.0,
                "blend": None,
                "blur": None,
                "corner1": None,
                "corner2": None,
                "crop": None,
                "fit": None,
                "matrixcolor": None,
                "matrixtransform": None,
                "maxsize": None,
                "mesh": False,
                "mesh_pad": None,
                "nearest": None,
                "orientation": None,
                "perspective": None,
                "point_to": None,
                "rotate": None,
                "shader": None,
                "transform_anchor": False,
                "xpan": None,
                "xrotate": None,
                "xsize": None,
                "xtile": 1,
                "xzoom": 1.0,
                "ypan": None,
                "yrotate": None,
                "ysize": None,
                "ytile": 1,
                "yzoom": 1.0,
                "zoom": 1.0,
                "zpos": 0.0,
                "zrotate": None,
                "zzoom": False,
            }
            for key, expected in required_defaults.items():
                if getattr(state, key, expected) != expected:
                    return False
            for key, value in getattr(state, "__dict__", {}).items():
                if (key.startswith("u_") or key.startswith("gl_")) and value is not None:
                    return False
            return True

        def static_png_source(item, depth=0):
            if item is None or depth > 4:
                return None
            source_name = _scenelight_plain_png_source(item)
            if source_name is not None:
                return source_name

            item_type = item.__class__
            item_module = getattr(item_type, "__module__", "")
            item_name = getattr(item_type, "__name__", "")
            if item_module == "renpy.display.image" and item_name == "ImageReference":
                target = getattr(item, "target", None)
                if target is None:
                    try:
                        if not item.find_target():
                            return None
                    except Exception:
                        return None
                    target = getattr(item, "target", None)
                return static_png_source(target, depth + 1)

            if item_name != "ATLTransform" or not static_transform_is_identity(item):
                return None
            if simple_position(item) != (0, 0):
                return None
            atl = getattr(item, "atl", None)
            if atl is None or bool(getattr(atl, "animation", False)):
                return None
            block = getattr(item, "block", None)
            if block is None:
                block = getattr(atl, "compiled_block", None)
            statements = tuple(getattr(block, "statements", ()))
            if len(statements) != 1 or tuple(getattr(block, "times", ())):
                return None
            statement = statements[0]
            statement_type = statement.__class__
            if (
                getattr(statement_type, "__module__", "") != "renpy.atl"
                or getattr(statement_type, "__name__", "") != "Child"
                or getattr(statement, "transition", None) is not None
            ):
                return None
            return static_png_source(getattr(statement, "child", None), depth + 1)

        def static_transform_source(item):
            if not static_transform_is_identity(item):
                return None
            return static_png_source(getattr(item, "child", None))

        children = tuple(getattr(fixed, "children", ()))
        if not children or len(children) > 256:
            return None
        raw_bounds = []
        for child in children:
            if isinstance(child, null_type):
                if getattr(child, "width", 0) not in (None, 0):
                    return None
                if getattr(child, "height", 0) not in (None, 0):
                    return None
                continue
            source_name = static_png_source(child)
            if source_name is None:
                source_name = static_transform_source(child)
            if source_name is None:
                return None
            position = simple_position(child)
            if position is None:
                return None
            before = len(layer_sizes)
            if not add_source(source_name, position[0], position[1]):
                return None
            source_width, source_height = layer_sizes[before]
            raw_bounds.append((position[0], position[1], source_width, source_height))

        if not layers or not raw_bounds:
            return None
        base_sizes = [
            (source_width, source_height)
            for offset_x, offset_y, source_width, source_height in raw_bounds
            if offset_x == 0 and offset_y == 0
        ]
        if not base_sizes:
            return None
        width = max(
            [value[0] for value in base_sizes]
            + [offset_x + source_width for offset_x, _, source_width, _ in raw_bounds]
        )
        height = max(
            [value[1] for value in base_sizes]
            + [offset_y + source_height for _, offset_y, _, source_height in raw_bounds]
        )
        if width < 1 or height < 1 or width > 16384 or height > 16384:
            return None
        if any(
            offset_x >= width
            or offset_y >= height
            or offset_x + source_width <= 0
            or offset_y + source_height <= 0
            for offset_x, offset_y, source_width, source_height in raw_bounds
        ):
            return None
        return {"size": [width, height], "layers": layers}

    def _scenelight_composite_job_path(relative):
        job_root = os.path.join(os.path.dirname(relative), "composite_jobs")
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
        return os.path.join(
            config.basedir,
            job_root,
            "composite_%s.json" % digest,
        )

    def _scenelight_load_deferred_composites(filename):
        result = {}
        if not os.path.isfile(filename):
            return result
        stream = open(filename, "r")
        try:
            for line in stream:
                try:
                    value = json.loads(line)
                    destination = value.get("destination")
                    manifest = value.get("manifest")
                    if (
                        isinstance(destination, _scenelight_string_types)
                        and callable(getattr(manifest, "get", None))
                    ):
                        result[destination.replace(os.sep, "/")] = manifest
                except Exception:
                    # A native crash can interrupt only the final append. Every
                    # earlier newline-delimited manifest remains reusable.
                    continue
        finally:
            stream.close()
        return result

    def _scenelight_form_key(name):
        """Return Ren'Py's order-independent identity for one image form."""

        parts = " ".join(str(name).lower().split()).split()
        if not parts:
            return ""
        return " ".join([parts[0]] + sorted(set(parts[1:])))

    def _scenelight_load_deferred_form_paths(filename):
        result = {}
        if not os.path.isfile(filename):
            return result
        stream = open(filename, "r")
        try:
            for line in stream:
                try:
                    value = json.loads(line)
                    name = value.get("name")
                    key = value.get("key")
                    relative = value.get("relative")
                    if isinstance(name, _scenelight_string_types) and isinstance(
                        relative,
                        _scenelight_string_types,
                    ):
                        if not isinstance(key, _scenelight_string_types):
                            key = _scenelight_form_key(name)
                        if key:
                            result[key] = relative.replace(os.sep, "/")
                except Exception:
                    continue
        finally:
            stream.close()
        return result

    def _scenelight_record_deferred_form(name, relative):
        paths = _scenelight_deferred_form_paths[0]
        stream = _scenelight_deferred_form_stream[0]
        if paths is None or stream is None:
            return
        form_key = _scenelight_form_key(name)
        if not form_key:
            return
        normalized_relative = relative.replace(os.sep, "/")
        if paths.get(form_key) == normalized_relative:
            return
        paths[form_key] = normalized_relative
        json.dump(
            {"key": form_key, "name": name, "relative": normalized_relative},
            stream,
            separators=(",", ":"),
        )
        stream.write("\n")
        _scenelight_deferred_form_count[0] += 1
        if _scenelight_deferred_form_count[0] % 32 == 0:
            stream.flush()

    def _scenelight_publish_composite_job(relative, manifest):
        deferred = _scenelight_deferred_composites[0]
        deferred_stream = _scenelight_deferred_composite_stream[0]
        if deferred is not None and deferred_stream is not None:
            normalized = relative.replace(os.sep, "/")
            deferred[normalized] = manifest
            json.dump(
                {"destination": normalized, "manifest": manifest},
                deferred_stream,
                separators=(",", ":"),
            )
            deferred_stream.write("\n")
            _scenelight_deferred_composite_count[0] += 1
            if _scenelight_deferred_composite_count[0] % 16 == 0:
                deferred_stream.flush()
            return
        destination = _scenelight_composite_job_path(relative)
        absolute_root = os.path.dirname(destination)
        if not os.path.isdir(absolute_root):
            try:
                os.makedirs(absolute_root)
            except OSError:
                if not os.path.isdir(absolute_root):
                    raise
        temporary = destination + ".tmp"
        stream = open(temporary, "w")
        try:
            json.dump(
                {
                    "destination": relative.replace(os.sep, "/"),
                    "manifest": manifest,
                },
                stream,
            )
        finally:
            stream.close()
        _scenelight_atomic_replace(temporary, destination)

    _scenelight_software_draw = [None]
    _scenelight_prior_draw = [None]

    def _scenelight_save_alpha_surface(displayable, relative):
        """Render one dynamic sprite without flattening its alpha in the GPU readback.

        Ren'Py versions before ``render_to_surface`` implement displayable
        screenshots by drawing into the active window framebuffer. That path
        reports the framebuffer as opaque and, on a scaled window, can also
        stretch a square sprite to the window aspect ratio. Ren'Py's bundled
        software compositor consumes the same resolved Render tree but writes
        a real alpha-bearing pygame surface. Selecting it for the isolated
        sprite-capture phase preserves LayeredImage, matrixcolor, ATL, and
        layout semantics without changing SceneLight's live shader path.
        """

        import renpy.display.swdraw as swdraw_module

        software_draw_type = getattr(swdraw_module, "SWDraw", None)
        if software_draw_type is None:
            raise Exception("Ren'Py has no alpha-preserving software compositor")

        software_draw = _scenelight_software_draw[0]
        if software_draw is None:
            software_draw = software_draw_type()
            # Ren'Py 8.5 moved these scale fields from ``reset`` to ``init``.
            # Calling ``init`` here would replace the game's live OpenGL
            # window, so provide the identity render-to-texture state directly.
            if not hasattr(software_draw, "draw_per_virt"):
                matrix_type = renpy.display.render.Matrix2D
                software_draw.draw_per_virt = 1.0
                software_draw.virt_to_draw = matrix_type(1.0, 0.0, 0.0, 1.0)
                software_draw.draw_to_virt = matrix_type(1.0, 0.0, 0.0, 1.0)
            if getattr(software_draw, "screen", None) is None:
                software_draw.screen = swdraw_module.surface(1, 1, True)
                software_draw.window = software_draw.screen
                software_draw.fullscreen_surface = software_draw.screen
            _scenelight_software_draw[0] = software_draw
        if renpy.display.draw is not software_draw:
            # Backgrounds are captured before forms. Clear their GPU Render
            # objects while the GPU renderer still owns them, then switch only
            # once for the complete sprite batch. Mixing cached GPU Textures
            # and software Surfaces across thousands of per-form switches can
            # crash native Ren'Py inside its compiled renderer.
            renpy.display.render.free_memory()
            # The image cache can retain renderer-owned textures separately
            # from the Render cache. Discard them before the handoff as well;
            # otherwise a later character form can feed a GL texture to the
            # software compositor and crash inside Ren'Py's compiled draw code.
            renpy.display.im.free_memory()
            if _scenelight_prior_draw[0] is None:
                _scenelight_prior_draw[0] = renpy.display.draw
            renpy.display.draw = software_draw

        rendered = renpy.render(
            displayable,
            config.screen_width,
            config.screen_height,
            0.0,
            0.0,
        )
        surface = software_draw.render_to_texture(rendered, True)

        filename = os.path.join(config.basedir, relative)
        _scenelight_save_surface_fast(surface, filename)
        _scenelight_mark_surface_checkpoint(filename)

    def _scenelight_render_to_file(
        displayable,
        relative,
        composite_captures,
        preserve_alpha=False,
    ):
        # Static Ren'Py image manipulators already have an exact, alpha-bearing
        # surface in the engine's image cache. Saving that surface avoids an
        # expensive GPU render/screenshot round-trip for every Composite form
        # while preserving the same source pixels. LayeredImages, transforms,
        # and other dynamic displayables continue through the renderer below.
        image_module = getattr(renpy.display, "im", None)
        image_base = getattr(image_module, "ImageBase", None)
        composite = _scenelight_export_composite(displayable, relative)
        if composite is not None:
            normalized_relative = relative.replace(os.sep, "/")
            composite_captures[normalized_relative] = composite
            _scenelight_publish_composite_job(relative, composite)
            return "composite"

        source_name = _scenelight_plain_png_source(displayable)
        if source_name is not None:
            # A plain PNG Image has no manipulator or dynamic render state.
            # Copy its verified archive/file bytes directly, then let the host
            # apply established renderer-alpha normalization.
            try:
                _scenelight_copy_source_png(source_name, relative)
                return "surface"
            except Exception:
                pass
        load_surface = getattr(renpy, "load_surface", None)
        if load_surface is None and image_module is not None:
            load_surface = getattr(image_module, "load_surface", None)
        if image_base is not None and load_surface is not None and isinstance(displayable, image_base):
            surface = load_surface(displayable)
            filename = os.path.join(config.basedir, relative)
            _scenelight_save_surface_fast(surface, filename)
            return "surface"

        if preserve_alpha:
            # Dynamic character forms must never go through a window
            # screenshot. Saving the software surface is also marked for the
            # established renderer-alpha normalization on the host, keeping
            # its edge semantics identical to static Composite/PNG captures.
            filename = os.path.join(config.basedir, relative)
            marker = filename + ".surface-checkpoint"
            normalized_marker = filename + ".surface-normalized"
            if os.path.isfile(filename) and os.path.isfile(normalized_marker):
                return "surface-normalized"
            if (
                os.path.isfile(filename)
                and os.path.getsize(filename) > 32
                and os.path.isfile(marker)
            ):
                return "surface-checkpoint"
            _scenelight_save_alpha_surface(displayable, relative)
            return "surface"

        render_to_file = getattr(renpy, "render_to_file", None)
        if render_to_file is not None:
            render_to_file(
                displayable,
                relative,
                width=config.screen_width,
                height=config.screen_height,
                resize=True,
            )
            return "renderer"

        # Ren'Py 7 predates renpy.render_to_file. Reproduce that API with the
        # renderer and surface hooks provided by the game's own engine.
        rendered = renpy.render(
            displayable,
            config.screen_width,
            config.screen_height,
            0.0,
            0.0,
        )
        screenshot = renpy.display.draw.screenshot
        try:
            # Ren'Py 7 and later accept only the render tree.
            surface = screenshot(rendered)
        except TypeError:
            # Ren'Py 6.99 also requires its fullscreen-video flag. This is the
            # renderer API bundled with the original DDLC release.
            surface = screenshot(rendered, False)
        surface = renpy.display.scale.smoothscale(
            surface,
            (rendered.width, rendered.height),
        )
        filename = os.path.join(config.basedir, relative)
        renpy.display.scale.image_save_unscaled(surface, filename)
        return "renderer"

    def _scenelight_temporal_displayable(displayable, depth=0, seen=None):
        """Identify displayables whose pixels can change while their image name stays fixed."""

        if displayable is None or depth > 8:
            return False
        if seen is None:
            seen = set()
        identity = id(displayable)
        if identity in seen:
            return False
        seen.add(identity)
        type_name = (
            getattr(displayable.__class__, "__module__", "")
            + "."
            + getattr(displayable.__class__, "__name__", "")
        ).lower()
        if any(
            marker in type_name
            for marker in ("animation", "atltransform", "dynamicdisplayable", "movie")
        ):
            return True
        for attribute in ("child", "displayable"):
            if _scenelight_temporal_displayable(
                getattr(displayable, attribute, None),
                depth + 1,
                seen,
            ):
                return True
        for attribute in ("children", "images"):
            values = getattr(displayable, attribute, ()) or ()
            for value in values:
                if _scenelight_temporal_displayable(value, depth + 1, seen):
                    return True
        return False

    def _scenelight_visible_sources(displayable, st=0.0, at=0.0, depth=0, seen=None):
        """Read the selected image tree without calling DynamicDisplayable callbacks."""
        if displayable is None or depth > 24:
            return []
        if seen is None:
            seen = set()
        if id(displayable) in seen:
            return []
        seen.add(id(displayable))
        filename = getattr(displayable, "filename", None)
        if isinstance(filename, (type(u""), type(b""))):
            return [filename.replace("\\", "/")]
        # TransitionAnimation.visit() returns ALL frames, not the visible one.
        images = getattr(displayable, "images", None)
        delays = getattr(displayable, "delays", None)
        if images and delays and len(images) == len(delays):
            total = sum(delays)
            if total <= 0:
                return []
            elapsed = (at if getattr(displayable, "anim_timebase", True) else st) % total
            for image, delay in zip(images, delays):
                if elapsed < delay:
                    return _scenelight_visible_sources(image, st, at, depth + 1, seen)
                elapsed -= delay
            return []
        result = []
        for attribute in ("child", "target", "displayable"):
            child = getattr(displayable, attribute, None)
            result.extend(_scenelight_visible_sources(child, st, at, depth + 1, seen))
        for child in getattr(displayable, "children", ()) or ():
            result.extend(_scenelight_visible_sources(child, st, at, depth + 1, seen))
        return sorted(set(result))

    def _scenelight_file_digest(filename):
        digest = hashlib.sha256()
        stream = open(filename, "rb")
        try:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        finally:
            stream.close()
        return digest.hexdigest()

    def _scenelight_render_scene_sample(displayable, relative, seconds):
        filename = os.path.join(config.basedir, relative)
        marker = filename + ".scene-checkpoint"
        # Advance the displayable even on checkpoint hits: its selected child
        # is part of the frame's identity, not just its saved pixel bytes.
        rendered = renpy.render(displayable, config.screen_width, config.screen_height,
                                float(seconds), float(seconds))
        if (
            os.path.isfile(filename)
            and os.path.getsize(filename) > 32
            and os.path.isfile(marker)
        ):
            return relative.replace(os.sep, "/")
        rendered = renpy.render(
            displayable,
            config.screen_width,
            config.screen_height,
            float(seconds),
            float(seconds),
        )
        screenshot = renpy.display.draw.screenshot
        try:
            surface = screenshot(rendered)
        except TypeError:
            surface = screenshot(rendered, False)
        surface = renpy.display.scale.smoothscale(
            surface,
            (rendered.width, rendered.height),
        )
        _scenelight_save_surface_image_atomic(surface, filename)
        _scenelight_mark_scene_checkpoint(filename)
        return relative.replace(os.sep, "/")

    def _scenelight_capture_scene_timeline(name, timeline_root, live=False):
        """Inventory selected source states; the sample window is NOT a loop."""

        displayable = _scenelight_capture_displayable(name)
        sample_count = 160 if _scenelight_temporal_displayable(displayable) else 1
        if live:
            sample_count = 1
        interval_ms = 25
        sample_times = [index * interval_ms for index in range(sample_count)]
        # Legacy Animation exposes its entire finite list. Visit every frame
        # boundary even for long loops or frames shorter than the scan cadence.
        pending, seen = ([] if live else [displayable]), set()
        while pending and len(seen) < 256:
            current = pending.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            delays = getattr(current, "delays", None)
            if delays and len(delays) <= 2048:
                elapsed = 0.0
                for delay in delays:
                    sample_times.append(int(round(elapsed * 1000.0)) + 1)
                    elapsed += max(0.0, float(delay))
            for attribute in ("child", "target", "displayable"):
                pending.append(getattr(current, attribute, None))
        sample_times = sorted(set(sample_times))
        frames = []
        source_frames = {}
        relative_by_digest = {}
        for sample_index, time_ms in enumerate(sample_times):
            seconds = time_ms / 1000.0
            renpy.render(displayable, config.screen_width, config.screen_height, seconds, seconds)
            sources = _scenelight_visible_sources(displayable, seconds, seconds)
            # This inventory routes by source identity. Repeated selections
            # need no duplicate GPU readback, PNG encoding, or disk hash.
            if len(sources) == 1 and sources[0] in source_frames:
                frames.append([time_ms, source_frames[sources[0]]])
                continue
            sample_name = name if sample_index == 0 else "%s temporal %05d" % (name, time_ms)
            relative = os.path.join(
                timeline_root,
                _scenelight_capture_filename("scene", sample_name),
            )
            relative = _scenelight_render_scene_sample(
                displayable,
                relative,
                float(time_ms) / 1000.0,
            )
            absolute = os.path.join(config.basedir, relative.replace("/", os.sep))
            digest = _scenelight_file_digest(absolute)
            canonical = relative_by_digest.get(digest)
            if canonical is None:
                canonical = relative
                relative_by_digest[digest] = canonical
            elif canonical != relative:
                try:
                    os.remove(absolute)
                except OSError:
                    pass
                try:
                    os.remove(absolute + ".scene-checkpoint")
                except OSError:
                    pass
            frames.append([time_ms, canonical])
            if len(sources) == 1:
                source_frames.setdefault(sources[0], canonical)
        return frames, source_frames

    def _scenelight_displayable_arguments():
        module = getattr(renpy.display, "displayable", None)
        if module is not None:
            arguments_type = getattr(module, "DisplayableArguments", None)
            if arguments_type is not None:
                return arguments_type()
        return renpy.display.core.DisplayableArguments()

    def _scenelight_registered_image_names():
        """Return registered image names on Ren'Py 6.99 through current Ren'Py."""
        list_images = getattr(renpy, "list_images", None)
        if list_images is None:
            list_images = getattr(getattr(renpy, "exports", None), "list_images", None)
        if list_images is not None:
            names = list_images()
        else:
            image_module = getattr(getattr(renpy, "display", None), "image", None)
            names = getattr(image_module, "images", {}).keys()

        result = []
        for name in names:
            if isinstance(name, (tuple, list)):
                result.append(" ".join(str(part) for part in name))
            else:
                result.append(str(name))
        return result

    def _scenelight_get_registered_image(name):
        getter = getattr(renpy, "get_registered_image", None)
        if getter is None:
            getter = getattr(getattr(renpy, "exports", None), "get_registered_image", None)
        if getter is not None:
            return getter(tuple(name))
        image_module = getattr(getattr(renpy, "display", None), "image", None)
        return getattr(image_module, "images", {}).get(tuple(name))

    def _scenelight_imspec_name(imspec):
        """Return the static image name carried by a Ren'Py AST imspec."""
        if not imspec:
            return None
        try:
            name = imspec[0]
        except Exception:
            return None
        if not isinstance(name, (tuple, list)) or not name:
            return None
        return " ".join(str(part).lower() for part in name if str(part).strip())

    def _scenelight_script_inventory(character_variable_tags, progress=None):
        """Recover scene/show names from compiled scripts without source files.

        Ren'Py preserves its statement AST after loading RPYC/RPA archives. A
        large number of games use names such as ``hotel day`` or ``room1``
        instead of DDLC's conventional ``bg residential`` family, so the AST
        is the authoritative cross-project inventory.
        """
        scenes = set()
        show_counts = {}
        hidden_tags = set()
        show_names = set()
        sequences = []
        sequence = []
        full_sequence = []
        script = getattr(getattr(renpy, "game", None), "script", None)
        statements = getattr(script, "all_stmts", ()) or ()
        say_type = getattr(getattr(renpy, "ast", None), "Say", ())
        statement_total = len(statements)
        if progress is not None and statement_total:
            progress("inventory", 0, statement_total)
        for statement_index, statement in enumerate(statements, 1):
            if (
                progress is not None
                and (
                    statement_index == 1
                    or statement_index % 500 == 0
                    or statement_index == statement_total
                )
            ):
                progress("inventory", statement_index, statement_total)
            filename = str(getattr(statement, "filename", "")).replace("\\", "/").lower()
            if filename.startswith("renpy/common/") or "/renpy/common/" in filename:
                continue
            statement_type = statement.__class__.__name__
            if statement_type == "Label":
                if sequence:
                    sequences.append(sequence)
                    sequence = []
                continue
            if statement_type == "Scene":
                name = _scenelight_imspec_name(getattr(statement, "imspec", None))
                if name:
                    scenes.add(name)
                sequence.append("scene")
                full_sequence.append("scene")
                continue
            # Compiled dialogue may be a TranslateSay (a Say subclass). Losing
            # its attributes also corrupts the inherited pose for later Show
            # statements, leaving the runtime without the matching surface.
            if isinstance(statement, say_type) or statement_type in ("Say", "TranslateSay"):
                attributes = getattr(statement, "attributes", None)
                who = str(getattr(statement, "who", "")).strip().lower()
                tag = character_variable_tags.get(who)
                temporary = list(getattr(statement, "temporary_attributes", None) or ())
                speaking = getattr(config, "speaking_attribute", None)
                if speaking and getattr(statement, "interact", True):
                    temporary.insert(0, speaking)
                for command, attrs in (("show", attributes), ("temporary", temporary)):
                    if tag and isinstance(attrs, (tuple, list)) and attrs:
                        name = " ".join([tag] + [str(part).lower() for part in attrs])
                        show_names.add(name)
                        show_counts[tag] = show_counts.get(tag, 0) + 1
                        sequence.append(command + " " + name)
                        full_sequence.append(command + " " + name)
                continue
            if statement_type not in ("Show", "Hide"):
                continue
            name = _scenelight_imspec_name(getattr(statement, "imspec", None))
            if not name:
                continue
            tag = name.split()[0]
            if statement_type == "Hide":
                hidden_tags.add(tag)
                event = "hide " + tag
            else:
                show_counts[tag] = show_counts.get(tag, 0) + 1
                show_names.add(name)
                event = "show " + name
            sequence.append(event)
            full_sequence.append(event)
        if sequence:
            sequences.append(sequence)
        if full_sequence:
            sequences.append(full_sequence)
        return scenes, show_counts, hidden_tags, show_names, sequences

    def _scenelight_plan_sequence(sequence, sprite_names, plan_form):
        """Resolve dialogue and show attributes through Ren'Py's own rules."""
        shown = renpy.display.image.ShownImageInfo()
        for event in sequence:
            command, _separator, value = str(event).partition(" ")
            if command == "scene":
                shown = renpy.display.image.ShownImageInfo()
                continue
            parts = tuple(value.lower().split())
            if not parts:
                continue
            if command == "hide":
                shown.predict_hide(None, parts)
                continue
            if command not in ("show", "temporary"):
                continue
            requested_name = " ".join(parts)
            try:
                canonical = shown.apply_attributes(None, parts[0], parts)
            except Exception:
                canonical = None
            if canonical is None:
                continue
            # Temporary dialogue/speaking attributes are visible for this line
            # only. apply_attributes is read-only; do not remember its result.
            if command == "show":
                shown.predict_show(None, canonical)
            if requested_name in sprite_names:
                plan_form(requested_name, " ".join(canonical))

    def _scenelight_capture_filename(kind, name):
        readable = "_".join(part for part in name.lower().split() if part)[:52]
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        return "%s_%s_%s.png" % (kind, readable, digest)

    def _scenelight_require_resolved_capture(displayable, name):
        """Reject Ren'Py's red missing-image Text before it becomes analysis data."""

        image_module = getattr(getattr(renpy, "display", None), "image", None)
        reference_type = getattr(image_module, "ImageReference", None)
        if reference_type is not None and isinstance(displayable, reference_type):
            # ImageReference.find_target() normally turns an unresolved image
            # into a small red Text displayable when developer mode is off.
            # That is suitable feedback while playing a game, but it is not a
            # character or background and must never be baked into SceneLight.
            if not displayable.find_target():
                raise Exception("Image '%s' not found." % name)
        return displayable

    def _scenelight_capture_displayable(name):
        """Resolve full image attributes, including LayeredImage arguments."""
        parts = tuple(name.split())
        if not parts:
            raise Exception("Empty image name")

        # Image lookup normally happens lazily when a show statement is
        # executed. Reproduce that longest-prefix lookup here so declarations
        # such as `layeredimage monika` can resolve `monika forward uniform
        # happ` even though the full tuple is not independently registered.
        for prefix_length in range(len(parts), 0, -1):
            prefix = parts[:prefix_length]
            original = _scenelight_get_registered_image(prefix)
            if original is None:
                continue

            attributes = parts[prefix_length:]
            if not attributes:
                if isinstance(original, renpy.Displayable):
                    return _scenelight_require_resolved_capture(original, name)
                duplicate = getattr(original, "_duplicate", None)
                if duplicate is not None:
                    args = _scenelight_displayable_arguments()
                    args.name = prefix
                    args.args = ()
                    return _scenelight_require_resolved_capture(duplicate(args), name)
                return _scenelight_require_resolved_capture(
                    renpy.easy.displayable(original),
                    name,
                )

            duplicate = getattr(original, "_duplicate", None)
            if duplicate is None:
                continue
            args = _scenelight_displayable_arguments()
            args.name = prefix
            args.args = attributes
            return _scenelight_require_resolved_capture(duplicate(args), name)

        # Keep Ren'Py's ordinary conversion as the final path for filenames
        # and other displayable-like declarations.
        return _scenelight_require_resolved_capture(
            renpy.easy.displayable(" ".join(parts)),
            name,
        )

    def _scenelight_capture_assets():
        request_path = os.environ.get("SCENELIGHT_CAPTURE_REQUEST")
        if not request_path:
            return

        # This callback runs after Ren'Py has created the GPU context required
        # by render_to_file. Keep that context, but hide its temporary native
        # window so setup remains a single-window experience.
        if getattr(renpy, "windows", False):
            try:
                import ctypes

                capture_pid = os.getpid()
                user32 = ctypes.windll.user32

                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def hide_capture_window(hwnd, _lparam):
                    window_pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                    if window_pid.value == capture_pid:
                        user32.ShowWindow(hwnd, 0)
                    return True

                user32.EnumWindows(hide_capture_window, 0)
            except Exception:
                # Window hiding is presentation only; never sacrifice a valid
                # asset capture because a platform API was unavailable.
                pass

        with open(request_path, "r") as stream:
            request = json.load(stream)
        _scenelight_log(
            "SceneLight request loaded: %s (%d explicit forms)."
            % (
                os.path.basename(request_path),
                len(request.get("explicit_forms", ())),
            )
        )

        # Ren'Py 6.99 invokes start_interact callbacks once inside its OpenGL
        # benchmark, before the normal game interaction is ready. At that
        # point an archive-backed game's image registry can still be empty.
        # Waiting for the next interaction avoids publishing a false empty
        # inventory while preserving the early callback as a renderer probe.
        if getattr(renpy.config, "display_start_callbacks", None) is None:
            get_location = getattr(renpy, "get_filename_line", None)
            if get_location is None:
                get_location = getattr(getattr(renpy, "exports", None), "get_filename_line", None)
            if get_location is not None:
                current_filename = str(get_location()[0]).replace("\\", "/").lower()
                if current_filename.endswith("/00gltest.rpy"):
                    return

        output_relative = request["output_dir"].replace("/", os.sep)
        output_root = os.path.join(config.basedir, output_relative)
        if not os.path.isdir(output_root):
            os.makedirs(output_root)
        shared_component_value = request.get("component_dir")
        _scenelight_shared_component_root[0] = (
            str(shared_component_value).replace("/", os.sep)
            if shared_component_value
            else None
        )
        deferred_manifest_path = os.path.join(output_root, "composite_manifest.jsonl")
        deferred_forms_path = os.path.join(output_root, "capture_forms.jsonl")
        if request.get("defer_composites"):
            _scenelight_deferred_composites[0] = _scenelight_load_deferred_composites(
                deferred_manifest_path
            )
            _scenelight_deferred_composite_stream[0] = open(
                deferred_manifest_path,
                "a",
            )
            _scenelight_deferred_composite_count[0] = 0
            _scenelight_deferred_form_paths[0] = _scenelight_load_deferred_form_paths(
                deferred_forms_path
            )
            _scenelight_deferred_form_stream[0] = open(deferred_forms_path, "a")
            _scenelight_deferred_form_count[0] = 0
        else:
            _scenelight_deferred_composites[0] = None
            _scenelight_deferred_composite_stream[0] = None
            _scenelight_deferred_composite_count[0] = 0
            _scenelight_deferred_form_paths[0] = None
            _scenelight_deferred_form_stream[0] = None
            _scenelight_deferred_form_count[0] = 0
        structure_index_path = os.path.join(output_root, "capture_structures.json")
        structure_index = _scenelight_load_structure_index(
            structure_index_path,
            output_relative,
        )

        progress_value = request.get("progress")
        progress_path = (
            os.path.join(config.basedir, progress_value.replace("/", os.sep))
            if progress_value
            else None
        )

        def publish_progress(stage, current, total, requests=None, item=None):
            if progress_path is None or total <= 0:
                return
            payload = {
                "stage": stage,
                "current": int(current),
                "total": int(total),
            }
            if requests is not None:
                payload["requests"] = int(requests)
            if item is not None:
                payload["item"] = str(item)
            temporary_progress_path = progress_path + ".tmp"
            with open(temporary_progress_path, "w") as stream:
                json.dump(payload, stream)
                stream.write("\n")
            _scenelight_atomic_replace(temporary_progress_path, progress_path)

        character_tags = set(str(tag).split()[0] for tag in request.get("character_tags", ()))
        explicit_character_tags = set(
            str(tag).split()[0] for tag in request.get("explicit_character_tags", ())
        )
        excluded_character_tags = set(
            str(tag).split()[0] for tag in request.get("excluded_character_tags", ())
        )
        explicit_character_tags.difference_update(excluded_character_tags)
        manual_character_selection = request.get("character_selection") == "manual"
        review_only = bool(request.get("review_only"))
        review_tags = set(explicit_character_tags)
        review_representatives = {}
        character_hints = set()
        character_variable_tags = {}
        for variable_name, value in list(vars(renpy.store).items()):
            if not isinstance(value, renpy.character.ADVCharacter):
                continue
            tag = value.image_tag
            if not tag:
                tag = value.show_args.get("image")
            if isinstance(tag, _scenelight_string_types) and tag:
                normalized_tag = tag.split()[0]
                character_tags.add(normalized_tag)
                character_variable_tags[str(variable_name).strip().lower()] = normalized_tag
                continue

            # A Character without image= is common in third-party projects.
            # Keep its store variable and simple display name as conservative
            # hints, then require a matching registered image family and
            # actual story-level show use below. This is deliberately not a
            # blanket "every repeated show is a character" rule: that turns
            # CG pages, overlays, and UI art into expensive false sprites.
            for hint in (variable_name, getattr(value, "name", None)):
                if not isinstance(hint, _scenelight_string_types):
                    continue
                normalized_hint = hint.strip().lower()
                if normalized_hint and normalized_hint.replace("_", "").isalnum():
                    character_hints.add(normalized_hint)

        raw_explicit_forms = request.get("explicit_forms")
        explicit_sequence = (
            raw_explicit_forms is not None
            and not isinstance(raw_explicit_forms, _scenelight_string_types)
            and not callable(getattr(raw_explicit_forms, "get", None))
            and callable(getattr(raw_explicit_forms, "__iter__", None))
        )
        if explicit_sequence:
            explicit_forms = set(
                " ".join(str(name).lower().split())
                for name in raw_explicit_forms
                if str(name).strip()
            )
            script_scenes = set()
            script_show_counts = {}
            script_hidden_tags = set()
            script_show_names = set()
            script_sprite_sequences = []
        else:
            explicit_forms = None
            (
                script_scenes,
                script_show_counts,
                script_hidden_tags,
                script_show_names,
                script_sprite_sequences,
            ) = _scenelight_script_inventory(character_variable_tags, publish_progress)
        sprite_names = (
            set(explicit_forms)
            if explicit_forms is not None
            else set(
                " ".join(str(name).lower().split())
                for name in request.get("sprite_names", ())
            )
        )
        if explicit_forms is not None:
            _scenelight_log(
                "SceneLight worker received %d explicit sprite forms."
                % len(explicit_forms)
            )
        scene_names = set()
        if request.get("inventory_backgrounds") or request.get("inventory_characters"):
            registered_names = _scenelight_registered_image_names()
            if request.get("inventory_backgrounds"):
                scene_names.update(script_scenes)

            if request.get("inventory_characters"):
                scene_tags = set(name.split()[0] for name in script_scenes if name.split())
                registered_tags = set(
                    name.split()[0] for name in registered_names if name.split()
                )

                # ``show expression ... as tag`` creates a real story sprite
                # without registering an image family under that tag. Retain
                # repeated/hidden aliases for live runtime routing even though
                # there is no static form to capture. Registered families still
                # pass through the structural and geometry checks below, which
                # prevents repeatedly shown CG/UI images from becoming sprites.
                for tag, count in script_show_counts.items():
                    if (
                        tag not in registered_tags
                        and tag not in scene_tags
                        and tag not in ("expression", "layer", "screen")
                        and tag in character_hints
                        and (count > 1 or tag in script_hidden_tags)
                    ):
                        character_tags.add(tag)

                # A registered LayeredImage is direct structural evidence of
                # a sprite family. It remains valid even when all authored
                # scripts and declarations live inside RPA/RPYC archives.
                checked_tags = set()
                if registered_names:
                    publish_progress("families", 0, len(registered_names))
                for registered_index, registered_name in enumerate(registered_names, 1):
                    if (
                        registered_index == 1
                        or registered_index % 500 == 0
                        or registered_index == len(registered_names)
                    ):
                        publish_progress("families", registered_index, len(registered_names))
                    parts = tuple(registered_name.split())
                    if not parts or parts[0] in checked_tags or parts[0] in scene_tags:
                        continue
                    checked_tags.add(parts[0])
                    original = _scenelight_get_registered_image((parts[0],))
                    if (
                        original is not None
                        and original.__class__.__name__.lower() == "layeredimage"
                    ):
                        character_tags.add(parts[0])
                        review_tags.add(parts[0])

                # For conventional static sprite families, accept only hints
                # derived from real Character objects and corroborated by the
                # compiled story AST. This covers archive-only projects while
                # leaving repeatedly shown CG/UI families untouched.
                for hint in character_hints:
                    if (
                        hint in registered_tags
                        and hint in script_show_counts
                        and hint not in scene_tags
                    ):
                        character_tags.add(hint)

                review_tags.update(character_tags)

                # Geometry validates semantic character evidence below; it
                # never creates that evidence. A portrait-shaped cut-in,
                # sticker sheet, or poem illustration can have exactly the
                # same dimensions and transparency as a sprite. Guessing from
                # pixels alone would therefore be unsafe across arbitrary mods.
                minimum_height = max(1, int(config.screen_height * 0.35))
                maximum_width = max(1, int(config.screen_width * 0.80))

                # Ren'Py uses the same image/tag machinery for characters,
                # stickers, poem pages, logos, cut-ins, and UI decoration.
                # Semantic metadata therefore proposes candidates but cannot
                # by itself make an asset eligible for automatic lighting.
                # Require foreground-scale portrait geometry for every
                # automatically discovered family. Explicit author config is
                # the intentional escape hatch for chibis and unusual art.
                # Keep selection preferences in the profile, but do not keep
                # removed families active in the generated runtime manifest.
                eligible_character_tags = explicit_character_tags & (
                    registered_tags | set(script_show_counts)
                )
                geometry_candidates = {}
                for registered_name in registered_names:
                    parts = tuple(registered_name.split())
                    if parts:
                        geometry_candidates.setdefault(parts[0], []).append(registered_name)
                automatic_tags = (
                    set() if manual_character_selection
                    else character_tags - explicit_character_tags - excluded_character_tags
                )
                ordered_automatic_tags = sorted(automatic_tags)
                if ordered_automatic_tags:
                    publish_progress("geometry", 0, len(ordered_automatic_tags))
                for tag_index, tag in enumerate(ordered_automatic_tags, 1):
                    publish_progress("geometry", tag_index, len(ordered_automatic_tags))
                    for registered_name in geometry_candidates.get(tag, ()):
                        try:
                            candidate = _scenelight_capture_displayable(registered_name)
                            rendered = renpy.render(
                                candidate,
                                config.screen_width,
                                config.screen_height,
                                0.0,
                                0.0,
                            )
                            width = int(rendered.width)
                            height = int(rendered.height)
                            portrait_ratio = float(width) / float(max(1, height))
                            if (
                                height >= minimum_height
                                and width < maximum_width
                                and portrait_ratio <= 1.05
                            ):
                                eligible_character_tags.add(tag)
                                break
                        except Exception:
                            pass
                        finally:
                            try:
                                renpy.display.render.free_memory()
                            except Exception:
                                pass
                character_tags = eligible_character_tags - excluded_character_tags

                if review_only:
                    for registered_name in sorted(registered_names):
                        parts = tuple(registered_name.split())
                        if parts and parts[0] in review_tags:
                            review_representatives.setdefault(parts[0], registered_name)

            story_names_by_tag = {}
            for story_name in script_show_names:
                story_parts = tuple(story_name.split())
                if story_parts:
                    story_names_by_tag.setdefault(story_parts[0], set()).add(story_name)

            if registered_names:
                publish_progress("catalog", 0, len(registered_names))
            for registered_index, registered_name in enumerate(registered_names, 1):
                if (
                    registered_index == 1
                    or registered_index % 500 == 0
                    or registered_index == len(registered_names)
                ):
                    publish_progress("catalog", registered_index, len(registered_names))
                parts = tuple(registered_name.split())
                if not parts:
                    continue
                if request.get("inventory_backgrounds") and parts[0] == "bg" and len(parts) > 1:
                    scene_names.add(registered_name)
                if (
                    request.get("inventory_characters")
                    and not review_only
                    and parts[0] in character_tags
                    and (
                        parts[0] not in story_names_by_tag
                        or registered_name in story_names_by_tag[parts[0]]
                    )
                ):
                    sprite_names.add(registered_name)
            if request.get("inventory_characters") and not review_only:
                for tag in character_tags:
                    sprite_names.update(story_names_by_tag.get(tag, ()))
            if review_only:
                sprite_names.update(review_representatives.values())

        if (
            getattr(renpy.config, "display_start_callbacks", None) is None
            and request.get("inventory_backgrounds")
            and not scene_names
        ):
            # Ren'Py 6.99 can invoke this before its renderer test and image
            # registry finish initializing. Allow up to five seconds before
            # reporting an empty static-scene inventory.
            if _scenelight_inventory_wait_started[0] is None:
                _scenelight_inventory_wait_started[0] = time.time()
            if time.time() - _scenelight_inventory_wait_started[0] < 5.0:
                try:
                    renpy.timeout(0.10)
                except Exception:
                    pass
                return

        prior_enabled = getattr(persistent, "scenelight_enabled", True)
        persistent.scenelight_enabled = False
        captures = {"scenes": {}, "sprites": {}}
        scene_sequences = {}
        scene_frame_sources = {}
        errors = []
        capture_failures = {}
        resolved_requests = set()
        planned_forms = set()
        planned_form_names = {}
        request_forms = {}
        surface_captures = set()
        normalized_captures = set()
        deferred_composites = _scenelight_deferred_composites[0]
        composite_captures = (
            deferred_composites if deferred_composites is not None else {}
        )

        def capture(kind, name):
            filename = _scenelight_capture_filename(kind, name)
            relative = os.path.join(output_relative, filename)
            capture_mode = None
            try:
                absolute_filename = os.path.join(config.basedir, relative)
                scene_marker = absolute_filename + ".scene-checkpoint"
                if (
                    kind == "scene"
                    and os.path.isfile(absolute_filename)
                    and os.path.getsize(absolute_filename) > 32
                    and os.path.isfile(scene_marker)
                ):
                    capture_mode = "renderer-checkpoint"
                    return relative.replace(os.sep, "/")
                if kind == "sprite":
                    surface_marker = absolute_filename + ".surface-checkpoint"
                    normalized_marker = absolute_filename + ".surface-normalized"
                    normalized_relative = relative.replace(os.sep, "/")
                    if (
                        os.path.isfile(absolute_filename)
                        and os.path.getsize(absolute_filename) > 32
                        and os.path.isfile(normalized_marker)
                    ):
                        capture_mode = "surface-normalized"
                        return normalized_relative
                    if (
                        os.path.isfile(absolute_filename)
                        and os.path.getsize(absolute_filename) > 32
                        and os.path.isfile(surface_marker)
                    ):
                        capture_mode = "surface-checkpoint"
                        surface_captures.add(normalized_relative)
                        return normalized_relative
                    if (
                        os.path.isfile(absolute_filename)
                        and os.path.getsize(absolute_filename) > 32
                        and os.path.isfile(absolute_filename + ".composite-normalized")
                    ):
                        capture_mode = "composite-normalized"
                        return normalized_relative
                    if (
                        normalized_relative in composite_captures
                        or os.path.isfile(_scenelight_composite_job_path(normalized_relative))
                    ):
                        capture_mode = "composite-manifest"
                        return normalized_relative
                displayable = _scenelight_capture_displayable(name)
                structure_signature = (
                    _scenelight_displayable_signature(displayable)
                    if kind == "sprite"
                    else None
                )
                structure_relative = structure_index.get(structure_signature)
                if structure_relative is not None:
                    structure_absolute = os.path.join(
                        config.basedir,
                        structure_relative.replace("/", os.sep),
                    )
                    if os.path.isfile(structure_absolute + ".surface-normalized"):
                        capture_mode = "surface-normalized"
                    elif os.path.isfile(structure_absolute + ".surface-checkpoint"):
                        capture_mode = "surface-checkpoint"
                    elif os.path.isfile(structure_absolute + ".composite-normalized"):
                        capture_mode = "composite-normalized"
                    elif (
                        structure_relative in composite_captures
                        or os.path.isfile(_scenelight_composite_job_path(structure_relative))
                    ):
                        capture_mode = "composite-manifest"
                    else:
                        structure_relative = None
                if structure_relative is None:
                    capture_mode = _scenelight_render_to_file(
                        displayable,
                        relative,
                        composite_captures,
                        preserve_alpha=(kind == "sprite"),
                    )
                    normalized_relative = relative.replace(os.sep, "/")
                    if structure_signature is not None and capture_mode in (
                        "surface-checkpoint",
                        "surface-normalized",
                        "surface",
                        "composite",
                        "composite-normalized",
                        "composite-manifest",
                    ):
                        structure_index[structure_signature] = normalized_relative
                        _scenelight_save_structure_index(
                            structure_index_path,
                            structure_index,
                        )
                else:
                    normalized_relative = structure_relative
                if capture_mode in ("surface", "surface-checkpoint"):
                    surface_captures.add(normalized_relative)
                if capture_mode == "surface-normalized":
                    normalized_captures.add(normalized_relative)
                if kind == "scene" and capture_mode == "renderer":
                    _scenelight_mark_scene_checkpoint(absolute_filename)
                return normalized_relative
            except Exception:
                capture_failures[(kind, name)] = traceback.format_exc().splitlines()[-1]
                return None

        def capture_sprite(name):
            normalized = " ".join(name.lower().split())
            if normalized in captures["sprites"]:
                return True
            filename = _scenelight_capture_filename("sprite", normalized)
            relative = os.path.join(output_relative, filename)
            relative = capture("sprite", normalized)
            if relative is None:
                return False
            captures["sprites"][normalized] = relative
            _scenelight_record_deferred_form(normalized, relative)
            return True

        def restore_sprite_checkpoint(name):
            normalized = " ".join(name.lower().split())
            filename = _scenelight_capture_filename("sprite", normalized)
            deterministic = os.path.join(output_relative, filename).replace(os.sep, "/")
            saved_paths = _scenelight_deferred_form_paths[0] or {}
            candidates = []
            saved = saved_paths.get(_scenelight_form_key(normalized))
            if saved is not None:
                candidates.append(saved)
            if deterministic not in candidates:
                candidates.append(deterministic)
            for relative in candidates:
                absolute = os.path.join(config.basedir, relative.replace("/", os.sep))
                composite_job = _scenelight_composite_job_path(relative)
                if (
                    os.path.isfile(absolute)
                    and os.path.getsize(absolute) > 32
                    and os.path.isfile(absolute + ".surface-checkpoint")
                ):
                    surface_captures.add(relative)
                elif (
                    os.path.isfile(absolute)
                    and os.path.getsize(absolute) > 32
                    and os.path.isfile(absolute + ".surface-normalized")
                ):
                    normalized_captures.add(relative)
                elif not (
                    os.path.isfile(absolute + ".composite-normalized")
                    or os.path.isfile(composite_job)
                    or relative in composite_captures
                ):
                    continue
                captures["sprites"][normalized] = relative
                return True
            return False

        def plan_form(requested_name, actual_name):
            requested_name = " ".join(requested_name.lower().split())
            actual_name = " ".join(actual_name.lower().split())
            actual_parts = tuple(actual_name.split())
            if not requested_name or not actual_name:
                return

            # Ren'Py compares attributes after the image tag as a set, but the
            # spelling still controls longest-prefix lookup. A project can
            # register ``image monika forward`` and resolve ``monika forward
            # e1a ...``; moving ``forward`` later produces Ren'Py's red "Image
            # not found" placeholder. Deduplicate on the unordered attribute
            # key while retaining the first valid spelling from ShownImageInfo.
            form_key = (
                actual_parts[0],
                tuple(sorted(set(actual_parts[1:]))),
            )
            representative = planned_form_names.get(form_key)
            if representative is None:
                representative = actual_name
                planned_form_names[form_key] = representative
                planned_forms.add(representative)
            request_forms.setdefault(requested_name, set()).add(representative)

        ordered_scenes = sorted(scene_names)
        if ordered_scenes:
            publish_progress("scene", 0, len(ordered_scenes))
        for scene_index, name in enumerate(ordered_scenes, 1):
            try:
                timeline, source_frames = _scenelight_capture_scene_timeline(
                    name, output_relative, live=request.get("scene_analysis") == "live")
            except Exception:
                timeline = []
                capture_failures[("scene", name)] = traceback.format_exc()
            if timeline:
                relative = timeline[0][1]
                parts = name.split()
                scene_key = (
                    " ".join(parts[1:])
                    if parts[0].lower() == "bg" and len(parts) > 1
                    else name
                ).lower()
                # Runtime scene-list lookup is case-insensitive. Keep the
                # first successfully resolved spelling so a later invalid
                # case-only alias cannot replace real background pixels.
                captures["scenes"].setdefault(scene_key, relative)
                if len(set(frame[1] for frame in timeline)) > 1:
                    scene_sequences[scene_key] = timeline
                    scene_frame_sources[scene_key] = source_frames
            else:
                errors.append(
                    "scene %s: %s" % (name, capture_failures.get(("scene", name), "unresolved"))
                )
            publish_progress("scene", scene_index, len(ordered_scenes))

        if ordered_scenes and not captures["scenes"]:
            errors.append(
                "background capture failed for all %d registered scenes"
                % len(ordered_scenes)
            )
            # A renderer/API incompatibility affects every subsequent capture
            # too. Publish the useful scene errors immediately instead of
            # spending minutes on hundreds of sprite forms or exhausting an
            # older 32-bit runtime.
            sprite_names.clear()

        plan_signature = request.get("plan_signature")
        plan_path = os.path.join(config.basedir, output_relative, "capture_plan.json")
        cached_plan = (
            None
            if explicit_forms is not None
            else _scenelight_load_capture_plan(plan_path, plan_signature, sprite_names)
        )
        if explicit_forms is not None:
            for explicit_form in sorted(explicit_forms):
                plan_form(explicit_form, explicit_form)
        elif cached_plan is not None:
            planned_forms, request_forms = cached_plan
            _scenelight_log(
                "SceneLight reused the deterministic character plan: %d forms."
                % len(planned_forms)
            )
        else:
            # Reconstruct Ren'Py's remembered image attributes along each static
            # story sequence. This turns shorthand such as `monika angr cm` into
            # the canonical `monika forward ... angr cm` state that the actual show
            # statement produces, including inherited pose and outfit attributes.
            all_sprite_sequences = list(request.get("sprite_sequences", ()))
            all_sprite_sequences.extend(script_sprite_sequences)
            if all_sprite_sequences:
                publish_progress("plan", 0, len(all_sprite_sequences))
            for sequence_index, sequence in enumerate(all_sprite_sequences, 1):
                _scenelight_plan_sequence(sequence, sprite_names, plan_form)
                if (
                    sequence_index == 1
                    or sequence_index % 25 == 0
                    or sequence_index == len(all_sprite_sequences)
                ):
                    publish_progress("plan", sequence_index, len(all_sprite_sequences))

            for name in sorted(sprite_names):
                normalized = " ".join(name.lower().split())
                if normalized in request_forms:
                    continue
                try:
                    _scenelight_capture_displayable(normalized)
                    plan_form(normalized, normalized)
                except Exception:
                    capture_failures[("sprite", normalized)] = traceback.format_exc().splitlines()[-1]
            _scenelight_save_capture_plan(
                plan_path,
                plan_signature,
                sprite_names,
                planned_forms,
                request_forms,
            )

        _scenelight_log(
            "SceneLight resolver planned %d canonical forms for %d requests."
            % (len(planned_forms), len(sprite_names))
        )
        plan_only_threshold = request.get("plan_only_threshold")
        try:
            plan_only_threshold = int(plan_only_threshold)
        except (TypeError, ValueError):
            plan_only_threshold = 0
        plan_only = bool(request.get("plan_only")) or (
            explicit_forms is None
            and plan_only_threshold > 0
            and len(planned_forms) >= plan_only_threshold
        )
        ordered_planned_forms = [] if plan_only else sorted(planned_forms)
        pending_forms = []
        for restore_index, actual_name in enumerate(ordered_planned_forms, 1):
            if not restore_sprite_checkpoint(actual_name):
                pending_forms.append(actual_name)
            if (
                restore_index == 1
                or restore_index % 100 == 0
                or restore_index == len(ordered_planned_forms)
            ):
                publish_progress(
                    "checkpoint",
                    restore_index,
                    len(ordered_planned_forms),
                )
        restored_forms = len(ordered_planned_forms) - len(pending_forms)
        if ordered_planned_forms:
            publish_progress(
                "planned",
                0,
                len(ordered_planned_forms),
                requests=len(sprite_names),
            )
            publish_progress(
                "restore",
                restored_forms,
                len(ordered_planned_forms),
            )
            time.sleep(0.10)
            _scenelight_log(
                "SceneLight restored %d/%d completed sprite forms; %d remain."
                % (restored_forms, len(ordered_planned_forms), len(pending_forms))
            )
        for index, actual_name in enumerate(pending_forms, 1):
            capture_sprite(actual_name)
            completed = restored_forms + index
            if index == 1 or index % 25 == 0 or index == len(pending_forms):
                _scenelight_log(
                    "SceneLight resolver form %d/%d"
                    % (completed, len(ordered_planned_forms))
                )
            if index == 1 or index % 5 == 0 or index == len(pending_forms):
                publish_progress(
                    "form",
                    completed,
                    len(ordered_planned_forms),
                    item=actual_name,
                )
        if not plan_only:
            for requested_name in sorted(sprite_names):
                forms = request_forms.get(requested_name, ())
                if any(form in captures["sprites"] for form in forms):
                    resolved_requests.add(requested_name)
                    continue
                detail = capture_failures.get(
                    ("sprite", requested_name),
                    "no canonical story state",
                )
                errors.append("sprite %s: %s" % (requested_name, detail))

        # Release the final partial batch before publishing the atomic result.
        try:
            renpy.display.render.free_memory()
        except Exception:
            pass
        try:
            renpy.display.im.free_memory()
        except Exception:
            pass
        if _scenelight_prior_draw[0] is not None:
            renpy.display.draw = _scenelight_prior_draw[0]
            _scenelight_prior_draw[0] = None

        character_candidates = {}
        for tag in sorted(review_tags):
            requested_name = review_representatives.get(tag)
            preview = None
            if requested_name is not None:
                for form in sorted(request_forms.get(requested_name, ())):
                    if form in captures["sprites"]:
                        preview = captures["sprites"][form]
                        break
            character_candidates[tag] = preview

        persistent.scenelight_enabled = prior_enabled
        deferred_stream = _scenelight_deferred_composite_stream[0]
        if deferred_stream is not None:
            deferred_stream.flush()
            deferred_stream.close()
            _scenelight_deferred_composite_stream[0] = None
        deferred_form_stream = _scenelight_deferred_form_stream[0]
        if deferred_form_stream is not None:
            deferred_form_stream.flush()
            deferred_form_stream.close()
            _scenelight_deferred_form_stream[0] = None
        result = {
            "version": 42,
            "texture_cleanup_ok": _scenelight_probe_texture_cleanup() if request.get("probe_texture_cleanup") else None,
            "renpy_version": renpy.version_string,
            # Source-only inspection cannot see this value when options.rpyc
            # lives inside an RPA. Publishing the initialized runtime value
            # lets setup preserve the exact roaming save namespace before it
            # changes the game's ordinary launch path.
            "save_directory": getattr(renpy.config, "save_directory", None),
            "character_tags": sorted(character_tags),
            "character_candidates": character_candidates,
            "background_inventory_requested": bool(request.get("inventory_backgrounds")),
            "scene_requests": len(ordered_scenes),
            "scenes": captures["scenes"],
            "scene_sequences": scene_sequences,
            "scene_frame_sources": scene_frame_sources,
            "sprites": captures["sprites"],
            "surface_captures": sorted(surface_captures),
            "normalized_captures": sorted(normalized_captures),
            "composite_captures": composite_captures,
            "resolved_requests": sorted(resolved_requests),
            "errors": errors,
            "plan_only": plan_only,
        }
        result_path = os.path.join(config.basedir, request["result"].replace("/", os.sep))
        temporary_result_path = result_path + ".tmp"
        with open(temporary_result_path, "w") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        _scenelight_atomic_replace(temporary_result_path, result_path)

        # This is a disposable managed-process capture, and its atomic result
        # is already closed on disk. A direct process exit avoids mod-defined
        # quit labels and old Ren'Py launchers that can swallow QuitException
        # inside the GL test and leave a hidden child process running.
        os._exit(0)

    if os.environ.get("SCENELIGHT_CAPTURE_REQUEST"):
        display_callbacks = getattr(renpy.config, "display_start_callbacks", None)
        if display_callbacks is not None:
            display_callbacks.append(_scenelight_capture_assets)
        else:
            # Ren'Py 7 has no display_start_callbacks. Its first-interaction
            # hook runs after the renderer exists and before the story becomes
            # visible, which is the equivalent safe capture point.
            config.start_interact_callbacks.append(_scenelight_capture_assets)
