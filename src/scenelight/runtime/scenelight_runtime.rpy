# SceneLight integration bootstrap for Ren'Py 6.99 through current Ren'Py.
# The GPU runtime activates on model-based renderer versions; legacy Ren'Py
# remains playable and uses SceneLight's compatibility launcher for lighting.
#
# Character images are flattened once by Ren'Py, then shaded on the GPU. The
# fragment shader samples cached scene light fields using the final transformed
# screen position, so existing ATL entrances, exits, hops, and position changes
# require no script edits.

default persistent.scenelight_enabled = True
default persistent.scenelight_strength = 1.0
default scenelight_control_state = _scenelight_control_initial_state()
default scenelight_fx_state = {
    "version": 1,
    "revision": 0,
    "scene": {},
    "characters": {},
}

init -50 python:
    import copy
    import json
    import os
    import time as _sc_diagnostic_time
    from collections import OrderedDict as _SceneLightOrderedDict
    try:
        from collections.abc import Mapping as _SceneLightMapping
    except ImportError:
        from collections import Mapping as _SceneLightMapping

    SCENELIGHT_CHARACTER_TAGS = set()
    SCENELIGHT_WRAPPED_IMAGES = []
    SCENELIGHT_MANIFEST_PATH = "scenelight_runtime/manifest.json"
    SCENELIGHT_FORM_MANIFEST_PATH = "scenelight_runtime/sprite_form_manifest.json"
    SCENELIGHT_EFFECT_PACK_MANIFEST_PATH = "scenelight_runtime/effect_packs.json"
    SCENELIGHT_LAST_PRESENTED_SCENE = None
    SCENELIGHT_STABLE_SCENE_KEY = None
    SCENELIGHT_STABLE_SCENE = None
    _SCENELIGHT_DIAGNOSTIC_FAILURE = False
    _SCENELIGHT_DIAGNOSTIC_STARTED = False

    def _scenelight_record_diagnostic(stage, details):
        """Record state changes only; no pixels, dialogue, or per-frame logging."""
        global _SCENELIGHT_DIAGNOSTIC_FAILURE, _SCENELIGHT_DIAGNOSTIC_STARTED
        if _SCENELIGHT_DIAGNOSTIC_FAILURE:
            return
        try:
            path = os.path.join(config.basedir, "scenelight-runtime.jsonl")
            if os.path.isfile(path) and os.path.getsize(path) > 2 * 1024 * 1024:
                previous = path + ".1"
                if os.path.exists(previous):
                    os.remove(previous)
                os.rename(path, previous)
            with open(path, "a") as stream:
                if not _SCENELIGHT_DIAGNOSTIC_STARTED:
                    _SCENELIGHT_DIAGNOSTIC_STARTED = True
                    stream.write(json.dumps({"stage": "runtime.start", "time": _sc_diagnostic_time.time(),
                        "renpy": getattr(renpy, "version_string", "unknown"),
                        "renderer": renpy.get_renderer_info(),
                        "manifest_version": SCENELIGHT_MANIFEST.get("version"),
                        "form_version": SCENELIGHT_FORM_MANIFEST.get("version"),
                        "profile_strength": SCENELIGHT_PROFILE_STRENGTH}, default=str) + "\n")
                stream.write(json.dumps({"time": _sc_diagnostic_time.time(), "stage": stage,
                                         "renpy": getattr(renpy, "version_string", "unknown"),
                                         "details": details}, ensure_ascii=True) + "\n")
        except Exception:
            _SCENELIGHT_DIAGNOSTIC_FAILURE = True
    _SCENELIGHT_MEASURING_EMITTERS = False
    # Ren'Py 6.99 can parse this runtime but predates the model-based shader
    # API entirely. Keep the original executable playable; SceneLight itself
    # is activated by the compatibility launcher installed beside that game.
    _SCENELIGHT_SHADER_AVAILABLE = callable(getattr(renpy, "register_shader", None))
    # Effect packs are experimental and script-only; the player panel is disabled.
    _SCENELIGHT_PLAYER_EFFECT_UI_ENABLED = False
    SCENELIGHT_DEBUG_CONTRAST = 0.0 if os.environ.get("SCENELIGHT_DEBUG_NO_CONTRAST") == "1" else 1.0
    _SCENELIGHT_CALIBRATION_DEFAULTS = {
        "auto_strength": 0.88,
        "exposure_bias": 0.0,
        "ambient_strength": 1.0,
        "color_adaptation": 0.78,
        "contrast_match": 0.72,
        "saturation_match": 0.58,
        "highlight_rolloff": 1.2,
        "key_strength": 0.82,
        "ray_shadow_strength": 0.58,
        "ambient_occlusion": 0.34,
        "probe_strength": 0.48,
        "bounce_strength": 0.32,
        "specular_strength": 0.24,
        "rim_strength": 0.64,
        "wrap_strength": 0.42,
        "grain_match": 0.52,
        "shadow_strength": 0.62,
        "individual_light_colors": 0.0,
        "adaptive_light_colors": 1.0,
        "light_color_red": 0.25,
        "light_color_green": 0.50,
        "light_color_blue": 1.0,
        "light_color_amount": 0.0,
        "light_color_tolerance": 0.25,
        "glow_strength": 0.0,
        "glow_radius": 1.0,
        "emission_strength": 0.0,
        "emission_radius": 0.35,
        "emission_red": 1.0,
        "emission_green": 1.0,
        "emission_blue": 1.0,
        "glow_red": 1.0,
        "glow_green": 1.0,
        "glow_blue": 1.0,
        "glow_color_mix": 0.0,
        "glow_rules": (),
    }
    _SCENELIGHT_CONTROL_KEYS = frozenset(
        ("enabled", "strength") + tuple(_SCENELIGHT_CALIBRATION_DEFAULTS.keys())
    )
    _SCENELIGHT_CONTROL_ALIASES = {
        "lighting_strength": "strength",
        "exposure": "exposure_bias",
        "separate_light_colors": "individual_light_colors",
    }
    def _scenelight_light_mode_values(**overrides):
        values = dict(_SCENELIGHT_CALIBRATION_DEFAULTS)
        values["strength"] = 1.0
        values.update(overrides)
        return values

    _SCENELIGHT_PHYSICAL_MODE = _scenelight_light_mode_values(
        individual_light_colors=0.0
    )
    _SCENELIGHT_SEPARATE_MODE = _scenelight_light_mode_values(
        individual_light_colors=1.0
    )
    _SCENELIGHT_LIGHT_MODES = {
        "physical": _SCENELIGHT_PHYSICAL_MODE,
        "combined": _SCENELIGHT_PHYSICAL_MODE,
        "realistic": _SCENELIGHT_PHYSICAL_MODE,
        "separate": _SCENELIGHT_SEPARATE_MODE,
        "individual": _SCENELIGHT_SEPARATE_MODE,
        "creative": _SCENELIGHT_SEPARATE_MODE,
        # Separate source colors with lower exposure. Explicit settings in the
        # same call override the preset.
        "cinematic": _scenelight_light_mode_values(
            strength=0.72,
            exposure_bias=-0.22,
            color_adaptation=0.92,
            individual_light_colors=1.0,
        ),
    }
    try:
        _SCENELIGHT_STRING_TYPES = (basestring,)
    except NameError:
        _SCENELIGHT_STRING_TYPES = (str,)

    _SCENELIGHT_INITIAL_CONTROL_STATE = {
        "version": 1,
        "revision": 0,
        "defaults": {},
        "scene": {},
        "backgrounds": {},
        "characters": {},
        "images": {},
        "groups": {},
    }

    def _scenelight_control_initial_state():
        # Ren'Py executes defaults again at New Game. Seed each new playthrough
        # from init-authored rules without sharing mutable save/rollback state.
        return copy.deepcopy(_SCENELIGHT_INITIAL_CONTROL_STATE)

    def _scenelight_control_current_state():
        state = getattr(renpy.store, "scenelight_control_state", None)
        if not isinstance(state, dict) or state.get("version") != 1:
            state = _scenelight_control_initial_state()
        elif state.get("revision", 0) == 0 and not any(
            state.get(scope) for scope in ("defaults", "scene", "backgrounds", "characters", "images", "groups")
        ):
            # Older saves may contain the untouched empty default that used to
            # erase init-authored rules. An intentional runtime clear/reset has
            # a nonzero revision and must remain empty when that save is loaded.
            state = _scenelight_control_initial_state()
        return state

    def _scenelight_control_assign(state):
        global _SCENELIGHT_INITIAL_CONTROL_STATE
        state["revision"] = int(state.get("revision", 0)) + 1
        renpy.store.scenelight_control_state = state
        if getattr(renpy, "is_init_phase", lambda: False)():
            _SCENELIGHT_INITIAL_CONTROL_STATE = copy.deepcopy(state)
        redraw_visible = globals().get("_scenelight_redraw_visible_sprites")
        if redraw_visible is not None:
            redraw_visible()
        # Reusable background/character rules are commonly declared in an
        # ``init python`` block, before Ren'Py has an interaction to restart.
        # Runtime calls still repaint immediately; init-time calls simply wait
        # for the first interaction.
        try:
            renpy.restart_interaction()
        except Exception:
            pass

    def _scenelight_control_name(value, scope):
        if isinstance(value, (tuple, list)):
            value = " ".join(str(part) for part in value)
        name = " ".join(str(value).strip().lower().split())
        if scope == "background" and name.startswith("bg "):
            name = name[3:].strip()
        if scope == "character":
            name = name.split()[0] if name else ""
        if not name or (scope == "character" and name == "bg"):
            raise ValueError("SceneLight %s overrides require a name" % scope)
        return name

    def _scenelight_control_glow_rules(raw_rules):
        """Normalize a serializable rule list without retaining caller-owned state."""
        import math
        try:
            import builtins as _sc_builtins
        except ImportError:
            import __builtin__ as _sc_builtins
        if not isinstance(raw_rules, (_sc_builtins.list, _sc_builtins.tuple)):
            raise ValueError("SceneLight glow_rules must be a list")
        rules = []
        defaults = {"name": "Color glow", "enabled": True,
            "color": (1.0, 0.0, 0.0), "strength": 1.0, "radius": 1.0,
            "tolerance": 0.15, "softness": 0.10}

        def bounded(raw, high):
            if isinstance(raw, (bool,) + _SCENELIGHT_STRING_TYPES):
                raise ValueError("Glow rule values must be finite numbers")
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError("Glow rule values must be finite numbers")
            if math.isnan(number) or math.isinf(number):
                raise ValueError("Glow rule values must be finite numbers")
            return max(0.0, min(number, high))

        for raw in raw_rules:
            if not isinstance(raw, _sc_builtins.dict):
                raise ValueError("Each SceneLight glow rule must be an object")
            unknown = sorted(set(raw) - set(defaults))
            if unknown:
                raise ValueError("Unknown SceneLight glow rule setting(s): " + ", ".join(unknown))
            rule = dict(defaults)
            rule.update(raw)
            if not isinstance(rule["name"], _SCENELIGHT_STRING_TYPES) or not isinstance(rule["enabled"], bool):
                raise ValueError("Glow rule name must be text and enabled must be true or false")
            rule["name"] = rule["name"].strip() or "Color glow"
            if not isinstance(rule["color"], (_sc_builtins.list, _sc_builtins.tuple)) or len(rule["color"]) != 3:
                raise ValueError("Glow rule color must contain three RGB numbers")
            rule["color"] = tuple(bounded(channel, 1.0) for channel in rule["color"])
            for name in ("strength", "radius", "tolerance", "softness"):
                maximum = 10.0 if name == "strength" else 2.0 if name == "radius" else 1.0
                rule[name] = bounded(rule[name], maximum)
            rules.append(rule)
        return rules

    def _scenelight_control_values(settings):
        normalized = {}
        if "light_color" in settings:
            color = settings["light_color"]
            if not isinstance(color, _SCENELIGHT_STRING_TYPES) or len(color) != 7 or not color.startswith("#"):
                raise ValueError("light_color must be a hex color such as #4080FF")
            try:
                channels = [int(color[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]
            except ValueError:
                raise ValueError("light_color must be a hex color such as #4080FF")
        raw_mode = settings.get("light_mode")
        if raw_mode is not None:
            mode = str(raw_mode).strip().lower().replace("-", "_")
            mode_values = _SCENELIGHT_LIGHT_MODES.get(mode)
            if mode_values is None:
                raise ValueError(
                    "SceneLight light_mode must be 'physical', 'cinematic', or 'separate'"
                )
            normalized.update(mode_values)
        if "light_color" in settings:
            normalized.update(zip(("light_color_red", "light_color_green", "light_color_blue"), channels))
        for raw_name, raw_value in settings.items():
            name = _SCENELIGHT_CONTROL_ALIASES.get(str(raw_name), str(raw_name))
            if name in ("light_mode", "light_color"):
                continue
            if name not in _SCENELIGHT_CONTROL_KEYS:
                raise ValueError("Unknown SceneLight lighting setting: %s" % raw_name)
            if name == "glow_rules":
                normalized[name] = _scenelight_control_glow_rules(raw_value)
                continue
            if name == "enabled":
                if isinstance(raw_value, _SCENELIGHT_STRING_TYPES):
                    value = raw_value.strip().lower()
                    if value in ("1", "true", "yes", "on"):
                        raw_value = True
                    elif value in ("0", "false", "no", "off"):
                        raw_value = False
                    else:
                        raise ValueError("SceneLight enabled must be true or false")
                normalized[name] = bool(raw_value)
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                raise ValueError("SceneLight %s must be a number" % name)
            if name == "strength":
                value = max(0.0, min(value, 2.0))
            elif name == "exposure_bias":
                value = max(-4.0, min(value, 4.0))
            elif name == "light_color_amount":
                value = max(-1.0, min(value, 1.0))
            elif name == "glow_strength":
                value = max(0.0, min(value, 10.0))
            elif name in ("glow_red", "glow_green", "glow_blue", "glow_color_mix", "light_color_red", "light_color_green", "light_color_blue", "light_color_tolerance"):
                value = max(0.0, min(value, 1.0))
            else:
                value = max(0.0, min(value, 2.0))
            normalized[name] = value
        return normalized

    def _scenelight_control_update(scope, name=None, settings=None):
        values = _scenelight_control_values(settings or {})
        state = copy.deepcopy(_scenelight_control_current_state())
        if scope in ("defaults", "scene"):
            state.setdefault(scope, {}).update(values)
        else:
            key = _scenelight_control_name(name, scope[:-1])
            state.setdefault(scope, {}).setdefault(key, {}).update(values)
        # Keep the authored call site with the rollback-aware rule, so the
        # inspector can locate a hidden override in the mod's actual script.
        location = None
        getter = getattr(renpy, "get_filename_line", None)
        if getter is not None:
            try:
                filename, line = getter()
                if filename:
                    location = {"file": filename, "line": int(line or 0)}
            except (AttributeError, TypeError, ValueError):
                pass
        if location is not None or "call_sites" in state:
            sites = state.setdefault("call_sites", {}).setdefault(scope, {})
            if scope not in ("defaults", "scene"):
                sites = sites.setdefault(key, {})
            for setting in values:
                if location is not None:
                    sites[setting] = dict(location)
                else:
                    sites.pop(setting, None)
        _scenelight_control_assign(state)

    def _scenelight_control_clear(scope, name=None):
        state = copy.deepcopy(_scenelight_control_current_state())
        if scope in ("defaults", "scene"):
            state[scope] = {}
            state.get("call_sites", {}).pop(scope, None)
        else:
            key = _scenelight_control_name(name, scope[:-1])
            state.setdefault(scope, {}).pop(key, None)
            state.get("call_sites", {}).get(scope, {}).pop(key, None)
        _scenelight_control_assign(state)

    def _scenelight_control_group_for_tag(state, tag):
        for name, group in state.get("groups", {}).items():
            if tag in group.get("members", ()):
                return name, group
        return None, None

    def _scenelight_control_group(name, members=None, anchor=None, settings=None):
        import math
        name = _scenelight_control_name(name, "group")
        state = copy.deepcopy(_scenelight_control_current_state())
        groups = state.setdefault("groups", {})
        group = copy.deepcopy(groups.get(name, {}))
        if members is not None:
            if isinstance(members, _SCENELIGHT_STRING_TYPES) or not isinstance(members, (list, tuple)):
                raise ValueError("Group members must be a list of image tags")
            tags = []
            for member in members:
                if not isinstance(member, _SCENELIGHT_STRING_TYPES) or len(member.split()) != 1:
                    raise ValueError("Group members must be single registered image tags")
                tag = _scenelight_control_name(member, "character")
                if tag in tags:
                    raise ValueError("Duplicate lighting-group member: " + tag)
                tags.append(tag)
            group["members"] = tags
        if not group.get("members"):
            raise ValueError("A lighting group needs at least one member")
        for other, entry in groups.items():
            if other != name and set(group["members"]) & set(entry.get("members", ())):
                raise ValueError("A sprite can belong to only one lighting group: " + other)
        if anchor is not None:
            if isinstance(anchor, _SCENELIGHT_STRING_TYPES):
                anchor = anchor.strip().lower()
                if anchor != "center" and anchor not in group["members"]:
                    raise ValueError("Group anchor must be 'center', a member tag, or an (x, y) point")
            elif isinstance(anchor, (list, tuple)) and len(anchor) == 2:
                anchor = tuple(float(value) for value in anchor)
                if any(math.isnan(value) or math.isinf(value) or not 0.0 <= value <= 1.0 for value in anchor):
                    raise ValueError("Group anchor coordinates must be finite numbers from 0 to 1")
            else:
                raise ValueError("Group anchor must be 'center', a member tag, or an (x, y) point")
            group["anchor"] = anchor
        group.setdefault("anchor", "center")
        if isinstance(group["anchor"], _SCENELIGHT_STRING_TYPES) and group["anchor"] != "center" and group["anchor"] not in group["members"]:
            raise ValueError("The anchor tag must remain a member of its lighting group")
        values = _scenelight_control_values(settings or {})
        group.setdefault("settings", {}).update(values)
        groups[name] = group
        sites = state.setdefault("call_sites", {}).setdefault("groups", {}).setdefault(name, {})
        try:
            filename, line = renpy.get_filename_line()
        except (AttributeError, TypeError, ValueError):
            filename, line = None, 0
        for setting in values:
            if filename:
                sites[setting] = {"file": filename, "line": int(line or 0)}
            else:
                sites.pop(setting, None)
        _scenelight_control_assign(state)

    def _scenelight_control_group_anchor(group):
        import math
        global _SCENELIGHT_MEASURING_EMITTERS
        anchor = group.get("anchor", "center")
        if isinstance(anchor, (tuple, list)):
            return tuple(anchor)
        layer = group.get("layer", "master")
        try:
            visible = set(renpy.get_showing_tags(layer=layer))
            sw, sh = float(config.screen_width), float(config.screen_height)
            if sw <= 0 or sh <= 0:
                return None
            # One result per presented frame keeps members independent of draw order.
            frame = (renpy.game.interface.frame_time, sw, sh,
                     _scenelight_control_current_state().get("revision", 0))
            previous, cache = getattr(renpy.display, "_scenelight_group_anchors", (None, {}))
            if previous != frame:
                cache = {}
                renpy.display._scenelight_group_anchors = (frame, cache)
            key = (layer, tuple(group["members"]), anchor, tuple(sorted(visible)))
            if key in cache:
                return cache[key]
            tags = [anchor] if anchor != "center" and anchor in visible else group["members"]
            bounds = []
            measuring = _SCENELIGHT_MEASURING_EMITTERS
            _SCENELIGHT_MEASURING_EMITTERS = True
            try:
                for tag in tags:
                    if tag not in visible:
                        continue
                    rect = renpy.get_image_bounds(tag, config.screen_width, config.screen_height, layer)
                    if rect and len(rect) == 4 and rect[2] > 0 and rect[3] > 0:
                        rect = tuple(float(value) for value in rect)
                        if not any(math.isnan(value) or math.isinf(value) for value in rect):
                            bounds.append(rect)
            finally:
                _SCENELIGHT_MEASURING_EMITTERS = measuring
            point = None
            if bounds:
                x0 = min(rect[0] for rect in bounds)
                y0 = min(rect[1] for rect in bounds)
                x1 = max(rect[0] + rect[2] for rect in bounds)
                y1 = max(rect[1] + rect[3] for rect in bounds)
                point = ((x0 + x1) * 0.5 / sw, (y0 + y1) * 0.5 / sh)
            cache[key] = point
            return point
        except (AttributeError, TypeError, ValueError, KeyError):
            return None

    def _scenelight_control_snapshot(background_key, tag, image_name):
        state = _scenelight_control_current_state()
        background_key = _scenelight_control_name(background_key, "background")
        character_key = _scenelight_control_name(tag, "character")
        image_key = _scenelight_control_name(image_name, "image")
        scene_layer = state.get("scene", {})
        layers = (
            state.get("defaults", {}),
            state.get("backgrounds", {}).get(background_key, {}),
            scene_layer,
            state.get("characters", {}).get(character_key, {}),
            state.get("images", {}).get(image_key, {}),
        )
        group_name, group = _scenelight_control_group_for_tag(state, character_key)
        if group is not None:
            # The group owns ordinary lighting. Glow/emission and disabled-image
            # rules stay local unless the group explicitly supplies those values.
            local = {}
            for layer in layers[3:]:
                local.update((key, value) for key, value in layer.items()
                             if key.startswith(("glow_", "emission_")))
            layers = layers[:3] + (local, group.get("settings", {}))
        result = {
            "enabled": True,
            "strength": 1.0,
            "strength_override": False,
            "calibration": {},
        }
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            if "enabled" in layer:
                result["enabled"] = bool(layer["enabled"])
            if "strength" in layer:
                result["strength"] = float(layer["strength"])
                result["strength_override"] = True
            for key in _SCENELIGHT_CALIBRATION_DEFAULTS:
                if key in layer:
                    result["calibration"][key] = (
                        copy.deepcopy(layer[key]) if key == "glow_rules" else float(layer[key])
                    )
        if group is not None:
            result["group"] = dict(copy.deepcopy(group), name=group_name)
            if any(state.get(scope, {}).get(key, {}).get("enabled") is False
                   for scope, key in (("characters", character_key), ("images", image_key))):
                result["enabled"] = False
        # A scripted scene bypass is absolute. It must not be undone by a
        # reusable character or image rule authored at a narrower scope.
        if isinstance(scene_layer, dict) and scene_layer.get("enabled") is False:
            result["enabled"] = False
        inspector = getattr(getattr(renpy, "display", None), "_scenelight_inspector", None)
        if inspector is not None:
            result = inspector.apply(background_key, character_key, image_key, result)
        return result

    def _scenelight_master_enabled():
        session = getattr(getattr(renpy, "display", None), "_scenelight_inspector", None)
        value = bool(getattr(persistent, "scenelight_enabled", True))
        return bool(session.master.get("enabled", value)) if session is not None else value

    def _scenelight_master_strength():
        session = getattr(getattr(renpy, "display", None), "_scenelight_inspector", None)
        value = float(getattr(persistent, "scenelight_strength", 1.0))
        return float(session.master.get("strength", value)) if session is not None else value

    class _SceneLightAPI(object):
        """Rollback-safe authored lighting controls for Ren'Py scripts."""

        def configure(self, **settings):
            _scenelight_control_update("defaults", settings=settings)

        defaults = configure

        def scene(self, **settings):
            _scenelight_control_update("scene", settings=settings)

        def background(self, name, **settings):
            _scenelight_control_update("backgrounds", name, settings)

        def character(self, tag, **settings):
            _scenelight_control_update("characters", tag, settings)

        def image(self, name, **settings):
            _scenelight_control_update("images", name, settings)

        def on(self):
            self.scene(enabled=True)

        def group(self, name, members=None, anchor=None, **settings):
            _scenelight_control_group(name, members, anchor, settings)

        def clear_group(self, name):
            _scenelight_control_clear("groups", name)

        def off(self):
            self.scene(enabled=False)

        enable = on
        disable = off

        def clear_defaults(self):
            _scenelight_control_clear("defaults")

        def clear_scene(self):
            _scenelight_control_clear("scene")

        def clear_background(self, name):
            _scenelight_control_clear("backgrounds", name)

        def clear_character(self, tag):
            _scenelight_control_clear("characters", tag)

        def clear_image(self, name):
            _scenelight_control_clear("images", name)

        def reset(self):
            _scenelight_control_assign(
                {
                    "version": 1,
                    "revision": 0,
                    "defaults": {},
                    "scene": {},
                    "backgrounds": {},
                    "characters": {},
                    "images": {},
                    "groups": {},
                }
            )

        def state(self):
            return copy.deepcopy(_scenelight_control_current_state())

        def inspect(self, tag=None):
            helper = globals().get("_scenelight_inspect")
            return helper(tag) if helper is not None else {}

        def inspector(self):
            helper = globals().get("_scenelight_open_inspector")
            if helper is not None:
                helper()

    scenelight = _SceneLightAPI()

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

    def _scenelight_load_optional_json(path, fallback):
        opener = getattr(renpy, "open_file", None)
        if opener is None:
            opener = renpy.loader.load
        try:
            stream = opener(path)
            try:
                payload = stream.read()
            finally:
                stream.close()
            if not isinstance(payload, str):
                payload = payload.decode("utf-8")
            return json.loads(payload)
        except Exception as error:
            try:
                renpy.log("SceneLight effect pack manifest unavailable: %s" % error)
            except Exception:
                pass
            return fallback

    def _scenelight_is_mapping(value):
        return callable(getattr(value, "get", None)) and callable(
            getattr(value, "items", None)
        )

    _SCENELIGHT_EFFECT_PACK_MANIFEST = _scenelight_load_optional_json(
        SCENELIGHT_EFFECT_PACK_MANIFEST_PATH,
        {"version": 1, "packs": [], "effects": {}},
    )
    _SCENELIGHT_CUSTOM_EFFECTS = _SCENELIGHT_EFFECT_PACK_MANIFEST.get("effects", {})
    if not _scenelight_is_mapping(_SCENELIGHT_CUSTOM_EFFECTS):
        _SCENELIGHT_CUSTOM_EFFECTS = {}

    if _SCENELIGHT_SHADER_AVAILABLE:
        renpy.register_shader(
            "scenelight.fx.alpha_guard",
            fragment_900="""
                gl_FragColor.rgb = clamp(
                    gl_FragColor.rgb,
                    vec3(0.0),
                    vec3(max(gl_FragColor.a, 0.0))
                );
            """,
        )
        for _sc_fx_name, _sc_fx_entry in sorted(_SCENELIGHT_CUSTOM_EFFECTS.items()):
            if not _scenelight_is_mapping(_sc_fx_entry):
                continue
            _sc_fx_shader = _sc_fx_entry.get("shader")
            _sc_fx_variables = _sc_fx_entry.get("variables")
            _sc_fx_fragment = _sc_fx_entry.get("fragment")
            _sc_fx_functions = _sc_fx_entry.get("fragment_functions", "")
            _sc_fx_priority = _sc_fx_entry.get("fragment_priority", 600)
            if (
                not isinstance(_sc_fx_shader, str)
                or not isinstance(_sc_fx_variables, str)
                or not isinstance(_sc_fx_fragment, str)
                or not isinstance(_sc_fx_priority, int)
                or _sc_fx_priority < 400
                or _sc_fx_priority > 900
            ):
                continue
            _sc_fx_parts = {"fragment_%d" % _sc_fx_priority: _sc_fx_fragment}
            if isinstance(_sc_fx_functions, str) and _sc_fx_functions:
                _sc_fx_parts["fragment_functions"] = _sc_fx_functions
            renpy.register_shader(
                _sc_fx_shader,
                variables=_sc_fx_variables,
                **_sc_fx_parts
            )

    _SCENELIGHT_EFFECT_DEFAULTS = {
        "rain": {
            "intensity": 0.0,
            "wetness": 0.72,
            "wind": 0.0,
            "speed": 1.0,
            "scale": 1.0,
            "color": (0.78, 0.88, 1.0),
        },
        "glitch": {
            "intensity": 0.0,
            "rgb_split": 0.62,
            "block_size": 1.0,
            "speed": 1.0,
            "tear": 0.55,
            "scanlines": 0.18,
            "alpha_fragment": 0.0,
            "seed": 947.0,
        },
    }
    for _sc_fx_name, _sc_fx_entry in sorted(_SCENELIGHT_CUSTOM_EFFECTS.items()):
        if not _scenelight_is_mapping(_sc_fx_entry):
            continue
        _sc_fx_parameters = _sc_fx_entry.get("parameters", {})
        if not _scenelight_is_mapping(_sc_fx_parameters):
            continue
        _sc_fx_defaults = {}
        for _sc_fx_parameter, _sc_fx_spec in sorted(_sc_fx_parameters.items()):
            if not _scenelight_is_mapping(_sc_fx_spec) or "default" not in _sc_fx_spec:
                continue
            _sc_fx_default = _sc_fx_spec["default"]
            if isinstance(_sc_fx_default, list):
                _sc_fx_default = tuple(_sc_fx_default)
            _sc_fx_defaults[str(_sc_fx_parameter)] = _sc_fx_default
        if "intensity" in _sc_fx_defaults:
            _SCENELIGHT_EFFECT_DEFAULTS[str(_sc_fx_name)] = _sc_fx_defaults

    def _scenelight_fx_clamp(value, low, high):
        try:
            return max(low, min(float(value), high))
        except (TypeError, ValueError):
            return low

    def _scenelight_fx_color(value, fallback):
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) == 3:
                text = "".join(character * 2 for character in text)
            if len(text) == 6:
                try:
                    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
                except ValueError:
                    pass
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            return tuple(_scenelight_fx_clamp(channel, 0.0, 1.0) for channel in value[:3])
        return tuple(fallback)

    def _scenelight_fx_normalize(name, parameters=None):
        name = str(name).strip().lower().replace("-", "_")
        aliases = {"wet": "rain"}
        name = aliases.get(name, name)
        if name not in _SCENELIGHT_EFFECT_DEFAULTS:
            raise ValueError("Unknown SceneLight effect: %s" % name)
        values = dict(_SCENELIGHT_EFFECT_DEFAULTS[name])
        values.update(dict(parameters or {}))
        if name in _SCENELIGHT_CUSTOM_EFFECTS:
            entry = _SCENELIGHT_CUSTOM_EFFECTS[name]
            specs = entry.get("parameters", {}) if _scenelight_is_mapping(entry) else {}
            normalized = {}
            for parameter_name, spec in sorted(specs.items()):
                if not _scenelight_is_mapping(spec):
                    continue
                kind = spec.get("type", "float")
                low = float(spec.get("min", 0.0))
                high = float(spec.get("max", 1.0))
                fallback = spec.get("default", 0.0)
                value = values.get(parameter_name, fallback)
                if kind == "float":
                    normalized[parameter_name] = _scenelight_fx_clamp(value, low, high)
                else:
                    width = {"vec2": 2, "vec3": 3, "vec4": 4}.get(kind, 0)
                    if not isinstance(value, (tuple, list)) or len(value) != width:
                        value = fallback
                    normalized[parameter_name] = tuple(
                        _scenelight_fx_clamp(component, low, high)
                        for component in value
                    )
            values = normalized
        elif name == "rain":
            values = {
                "intensity": _scenelight_fx_clamp(values["intensity"], 0.0, 2.0),
                "wetness": _scenelight_fx_clamp(values["wetness"], 0.0, 1.0),
                "wind": _scenelight_fx_clamp(values["wind"], -1.0, 1.0),
                "speed": _scenelight_fx_clamp(values["speed"], 0.05, 4.0),
                "scale": _scenelight_fx_clamp(values["scale"], 0.25, 4.0),
                "color": _scenelight_fx_color(values["color"], (0.78, 0.88, 1.0)),
            }
        elif name == "glitch":
            values = {
                "intensity": _scenelight_fx_clamp(values["intensity"], 0.0, 2.0),
                "rgb_split": _scenelight_fx_clamp(values["rgb_split"], 0.0, 1.0),
                "block_size": _scenelight_fx_clamp(values["block_size"], 0.25, 4.0),
                "speed": _scenelight_fx_clamp(values["speed"], 0.05, 4.0),
                "tear": _scenelight_fx_clamp(values["tear"], 0.0, 1.0),
                "scanlines": _scenelight_fx_clamp(values["scanlines"], 0.0, 1.0),
                "alpha_fragment": _scenelight_fx_clamp(values["alpha_fragment"], 0.0, 1.0),
                "seed": _scenelight_fx_clamp(values["seed"], 0.0, 65535.0),
            }
        return name, values

    def _scenelight_fx_current_state():
        state = getattr(renpy.store, "scenelight_fx_state", None)
        if not isinstance(state, dict) or state.get("version") != 1:
            state = {
                "version": 1,
                "revision": 0,
                "scene": {},
                "characters": {},
            }
        return state

    def _scenelight_fx_assign(state):
        state["revision"] = int(state.get("revision", 0)) + 1
        renpy.store.scenelight_fx_state = state
        redraw_visible = globals().get("_scenelight_redraw_visible_sprites")
        if redraw_visible is not None:
            redraw_visible()
        renpy.restart_interaction()

    def _scenelight_fx_snapshot(tag):
        state = _scenelight_fx_current_state()
        scene = state.get("scene", {})
        characters = state.get("characters", {})
        character = characters.get(str(tag).split()[0], {}) if isinstance(characters, dict) else {}
        result = {}
        for name in _SCENELIGHT_EFFECT_DEFAULTS:
            parameters = {}
            if isinstance(scene, dict) and isinstance(scene.get(name), dict):
                parameters.update(scene[name])
            if isinstance(character, dict) and isinstance(character.get(name), dict):
                parameters.update(character[name])
            result[name] = _scenelight_fx_normalize(name, parameters)[1]
        return result

    def _scenelight_fx_active(tag):
        """Check redraw need without rebuilding normalized effect dictionaries."""

        state = _scenelight_fx_current_state()
        scene = state.get("scene", {})
        characters = state.get("characters", {})
        character = (
            characters.get(str(tag).split()[0], {})
            if isinstance(characters, dict)
            else {}
        )
        for scope in (scene, character):
            if not isinstance(scope, dict):
                continue
            for effect_name, parameters in scope.items():
                if not isinstance(parameters, dict):
                    continue
                custom = _SCENELIGHT_CUSTOM_EFFECTS.get(effect_name)
                if _scenelight_is_mapping(custom) and not bool(
                    custom.get("animated", False)
                ):
                    continue
                try:
                    if float(parameters.get("intensity", 0.0)) > 0.0001:
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    def _scenelight_active_custom_effects(effects):
        active_effects = []
        for effect_name, effect_entry in sorted(_SCENELIGHT_CUSTOM_EFFECTS.items()):
            if not _scenelight_is_mapping(effect_entry):
                continue
            parameters = effects.get(effect_name, {})
            if not _scenelight_is_mapping(parameters):
                continue
            try:
                active = float(parameters.get("intensity", 0.0)) > 0.0001
            except (TypeError, ValueError):
                active = False
            shader_name = effect_entry.get("shader")
            if active and isinstance(shader_name, str):
                active_effects.append((effect_entry, parameters))
        return active_effects

    def _scenelight_apply_custom_effects(result, active_effects):
        for effect_entry, parameters in active_effects:
            result.add_shader(effect_entry["shader"])
            parameter_specs = effect_entry.get("parameters", {})
            if not _scenelight_is_mapping(parameter_specs):
                continue
            for parameter_name, parameter_spec in sorted(parameter_specs.items()):
                if not _scenelight_is_mapping(parameter_spec):
                    continue
                uniform_name = parameter_spec.get("uniform")
                if not isinstance(uniform_name, str):
                    continue
                value = parameters.get(parameter_name, parameter_spec.get("default", 0.0))
                if isinstance(value, list):
                    value = tuple(value)
                result.add_uniform(uniform_name, value)
        if active_effects:
            result.add_shader("scenelight.fx.alpha_guard")

    def _scenelight_custom_effect_render(source_render, active_effects):
        """Run each pack effect as its own post-lighting GPU pass."""

        current = source_render
        for effect_entry, parameters in active_effects:
            width, height = current.get_size()
            result = renpy.Render(width, height)
            result.blit(current, (0, 0))
            result.mesh = True
            result.add_shader("renpy.texture")
            _scenelight_apply_custom_effects(result, [(effect_entry, parameters)])
            current = result
        return current

    class _SceneLightEffectsAPI(object):
        """Rollback-safe optional effect controls exposed to Ren'Py scripts."""

        def scene(self, effect, **parameters):
            name, values = _scenelight_fx_normalize(effect, parameters)
            state = copy.deepcopy(_scenelight_fx_current_state())
            state.setdefault("scene", {})[name] = values
            _scenelight_fx_assign(state)

        def character(self, tag, effect, **parameters):
            name, values = _scenelight_fx_normalize(effect, parameters)
            normalized_tag = str(tag).strip().split()[0]
            if not normalized_tag or normalized_tag == "bg":
                raise ValueError("SceneLight character effects require an image tag")
            state = copy.deepcopy(_scenelight_fx_current_state())
            state.setdefault("characters", {}).setdefault(normalized_tag, {})[name] = values
            _scenelight_fx_assign(state)

        def clear_scene(self, effect=None):
            state = copy.deepcopy(_scenelight_fx_current_state())
            if effect is None:
                state["scene"] = {}
            else:
                name = _scenelight_fx_normalize(effect)[0]
                state.setdefault("scene", {}).pop(name, None)
            _scenelight_fx_assign(state)

        def clear_character(self, tag, effect=None):
            normalized_tag = str(tag).strip().split()[0]
            state = copy.deepcopy(_scenelight_fx_current_state())
            characters = state.setdefault("characters", {})
            if effect is None:
                characters.pop(normalized_tag, None)
            else:
                name = _scenelight_fx_normalize(effect)[0]
                effects = characters.get(normalized_tag, {})
                effects.pop(name, None)
                if not effects:
                    characters.pop(normalized_tag, None)
            _scenelight_fx_assign(state)

        def clear_all(self):
            _scenelight_fx_assign(
                {
                    "version": 1,
                    "revision": 0,
                    "scene": {},
                    "characters": {},
                }
            )

        def state(self):
            return copy.deepcopy(_scenelight_fx_current_state())

    scenelight_fx = _SceneLightEffectsAPI()

    def _scenelight_fx_intensity(effect, tag=None):
        snapshot = _scenelight_fx_snapshot(tag or "")
        return float(snapshot[effect]["intensity"])

    def _scenelight_fx_set_intensity(effect, value, tag=None):
        if tag:
            scenelight_fx.character(tag, effect, intensity=value)
        else:
            scenelight_fx.scene(effect, intensity=value)

    def _scenelight_fx_visible_tags():
        result = []
        for tag in sorted(SCENELIGHT_CHARACTER_TAGS):
            try:
                if renpy.get_attributes(tag, layer="master") is not None:
                    result.append(tag)
            except Exception:
                pass
        return result

    def _scenelight_load_json(path):
        opener = getattr(renpy, "open_file", None)
        if opener is None:
            opener = renpy.loader.load

        stream = opener(path)
        try:
            payload = stream.read()
        finally:
            stream.close()

        if not isinstance(payload, str):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    def _scenelight_texture(path):
        """Load a shader input without transparent-bound cropping on Ren'Py 7/8."""
        displayable = renpy.displayable(path)
        factory = getattr(renpy.display.im, "unoptimized_texture", None)
        if factory is not None:
            return factory(displayable)
        return renpy.display.im.Image(path, optimize_bounds=False)

    def _scenelight_render_for_texture(displayable, width, height, st, at):
        """Use Ren'Py 8's direct texture cache, with the equivalent Ren'Py 7 render path."""
        renderer = getattr(renpy.display.im, "render_for_texture", None)
        if renderer is not None:
            return renderer(displayable, width, height, st, at)
        return renpy.render(displayable, width, height, st, at)

    _SCENELIGHT_FRAGMENT_FUNCTION_ALIASES = (
        ("u_sc_wrap_uv_next", "sc7_wrap_uv_next"),
        ("u_sc_wrap_uv", "sc7_wrap_uv"),
        ("u_sc_wrap_texel", "sc7_wrap_texel"),
        ("u_sc_wrap_blend", "sc7_wrap_blend"),
        ("u_sc_scene_uv_next", "sc7_scene_uv_next"),
        ("u_sc_scene_blend", "sc7_scene_blend"),
        ("u_sc_live_background", "sc7_live_background"),
        ("u_sc_transport_subject_y_max", "sc7_transport_subject_y_max"),
        ("u_sc_transport_grid", "sc7_transport_grid"),
        ("u_sc_transport_uv", "sc7_transport_uv"),
        ("u_sc_atlas_texel", "sc7_atlas_texel"),
        ("u_sc_height_range", "sc7_height_range"),
        ("u_sc_scene_uv", "sc7_scene_uv"),
        ("u_sc_has_form", "sc7_has_form"),
        ("v_sc_center", "sc7_center"),
        ("v_sc_screen", "sc7_screen"),
        ("tex1", "sc7_tex1"),
        ("tex2", "sc7_tex2"),
        ("tex3", "sc7_tex3"),
        ("tex4", "sc7_tex4"),
        ("tex6", "sc7_tex6"),
        ("tex7", "sc7_tex7"),
    )

    _SCENELIGHT_FRAGMENT_FUNCTION_PREAMBLE = """
        uniform vec4 u_sc_wrap_uv;
        uniform vec4 u_sc_wrap_uv_next;
        uniform vec2 u_sc_wrap_texel;
        uniform float u_sc_wrap_blend;
        #define sc7_wrap_uv u_sc_wrap_uv
        #define sc7_wrap_uv_next u_sc_wrap_uv_next
        #define sc7_wrap_texel u_sc_wrap_texel
        #define sc7_wrap_blend u_sc_wrap_blend
        uniform vec4 u_sc_scene_uv_next;
        uniform float u_sc_scene_blend;
        uniform float u_sc_live_background;
        uniform sampler2D tex6;
        uniform sampler2D tex1;
        uniform sampler2D tex2;
        uniform sampler2D tex3;
        uniform sampler2D tex4;
        uniform sampler2D tex7;
        uniform vec4 u_sc_scene_uv;
        uniform vec2 u_sc_atlas_texel;
        uniform float u_sc_has_form;
        uniform vec2 u_sc_height_range;
        uniform vec4 u_sc_transport_uv;
        uniform vec2 u_sc_transport_grid;
        uniform float u_sc_transport_subject_y_max;
        varying vec2 v_sc_center;
        varying vec2 v_sc_screen;
        #define sc7_tex1 tex1
        #define sc7_scene_uv_next u_sc_scene_uv_next
        #define sc7_scene_blend u_sc_scene_blend
        #define sc7_live_background u_sc_live_background
        #define sc7_tex6 tex6
        #define sc7_tex2 tex2
        #define sc7_tex3 tex3
        #define sc7_tex4 tex4
        #define sc7_tex7 tex7
        #define sc7_scene_uv u_sc_scene_uv
        #define sc7_atlas_texel u_sc_atlas_texel
        #define sc7_has_form u_sc_has_form
        #define sc7_height_range u_sc_height_range
        #define sc7_transport_uv u_sc_transport_uv
        #define sc7_transport_grid u_sc_transport_grid
        #define sc7_transport_subject_y_max u_sc_transport_subject_y_max
        #define sc7_center v_sc_center
        #define sc7_screen v_sc_screen
    """

    def _scenelight_fragment_source(source, preamble=False):
        """Declare dependencies used only by reusable fragment functions.

        Ren'Py discovers a shader part's variables by scanning its numbered
        ``fragment_*`` body, not ``fragment_functions``. Ren'Py through 8.2
        also emits helper functions before the discovered declarations. Route
        helper-only dependencies through one explicit preamble on every
        supported renderer so neither assembler behavior can omit them.
        """
        for original, alias in _SCENELIGHT_FRAGMENT_FUNCTION_ALIASES:
            source = source.replace(original, alias)
        if preamble:
            return _SCENELIGHT_FRAGMENT_FUNCTION_PREAMBLE + source
        return source

    SCENELIGHT_MANIFEST = _scenelight_load_json(SCENELIGHT_MANIFEST_PATH)
    SCENELIGHT_FORM_MANIFEST = _scenelight_load_json(SCENELIGHT_FORM_MANIFEST_PATH)
    SCENELIGHT_ATLAS = SCENELIGHT_MANIFEST["atlas"]
    SCENELIGHT_TRANSPORT_ATLAS = SCENELIGHT_MANIFEST.get("transport_atlas", {})
    SCENELIGHT_SCENES = SCENELIGHT_MANIFEST["scenes"]
    SCENELIGHT_SCENE_SEQUENCES = SCENELIGHT_MANIFEST.get("scene_sequences", {})
    _SCENELIGHT_UNSEEN_TEMPORAL_STATES = set()
    _SCENELIGHT_MOVIE_CLOCK_FRAME = None
    _SCENELIGHT_MOVIE_POSITIONS = {}
    renpy.display._scenelight_transport_frames = None
    # Ren'Py rewrites dict literals into rollback-tracked RevertableDicts,
    # even when assigned outside the store. A movie texture in that dictionary
    # would survive in each interaction's rollback snapshot. Use the standard
    # library container so replacing a presented frame releases the old one.
    renpy.display._scenelight_presented_movies = _SceneLightOrderedDict()
    SCENELIGHT_CHARACTER_TAGS.update(
        str(tag).split()[0]
        for tag in SCENELIGHT_MANIFEST.get("character_tags", [])
        if str(tag).strip()
    )
    SCENELIGHT_REFERENCE_ART_MID = float(SCENELIGHT_MANIFEST["reference_art_mid"])
    try:
        SCENELIGHT_PROFILE_STRENGTH = max(
            0.0, min(float(SCENELIGHT_MANIFEST.get("strength", 1.0)), 2.0)
        )
    except (TypeError, ValueError):
        SCENELIGHT_PROFILE_STRENGTH = 1.0
    SCENELIGHT_FORM_SPRITES = SCENELIGHT_FORM_MANIFEST["sprites"]
    SCENELIGHT_FORM_FALLBACK = SCENELIGHT_FORM_MANIFEST["fallback"]

    def _scenelight_runtime_module(name):
        # Execute without Ren'Py's Python-2 unicode/store transformations.
        import sys
        import types
        module_name = "_scenelight_" + name
        if sys.version_info[0] < 3:
            module_name = module_name.encode("ascii")
        module = types.ModuleType(module_name)
        # .txt is a shipped runtime resource. Ren'Py deliberately excludes
        # standalone .py files from its asset loader and distribution archive.
        path = "scenelight_runtime/" + name + ".txt"
        with renpy.file(path) as stream:
            eval(compile(stream.read(), path, "exec", 0, True), module.__dict__)
        # Python 2 clears a module's globals when the module itself is freed,
        # even while an extracted class still references that globals dict.
        sys.modules[module_name] = module
        return module

    renpy.display._scenelight_live_renderer = None
    renpy.display._scenelight_live_error = None
    if (_SCENELIGHT_SHADER_AVAILABLE and SCENELIGHT_MANIFEST.get("scene_analysis", "live") == "live"
            and tuple(SCENELIGHT_TRANSPORT_ATLAS.get("grid_size", (16, 9))) == (16, 9)
            and renpy.loadable("scenelight_runtime/live_gpu.txt")):
        try:
            if renpy.loadable("scenelight_runtime/live_opencl.txt"):
                _scenelight_runtime_module("live_opencl")
            renpy.display._scenelight_live_renderer = _scenelight_runtime_module("live_renpy").Renderer(
                _scenelight_runtime_module("live_gpu"), renpy, config
            )
            if renpy.loadable("scenelight_runtime/prepared_movies.json") and renpy.loadable("scenelight_runtime/prepared_renpy.txt"):
                try:
                    renpy.display._scenelight_live_renderer.prepared = _scenelight_runtime_module("prepared_renpy").Movies(
                        renpy, _scenelight_runtime_module("prepared").Reader
                    )
                    renpy.display._scenelight_live_renderer.prepared.install_decode_hook()
                except Exception:
                    import traceback
                    renpy.display.log.write("SceneLight movie cache could not be opened; live analysis remains available.\n" + traceback.format_exc())
        except Exception:
            import traceback
            renpy.display._scenelight_live_error = traceback.format_exc()
            renpy.display.log.write("SceneLight could not load live analysis.\n" + renpy.display._scenelight_live_error)

    class _SceneLightFrameReference(object):
        """Serializable identity; GPU fields remain in the renderer's weak cache."""
        pass

    class _SceneLightBackground(renpy.Displayable):
        def __init__(self, child, scene_key):
            super(_SceneLightBackground, self).__init__()
            self.child = child
            self.scene_key = scene_key
            # Ren'Py may render a current-store copy instead of the scene-list
            # object. Copies of this showing share one serializable binding.
            self.binding = _SceneLightFrameReference()
            self._sc_canvas_mode = False
            self._sc_canvas_offset = (0, 0)
            self._sc_frozen_canvas = None

        def visit(self):
            return [self.child]

        def per_interact(self):
            renderer = renpy.display._scenelight_live_renderer
            if renderer is not None and renderer.frozen_canvas(self._sc_frozen_canvas) is not None:
                return
            if renderer is not None and not renderer.disabled and (renderer.frame(self) is None or renderer.animated(self)):
                # Save/load and rollback restore serializable bindings while
                # the renderer's transient weak cache remains outside the save.
                renpy.redraw(self, 0.0)

        def get_placement(self):
            if self._sc_canvas_mode:
                return (0, 0, 0, 0, 0, 0, False)
            return self.child.get_placement()

        def event(self, event, x, y, st):
            if self._sc_canvas_mode:
                x -= self._sc_canvas_offset[0]
                y -= self._sc_canvas_offset[1]
            return self.child.event(event, x, y, st)

        def set_transform_event(self, event):
            self.child.set_transform_event(event)
            super(_SceneLightBackground, self).set_transform_event(event)

        def _handles_event(self, event):
            return self.child._handles_event(event)

        def _show(self):
            self.child._show()

        def _hide(self, st, at, kind):
            child = self.child._hide(st, at, kind)
            if child is None:
                return None
            result = self._copy()
            result.child = child
            # A hide/replaced ATL is a new live animation, not the frozen
            # background image retained for a scene-wide transition.
            result._sc_frozen_canvas = None
            result._sc_canvas_mode = False
            return result

        def _change_transform_child(self, child):
            if isinstance(child, _SceneLightBackground):
                return child
            result = self._copy()
            result.child = self.child._change_transform_child(child)
            return result

        def _in_current_store(self):
            result = self._copy()
            result.child = self.child._in_current_store()
            renderer = renpy.display._scenelight_live_renderer
            if result._sc_frozen_canvas is None and renderer is not None:
                reference = _SceneLightFrameReference()
                if renderer.pin_canvas(self, reference):
                    result._sc_frozen_canvas = reference
                    result._sc_canvas_mode = True
            return result

        def render(self, width, height, st, at):
            renderer = renpy.display._scenelight_live_renderer
            if renderer is not None:
                frozen = renderer.frozen_canvas(self._sc_frozen_canvas)
                if frozen is not None:
                    texture, size = frozen
                    result = renpy.Render(*size)
                    result.blit(texture, (0, 0))
                    return result
            rendered = renpy.render(self.child, width, height, st, at)
            if renderer is not None:
                before = renderer.frame(self)
                renderer.capture(self, rendered, width, height, _SceneLightFrameReference)
                if renderer.frame(self) is not before:
                    _scenelight_redraw_visible_sprites()
                if renderer.animated(self):
                    renpy.redraw(self, 0.0)
                captured = renderer.canvas(self)
                if captured is not None:
                    canvas, self._sc_canvas_offset = captured
                    self._sc_canvas_mode = True
                    # Reuse the exact pixels analyzed, including u_random and
                    # draw-time uniforms. The full drawable resolution and
                    # original child/focus tree are retained by this mesh.
                    result = renpy.Render(width, height)
                    result.blit(canvas, (0, 0))
                    result.mesh = True
                    result.add_shader("renpy.texture")
                    result.add_property("mipmap", False)
                    result.add_property("drawable_resolution", True)
                    return result
            self._sc_canvas_mode = False
            # Give the tap its own dependency node. Ren'Py attaches render_of
            # to the returned Render; attaching it to a cached leaf would
            # retain the tap through the renderer's source-identity cache.
            result = renpy.Render(*rendered.get_size())
            result.blit(rendered, (0, 0))
            return result

    def _scenelight_live_fields(scene):
        renderer = renpy.display._scenelight_live_renderer
        return renderer.fields(scene.get("_sc_live_frame")) if renderer is not None and scene else None

    def _scenelight_resolve_live_scene(scene):
        if not scene or "_sc_live_binding" not in scene or _scenelight_live_fields(scene):
            return scene
        renderer = renpy.display._scenelight_live_renderer
        frame = renderer.frame(scene["_sc_live_binding"]) if renderer is not None else None
        # A frame that survived the binding lookup but lost its fields would put
        # the sprite in live-atlas coordinates while it samples the packaged
        # atlas. Require the fields themselves, so the fallback is always a
        # scene whose UVs match the textures it will actually be given.
        if frame is None or renderer.fields(frame) is None:
            return SCENELIGHT_SCENES.get(scene["_sc_live_key"])
        result = dict(scene)
        result.update({"uv": (0.0, 0.0, 1.0, 1.0),
            "transport_uv": (0.0, 0.0, 1.0 / 26.0, 0.9), "_sc_live_frame": frame})
        return result

    def _scenelight_calibration_blocks(scene, authored_values=None):
        values = dict(_SCENELIGHT_CALIBRATION_DEFAULTS)
        global_values = SCENELIGHT_MANIFEST.get("calibration", {})
        if isinstance(global_values, dict):
            values.update(global_values)
        scene_values = scene.get("calibration", {})
        if isinstance(scene_values, dict):
            values.update(scene_values)
        if isinstance(authored_values, dict):
            values.update(authored_values)

        def bounded(name, low=0.0, high=2.0):
            try:
                return max(low, min(float(values[name]), high))
            except (KeyError, TypeError, ValueError):
                return _SCENELIGHT_CALIBRATION_DEFAULTS[name]

        return (
            (bounded("auto_strength"), bounded("exposure_bias", -4.0, 4.0), bounded("ambient_strength"), bounded("color_adaptation")),
            (bounded("contrast_match"), bounded("saturation_match"), bounded("highlight_rolloff"), bounded("key_strength")),
            (bounded("ray_shadow_strength"), bounded("ambient_occlusion"), bounded("probe_strength"), bounded("bounce_strength")),
            (bounded("specular_strength"), bounded("rim_strength"), bounded("wrap_strength"), bounded("grain_match")),
            (bounded("shadow_strength"), bounded("individual_light_colors"), bounded("adaptive_light_colors"), bounded("light_color_tolerance", 0.0, 1.0)),
            (bounded("glow_strength", 0.0, 10.0), bounded("glow_radius"), bounded("emission_strength"), bounded("emission_radius")),
            (bounded("emission_red"), bounded("emission_green"), bounded("emission_blue"), 0.0),
            (bounded("glow_red", 0.0, 1.0), bounded("glow_green", 0.0, 1.0), bounded("glow_blue", 0.0, 1.0), bounded("glow_color_mix", 0.0, 1.0)),
            (bounded("light_color_red", 0.0, 1.0), bounded("light_color_green", 0.0, 1.0), bounded("light_color_blue", 0.0, 1.0), bounded("light_color_amount", -1.0, 1.0)),
        )

    def _scenelight_emission_controls(scene_key, tag, controls):
        """Whole-image aliases use the glow rule of the shown image."""
        try:
            entries = renpy.game.context().scene_lists.layers.get("master", ())
        except Exception:
            return controls
        for entry in entries:
            if getattr(entry, "tag", None) != tag:
                continue
            name = getattr(entry, "name", ()) or (tag,)
            name = name if isinstance(name, _SCENELIGHT_STRING_TYPES) else " ".join(name)
            visible = _scenelight_control_snapshot(scene_key, tag, name)
            updated = copy.deepcopy(controls)
            for key in _SCENELIGHT_CALIBRATION_DEFAULTS:
                if key.startswith(("glow_", "emission_")):
                    updated["calibration"].pop(key, None)
                    if key in visible["calibration"]:
                        updated["calibration"][key] = visible["calibration"][key]
            if not visible["enabled"]:
                updated["calibration"].update(glow_strength=0.0, emission_strength=0.0, glow_rules=[])
            return updated
        return controls

    def _scenelight_color_glow_rules(scene, controls):
        rules = SCENELIGHT_MANIFEST.get("calibration", {}).get("glow_rules", ())
        rules = (scene or {}).get("calibration", {}).get("glow_rules", rules)
        rules = controls.get("calibration", {}).get("glow_rules", rules)
        return tuple(rule for rule in _scenelight_control_glow_rules(rules)
                     if rule["enabled"] and rule["strength"] > 0.0)

    def _scenelight_sprite_emitters(receiver_tag):
        """Resolve visible emitters from the scene, independent of draw order."""
        global _SCENELIGHT_MEASURING_EMITTERS
        if _SCENELIGHT_MEASURING_EMITTERS or not _scenelight_master_enabled():
            return ()
        try:
            entries = renpy.game.context().scene_lists.layers.get("master", ())
        except Exception:
            return ()
        scene_key, scene = _scenelight_live_scene_entry()
        master = max(0.0, _scenelight_master_strength())
        lights = []
        for entry in entries:
            tag = getattr(entry, "tag", None)
            if tag not in SCENELIGHT_CHARACTER_TAGS or tag == receiver_tag:
                continue
            name = getattr(entry, "name", ()) or (tag,)
            name = name if isinstance(name, _SCENELIGHT_STRING_TYPES) else " ".join(name)
            controls = _scenelight_control_snapshot(scene_key, tag, name)
            blocks = _scenelight_calibration_blocks(scene or {}, controls.get("calibration", {}))
            intensity, radius = blocks[5][2:]
            if not controls["enabled"] or intensity * master <= 0.0 or radius <= 0.0:
                continue
            # Ren'Py's bounds API uses render_for_size (not a presented frame).
            # Bypass SceneLight only during this measurement to prevent recursive
            # emitter queries or overwriting last-presented transition state.
            _SCENELIGHT_MEASURING_EMITTERS = True
            try:
                bounds = renpy.get_image_bounds(tag, config.screen_width, config.screen_height, "master")
            finally:
                _SCENELIGHT_MEASURING_EMITTERS = False
            if not bounds or bounds[2] <= 0 or bounds[3] <= 0:
                continue
            x, y, width, height = bounds
            lights.append((
                tag,
                ((x + width * 0.5) / float(config.screen_width),
                 (y + height * 0.5) / float(config.screen_height), radius, intensity * master),
                blocks[6][:3],
            ))
        # Stable selection if a scene exceeds the four simultaneous sources.
        lights.sort(key=lambda light: (-light[1][3], light[0]))
        return tuple((data, color) for _tag, data, color in lights[:4])
    SCENELIGHT_FORM_CANDIDATES = {}
    for _sc_form_name, _sc_form_entry in SCENELIGHT_FORM_SPRITES.items():
        _sc_form_parts = tuple(_sc_form_name.split())
        if not _sc_form_parts:
            continue
        SCENELIGHT_FORM_CANDIDATES.setdefault(_sc_form_parts[0], []).append(
            (
                frozenset(_sc_form_parts[1:]),
                _sc_form_name,
                _sc_form_entry,
            )
        )

    def _scenelight_resolve_form_entry(form_key, base_form_key):
        """Use only the current expression's map, independent of attribute order."""
        exact = SCENELIGHT_FORM_SPRITES.get(form_key)
        if exact is not None:
            return exact
        parts = tuple(form_key.split())
        if parts:
            requested = frozenset(parts[1:])
            for attributes, name, entry in SCENELIGHT_FORM_CANDIDATES.get(parts[0], ()):
                if requested == attributes:
                    return entry
        # An arbitrary attribute superset can describe another mouth, eyes, or
        # pose. Let the shader infer the surface from the actual composite when
        # no exact map was captured; never borrow a different expression's map.
        return None

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

    def _scenelight_movie_position(channel):
        """Use the clock captured with the visible decoded texture, shared by all subjects."""
        global _SCENELIGHT_MOVIE_CLOCK_FRAME
        frame = renpy.game.interface.frame_time
        if frame != _SCENELIGHT_MOVIE_CLOCK_FRAME:
            _SCENELIGHT_MOVIE_POSITIONS.clear()
            _SCENELIGHT_MOVIE_CLOCK_FRAME = frame
        if channel not in _SCENELIGHT_MOVIE_POSITIONS:
            display = getattr(renpy, "display", None)
            presented = getattr(display, "_scenelight_presented_movies", {}).get(channel)
            textures = getattr(getattr(display, "video", None), "texture", {})
            if (presented is not None and textures.get(channel) is presented[2]
                and renpy.music.get_playing(channel=channel) == presented[0]):
                position = presented[1]
            else:
                position = renpy.music.get_pos(channel=channel)
            _SCENELIGHT_MOVIE_POSITIONS[channel] = position
        return _SCENELIGHT_MOVIE_POSITIONS[channel]

    def _scenelight_movie_texture_hook(original):
        """Observe the engine's decode; never ask it to decode a second frame."""
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            channel = kwargs.get("channel", args[0] if args else None)
            try:
                texture, changed = result
                frames = renpy.display._scenelight_presented_movies
                textures = getattr(renpy.display.video, "texture", {})
                for stale in list(frames):
                    if textures.get(stale) is not frames[stale][2]:
                        frames.pop(stale, None)
                if texture is None:
                    frames.pop(channel, None)
                elif changed:
                    renderer = getattr(renpy.display, "_scenelight_live_renderer", None)
                    prepared = getattr(renderer, "prepared", None)
                    decoded = prepared.decoded.get(channel) if prepared is not None else None
                    playing = renpy.music.get_playing(channel=channel)
                    frames[channel] = (
                        playing,
                        renpy.music.get_pos(channel=channel),
                        texture,
                        decoded[1] if decoded is not None and decoded[0] == playing else None,
                    )
            except Exception:
                # Optional clock bookkeeping must not break video playback on
                # an alternate backend. The resolver retains its clock fallback.
                getattr(renpy.display, "_scenelight_presented_movies", {}).pop(channel, None)
            return result
        wrapped._scenelight_movie_hook = True
        wrapped._scenelight_original = original
        return wrapped

    def _scenelight_timed_scene(key, token=None):
        """Use the displayed source or media position, never a dialogue clock."""
        base_scene = SCENELIGHT_SCENES.get(key)
        sequence = SCENELIGHT_SCENE_SEQUENCES.get(key)
        # Ren'Py's script compiler substitutes RevertableDict for `dict`.
        # json.loads returns a builtin dict, which fails that isinstance test.
        if not isinstance(sequence, _SceneLightMapping):
            return base_scene
        displayable = getattr(token, "displayable", None)
        if displayable is None:
            return None
        now = float(renpy.game.interface.frame_time)
        st = max(0.0, now - (getattr(token, "show_time", None) or now))
        at = max(0.0, now - (getattr(token, "animation_time", None) or now))
        if sequence.get("mode") == "visible-source":
            sources = _scenelight_visible_sources(displayable, st, at)
            if len(sources) == 1:
                selected_key = sequence.get("sources", {}).get(sources[0])
                if selected_key in SCENELIGHT_SCENES:
                    return SCENELIGHT_SCENES[selected_key]
            # An unseen Python-produced state must not inherit an unrelated
            # frame's lighting. Discovery coverage is bounded, not universal.
            diagnostic = (key, tuple(sources))
            if diagnostic not in _SCENELIGHT_UNSEEN_TEMPORAL_STATES:
                if len(_SCENELIGHT_UNSEEN_TEMPORAL_STATES) < 128:
                    _SCENELIGHT_UNSEEN_TEMPORAL_STATES.add(diagnostic)
                    renpy.log("SceneLight: unanalysed background state %r; leaving sprite unlit." % (diagnostic,))
            return None
        if sequence.get("mode") != "movie-position":
            return None
        pending, seen = [displayable], set()
        while pending and len(seen) < 256:
            current = pending.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            if current.__class__.__name__ == "Movie":
                playing = renpy.music.get_playing(channel=current.channel)
                if playing != sequence.get("source"):
                    return base_scene
                position = _scenelight_movie_position(current.channel)
                if position is None or position < 0:
                    return base_scene
                elapsed_ms = position * 1000.0
                # Decoder position already handles looping, seeking and pause.
                # Do not modulo an inferred duration or restart on expressions.
                selected_key = key
                selected_time = 0.0
                for frame_time, frame_key in sequence.get("frames", ()):
                    if frame_time > elapsed_ms:
                        left = SCENELIGHT_SCENES.get(selected_key, base_scene)
                        right = SCENELIGHT_SCENES.get(frame_key, left)
                        # Cut boundaries must remain abrupt. Capture records
                        # both sides; old manifests have no cut information.
                        if frame_time in sequence.get("cuts_ms", ()):
                            return left
                        amount = (elapsed_ms - selected_time) / max(frame_time - selected_time, 1.0)
                        return _scenelight_blended_scene(left, right, amount)
                    selected_key = frame_key
                    selected_time = frame_time
                return SCENELIGHT_SCENES.get(selected_key, base_scene)
            for attribute in ("child", "target", "displayable"):
                pending.append(getattr(current, attribute, None))
        return base_scene

    def _scenelight_lerp_scene_value(left, right, amount):
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return float(left) + (float(right) - float(left)) * amount
        if isinstance(left, _SceneLightMapping) and isinstance(right, _SceneLightMapping):
            return {
                name: _scenelight_lerp_scene_value(value, right.get(name, value), amount)
                for name, value in left.items()
            }
        if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)) and len(left) == len(right):
            return [_scenelight_lerp_scene_value(a, b, amount) for a, b in zip(left, right)]
        return left if amount < 0.5 else right

    def _scenelight_blended_scene(left, right, amount):
        """Keep exact endpoint records; intermediate fields are mixed on GPU."""
        if left is None or right is None or left is right or amount <= 0.0:
            return left
        if amount >= 1.0:
            return right
        result = _scenelight_lerp_scene_value(left, right, amount)
        for name in ("uv", "transport_uv", "calibration", "tile"):
            if name in left:
                result[name] = left[name]
        result["_sc_next_uv"] = right.get("uv", (0.0, 0.0, 1.0, 1.0))
        result["_sc_next_transport_uv"] = right.get("transport_uv", (0.0, 0.0, 1.0, 1.0))
        result["_sc_blend"] = amount
        changed = bool(left.get("light_transport_layout") and right.get("light_transport_layout")
            and left["light_transport_layout"] != right["light_transport_layout"])
        result["_sc_layout_change"] = changed
        if changed:
            side = left if amount < 0.5 else right
            phase = amount * 2.0 if amount < 0.5 else amount * 2.0 - 1.0
            fade = phase * phase * (3.0 - 2.0 * phase)
            if amount < 0.5:
                fade = 1.0 - fade
            lights = result.get("light_transport", [])[:1]
            for light in side.get("light_transport", [])[1:4]:
                faded = copy.deepcopy(light)
                for name, indices in (("position_radius_intensity", (3,)), ("chroma_confidence", (3,)), ("emission_enabled", (0, 1))):
                    values = list(faded[name])
                    for index in indices:
                        values[index] *= fade
                    faded[name] = values
                lights.append(faded)
            result["light_transport"] = lights
        return result

    def _scenelight_live_scene_entry():
        global SCENELIGHT_STABLE_SCENE_KEY, SCENELIGHT_STABLE_SCENE
        # Prefer the exact image name retained by Ren'Py's scene list. This
        # supports games whose backgrounds are named ``room day`` or ``room1``
        # instead of using DDLC's conventional ``bg <name>`` tag.
        explicit_background = False
        try:
            entries = renpy.game.context().scene_lists.layers.get("master", ())
            for entry in reversed(entries):
                entry_tag = getattr(entry, "tag", None)
                if entry_tag and str(entry_tag).startswith(("hide$", "replaced$")):
                    continue
                background = getattr(entry, "displayable", None)
                renderer = renpy.display._scenelight_live_renderer
                if isinstance(background, _SceneLightBackground) and renderer is not None:
                    key = background.scene_key
                    scene = dict(SCENELIGHT_SCENES.get(key, {}))
                    scene.update({"_sc_live_binding": background.binding, "_sc_live_key": key})
                    frame = renderer.frame(background)
                    if frame is not None and renderer.fields(frame) is not None:
                        scene.update({"uv": (0.0, 0.0, 1.0, 1.0),
                            "transport_uv": (0.0, 0.0, 1.0 / 26.0, 0.9),
                            "_sc_live_frame": frame})
                    SCENELIGHT_STABLE_SCENE_KEY = key
                    SCENELIGHT_STABLE_SCENE = scene
                    return key, scene
                image_name = getattr(entry, "name", None)
                if not image_name:
                    continue
                if isinstance(image_name, (tuple, list)):
                    parts = tuple(str(part).lower() for part in image_name)
                else:
                    parts = tuple(str(image_name).lower().split())
                if not parts:
                    continue
                if parts[0] == "bg":
                    explicit_background = True
                key = " ".join(parts[1:]) if parts[0] == "bg" and len(parts) > 1 else " ".join(parts)
                scene = _scenelight_timed_scene(key, entry)
                if key in SCENELIGHT_SCENE_SEQUENCES:
                    SCENELIGHT_STABLE_SCENE_KEY = key
                    SCENELIGHT_STABLE_SCENE = scene
                    return key, scene
                if scene is not None:
                    SCENELIGHT_STABLE_SCENE_KEY = key
                    SCENELIGHT_STABLE_SCENE = scene
                    return key, scene
        except Exception:
            pass

        # Ren'Py 6 scene-list entries predate the retained image-name field.
        # Keep the original DDLC lookup as the compatibility path.
        try:
            attributes = renpy.get_attributes("bg", layer="master")
        except Exception:
            attributes = None
        if attributes:
            explicit_background = True
            candidates = (" ".join(attributes), attributes[0])
            for key in candidates:
                scene = _scenelight_timed_scene(key)
                if scene is not None:
                    SCENELIGHT_STABLE_SCENE_KEY = key
                    SCENELIGHT_STABLE_SCENE = scene
                    return key, scene

        # A show/hide operation mutates Ren'Py's scene list in stages. During
        # that mutation the background can disappear from the list for one
        # interaction even though it did not change on screen. Retain the last
        # valid field for that transient gap so characters never flash unlit.
        if not explicit_background and SCENELIGHT_STABLE_SCENE is not None:
            timed = _scenelight_timed_scene(SCENELIGHT_STABLE_SCENE_KEY)
            if timed is not None:
                SCENELIGHT_STABLE_SCENE = timed
            return SCENELIGHT_STABLE_SCENE_KEY, SCENELIGHT_STABLE_SCENE

        # An explicit, unsupported ``bg`` image is a real scene change rather
        # than a transient list mutation. Do not leak the old scene into it.
        SCENELIGHT_STABLE_SCENE_KEY = None
        SCENELIGHT_STABLE_SCENE = None
        return None, None

    def _scenelight_live_scene():
        return _scenelight_live_scene_entry()[1]

    def _scenelight_contains_lit_sprite(displayable):
        """Return True when a render tree contains a SceneLight sprite.

        Ren'Py transitions receive complete layer trees, not the image tag
        that initiated the transition. Walking ``visit`` is the only stable
        cross-version way to identify a lit side without depending on a
        transition's private implementation.
        """
        pending = [displayable]
        seen = set()
        while pending and len(seen) < 4096:
            current = pending.pop()
            if current is None:
                continue
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            if isinstance(current, SceneLightSprite):
                return True
            visit = getattr(current, "visit", None)
            if visit is None:
                continue
            try:
                pending.extend(visit() or ())
            except Exception:
                pass
        return False

    def _scenelight_flatten_lit_side(displayable):
        """Bake lighting before a transition changes screen coordinates."""
        if displayable is None or not _scenelight_contains_lit_sprite(displayable):
            return displayable
        prepared_sprites = []
        pending = [displayable]
        seen = set()
        while pending and len(seen) < 4096:
            current = pending.pop()
            if current is None:
                continue
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            if isinstance(current, SceneLightSprite):
                if current._sc_snapshot_frozen:
                    if current._sc_frozen_screen_rect is None:
                        current._sc_frozen_screen_rect = current._scenelight_screen_rect()
                else:
                    current._sc_transition_screen_rect = current._scenelight_screen_rect()
                    prepared_sprites.append(current)
            visit = getattr(current, "visit", None)
            if visit is not None:
                try:
                    pending.extend(visit() or ())
                except Exception:
                    pass
        try:
            rendered = renpy.render(
                displayable,
                config.screen_width,
                config.screen_height,
                0.0,
                0.0,
            )
            renderer = renpy.display._scenelight_live_renderer
            # RTT does not resolve the mesh samplers itself. Drawing this tree
            # early can fail after allocation and leak an unfinished texture.
            texture = renderer.snapshot(rendered) if renderer is not None else None
            if texture is not None:
                return _SceneLightFrozenSide(
                    texture,
                    rendered.get_size(),
                    displayable.get_placement(),
                )
        except Exception:
            # Older/alternate model renderers may not expose GPU RTT here.
            # Retain Ren'Py's supported lazy flattening path rather than
            # breaking the authored transition.
            pass
        finally:
            for sprite in prepared_sprites:
                sprite._sc_transition_screen_rect = None
        flatten = getattr(getattr(renpy.display, "layout", None), "Flatten", None)
        if flatten is None:
            return displayable
        return flatten(displayable)

    class _SceneLightFrozenSide(renpy.Displayable):
        """Display one already-rendered transition side without re-running shaders."""

        def __init__(self, texture, size, placement):
            super(_SceneLightFrozenSide, self).__init__()
            self.texture = texture
            self.size = tuple(size)
            self.placement = placement

        def render(self, width, height, st, at):
            rv = renpy.Render(*self.size)
            rv.blit(self.texture, (0, 0))
            return rv

        def get_placement(self):
            return self.placement

    class _SceneLightLiveTransitionSide(renpy.Displayable):
        """Resolve the incoming scene's lighting in its own coordinates each frame."""

        def __init__(self, child):
            super(_SceneLightLiveTransitionSide, self).__init__()
            self.child = child

        def visit(self):
            return [self.child]

        def get_placement(self):
            return self.child.get_placement()

        def event(self, event, x, y, st):
            return self.child.event(event, x, y, st)

        def render(self, width, height, st, at):
            rendered = renpy.render(self.child, width, height, st, at)
            # Let child dependencies schedule updates; do not force a texture
            # snapshot or query every character for its bounds.
            #
            # The render must stay exactly as the transition asked for it.
            # Ren'Py scales the virtual screen to the drawable for both sides
            # of a transition, and the rasteriser clips anything outside that
            # space. Clipping into an extra screen-sized render, wrapping it in
            # a mesh pass, or claiming the drawable resolution all put this side
            # in a different coordinate system from the outgoing side: the
            # scene scales wrongly and screen-space sprite lighting samples
            # outside its field, which shows up mid-transition as an opaque
            # black sprite quad and a black character silhouette.
            return rendered

    # Scene-wide transitions render their sides into another framebuffer. That
    # changes the coordinate system seen by a screen-space sprite shader, so
    # retain the outgoing snapshot and resolve the incoming side live, in the
    # transition's own coordinates. Its own movie/animation dependencies remain
    # live without repeated synchronous snapshots or character-bounds queries.
    # Never use screenshot_to_bytes here: it reads the framebuffer back to the
    # CPU and PNG-encodes it synchronously, which stalls story advancement.
    _scenelight_existing_with_callback = config.with_callback
    if (
        getattr(_scenelight_existing_with_callback, "_scenelight_callback", False)
        or getattr(_scenelight_existing_with_callback, "__name__", "")
        == "_scenelight_with_callback"
    ):
        _SCENELIGHT_PREVIOUS_WITH_CALLBACK = getattr(
            _scenelight_existing_with_callback,
            "_scenelight_previous",
            None,
        )
    else:
        _SCENELIGHT_PREVIOUS_WITH_CALLBACK = _scenelight_existing_with_callback

    def _scenelight_with_callback(transition, paired):
        if _SCENELIGHT_PREVIOUS_WITH_CALLBACK is not None:
            transition = _SCENELIGHT_PREVIOUS_WITH_CALLBACK(transition, paired)

        if (
            not transition
            or paired is not None
            or not _scenelight_master_enabled()
        ):
            return transition

        def apply_stable_transition(old_widget=None, new_widget=None):
            old_side = _scenelight_flatten_lit_side(old_widget)
            new_side = (
                _SceneLightLiveTransitionSide(new_widget)
                if _scenelight_contains_lit_sprite(new_widget) else new_widget
            )
            return transition(old_widget=old_side, new_widget=new_side)

        return apply_stable_transition

    if _SCENELIGHT_SHADER_AVAILABLE:
        _scenelight_with_callback._scenelight_callback = True
        _scenelight_with_callback._scenelight_previous = _SCENELIGHT_PREVIOUS_WITH_CALLBACK
        config.with_callback = _scenelight_with_callback

    # The live-source prototype uses the same shader in both hosts. Its field
    # is diagnostic until the complete source/exposure solver passes the
    # reference gate; it is never substituted for the production light model.
    _scenelight_shader_data = _scenelight_runtime_module("shader_data").SHADERS

    _scenelight_shader_live_probe_variables = _scenelight_shader_data['live_probe_variables']
    _scenelight_shader_live_probe_fragment = _scenelight_shader_data['live_probe_fragment']

    _scenelight_shader_transport_blend_variables = _scenelight_shader_data['transport_blend_variables']
    _scenelight_shader_transport_blend_fragment = _scenelight_shader_data['transport_blend_fragment']

    if _SCENELIGHT_SHADER_AVAILABLE:
        renpy.register_shader(
            "scenelight.transport_blend",
            variables=_scenelight_shader_transport_blend_variables,
            fragment_300=_scenelight_shader_transport_blend_fragment,
        )

    def _scenelight_transport_frame(scene, atlas, st, at):
        """Reuse the same tiny GPU field while the decoded lighting state is unchanged."""
        # Keep transient Render objects in the renderer module, outside save and
        # rollback state. Only immutable scene parameters enter the save graph.
        state = getattr(renpy.display, "_scenelight_transport_frames", None)
        if state is None or state[0] is not renpy.display.draw:
            state = (renpy.display.draw, _SceneLightOrderedDict())
            renpy.display._scenelight_transport_frames = state
        left = tuple(scene["transport_uv"])
        right = tuple(scene["_sc_next_transport_uv"])
        key = (id(atlas), left, right, scene["_sc_blend"], scene.get("_sc_layout_change", False))
        if key in state[1]:
            result = state[1].pop(key)
            # Ren'Py can clear Render children during cache collection even
            # while a Python reference survives. Never resurrect that object.
            if not getattr(result, "killed", True) and not getattr(result, "cache_killed", True):
                state[1][key] = result
                return result
        grid = SCENELIGHT_TRANSPORT_ATLAS.get("grid_size", (16, 9))
        width, height = grid[0] * 26, grid[1]
        result = renpy.Render(width, height)
        result.blit(renpy.render(Solid("#fff", xsize=width, ysize=height), width, height, st, at), (0, 0))
        result.blit(atlas, (0, 0))
        result.mesh = True
        result.add_shader("renpy.texture")
        result.add_shader("scenelight.transport_blend")
        result.add_uniform("u_sc_field_left", (left[0], left[1], left[2] * 26, left[3]))
        result.add_uniform("u_sc_field_right", (right[0], right[1], right[2] * 26, right[3]))
        result.add_uniform("u_sc_field_amount", float(scene["_sc_blend"]))
        result.add_uniform("u_sc_field_layout_change", 1.0 if scene.get("_sc_layout_change") else 0.0)
        state[1][key] = result
        while len(state[1]) > 8:
            state[1].popitem(last=False)
        return result

    # Every rule is a separate three-texture pass. tex1 is ALWAYS the immutable
    # input artwork; tex0 is only the accumulated result. No lighting is rerun,
    # no rule limit is imposed by a fixed uniform array or sampler allocation.
    _scenelight_shader_color_glow_variables = _scenelight_shader_data['color_glow_variables']
    _scenelight_shader_color_glow_functions = _scenelight_shader_data['color_glow_functions']
    _scenelight_shader_color_glow_fragment = _scenelight_shader_data['color_glow_fragment']
    _scenelight_shader_color_glow_mask_fragment = _scenelight_shader_data['color_glow_mask_fragment']
    _scenelight_shader_color_glow_blur_variables = _scenelight_shader_data['color_glow_blur_variables']
    _scenelight_shader_color_glow_blur_functions = _scenelight_shader_data['color_glow_blur_functions']
    _scenelight_shader_color_glow_blur_fragment = _scenelight_shader_data['color_glow_blur_fragment']
    if _SCENELIGHT_SHADER_AVAILABLE:
        renpy.register_shader("scenelight.color_glow",
            variables=_scenelight_shader_color_glow_variables,
            fragment_functions=_scenelight_shader_color_glow_functions,
            fragment_350=_scenelight_shader_color_glow_fragment)
        renpy.register_shader("scenelight.color_glow_mask",
            variables=_scenelight_shader_color_glow_variables,
            fragment_functions=_scenelight_shader_color_glow_functions,
            fragment_350=_scenelight_shader_color_glow_mask_fragment)
        renpy.register_shader("scenelight.color_glow_blur",
            variables=_scenelight_shader_color_glow_blur_variables,
            fragment_functions=_scenelight_shader_color_glow_blur_functions,
            fragment_350=_scenelight_shader_color_glow_blur_fragment)

    def _scenelight_color_glow_steps(size, radius):
        """Widen an already smoothed mask, so small features never form sparse lobes."""
        variance = (0.014 * min(size) * radius) ** 2
        step_size = 1.0
        steps = []
        while variance > 0.000001:
            step = min(step_size, (variance / 2.854054054) ** 0.5)
            steps.append(step)
            variance = max(0.0, variance - 2.854054054 * step * step)
            step_size *= 2.0
        return steps

    def _scenelight_color_glow_render(lit, source, rules, master=1.0):
        if master <= 0.0:
            return lit
        for rule in rules:
            mask = renpy.Render(*source.get_size())
            mask.blit(source, (0, 0))
            mask.mesh = True
            mask.add_shader("renpy.texture")
            mask.add_shader("scenelight.color_glow_mask")
            mask.add_uniform("u_sc_rule_color", tuple(rule["color"]))
            mask.add_uniform("u_sc_rule_data", (rule["strength"], rule["radius"], rule["tolerance"], rule["softness"]))
            size = source.get_size()
            for step in _scenelight_color_glow_steps(size, rule["radius"]):
                for direction in ((step / max(size[0], 1.0), 0.0), (0.0, step / max(size[1], 1.0))):
                    blurred = renpy.Render(*size)
                    blurred.blit(mask, (0, 0))
                    blurred.mesh = True
                    blurred.add_shader("renpy.texture")
                    blurred.add_shader("scenelight.color_glow_blur")
                    blurred.add_uniform("u_sc_rule_step", direction)
                    mask = blurred
            result = renpy.Render(*lit.get_size())
            result.blit(lit, (0, 0))
            result.blit(source, (0, 0))
            result.blit(mask, (0, 0))
            result.mesh = True
            result.add_shader("renpy.texture")
            result.add_shader("scenelight.color_glow")
            result.add_uniform("u_sc_rule_color", tuple(rule["color"]))
            result.add_uniform("u_sc_rule_data", (rule["strength"] * master,
                rule["radius"], rule["tolerance"], rule["softness"]))
            result.add_uniform("u_sc_rule_size", tuple(float(v) for v in source.get_size()))
            result.add_uniform("u_sc_rule_compare", 0.0)
            lit = result
        return lit

    def _scenelight_color_glow_tree(root, original=False, memo=None):
        """Keep composite geometry, but recover source art or strip earlier rule passes.

        A Composite can contain registered image pieces that each resolve their
        own SceneLight wrapper. The final composite owns the color selection:
        earlier selective passes are removed, and its immutable mask source is
        rebuilt without SceneLight lighting. Foreign authored shaders, offsets,
        clipping, alpha and transforms retain their original render properties.
        Only newly created Render nodes are changed; cached children are untouched.
        """
        if not isinstance(root, renpy.Render):
            return root
        if memo is None:
            memo = {}
        if id(root) in memo:
            return memo[id(root)]
        memo[id(root)] = root
        children = getattr(root, "children", ())
        shaders = getattr(root, "shaders", ()) or ()
        if "scenelight.color_glow" in shaders and len(children) >= 2:
            result = _scenelight_color_glow_tree(children[1 if original else 0][0], original, memo)
            memo[id(root)] = result
            return result
        if original and globals().get("_scenelight_sprite_shader") in shaders and children:
            result = _scenelight_color_glow_tree(children[0][0], original, memo)
            memo[id(root)] = result
            return result
        replacements = [_scenelight_color_glow_tree(item[0], original, memo) for item in children]
        if all(child is item[0] for child, item in zip(replacements, children)):
            return root
        result = renpy.Render(*root.get_size())
        # These are Render's public draw/geometry properties in Ren'Py 7/8.
        # Texture/model/cache fields must stay new, not copied from the source.
        for name in ("forward", "reverse", "alpha", "over", "nearest", "xclipping",
                     "yclipping", "operation", "operation_complete", "operation_alpha",
                     "operation_parameter", "mesh", "shaders", "uniforms", "properties"):
            if hasattr(root, name):
                setattr(result, name, getattr(root, name))
        for child, item in zip(replacements, children):
            result.subpixel_blit(child, (item[1], item[2]), focus=False, main=item[4])
        result.depends_on(root, focus=True)
        memo[id(root)] = result
        return result

    _scenelight_shader_variables = _scenelight_shader_data['variables']
    _scenelight_shader_vertex_150 = _scenelight_shader_data['vertex_150']
    _scenelight_shader_fragment_functions = _scenelight_fragment_source(_scenelight_shader_data['fragment_functions'], preamble=True)
    _scenelight_shader_fragment_350 = _scenelight_fragment_source(_scenelight_shader_data['fragment_350'])

    _scenelight_sprite_shader = "scenelight.dynamic_sprite"
    if _SCENELIGHT_SHADER_AVAILABLE:
        renpy.register_shader(
            "scenelight.dynamic_sprite",
            variables=_scenelight_shader_variables,
            vertex_150=_scenelight_shader_vertex_150,
            fragment_functions=_scenelight_shader_fragment_functions,
            fragment_350=_scenelight_shader_fragment_350,
        )
        if renpy.loadable("scenelight_runtime/shader_stages.txt") and renpy.loadable("scenelight_runtime/shader_renpy.txt"):
            try:
                _sc_stage_module = _scenelight_runtime_module("shader_stages")
                _sc_stage_functions = _scenelight_shader_fragment_functions
                _sc_stage_fragment = _scenelight_shader_fragment_350
                for _sc_original, _sc_alias in _SCENELIGHT_FRAGMENT_FUNCTION_ALIASES:
                    _sc_stage_functions = _sc_stage_functions.replace(_sc_alias, _sc_original)
                    _sc_stage_fragment = _sc_stage_fragment.replace(_sc_alias, _sc_original)
                _sc_stage_variables, _sc_stage_helpers, _sc_stage_body, _sc_stage_fragment = _sc_stage_module.build(
                    _sc_stage_functions, _sc_stage_fragment
                )
                _sc_stage_helpers, _sc_stage_body = _sc_stage_module.vertex_preamble(
                    _scenelight_shader_variables, _sc_stage_helpers, _sc_stage_body
                )
                renpy.register_shader(
                    _sc_stage_module.OPTIMIZED,
                    variables=_scenelight_shader_variables + "\n" + _sc_stage_variables,
                    vertex_functions=_sc_stage_helpers,
                    vertex_150=_scenelight_shader_vertex_150 + "\n" + _sc_stage_body,
                    fragment_functions=_scenelight_shader_fragment_functions,
                    fragment_350=_scenelight_fragment_source(_sc_stage_fragment),
                )
                import renpy.gl2.gl2shadercache as _sc_shader_cache
                _scenelight_runtime_module("shader_renpy").install(
                    _sc_shader_cache, _scenelight_runtime_module("live_gpu"),
                    # The store's config proxy raises non-AttributeError for
                    # options absent in older engines. Use the actual module.
                    _sc_stage_module, renpy.config, renpy.display.log.write
                )
                _scenelight_sprite_shader = _sc_stage_module.OPTIMIZED
            except Exception:
                import traceback
                renpy.display.log.write("SceneLight retained its original shader.\n" + traceback.format_exc())

    class SceneLightSprite(renpy.Displayable):
        def __init__(
            self,
            child,
            image_name,
            form_key=None,
            authored_grade_strength=0.0,
            **properties
        ):
            super(SceneLightSprite, self).__init__(**properties)
            self.child = renpy.displayable(child)
            self.image_name = tuple(image_name)
            self.form_key = " ".join(form_key or self.image_name).strip().lower()
            self.base_form_key = " ".join(self.image_name).strip().lower()
            self.authored_grade_strength = max(
                0.0,
                min(float(authored_grade_strength), 1.0),
            )
            self._sc_exposure_owner = True
            self._sc_exposure_bias_owner = True
            self._sc_exposure_auto = 0.0
            self._sc_exposure_bias = 0.0
            self._sc_exposure_subtree = None
            self._sc_exposure_terms = None
            self._sc_refresh_form_binding()
            # Ren'Py builds an animated transition from a frozen copy of the
            # previously rendered scene and the new live scene. Keep the last
            # state used by this displayable so that frozen copy cannot query
            # the replacement background while it is still fading or wiping
            # away on screen.
            self._sc_snapshot_frozen = False
            self._sc_frozen_scene = None
            self._sc_frozen_enabled = True
            self._sc_frozen_strength = 1.0
            self._sc_frozen_effects = None
            self._sc_frozen_effect_time = 0.0
            self._sc_frozen_controls = None
            self._sc_frozen_screen_rect = None
            self._sc_transition_screen_rect = None
            self._sc_last_rendered_scene = None
            self._sc_last_rendered_enabled = True
            self._sc_last_rendered_strength = 1.0
            self._sc_last_rendered_effects = None
            self._sc_last_rendered_effect_time = 0.0
            self._sc_last_rendered_controls = None
            self._sc_last_rendered_emitters = ()
            self._sc_frozen_emitters = ()
            self.irradiance = _scenelight_texture(SCENELIGHT_ATLAS["irradiance"])
            self.emitter = _scenelight_texture(SCENELIGHT_ATLAS["emitter"])
            self.wrap_atlas = _scenelight_texture(
                SCENELIGHT_ATLAS.get("wrap", SCENELIGHT_ATLAS["irradiance"])
            )
            self.transport_atlas = _scenelight_texture(
                SCENELIGHT_TRANSPORT_ATLAS.get("texture", SCENELIGHT_ATLAS["irradiance"])
            )

        def _sc_refresh_form_binding(self):
            self.form_entry = _scenelight_resolve_form_entry(
                self.form_key,
                self.base_form_key,
            )
            self.has_form = self.form_entry is not None
            form_assets = self.form_entry if self.has_form else SCENELIGHT_FORM_FALLBACK
            self.form_normal_noise = _scenelight_texture(form_assets["normal_noise"])
            self.form_height_ao_edge = _scenelight_texture(form_assets["height_ao_edge"])
            self.form_response = _scenelight_texture(form_assets["response"])
            self._sc_form_binding_pending = False

        def after_setstate(self):
            # Saves retain the captured map and texture displayables from their
            # installation. Rebind after loading, when the current inventory is
            # available, before Ren'Py renders the first interaction.
            self._sc_form_binding_pending = True

        def _sc_exposure_coefficients(self):
            # Claim only coefficients this pass really applies. Named image
            # controls can bypass an inner alias independently of its parent.
            if self._sc_snapshot_frozen:
                scene = self._sc_frozen_scene
                enabled = self._sc_frozen_enabled
                strength = self._sc_frozen_strength
                controls = self._sc_frozen_controls or {}
            else:
                scene, enabled, strength, _effects, _time, controls = self._live_lighting_state()
            scene = _scenelight_resolve_live_scene(scene)
            if not _SCENELIGHT_SHADER_AVAILABLE or not scene or not enabled or strength <= 0.0:
                return (0.0, 0.0, 0.0)
            calibration = _scenelight_calibration_blocks(scene, controls.get("calibration", {}))[0]
            adaptation = 1.0 - (
                getattr(self, "authored_grade_strength", 0.0) if strength >= 0.0001 else 0.0
            )
            auto_profile = calibration[0] * strength
            return (auto_profile * adaptation, calibration[1] * strength, auto_profile)

        def _sc_prepare_exposure_ownership(self):
            # Ownership depends only on each wrapper's alias chain, never on
            # render-stack depth. Shared/cached children therefore keep the
            # same exposure whether rendered alone or through another alias.
            # ImageReference.visit resolves late targets before they are used.
            memo = {}
            display = getattr(renpy, "display", None)
            alias_classes = tuple(cls for cls in (
                getattr(getattr(display, "image", None), "ImageReference", None),
                getattr(getattr(display, "transform", None), "Transform", None),
            ) if isinstance(cls, type))
            empty = (0.0, 0.0, (), ())

            def walk(current):
                if current is None:
                    return empty
                identity = id(current)
                if identity in memo:
                    return memo[identity]
                memo[identity] = empty
                if isinstance(current, SceneLightSprite):
                    frozen = getattr(current, "_sc_snapshot_frozen", False)
                    captured = getattr(current, "_sc_exposure_subtree", None)
                    captured_terms = getattr(current, "_sc_exposure_terms", None)
                    if (
                        frozen and captured is not None and captured_terms is not None
                        and hasattr(current, "_sc_exposure_auto")
                        and hasattr(current, "_sc_exposure_bias")
                    ):
                        result = captured + captured_terms
                        memo[identity] = result
                        return result
                    child_auto, child_bias, auto_terms, bias_terms = walk(current.child)
                    own_auto, own_bias, auto_profile = current._sc_exposure_coefficients()
                    owner = own_auto != 0.0 and auto_profile not in auto_terms
                    bias_owner = own_bias != 0.0 and own_bias not in bias_terms
                    # Repeated aliases share one exposure profile, but a
                    # distinct authored coefficient must still contribute.
                    # Grade attenuation does not create a new profile: the
                    # deepest active occurrence retains its graded value.
                    absolute_auto = child_auto + (own_auto if owner else 0.0)
                    absolute_bias = child_bias + (own_bias if bias_owner else 0.0)
                    if owner:
                        auto_terms += (auto_profile,)
                    if bias_owner:
                        bias_terms += (own_bias,)
                    absolute = (absolute_auto, absolute_bias)
                    result = absolute + (auto_terms, bias_terms)
                    if captured is not None and (
                        getattr(current, "_sc_exposure_owner", True) != owner
                        or getattr(current, "_sc_exposure_bias_owner", True) != bias_owner
                        or captured != absolute
                    ):
                        renpy.redraw(current, 0.0)
                    current._sc_exposure_owner = owner
                    current._sc_exposure_bias_owner = bias_owner
                    current._sc_exposure_auto = absolute_auto
                    current._sc_exposure_bias = absolute_bias
                    current._sc_exposure_subtree = absolute
                    current._sc_exposure_terms = (auto_terms, bias_terms)
                else:
                    visit = getattr(current, "visit", None)
                    children = list((visit() if visit is not None else ()) or ())
                    coverage = [walk(child) for child in children]
                    # A lit descendant does not imply that every pixel of a
                    # composite has been exposed. Only engine alias/transform
                    # chains forward whole-image coverage. Unknown or branching
                    # displayables retain the prior outer exposure behavior.
                    result = coverage[0] if isinstance(current, alias_classes) and len(coverage) == 1 else empty
                memo[identity] = result
                return result

            return walk(self)[:2]

        def visit(self):
            return [
                self.child,
                self.irradiance,
                self.emitter,
                self.form_normal_noise,
                self.form_height_ao_edge,
                self.form_response,
                self.wrap_atlas,
                self.transport_atlas,
            ]

        def per_interact(self):
            if getattr(self, "_sc_form_binding_pending", False):
                self._sc_refresh_form_binding()
                renpy.redraw(self, 0.0)
            self._sc_prepare_exposure_ownership()
            # Static lighting remains valid across dialogue interactions. The
            # former unconditional redraw rebuilt every character shader pass
            # for every line of typewriter text. Procedural effects opt back
            # into continuous redraw below; scene and API mutations invalidate
            # visible sprites explicitly.
            if _scenelight_fx_active(self.image_name[0]):
                renpy.redraw(self, 0.0)
            else:
                scene = self._sc_frozen_scene if self._sc_snapshot_frozen else self._sc_last_rendered_scene
                if scene and "_sc_live_binding" in scene and not _scenelight_live_fields(scene):
                    renpy.redraw(self, 0.0)

        def set_transform_event(self, event):
            # SceneLight is a visual filter, not an ATL boundary. Forward the
            # complete show/replace/hide lifecycle to the wrapped displayable.
            self.child.set_transform_event(event)
            super(SceneLightSprite, self).set_transform_event(event)

        def _handles_event(self, event):
            handles = getattr(self.child, "_handles_event", None)
            if handles is None:
                return False
            return bool(handles(event))

        def _hide(self, st, at, kind):
            new_child = self.child._hide(st, at, kind)
            if new_child is None:
                return None
            rv = self._copy()
            rv.child = new_child
            renpy.redraw(rv, 0.0)
            return rv

        def _show(self):
            show = getattr(self.child, "_show", None)
            if show is not None:
                show()

        def _change_transform_child(self, child):
            # keep_running_transform supplies the new expression as the
            # replacement child. Preserve its own SceneLight metadata when the
            # scene router has already wrapped it.
            if isinstance(child, SceneLightSprite):
                return child
            rv = self._copy()
            rv.child = child
            reference_class = getattr(
                getattr(renpy.display, "image", None), "ImageReference", None
            )
            if reference_class is not None and isinstance(child, reference_class):
                # show() resolves inherited attributes before creating this
                # reference. The retained transform can now contain a wholly
                # different pose, so its old map must not survive replacement.
                name = child.name
                if isinstance(name, _SCENELIGHT_STRING_TYPES):
                    name = tuple(name.split())
                if isinstance(name, (tuple, list)) and name:
                    rv.form_key = " ".join(name).strip().lower()
                    rv.base_form_key = rv.form_key
                    # Keep the scene tag (including `show ... as`) and the
                    # grading supplied by the running outer transform.
                    rv.image_name = (self.image_name[0],) + tuple(name[1:])
                    rv._sc_refresh_form_binding()
            return rv

        def _live_scene(self):
            return _scenelight_live_scene()

        def _live_scene_entry(self):
            return _scenelight_live_scene_entry()

        def _live_lighting_state(self):
            """Resolve a complete state even before this displayable's first frame."""
            scene_key, scene = self._live_scene_entry()
            controls = _scenelight_control_snapshot(
                scene_key or "unknown",
                self.image_name[0],
                self.form_key,
            )
            controls = _scenelight_emission_controls(scene_key, self.image_name[0], controls)
            enabled = _scenelight_master_enabled() and bool(
                controls["enabled"]
            )
            authored_strength = (
                float(controls["strength"])
                if controls.get("strength_override")
                else SCENELIGHT_PROFILE_STRENGTH
            )
            strength = _scenelight_master_strength() * authored_strength
            effects = _scenelight_fx_snapshot(self.image_name[0])
            effect_time = float(renpy.get_game_runtime())
            return scene, enabled, strength, effects, effect_time, controls

        def _scenelight_screen_rect(self):
            """Return this tag's settled bounds in normalized screen space."""
            try:
                bounds = renpy.get_image_bounds(
                    self.image_name[0],
                    config.screen_width,
                    config.screen_height,
                    None,
                )
            except Exception:
                return None
            if not bounds or len(bounds) != 4:
                return None
            screen_width = float(config.screen_width)
            screen_height = float(config.screen_height)
            if screen_width <= 0.0 or screen_height <= 0.0:
                return None
            x, y, width, height = [float(value) for value in bounds]
            if width <= 0.0 or height <= 0.0:
                return None
            return (
                x / screen_width,
                y / screen_height,
                width / screen_width,
                height / screen_height,
            )

        def _sc_emission_coverage(self):
            """Avoid reapplying emission through a whole-image alias chain."""
            current = self.child
            seen = set()
            receive, glow = False, False
            display = getattr(renpy, "display", None)
            aliases = tuple(cls for cls in (
                getattr(getattr(display, "image", None), "ImageReference", None),
                getattr(getattr(display, "transform", None), "Transform", None),
            ) if isinstance(cls, type))
            while current is not None and id(current) not in seen:
                seen.add(id(current))
                if isinstance(current, SceneLightSprite):
                    if current._sc_snapshot_frozen:
                        scene, enabled = current._sc_frozen_scene, current._sc_frozen_enabled
                        child_strength = current._sc_frozen_strength
                        controls = current._sc_frozen_controls or {}
                    else:
                        scene, enabled, child_strength, _fx, _time, controls = current._live_lighting_state()
                    if enabled:
                        receive = receive or bool(scene and child_strength > 0.0)
                        block = _scenelight_calibration_blocks(scene or {}, controls.get("calibration", {}))[5]
                        # Selective passes are stripped/reapplied on the outer
                        # resolved image below. They must not bypass this alias's
                        # normal lighting, even when the rule matches no pixels.
                        glow = glow or bool(scene and block[0] > 0.0)
                    current = current.child
                elif isinstance(current, aliases):
                    children = list(current.visit() or ())
                    current = children[0] if len(children) == 1 else None
                else:
                    break
            return receive, glow

        def _in_current_store(self):
            """Freeze the exact lighting used by Ren'Py's outgoing scene."""
            rv = self._copy()
            rv.child = self.child._in_current_store()
            rv._sc_snapshot_frozen = True
            # Ren'Py 7 snapshots displayables before hide/replaced/cancel
            # lifecycle handling. A show-at immediately followed by hide can
            # therefore arrive here before its first render. Resolve the same
            # complete live state used by render instead of freezing ``None``.
            if self._sc_last_rendered_scene is None:
                (
                    frozen_scene,
                    frozen_enabled,
                    frozen_strength,
                    frozen_effects,
                    frozen_effect_time,
                    frozen_controls,
                ) = self._live_lighting_state()
                if frozen_controls.get("group") is not None:
                    frozen_controls["group_anchor"] = _scenelight_control_group_anchor(frozen_controls["group"])
            else:
                frozen_scene = self._sc_last_rendered_scene
                frozen_enabled = self._sc_last_rendered_enabled
                frozen_strength = self._sc_last_rendered_strength
                frozen_effects = self._sc_last_rendered_effects
                frozen_effect_time = self._sc_last_rendered_effect_time
                frozen_controls = self._sc_last_rendered_controls
            rv._sc_frozen_scene = frozen_scene
            rv._sc_frozen_enabled = frozen_enabled
            rv._sc_frozen_strength = frozen_strength
            rv._sc_frozen_effects = copy.deepcopy(frozen_effects)
            rv._sc_frozen_effect_time = frozen_effect_time
            rv._sc_frozen_controls = copy.deepcopy(frozen_controls)
            rv._sc_frozen_emitters = copy.deepcopy(getattr(self, "_sc_last_rendered_emitters", ()))
            rv._sc_frozen_screen_rect = self._scenelight_screen_rect()
            rv._sc_transition_screen_rect = None
            # Rebuild from the frozen children's last-rendered controls. Live
            # rules may already describe the incoming scene at snapshot time.
            rv._sc_exposure_subtree = None
            rv._sc_prepare_exposure_ownership()
            return rv

        def render(self, width, height, st, at):
            child_render = renpy.render(self.child, width, height, st, at)
            if globals().get("_SCENELIGHT_MEASURING_EMITTERS", False):
                return child_render
            # A dynamic child may have resolved a new nested wrapper during
            # its render. Its own ownership is already stable; refresh this
            # ancestor before binding its uniforms, without flushing caches.
            self._sc_prepare_exposure_ownership()

            if self._sc_snapshot_frozen:
                scene = self._sc_frozen_scene
                enabled = self._sc_frozen_enabled
                strength = self._sc_frozen_strength
                effects = self._sc_frozen_effects or _scenelight_fx_snapshot(self.image_name[0])
                effect_time = self._sc_frozen_effect_time
                controls = self._sc_frozen_controls or {
                    "enabled": enabled,
                    "strength": strength,
                    "calibration": {},
                }
            else:
                (
                    scene,
                    enabled,
                    strength,
                    effects,
                    effect_time,
                    controls,
                ) = self._live_lighting_state()
                # Game runtime is stored in save files and restored by
                # rollback/load. It keeps procedural animation deterministic
                # across expression swaps instead of restarting with each new
                # displayable's ATL time.
                group = controls.get("group")
                if group is not None:
                    controls["group_anchor"] = _scenelight_control_group_anchor(group)
                    renpy.redraw(self, 0.0)
                self._sc_last_rendered_scene = scene
                self._sc_last_rendered_enabled = enabled
                self._sc_last_rendered_strength = strength
                self._sc_last_rendered_effects = copy.deepcopy(effects)
                self._sc_last_rendered_effect_time = effect_time
                self._sc_last_rendered_controls = copy.deepcopy(controls)
                global SCENELIGHT_LAST_PRESENTED_SCENE
                if scene is not None:
                    SCENELIGHT_LAST_PRESENTED_SCENE = scene

            resolved_scene = _scenelight_resolve_live_scene(scene)
            if self._sc_snapshot_frozen:
                if _scenelight_live_fields(resolved_scene):
                    self._sc_frozen_scene = resolved_scene
            else:
                self._sc_last_rendered_scene = resolved_scene
            scene = resolved_scene
            if scene is not None and not self._sc_snapshot_frozen:
                SCENELIGHT_LAST_PRESENTED_SCENE = scene

            effects_active = any(
                float(effect.get("intensity", 0.0)) > 0.0001
                for effect in effects.values()
                if isinstance(effect, dict)
            )
            active_custom_effects = _scenelight_active_custom_effects(effects)
            if not _SCENELIGHT_SHADER_AVAILABLE:
                return child_render

            if (
                not self._sc_snapshot_frozen
                and _scenelight_fx_active(self.image_name[0])
            ):
                # Effect time changes every frame only while an authored
                # procedural effect is visibly active.
                renpy.redraw(self, 0.0)
            elif (
                not self._sc_snapshot_frozen
                and SCENELIGHT_STABLE_SCENE_KEY in SCENELIGHT_SCENE_SEQUENCES
            ):
                # Read the selected background state on each presented frame.
                # An independent 8-Hz redraw aliases short authored frames.
                renpy.redraw(self, 0.0)

            # Shareable custom effects are independent of background analysis.
            # They remain available in games that use procedural, video, or
            # otherwise unrecognized scenes, while ordinary lighting still
            # requires a valid SceneLight scene record.
            rules = _scenelight_color_glow_rules(scene, controls) if enabled else ()
            master = max(0.0, _scenelight_master_strength())
            if not scene:
                _receive_covered, glow_covered = self._sc_emission_coverage()
                source = _scenelight_color_glow_tree(child_render, original=True) if rules and not glow_covered else child_render
                base = _scenelight_color_glow_tree(child_render) if rules and not glow_covered else child_render
                result = _scenelight_color_glow_render(base, source,
                    () if glow_covered else rules, master)
                return _scenelight_custom_effect_render(
                    result,
                    active_custom_effects,
                )
            if not enabled and not effects_active:
                return child_render

            emitters = (
                getattr(self, "_sc_frozen_emitters", ()) if self._sc_snapshot_frozen
                else _scenelight_sprite_emitters(self.image_name[0])
            )
            if not self._sc_snapshot_frozen:
                self._sc_last_rendered_emitters = emitters
                if emitters:
                    # Moving/animated emitters must update receivers even when
                    # their own art is static. No extra redraw when disabled.
                    renpy.redraw(self, 0.0)
            receive_covered, glow_covered = self._sc_emission_coverage()
            if glow_covered:
                # The resolved child already contains luminous art and its
                # alpha-shaped halo. An alias must not relight that completed
                # emission texture or turn its halo back into dark geometry.
                return _scenelight_custom_effect_render(child_render, active_custom_effects)

            rule_source = child_render
            if rules:
                rule_source = _scenelight_color_glow_tree(child_render, original=True)
                child_render = _scenelight_color_glow_tree(child_render)

            # This render-to-texture boundary is intentional. Never copy a
            # child's shaders, uniforms, or GL properties onto SceneLight's
            # model: an image-declared custom shader must finish in its own
            # pass, while a `show ... at CustomShader` mesh transform remains
            # a later outer pass. That keeps both stacks independent.
            result = renpy.Render(*child_render.get_size())
            result.blit(child_render, (0, 0))
            # Ren'Py's resN uniforms follow sampler allocation order, not the
            # texN name. Helper samplers can claim res0 for a light-field texture.
            # Use the sprite canvas explicitly so normal/shadow offsets remain
            # in sprite pixels, independent of sampler order and window scaling.
            result.add_uniform("u_sc_sprite_size", tuple(float(v) for v in child_render.get_size()))
            live_fields = _scenelight_live_fields(scene)
            atlas_width = float(SCENELIGHT_ATLAS["tile_size"][0] * SCENELIGHT_ATLAS["columns"])
            atlas_height = float(SCENELIGHT_ATLAS["tile_size"][1] * SCENELIGHT_ATLAS["rows"])
            if live_fields:
                atlas_width, atlas_height = 160.0, 90.0
                irradiance_render = live_fields["irradiance"]
                emitter_render = live_fields["emitter"]
            else:
                irradiance_render = _scenelight_render_for_texture(
                    self.irradiance, atlas_width, atlas_height, st, at
                )
                emitter_render = _scenelight_render_for_texture(
                    self.emitter, atlas_width, atlas_height, st, at
                )
            if self.has_form:
                form_width, form_height = self.form_entry["source_size"]
                response_width, response_height = self.form_entry["response_size"]
            else:
                form_width = form_height = response_width = response_height = 1
            form_normal_render = _scenelight_render_for_texture(
                self.form_normal_noise, form_width, form_height, st, at
            )
            form_aux_render = _scenelight_render_for_texture(
                self.form_height_ao_edge, form_width, form_height, st, at
            )
            form_response_render = _scenelight_render_for_texture(
                self.form_response, response_width, response_height, st, at
            )
            wrap_render = live_fields["wrap"] if live_fields else _scenelight_render_for_texture(
                self.wrap_atlas, atlas_width, atlas_height, st, at
            )
            transport_grid = SCENELIGHT_TRANSPORT_ATLAS.get("grid_size", (1, 1))
            transport_planes = float(SCENELIGHT_TRANSPORT_ATLAS.get("planes", 1))
            transport_columns = float(SCENELIGHT_TRANSPORT_ATLAS.get("columns", 1))
            transport_rows = float(SCENELIGHT_TRANSPORT_ATLAS.get("rows", 1))
            transport_width = float(transport_grid[0]) * transport_planes * transport_columns
            transport_height = float(transport_grid[1]) * transport_rows
            transport_render = live_fields["transport"] if live_fields else _scenelight_render_for_texture(
                self.transport_atlas, transport_width, transport_height, st, at
            )
            if live_fields:
                transport_grid = (16, 9)
            transport_prepared = bool(scene.get("_sc_blend", 0.0) > 0.0 and scene.get("transport_uv"))
            if transport_prepared:
                transport_render = _scenelight_transport_frame(scene, transport_render, st, at)
            result.blit(irradiance_render, (0, 0))
            result.blit(emitter_render, (0, 0))
            result.blit(form_normal_render, (0, 0))
            result.blit(form_aux_render, (0, 0))
            result.blit(form_response_render, (0, 0))
            result.blit(wrap_render, (0, 0))
            result.blit(transport_render, (0, 0))
            result.mesh = True
            result.add_shader("renpy.texture")
            result.add_shader(_scenelight_sprite_shader)
            result.add_uniform("u_sc_scene_uv", tuple(scene["uv"]))
            result.add_uniform("u_sc_wrap_uv", tuple(scene["uv"]))
            result.add_uniform("u_sc_wrap_uv_next", tuple(scene.get("_sc_next_uv", scene["uv"])))
            result.add_uniform("u_sc_wrap_texel", (1.0 / atlas_width, 1.0 / atlas_height))
            result.add_uniform("u_sc_wrap_blend", float(scene.get("_sc_blend", 0.0)))
            result.add_uniform("u_sc_scene_uv_next", tuple(scene.get("_sc_next_uv", scene["uv"])))
            result.add_uniform("u_sc_scene_blend", float(scene.get("_sc_blend", 0.0)))
            result.add_uniform("u_sc_atlas_texel", (1.0 / atlas_width, 1.0 / atlas_height))
            result.add_uniform("u_sc_reference_mid", SCENELIGHT_REFERENCE_ART_MID)
            result.add_uniform("u_sc_strength", strength if enabled else 0.0)
            result.add_uniform("u_sc_authored_grade", self.authored_grade_strength)
            result.add_uniform("u_sc_exposure_owner", float(self._sc_exposure_owner))
            result.add_uniform("u_sc_exposure_bias_owner", float(self._sc_exposure_bias_owner))
            result.add_uniform("u_sc_exposure_auto", float(self._sc_exposure_auto))
            result.add_uniform("u_sc_exposure_bias", float(self._sc_exposure_bias))
            result.add_uniform("u_sc_effect_time", effect_time)
            result.add_uniform("u_sc_chroma_range", float(SCENELIGHT_ATLAS["chroma_range"]))
            result.add_uniform("u_sc_target_range", float(SCENELIGHT_ATLAS["target_mid_range"]))
            result.add_uniform(
                "u_sc_has_transport",
                1.0 if SCENELIGHT_TRANSPORT_ATLAS and scene.get("transport_uv") else 0.0,
            )
            result.add_uniform("u_sc_live_background", 0.0)
            result.add_uniform("u_sc_live_analysis", 1.0 if live_fields else 0.0)
            result.add_uniform(
                "u_sc_transport_uv",
                (0.0, 0.0, 1.0 / 26.0, 1.0) if transport_prepared else tuple(scene.get("transport_uv", (0.0, 0.0, 1.0, 1.0))),
            )
            result.add_uniform("u_sc_transport_grid", tuple(transport_grid))
            result.add_uniform(
                "u_sc_transport_subject_y_max",
                float(SCENELIGHT_TRANSPORT_ATLAS.get("subject_y_max", 1.0)),
            )
            result.add_uniform("u_sc_debug_contrast", SCENELIGHT_DEBUG_CONTRAST)
            result.add_uniform("u_sc_compare_mode", 0.0)
            glow_block = _scenelight_calibration_blocks(scene, controls.get("calibration", {}))[5]
            result.add_uniform("u_sc_glow_data", (
                glow_block[0] * _scenelight_master_strength()
                if enabled and not glow_covered else 0.0,
                glow_block[1],
            ))
            result.add_uniform("u_sc_glow_color", tuple(_scenelight_calibration_blocks(scene, controls.get("calibration", {}))[7]))
            result.add_uniform("u_sc_screen_aspect", float(config.screen_width) / max(float(config.screen_height), 1.0))
            for index in range(4):
                data, color = emitters[index] if enabled and not receive_covered and index < len(emitters) else (
                    (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
                )
                result.add_uniform("u_sc_sprite_light%d_data" % index, tuple(data))
                result.add_uniform("u_sc_sprite_light%d_color" % index, tuple(color))
            for calibration_index, calibration_block in enumerate(
                _scenelight_calibration_blocks(scene, controls.get("calibration", {}))
            ):
                result.add_uniform(
                    "u_sc_calibration%d" % calibration_index,
                    tuple(calibration_block),
                )
            rain = effects["rain"]
            result.add_uniform(
                "u_sc_rain_data",
                (rain["intensity"], rain["wetness"], rain["wind"], rain["speed"]),
            )
            result.add_uniform(
                "u_sc_rain_color_scale",
                tuple(rain["color"]) + (rain["scale"],),
            )
            glitch = effects["glitch"]
            result.add_uniform(
                "u_sc_glitch_data",
                (
                    glitch["intensity"],
                    glitch["rgb_split"],
                    glitch["block_size"],
                    glitch["speed"],
                ),
            )
            result.add_uniform(
                "u_sc_glitch_extra",
                (
                    glitch["tear"],
                    glitch["scanlines"],
                    glitch["alpha_fragment"],
                    glitch["seed"],
                ),
            )
            result.add_uniform("u_sc_shadow_chroma", tuple(scene.get("shadow_chroma", (1.0, 1.0, 1.0))))
            result.add_uniform("u_sc_local_saturation", float(scene.get("local_saturation", 0.26)))
            result.add_uniform("u_sc_local_contrast", float(scene.get("local_contrast", 0.55)))
            result.add_uniform("u_sc_light_confidence", float(scene.get("light_confidence", 0.5)))
            result.add_uniform("u_sc_source_size", float(scene.get("source_size", 0.5)))
            result.add_uniform("u_sc_grain", float(scene.get("grain", 0.0)))
            result.add_uniform("u_sc_sharpness", float(scene.get("sharpness", 0.0)))
            result.add_uniform("u_sc_local_luminance", float(scene.get("local_luminance", 0.12)))
            light_transport = list(scene.get("light_transport", ()))[:4]
            while len(light_transport) < 4:
                light_transport.append({
                    "position_radius_intensity": (0.5, 0.2, 1.0, 0.0),
                    "chroma_confidence": (1.0, 1.0, 1.0, 0.0),
                    "emission_enabled": (0.0, 0.0),
                })
            for light_index, light in enumerate(light_transport):
                result.add_uniform(
                    "u_sc_light%d_data" % light_index,
                    tuple(light["position_radius_intensity"]),
                )
                result.add_uniform(
                    "u_sc_light%d_color" % light_index,
                    tuple(light["chroma_confidence"]),
                )
                result.add_uniform(
                    "u_sc_light%d_extra" % light_index,
                    tuple(light["emission_enabled"]),
                )
            probe_transport = list(scene.get("probe_transport", ()))[:8]
            while len(probe_transport) < 8:
                probe_transport.append({
                    "direction_luminance_enabled": (0.0, -1.0, 0.0, 0.0),
                    "chroma": (1.0, 1.0, 1.0),
                })
            for probe_index, probe in enumerate(probe_transport):
                result.add_uniform(
                    "u_sc_probe%d_data" % probe_index,
                    tuple(probe["direction_luminance_enabled"]),
                )
                result.add_uniform(
                    "u_sc_probe%d_color" % probe_index,
                    tuple(probe["chroma"]),
                )
            group_anchor = controls.get("group_anchor")
            result.add_uniform("u_sc_group_anchor", tuple(group_anchor) + (1.0,)
                               if group_anchor is not None else (0.0, 0.0, 0.0))
            result.add_uniform("u_sc_has_form", 1.0 if self.has_form else 0.0)
            if self._sc_snapshot_frozen:
                snapshot_rect = self._sc_frozen_screen_rect
            else:
                snapshot_rect = self._sc_transition_screen_rect
            result.add_uniform(
                "u_sc_snapshot_rect",
                tuple(snapshot_rect or (0.0, 0.0, 1.0, 1.0)),
            )
            result.add_uniform(
                "u_sc_use_snapshot_rect",
                1.0 if snapshot_rect is not None else 0.0,
            )
            if self.has_form:
                result.add_uniform("u_sc_form_center", tuple(self.form_entry["center"]))
                result.add_uniform(
                    "u_sc_mean_form_visibility",
                    float(self.form_entry["mean_form_visibility"]),
                )
                result.add_uniform(
                    "u_sc_form_contrast_mid",
                    float(self.form_entry["contrast_mid"]),
                )
                result.add_uniform("u_sc_height_range", tuple(self.form_entry["height_range"]))
                result.add_uniform("u_sc_noise_range", float(self.form_entry["noise_range"]))
            else:
                result.add_uniform("u_sc_form_center", (0.5, 0.5))
                result.add_uniform("u_sc_mean_form_visibility", 1.0)
                result.add_uniform("u_sc_form_contrast_mid", SCENELIGHT_REFERENCE_ART_MID)
                result.add_uniform("u_sc_height_range", (-0.25, 1.25))
                result.add_uniform("u_sc_noise_range", 4.0)
            diagnostic_key = (SCENELIGHT_STABLE_SCENE_KEY, self.form_key, self.has_form,
                              child_render.get_size(), self._sc_exposure_owner,
                              strength, enabled, repr(controls.get("calibration", {})),
                              self._sc_snapshot_frozen,
                              self.form_entry.get("normal_noise") if self.has_form else None)
            if getattr(self, "_sc_diagnostic_key", None) != diagnostic_key:
                self._sc_diagnostic_key = diagnostic_key
                _scenelight_record_diagnostic("sprite.binding", {
                    "background": SCENELIGHT_STABLE_SCENE_KEY, "image": self.form_key,
                    "tag": self.image_name[0], "canvas": child_render.get_size(),
                    "mapped_form": self.has_form,
                    "form_size": self.form_entry.get("source_size") if self.has_form else None,
                    "exposure_owner": self._sc_exposure_owner, "strength": strength,
                    "enabled": enabled, "calibration": controls.get("calibration", {}),
                    "authored_grade": self.authored_grade_strength,
                    "frozen_transition": self._sc_snapshot_frozen,
                })
            return _scenelight_custom_effect_render(
                _scenelight_color_glow_render(result, rule_source, rules, master),
                active_custom_effects,
            )

    def _scenelight_authored_grade_strength(displayable):
        """Return one only when Ren'Py will apply authored color grading.

        Registered LayeredImages are resolved before the scene-boundary router,
        while runtime expression displayables reach the router directly. Inspect
        the actual transform chain in both paths so the decision is independent
        of image names, character families, and project conventions.
        """

        transform_class = getattr(
            getattr(renpy.display, "transform", None),
            "Transform",
            None,
        )
        current = displayable
        depth = 0
        while (
            transform_class is not None
            and isinstance(current, transform_class)
            and depth < 64
        ):
            transform_state = getattr(current, "state", None)
            if (
                transform_state is not None
                and getattr(transform_state, "matrixcolor", None) is not None
            ):
                return 1.0
            current = getattr(current, "child", None)
            depth += 1
        return 0.0

    class SceneLightImageLike(object):
        """Resolve LayeredImage attributes before applying the GPU shader."""

        def __init__(self, original, image_name):
            self.original = original
            self.image_name = tuple(image_name)

        def _duplicate(self, args):
            child = self.original._duplicate(args)
            resolved_name = self.image_name
            if args is not None:
                resolved_name = tuple(getattr(args, "name", ()) or self.image_name)
                resolved_name += tuple(getattr(args, "args", ()) or ())
            return SceneLightSprite(
                child,
                self.image_name,
                resolved_name,
                authored_grade_strength=_scenelight_authored_grade_strength(child),
            )

        def __getattr__(self, name):
            if name == "original":
                raise AttributeError(name)
            return getattr(self.original, name)

    def scenelight_set_enabled(enabled):
        persistent.scenelight_enabled = bool(enabled)
        _scenelight_redraw_visible_sprites()
        renpy.restart_interaction()

    def scenelight_set_strength(strength):
        persistent.scenelight_strength = max(0.0, min(float(strength), 1.5))
        _scenelight_redraw_visible_sprites()
        renpy.restart_interaction()

    def scenelight_register_tag(tag):
        """Route another Ren'Py character image tag through the same shader."""
        if not _SCENELIGHT_SHADER_AVAILABLE:
            return
        parts = str(tag).split()
        if not parts or parts[0] == "bg":
            return
        tag = parts[0]
        # Author registration may discover a tag that static analysis missed,
        # but must not override an explicit choice in the Characters checklist.
        if tag in globals().get("SCENELIGHT_MANIFEST", {}).get("excluded_character_tags", ()):
            return
        SCENELIGHT_CHARACTER_TAGS.add(tag)
        for image_name in list(_scenelight_registered_image_names()):
            image_tuple = tuple(image_name.split())
            if not image_tuple or image_tuple[0] != tag:
                continue
            original = _scenelight_get_registered_image(image_tuple)
            if original is None or isinstance(original, (SceneLightSprite, SceneLightImageLike)):
                continue
            if isinstance(original, renpy.Displayable):
                wrapped = SceneLightSprite(original, image_tuple)
            else:
                wrapped = SceneLightImageLike(original, image_tuple)
            renpy.image(image_tuple, wrapped)
            SCENELIGHT_WRAPPED_IMAGES.append(image_name)

    def _scenelight_scene_lists_class():
        """Return Ren'Py's scene-list class across engine generations."""
        display = getattr(renpy, "display", None)
        for module_name in ("scenelists", "core"):
            module = getattr(display, module_name, None)
            candidate = getattr(module, "SceneLists", None)
            if candidate is not None:
                return candidate
        return None

    def _scenelight_redraw_tree(displayable):
        """Invalidate only SceneLight sprites reachable from one scene entry."""

        pending = [displayable]
        seen = set()
        while pending and len(seen) < 4096:
            current = pending.pop()
            if current is None:
                continue
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            if isinstance(current, SceneLightSprite):
                renpy.redraw(current, 0.0)
            visit = getattr(current, "visit", None)
            if visit is None:
                continue
            try:
                pending.extend(visit() or ())
            except Exception:
                pass

    def _scenelight_redraw_visible_sprites(scene_lists=None):
        """Refresh lighting after real scene changes, never plain dialogue."""

        if scene_lists is None:
            try:
                scene_lists = renpy.game.context().scene_lists
            except Exception:
                return
        try:
            entries = scene_lists.layers.get("master", ())
        except Exception:
            return
        for entry in entries:
            _scenelight_redraw_tree(getattr(entry, "displayable", None))

    def _scenelight_wrap_backgrounds(owner):
        if renpy.display._scenelight_live_renderer is None:
            return False
        changed = False
        for index, entry in enumerate(owner.layers.get("master", ())):
            if isinstance(entry.displayable, _SceneLightBackground):
                continue
            parts = getattr(entry, "name", ()) or ()
            if isinstance(parts, _SCENELIGHT_STRING_TYPES):
                parts = parts.split()
            parts = tuple(str(part).lower() for part in parts)
            entry_tag = getattr(entry, "tag", None)
            scene_key = " ".join(parts[1:] if parts and parts[0] == "bg" else parts)
            if (entry_tag == "bg" or scene_key in SCENELIGHT_SCENES
                    or scene_key in SCENELIGHT_SCENE_SEQUENCES):
                updated = entry.copy()
                updated.displayable = _SceneLightBackground(entry.displayable, scene_key)
                owner.layers["master"][index] = updated
                changed = True
        return changed

    def _scenelight_restore_background_bindings():
        # Saves made before the live engine contain ordinary background
        # displayables. Attach those at the next interaction, without waiting
        # for another scene/show statement or altering the saved game itself.
        owner = renpy.game.context().scene_lists
        if _scenelight_wrap_backgrounds(owner):
            _scenelight_redraw_visible_sprites(owner)

    def _scenelight_unwrap_replaced_background(owner, tag):
        # Ren'Py's add implementation uses isinstance(Transform) to inherit
        # the previous ATL state. Expose that original transform during add,
        # then attach the tap to the resulting scene entry again.
        for index, entry in enumerate(owner.layers.get("master", ())):
            if entry.tag == tag and isinstance(entry.displayable, _SceneLightBackground):
                original = entry.copy()
                original.displayable = entry.displayable.child
                owner.layers["master"][index] = original

    def _scenelight_route_scene_add(original_add, owner, args, kwargs):
        """Shade expression sprites at the engine scene boundary."""
        routed_args = list(args)
        layer = kwargs.get("layer", routed_args[0] if len(routed_args) > 0 else None)
        child = kwargs.get("thing", routed_args[1] if len(routed_args) > 1 else None)
        key = kwargs.get("key", routed_args[2] if len(routed_args) > 2 else None)
        name = kwargs.get("name", routed_args[6] if len(routed_args) > 6 else None)

        tag = str(key).split()[0] if key else ""
        if not tag and isinstance(name, (tuple, list)) and name:
            tag = str(name[0]).split()[0]

        image_name = tuple(name) if isinstance(name, (tuple, list)) and name else (tag,)
        registered = _scenelight_get_registered_image(image_name) if tag else None

        if (
            layer == "master"
            and tag in SCENELIGHT_CHARACTER_TAGS
            and child is not None
            and not isinstance(child, (SceneLightSprite, SceneLightImageLike))
            and not isinstance(registered, (SceneLightSprite, SceneLightImageLike))
        ):
            # Put the shader inside existing ATL/default transforms. Ren'Py can
            # then animate, replace, and hide those transforms normally while
            # the shader still sees the final screen-space transform matrix.
            transform_class = getattr(
                getattr(renpy.display, "transform", None),
                "Transform",
                None,
            )
            if transform_class is not None and isinstance(child, transform_class):
                # A color matrix outside the SceneLight child is an authored
                # final-art grade. Detect the real Ren'Py transform state rather
                # than relying on image names such as dusk/night. Geometry-only
                # ATL remains on the ordinary lighting path.
                authored_grade_strength = _scenelight_authored_grade_strength(child)
                innermost = child
                while (
                    isinstance(innermost, transform_class)
                    and getattr(innermost, "child", None) is not None
                ):
                    innermost = innermost.child
                routed_child = child._change_transform_child(
                    SceneLightSprite(
                        innermost,
                        image_name,
                        authored_grade_strength=authored_grade_strength,
                    )
                )
            else:
                routed_child = SceneLightSprite(child, image_name)
            if "thing" in kwargs:
                kwargs = dict(kwargs)
                kwargs["thing"] = routed_child
            elif len(routed_args) > 1:
                routed_args[1] = routed_child

        if layer == "master" and tag:
            _scenelight_unwrap_replaced_background(owner, tag)
        try:
            result = original_add(owner, *tuple(routed_args), **kwargs)
        finally:
            if layer == "master":
                _scenelight_wrap_backgrounds(owner)
        if layer == "master":
            _scenelight_redraw_visible_sprites(owner)
        return result

    def _scenelight_route_scene_mutation(original, owner, args, kwargs):
        """Invalidate remaining lit sprites after hide/scene operations."""

        layer = kwargs.get("layer", args[0] if args else None)
        result = original(owner, *args, **kwargs)
        if layer == "master":
            _scenelight_redraw_visible_sprites(owner)
        return result

    def _scenelight_mutation_router(original):
        def routed(owner, *args, **kwargs):
            # A full restart resets the store but leaves this router attached to
            # the engine's scene-list class, and the rebuilt scene lists call it
            # before init blocks run again. Resolve the implementation at call
            # time so a reset store falls through to the engine instead of
            # raising NameError during bootstrap.
            route = globals().get("_scenelight_route_scene_mutation")
            if route is None:
                return original(owner, *args, **kwargs)
            return route(original, owner, args, kwargs)

        return routed

    def _scenelight_install_scene_router():
        scene_lists = _scenelight_scene_lists_class()
        if scene_lists is None:
            return
        # Rebind on every init so a restarted store gets routers that reference
        # the live namespace; the captured originals are kept from the first run.
        original_add = getattr(scene_lists, "_scenelight_original_add", None)
        if original_add is None:
            original_add = scene_lists.add
            scene_lists._scenelight_original_add = original_add

        def routed_add(owner, *args, **kwargs):
            route = globals().get("_scenelight_route_scene_add")
            if route is None:
                return original_add(owner, *args, **kwargs)
            return route(original_add, owner, args, kwargs)

        scene_lists.add = routed_add
        for method_name in ("remove", "clear"):
            original = getattr(scene_lists, "_scenelight_original_" + method_name, None)
            if original is None:
                original = getattr(scene_lists, method_name, None)
                if original is None:
                    continue
                setattr(scene_lists, "_scenelight_original_" + method_name, original)
            setattr(scene_lists, method_name, _scenelight_mutation_router(original))


init 999 python:
    # Scan/update resolves automatic inclusion and explicit exclusions. Keep
    # that manifest selection authoritative; discovering Character declarations
    # again here would silently re-enable families the user unchecked.
    if _SCENELIGHT_SHADER_AVAILABLE:
        _scenelight_movie_texture = getattr(renpy.display.video, "get_movie_texture", None)
        if callable(_scenelight_movie_texture):
            if getattr(_scenelight_movie_texture, "_scenelight_movie_hook", False):
                _scenelight_movie_texture = _scenelight_movie_texture._scenelight_original
            renpy.display.video.get_movie_texture = _scenelight_movie_texture_hook(_scenelight_movie_texture)
        # Re-register the finished image displayables under the same names. All
        # existing show statements and ATL transforms therefore continue to work.
        for _scenelight_tag in list(SCENELIGHT_CHARACTER_TAGS):
            scenelight_register_tag(_scenelight_tag)

        # Named images are already wrapped above. This also catches runtime
        # expression aliases and other displayables that never enter the registry.
        _scenelight_install_scene_router()
        config.interact_callbacks[:] = [callback for callback in config.interact_callbacks
            if not getattr(callback, "_scenelight_background_binding_callback", False)]
        if renpy.display._scenelight_live_renderer is not None:
            _scenelight_restore_background_bindings._scenelight_background_binding_callback = True
            config.interact_callbacks.append(_scenelight_restore_background_bindings)


screen scenelight_effect_controls():
    modal True
    zorder 2000

    key "scenelight_effects" action Hide("scenelight_effect_controls")
    key "game_menu" action Hide("scenelight_effect_controls")

    use scenelight_effect_controls_panel


screen scenelight_effect_controls_panel():

    frame:
        xalign 0.98
        yalign 0.06
        xmaximum 520
        background Solid("#101925ee")
        padding (22, 18)

        vbox:
            spacing 12
            text "SceneLight effects" size 30 color "#ffffff"
            text "Scene-wide, live GPU effects" size 16 color "#9dc9f7"

            text "Rain / wetness" size 20 color "#ffffff"
            hbox:
                spacing 8
                textbutton "Off" action Function(_scenelight_fx_set_intensity, "rain", 0.0)
                textbutton "Light" action Function(
                    scenelight_fx.scene,
                    "rain",
                    intensity=0.45,
                    wetness=0.45,
                    wind=0.12,
                )
                textbutton "Heavy" action Function(
                    scenelight_fx.scene,
                    "rain",
                    intensity=1.0,
                    wetness=0.82,
                    wind=0.28,
                )

            text "Glitch / corruption" size 20 color "#ffffff"
            hbox:
                spacing 8
                textbutton "Off" action Function(_scenelight_fx_set_intensity, "glitch", 0.0)
                textbutton "Subtle" action Function(
                    scenelight_fx.scene,
                    "glitch",
                    intensity=0.35,
                    rgb_split=0.35,
                    tear=0.25,
                )
                textbutton "Heavy" action Function(
                    scenelight_fx.scene,
                    "glitch",
                    intensity=1.0,
                    rgb_split=0.85,
                    tear=0.78,
                    scanlines=0.48,
                )

            hbox:
                spacing 12
                textbutton "Reset all" action Function(scenelight_fx.clear_all)
                textbutton "Close" action Hide("scenelight_effect_controls")

            text "Shift+F8 opens or closes this panel." size 14 color "#aebccc"


init 999 python:
    # Player attachments expose optional effects without editing the mod. The
    # shifted function key avoids Ren'Py's normal F8 profiler binding.
    if _SCENELIGHT_SHADER_AVAILABLE and _SCENELIGHT_PLAYER_EFFECT_UI_ENABLED:
        config.keymap.setdefault("scenelight_effects", [])
        if "shift_K_F8" not in config.keymap["scenelight_effects"]:
            config.keymap["scenelight_effects"].append("shift_K_F8")
        config.underlay.append(
            renpy.Keymap(
                scenelight_effects=ToggleScreen("scenelight_effect_controls")
            )
        )
