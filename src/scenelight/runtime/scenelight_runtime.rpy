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
default scenelight_control_state = {
    "version": 1,
    "revision": 0,
    "defaults": {},
    "scene": {},
    "backgrounds": {},
    "characters": {},
    "images": {},
}
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
    # Ren'Py 6.99 can parse this runtime but predates the model-based shader
    # API entirely. Keep the original executable playable; SceneLight itself
    # is activated by the compatibility launcher installed beside that game.
    _SCENELIGHT_SHADER_AVAILABLE = callable(getattr(renpy, "register_shader", None))
    # Custom/effect-pack controls are intentionally dormant in the 1.0 release.
    # The implementation remains versioned for a later opt-in update, but 1.0
    # must not register a player-facing hotkey or expose the panel accidentally.
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
        # A validated, palette-independent cinematic compromise discovered by
        # combining separated source colors with compressed scene exposure.
        # Explicit values in the same API call override these preset values.
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

    def _scenelight_control_current_state():
        state = getattr(renpy.store, "scenelight_control_state", None)
        if not isinstance(state, dict) or state.get("version") != 1:
            state = {
                "version": 1,
                "revision": 0,
                "defaults": {},
                "scene": {},
                "backgrounds": {},
                "characters": {},
                "images": {},
            }
        return state

    def _scenelight_control_assign(state):
        state["revision"] = int(state.get("revision", 0)) + 1
        renpy.store.scenelight_control_state = state
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

    def _scenelight_control_values(settings):
        normalized = {}
        raw_mode = settings.get("light_mode")
        if raw_mode is not None:
            mode = str(raw_mode).strip().lower().replace("-", "_")
            mode_values = _SCENELIGHT_LIGHT_MODES.get(mode)
            if mode_values is None:
                raise ValueError(
                    "SceneLight light_mode must be 'physical', 'cinematic', or 'separate'"
                )
            normalized.update(mode_values)
        for raw_name, raw_value in settings.items():
            name = _SCENELIGHT_CONTROL_ALIASES.get(str(raw_name), str(raw_name))
            if name == "light_mode":
                continue
            if name not in _SCENELIGHT_CONTROL_KEYS:
                raise ValueError("Unknown SceneLight lighting setting: %s" % raw_name)
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
        _scenelight_control_assign(state)

    def _scenelight_control_clear(scope, name=None):
        state = copy.deepcopy(_scenelight_control_current_state())
        if scope in ("defaults", "scene"):
            state[scope] = {}
        else:
            key = _scenelight_control_name(name, scope[:-1])
            state.setdefault(scope, {}).pop(key, None)
        _scenelight_control_assign(state)

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
                    result["calibration"][key] = float(layer[key])
        # A scripted scene bypass is absolute. It must not be undone by a
        # reusable character or image rule authored at a narrower scope.
        if isinstance(scene_layer, dict) and scene_layer.get("enabled") is False:
            result["enabled"] = False
        return result

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
                }
            )

        def state(self):
            return copy.deepcopy(_scenelight_control_current_state())

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
            0.0, min(float(SCENELIGHT_MANIFEST.get("strength", 1.0)), 1.5)
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
        if frame is None:
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
            (bounded("shadow_strength"), bounded("individual_light_colors"), bounded("adaptive_light_colors"), 0.0),
        )
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
        """Match Ren'Py's visible attributes to its captured canonical form.

        LayeredImage omits internal/default attributes from DisplayableArguments.
        The resolver capture includes those attributes because they can affect
        conditional layers. Exact string lookup therefore misses legitimate
        forms such as ``forward worr cm oe`` versus its captured canonical
        ``forward worr cm n2 ldown oe``. A canonical candidate must contain
        every runtime-visible attribute; the least-augmented candidate is the
        deterministic form produced by those defaults. Character colors are
        never considered.
        """

        exact = SCENELIGHT_FORM_SPRITES.get(form_key)
        if exact is not None:
            return exact
        parts = tuple(form_key.split())
        if parts:
            requested = frozenset(parts[1:])
            candidates = []
            for attributes, name, entry in SCENELIGHT_FORM_CANDIDATES.get(parts[0], ()):
                if requested.issubset(attributes):
                    candidates.append((len(attributes - requested), name, entry))
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                return candidates[0][2]
        return SCENELIGHT_FORM_SPRITES.get(base_form_key)

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
            # Ren'Py Render sizes do not themselves clip overflowing children.
            # A fixed viewport makes the offscreen projection match the scene's
            # screen coordinates, including sprites extending past an edge.
            # Let child dependencies schedule updates; do not force a texture
            # snapshot or query/re-render every character for its bounds.
            viewport = renpy.Render(config.screen_width, config.screen_height)
            viewport.xclipping = True
            viewport.yclipping = True
            viewport.blit(rendered, (0, 0))
            result = renpy.Render(config.screen_width, config.screen_height)
            result.blit(viewport, (0, 0))
            result.mesh = True
            result.add_shader("renpy.texture")
            result.add_property("drawable_resolution", True)
            result.add_property("mipmap", renpy.config.mipmap_dissolves)
            return result

    # Scene-wide transitions render their sides into another framebuffer. That
    # changes the coordinate system seen by a screen-space sprite shader, so
    # retain the outgoing snapshot and resolve the incoming side in a clipped
    # screen-sized viewport. Its own movie/animation dependencies remain live
    # without repeated synchronous snapshots or character-bounds queries.
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
            or not getattr(persistent, "scenelight_enabled", True)
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
    _scenelight_shader_live_probe_variables = """
        uniform sampler2D tex1;
        uniform vec2 u_sc_probe_grid;
        varying vec2 v_tex_coord;
    """
    _scenelight_shader_live_probe_fragment = """
        vec3 total = vec3(0.0);
        for (int y = 0; y < 4; y++) {
            for (int x = 0; x < 4; x++) {
                vec2 offset = (vec2(float(x), float(y)) - vec2(1.5))
                    / (u_sc_probe_grid * 4.0);
                vec3 color = texture2D(tex1, clamp(v_tex_coord + offset,
                    vec2(0.0), vec2(1.0))).rgb;
                vec3 low = color / 12.92;
                vec3 high = pow((color + vec3(0.055)) / 1.055, vec3(2.4));
                total += mix(low, high, step(vec3(0.04045), color));
            }
        }
        gl_FragColor = vec4(total / 16.0, 1.0);
    """

    _scenelight_shader_transport_blend_variables = """
        uniform sampler2D tex1;
        uniform vec4 u_sc_field_left;
        uniform vec4 u_sc_field_right;
        uniform float u_sc_field_amount;
        uniform float u_sc_field_layout_change;
        varying vec2 v_tex_coord;
    """
    _scenelight_shader_transport_blend_fragment = """
        vec4 left_value = texture2D(tex1,
            u_sc_field_left.xy + v_tex_coord * u_sc_field_left.zw);
        vec4 right_value = texture2D(tex1,
            u_sc_field_right.xy + v_tex_coord * u_sc_field_right.zw);
        vec3 value = mix(left_value.rgb, right_value.rgb, u_sc_field_amount);
        float plane = floor(v_tex_coord.x * 26.0);
        if (u_sc_field_layout_change > 0.5 && plane >= 6.0 && plane < 15.0) {
            value = u_sc_field_amount < 0.5 ? left_value.rgb : right_value.rgb;
            if (mod(plane, 3.0) > 1.5) {
                float phase = u_sc_field_amount < 0.5
                    ? 1.0 - u_sc_field_amount * 2.0
                    : u_sc_field_amount * 2.0 - 1.0;
                value *= smoothstep(0.0, 1.0, phase);
            }
        }
        // Quantize each field texel before the sprite samples it bilinearly,
        // matching the reference's round-to-nearest/even data contract.
        vec3 scaled = value * 255.0;
        vec3 integral = floor(scaled);
        vec3 fraction = scaled - integral;
        vec3 rounded = floor(scaled + 0.5);
        rounded = mix(rounded, integral + mod(integral, 2.0),
            vec3(equal(fraction, vec3(0.5))));
        gl_FragColor = vec4(rounded / 255.0, 1.0);
    """

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

    _scenelight_shader_variables = """
            uniform vec4 u_sc_wrap_uv;
            uniform vec4 u_sc_wrap_uv_next;
            uniform vec2 u_sc_wrap_texel;
            uniform float u_sc_wrap_blend;
            uniform sampler2D tex1;
            uniform sampler2D tex2;
            uniform sampler2D tex3;
            uniform sampler2D tex4;
            uniform sampler2D tex5;
            uniform sampler2D tex6;
            uniform sampler2D tex7;
            uniform vec2 res0;
            uniform vec2 u_model_size;
            uniform mat4 u_transform;
            uniform vec4 u_sc_scene_uv;
            uniform vec4 u_sc_scene_uv_next;
            uniform float u_sc_scene_blend;
            uniform vec2 u_sc_atlas_texel;
            uniform float u_sc_reference_mid;
            uniform float u_sc_strength;
            uniform float u_sc_authored_grade;
            uniform float u_sc_chroma_range;
            uniform float u_sc_target_range;
            uniform vec3 u_sc_shadow_chroma;
            uniform float u_sc_local_saturation;
            uniform float u_sc_local_contrast;
            uniform float u_sc_light_confidence;
            uniform float u_sc_source_size;
            uniform float u_sc_grain;
            uniform float u_sc_sharpness;
            uniform float u_sc_has_form;
            uniform vec2 u_sc_form_center;
            uniform vec4 u_sc_snapshot_rect;
            uniform float u_sc_use_snapshot_rect;
            uniform float u_sc_mean_form_visibility;
            uniform float u_sc_form_contrast_mid;
            uniform vec2 u_sc_height_range;
            uniform float u_sc_noise_range;
            uniform float u_sc_local_luminance;
            uniform float u_sc_has_transport;
            uniform float u_sc_live_background;
            uniform float u_sc_live_analysis;
            uniform vec4 u_sc_transport_uv;
            uniform vec2 u_sc_transport_grid;
            uniform float u_sc_transport_subject_y_max;
            uniform float u_sc_debug_contrast;
            uniform float u_sc_compare_mode;
            uniform float u_sc_effect_time;
            uniform vec4 u_sc_rain_data;
            uniform vec4 u_sc_rain_color_scale;
            uniform vec4 u_sc_glitch_data;
            uniform vec4 u_sc_glitch_extra;
            uniform vec4 u_sc_calibration0;
            uniform vec4 u_sc_calibration1;
            uniform vec4 u_sc_calibration2;
            uniform vec4 u_sc_calibration3;
            uniform vec4 u_sc_calibration4;
            uniform vec4 u_sc_light0_data;
            uniform vec4 u_sc_light0_color;
            uniform vec2 u_sc_light0_extra;
            uniform vec4 u_sc_light1_data;
            uniform vec4 u_sc_light1_color;
            uniform vec2 u_sc_light1_extra;
            uniform vec4 u_sc_light2_data;
            uniform vec4 u_sc_light2_color;
            uniform vec2 u_sc_light2_extra;
            uniform vec4 u_sc_light3_data;
            uniform vec4 u_sc_light3_color;
            uniform vec2 u_sc_light3_extra;
            uniform vec4 u_sc_probe0_data;
            uniform vec3 u_sc_probe0_color;
            uniform vec4 u_sc_probe1_data;
            uniform vec3 u_sc_probe1_color;
            uniform vec4 u_sc_probe2_data;
            uniform vec3 u_sc_probe2_color;
            uniform vec4 u_sc_probe3_data;
            uniform vec3 u_sc_probe3_color;
            uniform vec4 u_sc_probe4_data;
            uniform vec3 u_sc_probe4_color;
            uniform vec4 u_sc_probe5_data;
            uniform vec3 u_sc_probe5_color;
            uniform vec4 u_sc_probe6_data;
            uniform vec3 u_sc_probe6_color;
            uniform vec4 u_sc_probe7_data;
            uniform vec3 u_sc_probe7_color;
            varying vec2 v_sc_screen;
            varying vec2 v_sc_center;
        """
    _scenelight_shader_vertex_150 = """
            vec2 sc_live_screen = vec2(
                gl_Position.x * 0.5 + 0.5,
                -gl_Position.y * 0.5 + 0.5
            );
            vec4 sc_center_position = u_transform * vec4(
                u_model_size * u_sc_form_center,
                0.0,
                1.0
            );
            vec2 sc_live_center = vec2(
                sc_center_position.x * 0.5 + 0.5,
                -sc_center_position.y * 0.5 + 0.5
            );
            vec2 sc_snapshot_screen = u_sc_snapshot_rect.xy
                + a_tex_coord * u_sc_snapshot_rect.zw;
            vec2 sc_snapshot_center = u_sc_snapshot_rect.xy
                + u_sc_form_center * u_sc_snapshot_rect.zw;
            v_sc_screen = mix(
                sc_live_screen,
                sc_snapshot_screen,
                u_sc_use_snapshot_rect
            );
            v_sc_center = mix(
                sc_live_center,
                sc_snapshot_center,
                u_sc_use_snapshot_rect
            );
        """
    _scenelight_shader_fragment_functions = _scenelight_fragment_source("""
            vec2 scenelight_field_uv(vec2 screen_uv, vec4 tile) {
                vec2 half_texel = u_sc_atlas_texel * 0.5;
                return clamp(tile.xy + screen_uv * tile.zw,
                    tile.xy + half_texel, tile.xy + tile.zw - half_texel);
            }

            vec2 scenelight_atlas_uv(vec2 screen_uv) {
                vec2 half_texel = u_sc_atlas_texel * 0.5;
                vec2 tile_min = u_sc_scene_uv.xy + half_texel;
                vec2 tile_max = u_sc_scene_uv.xy + u_sc_scene_uv.zw - half_texel;
                return clamp(u_sc_scene_uv.xy + screen_uv * u_sc_scene_uv.zw, tile_min, tile_max);
            }

            vec4 scenelight_scene_at(sampler2D source_field, vec2 screen_uv) {
                vec4 current = texture2D(source_field, scenelight_atlas_uv(screen_uv));
                if (u_sc_scene_blend <= 0.0) return current;
                vec4 following = texture2D(source_field,
                    scenelight_field_uv(screen_uv, u_sc_scene_uv_next));
                return mix(current, following, u_sc_scene_blend);
            }

            vec3 scenelight_wrap_at(vec2 screen_uv) {
                vec2 half_texel = u_sc_wrap_texel * 0.5;
                vec2 current_uv = clamp(u_sc_wrap_uv.xy + screen_uv * u_sc_wrap_uv.zw,
                    u_sc_wrap_uv.xy + half_texel, u_sc_wrap_uv.xy + u_sc_wrap_uv.zw - half_texel);
                vec3 current = texture2D(tex6, current_uv).rgb;
                if (u_sc_wrap_blend <= 0.0) return current;
                vec2 next_uv = clamp(u_sc_wrap_uv_next.xy + screen_uv * u_sc_wrap_uv_next.zw,
                    u_sc_wrap_uv_next.xy + half_texel, u_sc_wrap_uv_next.xy + u_sc_wrap_uv_next.zw - half_texel);
                return mix(current, texture2D(tex6, next_uv).rgb, u_sc_wrap_blend);
            }

            vec4 scenelight_transport_at(float plane, vec2 screen_uv) {
                vec2 grid_position = vec2(
                    clamp(screen_uv.x, 0.0, 1.0),
                    clamp(screen_uv.y / max(u_sc_transport_subject_y_max, 0.001), 0.0, 1.0)
                );
                vec2 grid_texel_position = vec2(
                    0.5 + grid_position.x * (u_sc_transport_grid.x - 1.0),
                    0.5 + grid_position.y * (u_sc_transport_grid.y - 1.0)
                );
                vec2 local_uv = grid_texel_position / u_sc_transport_grid;
                vec2 atlas_uv = vec2(
                    u_sc_transport_uv.x + (plane + local_uv.x) * u_sc_transport_uv.z,
                    u_sc_transport_uv.y + local_uv.y * u_sc_transport_uv.w
                );
                // V5 transport planes are deliberately opaque. Independent
                // scalars live in RGB-only planes, preventing Ren'Py's texture
                // premultiplication from quantizing chroma in dark scenes.
                return texture2D(tex7, atlas_uv);
            }

            float scenelight_emitter_at(vec2 screen_uv) {
                return scenelight_scene_at(tex2, screen_uv).a;
            }

            vec3 scenelight_irradiance_at(vec2 screen_uv) {
                return scenelight_scene_at(tex1, screen_uv).rgb;
            }

            float scenelight_straight_luma(vec4 pixel) {
                vec3 straight_rgb = pixel.rgb / max(pixel.a, 0.001);
                vec3 low = straight_rgb / 12.92;
                vec3 high = pow((straight_rgb + vec3(0.055)) / 1.055, vec3(2.4));
                vec3 linear_rgb = mix(low, high, step(vec3(0.04045), straight_rgb));
                return dot(linear_rgb, vec3(0.2126, 0.7152, 0.0722));
            }

            vec3 scenelight_srgb_to_linear(vec3 color) {
                color = max(color, vec3(0.0));
                vec3 low = color / 12.92;
                vec3 high = pow((color + vec3(0.055)) / 1.055, vec3(2.4));
                return mix(low, high, step(vec3(0.04045), color));
            }

            vec3 scenelight_linear_to_srgb(vec3 color) {
                color = max(color, vec3(0.0));
                vec3 low = color * 12.92;
                vec3 high = 1.055 * pow(color, vec3(1.0 / 2.4)) - vec3(0.055);
                return mix(low, high, step(vec3(0.0031308), color));
            }

            vec3 scenelight_unit_energy(vec3 chroma) {
                float energy = dot(chroma, vec3(0.2126, 0.7152, 0.0722));
                return clamp(chroma / max(energy, 0.001), vec3(0.45), vec3(2.4));
            }

            float scenelight_fx_hash(vec2 value) {
                return fract(sin(dot(value, vec2(127.1, 311.7))) * 43758.5453123);
            }

            float scenelight_fx_rain_streak(
                vec2 sprite_uv,
                float time,
                float wind,
                float scale
            ) {
                vec2 rain_uv = sprite_uv;
                rain_uv.x -= rain_uv.y * wind * 0.28;
                rain_uv *= vec2(42.0, 9.0) / max(scale, 0.25);
                vec2 cell = floor(rain_uv);
                vec2 local = fract(rain_uv);
                float random = scenelight_fx_hash(cell);
                float phase = fract(local.y + time * (0.70 + random * 0.85) + random);
                float trail_x = abs(local.x - (0.14 + random * 0.72));
                float thin = 1.0 - smoothstep(0.012, 0.055, trail_x);
                float head = 1.0 - smoothstep(0.02, 0.16, phase);
                float tail = smoothstep(0.04, 0.22, phase) * (1.0 - smoothstep(0.22, 0.92, phase));
                return thin * (head + tail * 0.42) * step(0.40, random);
            }

            float scenelight_height(vec2 sprite_uv, sampler2D source_texture, float lod_bias) {
                if (u_sc_has_form > 0.5) {
                    float encoded = texture2D(
                        tex4,
                        clamp(sprite_uv, vec2(0.0), vec2(1.0))
                    ).r;
                    return mix(u_sc_height_range.x, u_sc_height_range.y, encoded);
                }
                vec4 pixel = texture2D(
                    source_texture,
                    clamp(sprite_uv, vec2(0.0), vec2(1.0)),
                    lod_bias
                );
                return pixel.a * 0.72 + scenelight_straight_luma(pixel) * 0.28;
            }

            vec3 scenelight_form_normal(
                vec2 sprite_uv,
                vec2 sprite_texel,
                sampler2D source_texture,
                float lod_bias
            ) {
                if (u_sc_has_form > 0.5) {
                    vec2 encoded = texture2D(tex3, clamp(sprite_uv, vec2(0.0), vec2(1.0))).rg;
                    vec2 normal_xy = encoded * 2.0 - 1.0;
                    float normal_z = sqrt(max(1.0 - dot(normal_xy, normal_xy), 0.0001));
                    return normalize(vec3(normal_xy, normal_z));
                }
                float height_left = scenelight_height(
                    sprite_uv - vec2(sprite_texel.x * 2.0, 0.0), source_texture, lod_bias
                );
                float height_right = scenelight_height(
                    sprite_uv + vec2(sprite_texel.x * 2.0, 0.0), source_texture, lod_bias
                );
                float height_up = scenelight_height(
                    sprite_uv - vec2(0.0, sprite_texel.y * 2.0), source_texture, lod_bias
                );
                float height_down = scenelight_height(
                    sprite_uv + vec2(0.0, sprite_texel.y * 2.0), source_texture, lod_bias
                );
                return normalize(vec3(
                    (height_left - height_right) * 2.8,
                    (height_up - height_down) * 2.8,
                    1.0
                ));
            }

            vec4 scenelight_light_vector_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale,
                vec2 fallback_direction
            ) {
                float enabled = extra.y;
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                float weight = data.w * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * enabled;
                float elevation = 0.72 + data.z * 0.65;
                vec2 center_delta = data.xy - v_sc_center;
                float center_distance = length(center_delta);
                vec2 center_direction = center_delta / max(center_distance, 0.12);
                center_direction += fallback_direction * step(center_distance, 0.0001) * 0.0001;
                vec3 broad_vector = normalize(vec3(center_direction, elevation));
                vec2 pixel_delta = data.xy - v_sc_screen;
                vec2 pixel_direction = pixel_delta / max(length(pixel_delta), 0.12);
                vec3 point_vector = normalize(vec3(pixel_direction, elevation));
                float emitter_blend = clamp(extra.x, 0.0, 1.0);
                vec3 light_vector = normalize(mix(broad_vector, point_vector, emitter_blend));

                float source_reach = 0.08 + data.z * 0.90;
                float pixel_distance = distance(data.xy, v_sc_screen);
                float falloff = 1.0 / (1.0 + pow(pixel_distance / source_reach, 2.0));
                float center_falloff = 1.0 / (1.0 + pow(screen_distance / source_reach, 2.0));
                float relative_falloff = clamp(falloff / max(center_falloff, 0.0001), 0.32, 1.85);
                float spatial_weight = 1.0 + (relative_falloff - 1.0) * emitter_blend * 0.72;
                return vec4(light_vector, weight * spatial_weight);
            }

            float scenelight_light_base_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale
            ) {
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                return data.w * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * extra.y;
            }

            float scenelight_creative_light_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale
            ) {
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                float source_present = step(0.001, data.w + extra.x);
                float source_reach = 0.08 + data.z * 0.90;
                float pixel_distance = distance(data.xy, v_sc_screen);
                float falloff = 1.0 / (1.0 + pow(pixel_distance / source_reach, 2.0));
                float center_falloff = 1.0 / (1.0 + pow(screen_distance / source_reach, 2.0));
                float relative_falloff = clamp(
                    falloff / max(center_falloff, 0.0001),
                    0.28,
                    2.10
                );
                return source_present * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * relative_falloff
                    * step(0.001, color.a);
            }

            float scenelight_separation_pair_evidence(
                vec4 data_a,
                vec4 color_a,
                vec2 extra_a,
                vec4 data_b,
                vec4 color_b,
                vec2 extra_b
            ) {
                // Hue-family sources are encoded with physical intensity off
                // (data.w == 0) and their measured source energy in extra.x.
                // Requiring two such sources prevents colorful props or one
                // dominant lamp from turning an ordinary scene into a grade.
                float creative_a = (1.0 - step(0.001, data_a.w))
                    * step(0.001, extra_a.x) * step(0.001, color_a.a);
                float creative_b = (1.0 - step(0.001, data_b.w))
                    * step(0.001, extra_b.x) * step(0.001, color_b.a);
                float chroma_evidence = smoothstep(
                    0.55,
                    0.95,
                    length(color_a.rgb - color_b.rgb)
                );
                float spatial_evidence = smoothstep(
                    0.04,
                    0.24,
                    distance(data_a.xy, data_b.xy)
                );
                float energy_evidence = smoothstep(
                    0.55,
                    0.85,
                    min(extra_a.x, extra_b.x)
                );
                float confidence_evidence = smoothstep(
                    0.58,
                    0.82,
                    min(color_a.a, color_b.a)
                );
                return creative_a * creative_b * chroma_evidence
                    * spatial_evidence * energy_evidence * confidence_evidence;
            }

            float scenelight_primary_creative_evidence(
                vec4 primary_data,
                vec4 primary_color,
                vec4 creative_data,
                vec4 creative_color,
                vec2 creative_extra
            ) {
                // One strongly colored practical plus a neutral key is already
                // a separated-light scene. Keep the gate conservative so a
                // weak saturated prop cannot turn an ordinary photograph into
                // a global grade.
                float primary_present = step(0.001, primary_data.w)
                    * step(0.001, primary_color.a);
                float creative_present = (1.0 - step(0.001, creative_data.w))
                    * step(0.001, creative_extra.x)
                    * step(0.001, creative_color.a);
                float neutral_evidence = 1.0 - smoothstep(
                    0.22,
                    0.40,
                    length(primary_color.rgb - vec3(1.0))
                );
                float chroma_evidence = smoothstep(
                    0.45,
                    0.80,
                    length(primary_color.rgb - creative_color.rgb)
                );
                float spatial_evidence = smoothstep(
                    0.10,
                    0.24,
                    distance(primary_data.xy, creative_data.xy)
                );
                float energy_evidence = smoothstep(0.72, 0.90, creative_extra.x);
                float confidence_evidence = smoothstep(0.72, 0.90, creative_color.a);
                return primary_present * creative_present * neutral_evidence
                    * chroma_evidence * spatial_evidence
                    * energy_evidence * confidence_evidence;
            }

            vec3 scenelight_center_light_vector(
                vec4 data,
                vec2 fallback_direction
            ) {
                vec2 delta = data.xy - v_sc_center;
                float distance_to_light = length(delta);
                vec2 direction = delta / max(distance_to_light, 0.12);
                direction += fallback_direction * step(distance_to_light, 0.0001) * 0.0001;
                return normalize(vec3(direction, 0.72 + data.z * 0.65));
            }

            float scenelight_filtered_lambert(
                vec3 light_vector,
                vec3 normal0,
                vec3 normal1,
                vec3 normal2,
                vec3 normal3,
                vec3 normal4
            ) {
                // The installed form normal is already spatially filtered.
                // A center-plus-cross kernel preserves the broad Lambert lobe
                // without paying for four redundant diagonal texture reads.
                float value = max(dot(normal0, light_vector), 0.0) * 0.36;
                value += max(dot(normal1, light_vector), 0.0) * 0.16;
                value += max(dot(normal2, light_vector), 0.0) * 0.16;
                value += max(dot(normal3, light_vector), 0.0) * 0.16;
                value += max(dot(normal4, light_vector), 0.0) * 0.16;
                return value;
            }

            float scenelight_ray_shadow(
                vec2 light_direction,
                float elevation,
                vec2 sprite_texel,
                float alpha,
                vec2 sprite_uv,
                vec2 source_resolution,
                sampler2D source_texture,
                float lod_bias
            ) {
                float center_height = scenelight_height(
                    sprite_uv, source_texture, lod_bias
                ) + u_sc_height_range.x * 0.0;
                float shadow = 0.0;
                // Six evenly spaced taps retain the full shadow reach. The
                // old fourteen-tap search oversampled a deliberately smooth
                // generated height field and dominated older integrated GPUs.
                for (int ray_step = 1; ray_step <= 6; ray_step++) {
                    float fraction = float(ray_step) / 6.0;
                    float step_distance = min(source_resolution.x, source_resolution.y) * 0.46 * fraction;
                    vec2 ray_uv = sprite_uv + light_direction * sprite_texel * step_distance;
                    float sampled_alpha = texture2D(
                        source_texture, clamp(ray_uv, vec2(0.0), vec2(1.0)), lod_bias
                    ).a;
                    float ray_rise = fraction * (0.22 + 0.34 * elevation);
                    float blocker = max(
                        scenelight_height(ray_uv, source_texture, lod_bias) - center_height - ray_rise,
                        0.0
                    ) * sampled_alpha;
                    shadow = max(shadow, blocker);
                }
                return clamp(shadow * 4.4, 0.0, 1.0) * step(0.001, alpha);
            }

            void scenelight_accumulate_probe(
                vec4 data,
                vec3 color,
                vec3 normal,
                float local_reference,
                inout vec3 probe_rgb,
                inout float probe_weight,
                inout vec3 ground_rgb,
                inout float ground_energy
            ) {
                float incidence = clamp(
                    normal.x * data.x + normal.y * data.y + normal.z * 0.42,
                    0.0,
                    1.0
                );
                float relative_energy = clamp(
                    (data.z + 0.015) / local_reference,
                    0.18,
                    2.6
                );
                float weight = incidence * (0.25 + 0.75 * relative_energy) * data.w;
                probe_rgb += weight * clamp(color, vec3(0.55), vec3(2.1));
                probe_weight += weight;
                float is_ground = step(0.5, data.y) * data.w;
                float energy = (data.z + 0.02) * is_ground;
                ground_rgb += color * energy;
                ground_energy += energy;
            }
        """, preamble=True)
    _scenelight_shader_fragment_350 = _scenelight_fragment_source("""
            // Ren'Py 7 discovers declarations by scanning numbered shader
            // blocks, but not fragment_functions. Keep function-only names
            // visible to that parser without adding GPU work:
            // tex1 tex2 tex3 tex4 tex5 tex6 tex7
            // u_sc_scene_uv u_sc_atlas_texel u_sc_reference_mid
            // u_sc_authored_grade
            // u_sc_chroma_range u_sc_target_range u_sc_shadow_chroma
            // u_sc_local_saturation u_sc_local_contrast u_sc_light_confidence
            // u_sc_source_size u_sc_grain u_sc_sharpness u_sc_has_form
            // u_sc_form_center u_sc_mean_form_visibility u_sc_form_contrast_mid
            // u_sc_height_range u_sc_noise_range u_sc_local_luminance
            // u_sc_has_transport u_sc_live_background u_sc_transport_uv
            // u_sc_transport_grid u_sc_transport_subject_y_max
            // u_sc_light0_data u_sc_light0_color u_sc_light0_extra
            // u_sc_light1_data u_sc_light1_color u_sc_light1_extra
            // u_sc_light2_data u_sc_light2_color u_sc_light2_extra
            // u_sc_light3_data u_sc_light3_color u_sc_light3_extra
            // u_sc_probe0_data u_sc_probe0_color u_sc_probe1_data u_sc_probe1_color
            // u_sc_probe2_data u_sc_probe2_color u_sc_probe3_data u_sc_probe3_color
            // u_sc_probe4_data u_sc_probe4_color u_sc_probe5_data u_sc_probe5_color
            // u_sc_probe6_data u_sc_probe6_color u_sc_probe7_data u_sc_probe7_color
            // Compose from the fragment color produced by any lower-priority
            // shader part instead of resampling tex0. Most foreign mesh
            // transforms are isolated passes, but this also preserves a
            // deliberately combined Ren'Py shader stack.
            vec4 source = gl_FragColor;
            float sc_live_grain = u_sc_grain;
            float sc_live_sharpness = u_sc_sharpness;
            if (u_sc_live_analysis > 0.5) {
                vec3 sc_live_grain_rgb = texture2D(tex7, vec2(0.5 / 416.0, 9.5 / 10.0)).rgb;
                vec3 sc_live_sharpness_rgb = texture2D(tex7, vec2(1.5 / 416.0, 9.5 / 10.0)).rgb;
                vec3 sc_live_decode = vec3(65536.0, 256.0, 1.0) * (255.0 / 16777215.0);
                sc_live_grain = dot(sc_live_grain_rgb, sc_live_decode);
                sc_live_sharpness = dot(sc_live_sharpness_rgb, sc_live_decode);
            }
            float sc_glitch_intensity = u_sc_glitch_data.x;
            if (sc_glitch_intensity > 0.0001) {
                float sc_glitch_tick = floor(
                    u_sc_effect_time * max(u_sc_glitch_data.w, 0.05) * 18.0
                );
                float sc_glitch_rows = max(18.0, 84.0 / max(u_sc_glitch_data.z, 0.25));
                float sc_glitch_row = floor(v_tex_coord.y * sc_glitch_rows);
                float sc_glitch_random = scenelight_fx_hash(
                    vec2(sc_glitch_row + u_sc_glitch_extra.w, sc_glitch_tick)
                );
                float sc_glitch_gate = step(0.78 - 0.48 * sc_glitch_intensity, sc_glitch_random);
                float sc_glitch_offset = (
                    sc_glitch_random - 0.5
                ) * 0.075 * u_sc_glitch_extra.x * sc_glitch_intensity * sc_glitch_gate;
                vec2 sc_glitch_uv = clamp(
                    v_tex_coord + vec2(sc_glitch_offset, 0.0),
                    vec2(0.0),
                    vec2(1.0)
                );
                source = texture2D(tex0, sc_glitch_uv, u_lod_bias);
                float sc_split = 0.010 * u_sc_glitch_data.y * sc_glitch_intensity;
                vec4 sc_red = texture2D(
                    tex0,
                    clamp(sc_glitch_uv + vec2(sc_split, 0.0), vec2(0.0), vec2(1.0)),
                    u_lod_bias
                );
                vec4 sc_blue = texture2D(
                    tex0,
                    clamp(sc_glitch_uv - vec2(sc_split, 0.0), vec2(0.0), vec2(1.0)),
                    u_lod_bias
                );
                source.r = sc_red.r;
                source.b = sc_blue.b;
            }
            float alpha = source.a;
            vec3 base_srgb = source.rgb / max(alpha, 0.001);
            vec3 base = scenelight_srgb_to_linear(base_srgb);
            float base_luma = dot(base, vec3(0.2126, 0.7152, 0.0722));
            float material_response = smoothstep(0.012, 0.115, base_luma);
            float sc_height_dependency = u_sc_height_range.x * 0.0;
            // Ren'Py discovers varyings from the fragment body rather than
            // recursively through helper functions. Keep this explicit zero
            // dependency so v_sc_screen remains available to the light and
            // shadow transport helpers above.
            vec2 sc_screen_dependency = v_sc_screen * 0.0;
            vec4 sc_transport_dependency = texture2D(tex7, vec2(0.0)) * 0.0;
            sc_transport_dependency += vec4(
                u_sc_transport_uv.xy,
                u_sc_transport_grid.x / max(u_sc_transport_grid.y, 1.0),
                u_sc_transport_subject_y_max
            ) * 0.0;

            // The CPU reference meters one local environment around the
            // subject. Sampling ambient color independently behind every body
            // pixel made the former runtime look like a translucent cutout of
            // the background. Keep broad adaptation constant across the form;
            // only explicit lights and edge wrap are spatially local.
            vec2 scene_uv = scenelight_atlas_uv(v_sc_center);
            vec4 irradiance_sample = scenelight_scene_at(tex1, v_sc_center);
            vec4 emitter_sample = scenelight_scene_at(tex2, v_sc_center);
            vec4 transport_scalar = scenelight_transport_at(0.0, v_sc_center);
            vec4 transport_ambient = scenelight_transport_at(1.0, v_sc_center);
            vec4 transport_global_extra = scenelight_transport_at(2.0, v_sc_center);
            float transport_mix = step(0.5, u_sc_has_transport);
            vec3 ambient_chroma = mix(
                scenelight_unit_energy(irradiance_sample.rgb * u_sc_chroma_range),
                transport_ambient.rgb * u_sc_chroma_range,
                transport_mix
            );
            vec3 emitter_chroma = scenelight_unit_energy(emitter_sample.rgb * u_sc_chroma_range);
            float local_contrast = mix(u_sc_local_contrast, transport_scalar.r * 2.0, transport_mix);
            float local_saturation = mix(u_sc_local_saturation, transport_scalar.g, transport_mix);
            float local_luminance = mix(u_sc_local_luminance, transport_scalar.b, transport_mix);
            float transported_target_mid = mix(
                irradiance_sample.a * u_sc_target_range,
                transport_global_extra.r * u_sc_target_range,
                transport_mix
            );
            // Animated backgrounds keep the exact static transport solution
            // for geometry, multiple emitters, probes, and character motion.
            // Their current blurred environment frame updates broad exposure
            // and chroma every displayed frame without a CPU re-analysis.
            if (u_sc_live_background > 0.5) {
                vec3 live_environment = scenelight_srgb_to_linear(
                    scenelight_wrap_at(v_sc_center)
                );
                float live_luminance = dot(
                    live_environment,
                    vec3(0.2126, 0.7152, 0.0722)
                );
                float live_exposure_ratio = sqrt(
                    (live_luminance + 0.008) / (local_luminance + 0.008)
                );
                ambient_chroma = scenelight_unit_energy(live_environment);
                transported_target_mid = clamp(
                    transported_target_mid * live_exposure_ratio,
                    0.035,
                    u_sc_target_range
                );
                local_luminance = live_luminance;
            }
            vec3 shadow_chroma = mix(
                u_sc_shadow_chroma,
                scenelight_unit_energy(ambient_chroma * vec3(0.91, 0.96, 1.07)),
                transport_mix
            );

            // Offset in screen space, then clamp inside the current atlas tile.
            // Offsetting the atlas UV itself can leak light from a neighboring
            // background when a character reaches a screen edge.
            vec2 screen_dx = vec2(u_sc_atlas_texel.x / u_sc_scene_uv.z * 1.5, 0.0);
            vec2 screen_dy = vec2(0.0, u_sc_atlas_texel.y / u_sc_scene_uv.w * 1.5);
            float field_left = scenelight_emitter_at(v_sc_center - screen_dx);
            float field_right = scenelight_emitter_at(v_sc_center + screen_dx);
            float field_up = scenelight_emitter_at(v_sc_center - screen_dy);
            float field_down = scenelight_emitter_at(v_sc_center + screen_dy);
            vec2 light_gradient = vec2(field_right - field_left, field_down - field_up);
            light_gradient += vec2(0.0, -0.012);
            vec2 light_direction = normalize(light_gradient + vec2(0.00001, -0.00001));

            // Transparent canvas pixels only need the contact-shadow branch.
            // Keep later shader parts running, and retain the exact original
            // alpha threshold and shadow calculation below.
            if (alpha > 0.001) {
            vec2 sprite_texel = 1.0 / max(res0, vec2(1.0));
            vec3 normal = scenelight_form_normal(v_tex_coord, sprite_texel, tex0, u_lod_bias);
            // Fetch the Gaussian form neighborhood once and reuse it for all
            // four lights. This is both exact to the chosen kernel and much
            // cheaper than resampling the normal map inside every light lobe.
            vec2 form_filter_offset = sprite_texel * 1.310548;
            vec3 normal1 = scenelight_form_normal(v_tex_coord + vec2(form_filter_offset.x, 0.0), sprite_texel, tex0, u_lod_bias);
            vec3 normal2 = scenelight_form_normal(v_tex_coord - vec2(form_filter_offset.x, 0.0), sprite_texel, tex0, u_lod_bias);
            vec3 normal3 = scenelight_form_normal(v_tex_coord + vec2(0.0, form_filter_offset.y), sprite_texel, tex0, u_lod_bias);
            vec3 normal4 = scenelight_form_normal(v_tex_coord - vec2(0.0, form_filter_offset.y), sprite_texel, tex0, u_lod_bias);
            vec4 transport_light0_position = scenelight_transport_at(3.0, v_sc_center);
            vec4 transport_light0_color_sample = scenelight_transport_at(4.0, v_sc_center);
            vec4 transport_light0_scalar = scenelight_transport_at(5.0, v_sc_center);
            vec4 transport_light1_position = scenelight_transport_at(6.0, v_sc_center);
            vec4 transport_light1_color_sample = scenelight_transport_at(7.0, v_sc_center);
            vec4 transport_light1_scalar = scenelight_transport_at(8.0, v_sc_center);
            vec4 transport_light2_position = scenelight_transport_at(9.0, v_sc_center);
            vec4 transport_light2_color_sample = scenelight_transport_at(10.0, v_sc_center);
            vec4 transport_light2_scalar = scenelight_transport_at(11.0, v_sc_center);
            vec4 transport_light3_position = scenelight_transport_at(12.0, v_sc_center);
            vec4 transport_light3_color_sample = scenelight_transport_at(13.0, v_sc_center);
            vec4 transport_light3_scalar = scenelight_transport_at(14.0, v_sc_center);
            vec4 sc_light0_data = mix(
                u_sc_light0_data,
                vec4(transport_light0_position.rgb, transport_light0_scalar.r),
                transport_mix
            );
            vec4 sc_light1_data = mix(
                u_sc_light1_data,
                vec4(transport_light1_position.rgb, transport_light1_scalar.r),
                transport_mix
            );
            vec4 sc_light2_data = mix(
                u_sc_light2_data,
                vec4(transport_light2_position.rgb, transport_light2_scalar.r),
                transport_mix
            );
            vec4 sc_light3_data = mix(
                u_sc_light3_data,
                vec4(transport_light3_position.rgb, transport_light3_scalar.r),
                transport_mix
            );
            vec4 sc_light0_color = mix(
                u_sc_light0_color,
                vec4(transport_light0_color_sample.rgb * u_sc_chroma_range, transport_light0_scalar.g),
                transport_mix
            );
            vec4 sc_light1_color = mix(
                u_sc_light1_color,
                vec4(transport_light1_color_sample.rgb * u_sc_chroma_range, transport_light1_scalar.g),
                transport_mix
            );
            vec4 sc_light2_color = mix(
                u_sc_light2_color,
                vec4(transport_light2_color_sample.rgb * u_sc_chroma_range, transport_light2_scalar.g),
                transport_mix
            );
            vec4 sc_light3_color = mix(
                u_sc_light3_color,
                vec4(transport_light3_color_sample.rgb * u_sc_chroma_range, transport_light3_scalar.g),
                transport_mix
            );
            vec2 sc_light0_extra = mix(
                u_sc_light0_extra,
                vec2(transport_light0_scalar.b, step(0.001, transport_light0_scalar.r)),
                transport_mix
            );
            vec2 sc_light1_extra = mix(
                u_sc_light1_extra,
                vec2(transport_light1_scalar.b, step(0.001, transport_light1_scalar.r)),
                transport_mix
            );
            vec2 sc_light2_extra = mix(
                u_sc_light2_extra,
                vec2(transport_light2_scalar.b, step(0.001, transport_light2_scalar.r)),
                transport_mix
            );
            vec2 sc_light3_extra = mix(
                u_sc_light3_extra,
                vec2(transport_light3_scalar.b, step(0.001, transport_light3_scalar.r)),
                transport_mix
            );
            vec4 light0 = scenelight_light_vector_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0, light_direction
            );
            vec4 light1 = scenelight_light_vector_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 0.82, light_direction
            );
            vec4 light2 = scenelight_light_vector_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 0.82, light_direction
            );
            vec4 light3 = scenelight_light_vector_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 0.82, light_direction
            );
            // CPU parity: spatial falloff belongs only in the transported
            // numerator. Dividing by a spatially varying denominator cancels
            // the local bright/dark response and reduces the result to a
            // scene-colored wash.
            float base_light_weight0 = scenelight_light_base_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0
            );
            float base_light_weight1 = scenelight_light_base_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 0.82
            );
            float base_light_weight2 = scenelight_light_base_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 0.82
            );
            float base_light_weight3 = scenelight_light_base_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 0.82
            );
            float total_light_weight = max(
                base_light_weight0 + base_light_weight1 + base_light_weight2 + base_light_weight3,
                0.0001
            );
            vec3 center_light_vector0 = scenelight_center_light_vector(sc_light0_data, light_direction);
            vec3 center_light_vector1 = scenelight_center_light_vector(sc_light1_data, light_direction);
            vec3 center_light_vector2 = scenelight_center_light_vector(sc_light2_data, light_direction);
            vec3 center_light_vector3 = scenelight_center_light_vector(sc_light3_data, light_direction);
            vec2 primary_ray_direction = normalize(sc_light0_data.xy - v_sc_center + vec2(0.00001));
            float primary_ray_elevation = normalize(vec3(
                primary_ray_direction,
                0.72 + sc_light0_data.z * 0.65
            )).z;
            float ray_shadow = 0.0;
            if (sc_light0_extra.y > 0.5 && u_sc_calibration2.x > 0.0001) {
                ray_shadow = scenelight_ray_shadow(
                    primary_ray_direction,
                    primary_ray_elevation,
                    sprite_texel,
                    alpha,
                    v_tex_coord,
                    res0,
                    tex0,
                    u_lod_bias
                );
            }
            vec2 secondary_ray_direction = normalize(sc_light1_data.xy - v_sc_center + vec2(0.00001));
            float secondary_ray_elevation = normalize(vec3(
                secondary_ray_direction,
                0.72 + sc_light1_data.z * 0.65
            )).z;
            float secondary_ray_shadow = 0.0;
            if (sc_light1_extra.y > 0.5 && u_sc_calibration2.x > 0.0001) {
                secondary_ray_shadow = scenelight_ray_shadow(
                    secondary_ray_direction,
                    secondary_ray_elevation,
                    sprite_texel,
                    alpha,
                    v_tex_coord,
                    res0,
                    tex0,
                    u_lod_bias
                );
            }

            float lambert0 = scenelight_filtered_lambert(light0.xyz, normal, normal1, normal2, normal3, normal4) * (1.0 - ray_shadow * 0.58);
            float lambert1 = scenelight_filtered_lambert(light1.xyz, normal, normal1, normal2, normal3, normal4) * (1.0 - secondary_ray_shadow * 0.58);
            float lambert2 = scenelight_filtered_lambert(light2.xyz, normal, normal1, normal2, normal3, normal4);
            float lambert3 = scenelight_filtered_lambert(light3.xyz, normal, normal1, normal2, normal3, normal4);
            float lambert = clamp(
                (lambert0 * light0.w + lambert1 * light1.w + lambert2 * light2.w + lambert3 * light3.w)
                    / total_light_weight,
                0.0,
                1.0
            );
            // A generated pseudo-normal cannot distinguish real relief from
            // a flat painted boundary between expression/hair layers. Use
            // nearby source structure as receiver confidence before that
            // normal can drive a narrow specular response. Diffuse form stays
            // on its established path; the gate only prevents false glossy
            // bands across smooth paint. Sprites without exact form maps remain
            // unchanged as well.
            float form_detail_left = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord - vec2(sprite_texel.x * 2.0, 0.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_right = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord + vec2(sprite_texel.x * 2.0, 0.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_up = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord - vec2(0.0, sprite_texel.y * 2.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_down = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord + vec2(0.0, sprite_texel.y * 2.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_span = abs(form_detail_left - form_detail_right)
                + abs(form_detail_up - form_detail_down);
            float form_detail_visibility = mix(
                1.0,
                smoothstep(0.018, 0.110, form_detail_span),
                step(0.5, u_sc_has_form)
            );
            vec3 source_color_field = (
                lambert0 * light0.w * sc_light0_color.rgb
                + lambert1 * light1.w * sc_light1_color.rgb
                + lambert2 * light2.w * sc_light2_color.rgb
                + lambert3 * light3.w * sc_light3_color.rgb
            ) / total_light_weight;
            float sc_creative_weight0 = scenelight_creative_light_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0
            );
            float sc_creative_weight1 = scenelight_creative_light_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 1.0
            );
            float sc_creative_weight2 = scenelight_creative_light_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 1.0
            );
            float sc_creative_weight3 = scenelight_creative_light_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 1.0
            );
            vec3 primary_light_vector = light0.xyz;

            vec4 form_aux = texture2D(tex4, clamp(v_tex_coord, vec2(0.0), vec2(1.0)));
            float surface_ao = mix(0.0, form_aux.g, step(0.5, u_sc_has_form));
            float target_mid = transported_target_mid
                + sc_height_dependency
                + dot(sc_screen_dependency, vec2(1.0))
                + dot(sc_transport_dependency, vec4(1.0));
            float scene_exposure = clamp((target_mid + 0.035) / (u_sc_reference_mid + 0.035), 0.18, 2.15);
            float auto_amount = u_sc_calibration0.x * u_sc_strength;
            // A Ren'Py matrixcolor outside this displayable is authored final
            // grading, not unlit material. Keep generated form and direction,
            // but do not meter the same scene exposure through that grade a
            // second time. Ordinary sprites remain bit-for-bit on the original
            // path because their authored-grade value is zero.
            float sc_authored_grade = clamp(u_sc_authored_grade, 0.0, 1.0)
                * step(0.0001, u_sc_strength);
            float sc_environment_adaptation = 1.0 - sc_authored_grade;
            float exposure = pow(scene_exposure, auto_amount * sc_environment_adaptation)
                * exp2(u_sc_calibration0.y * u_sc_strength);
            float confidence = 0.34 + 0.66 * mix(u_sc_light_confidence, sc_light0_color.a, transport_mix);
            float key_amount = u_sc_calibration1.w * confidence * u_sc_strength;
            // High-key broad illumination in a photograph has normally
            // already undergone camera white balance. Classify that condition
            // from scene transport only; character identity, palette, skin,
            // filenames, and background names never enter the gate.
            float sc_broad_radius = mix(u_sc_source_size, sc_light0_data.z, transport_mix);
            float sc_primary_confidence = mix(
                u_sc_light_confidence, sc_light0_color.a, transport_mix
            );
            float sc_primary_emission = mix(0.0, sc_light0_extra.x, transport_mix);
            float sc_high_key = smoothstep(0.30, 0.46, local_luminance);
            float sc_broad = smoothstep(0.62, 0.90, sc_broad_radius);
            float sc_uncertain = 1.0 - smoothstep(0.34, 0.60, sc_primary_confidence);
            float sc_diffuse = 1.0 - smoothstep(0.12, 0.35, sc_primary_emission);
            float sc_chroma_guard = clamp(
                sc_high_key * sc_broad * sc_uncertain * sc_diffuse,
                0.0,
                1.0
            );

            // Match the standalone renderer's energy-balanced form model.
            // Near-black fur, line art, and cloth retain a deliberately
            // shallower generated response. Normalize around the expected
            // broad-surface response so a complex silhouette cannot become
            // globally brighter merely because it has more reconstructed
            // normals facing the light.
            float diffuse_span = 0.22 + key_amount * 0.31;
            float form_light = 0.73 + lambert * diffuse_span;
            vec2 average_light_direction = normalize(
                center_light_vector0.xy * base_light_weight0
                    + center_light_vector1.xy * base_light_weight1
                    + center_light_vector2.xy * base_light_weight2
                    + center_light_vector3.xy * base_light_weight3
                    + vec2(0.00001)
            );
            float broad_weight = (
                base_light_weight0 * (1.0 - sc_light0_extra.x)
                + base_light_weight1 * (1.0 - sc_light1_extra.x)
                + base_light_weight2 * (1.0 - sc_light2_extra.x)
                + base_light_weight3 * (1.0 - sc_light3_extra.x)
            ) / total_light_weight;
            vec2 relative_form_position = v_tex_coord - u_sc_form_center;
            float directional = clamp(
                0.5 + dot(relative_form_position, average_light_direction) * 0.9,
                0.0,
                1.0
            );
            form_light *= 1.0 + (directional - 0.5) * 0.32 * key_amount * broad_weight;
            vec3 response0 = texture2D(tex5, clamp(center_light_vector0.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response1 = texture2D(tex5, clamp(center_light_vector1.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response2 = texture2D(tex5, clamp(center_light_vector2.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response3 = texture2D(tex5, clamp(center_light_vector3.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response = (
                response0 * base_light_weight0
                    + response1 * base_light_weight1
                    + response2 * base_light_weight2
                    + response3 * base_light_weight3
            ) / total_light_weight;
            float expected_lambert = mix(0.72, response.r, step(0.5, u_sc_has_form));
            float expected_form = 0.73 + expected_lambert * diffuse_span;
            form_light /= max(expected_form, 0.001);
            float form_visibility = 0.38 + 0.62 * material_response;
            form_light = 1.0 + (form_light - 1.0) * form_visibility;
            if (u_sc_has_form > 0.5) {
                float mean_after_visibility = 1.0
                    + (0.73 * u_sc_mean_form_visibility + diffuse_span * response.g)
                        / max(expected_form, 0.001)
                    - u_sc_mean_form_visibility;
                form_light /= max(mean_after_visibility, 0.001);
            }
            form_light = mix(1.0, clamp(form_light, 0.72, 1.32), u_sc_strength);
            float occlusion = clamp(
                surface_ao * u_sc_calibration2.y * u_sc_strength
                + ray_shadow * 0.18 * u_sc_calibration2.x * u_sc_strength,
                0.0,
                0.72
            );
            occlusion *= 0.36 + 0.64 * material_response;

            vec3 ambient_tint = pow(
                clamp(ambient_chroma, vec3(0.55), vec3(1.9)),
                vec3(u_sc_calibration0.w * auto_amount * sc_environment_adaptation)
            );
            float sc_scene_chroma_span = max(
                ambient_chroma.r,
                max(ambient_chroma.g, ambient_chroma.b)
            ) - min(
                ambient_chroma.r,
                min(ambient_chroma.g, ambient_chroma.b)
            );
            float sc_extreme_scene_chroma = smoothstep(
                0.55,
                1.15,
                sc_scene_chroma_span
            );
            // Only genuinely extreme environment chroma is compressed. Typical
            // daylight/classroom transport stays exactly on the original path;
            // this is an energy guard for backgrounds whose baked grade is too
            // saturated to represent incident light literally.
            ambient_tint = pow(
                ambient_tint,
                vec3(mix(1.0, 0.25, sc_extreme_scene_chroma))
            );
            float source_mix = clamp((lambert - 0.52) * 0.34 * key_amount, 0.0, 0.32);
            vec3 source_tint = mix(
                vec3(1.0),
                clamp(source_color_field, vec3(0.58), vec3(2.0)),
                source_mix
            );
            source_tint = mix(vec3(1.0), source_tint, sc_environment_adaptation);
            // The photographed, energy-balanced aggregate remains the normal
            // path. Automatic separation engages for two distinct hue-family
            // sources, or for one strong colored source separated from a
            // neutral physical key. The manual control can still force the
            // effect for intentionally stylized work.
            float sc_separation_evidence = max(
                scenelight_separation_pair_evidence(
                    sc_light1_data, sc_light1_color, sc_light1_extra,
                    sc_light2_data, sc_light2_color, sc_light2_extra
                ),
                max(
                    scenelight_separation_pair_evidence(
                        sc_light1_data, sc_light1_color, sc_light1_extra,
                        sc_light3_data, sc_light3_color, sc_light3_extra
                    ),
                    scenelight_separation_pair_evidence(
                        sc_light2_data, sc_light2_color, sc_light2_extra,
                        sc_light3_data, sc_light3_color, sc_light3_extra
                    )
                )
            );
            sc_separation_evidence = max(
                sc_separation_evidence,
                max(
                    scenelight_primary_creative_evidence(
                        sc_light0_data, sc_light0_color,
                        sc_light1_data, sc_light1_color, sc_light1_extra
                    ),
                    max(
                        scenelight_primary_creative_evidence(
                            sc_light0_data, sc_light0_color,
                            sc_light2_data, sc_light2_color, sc_light2_extra
                        ),
                        scenelight_primary_creative_evidence(
                            sc_light0_data, sc_light0_color,
                            sc_light3_data, sc_light3_color, sc_light3_extra
                        )
                    )
                )
            );
            float sc_adaptive_light_colors = u_sc_calibration4.z
                * smoothstep(0.03, 0.28, sc_separation_evidence);
            float sc_individual_light_colors = clamp(
                max(u_sc_calibration4.y, sc_adaptive_light_colors) * u_sc_strength,
                0.0,
                2.0
            );
            if (sc_individual_light_colors > 0.0001) {
                // Creative mode gives every detected hue family equal artistic
                // standing, then separates their directional lobes. Realistic
                // mode above remains energy-weighted and fully additive.
                float sc_creative_power = 2.0
                    + 3.0 * sc_individual_light_colors;
                float sc_creative_spread = clamp(
                    sc_individual_light_colors * 0.42,
                    0.0,
                    0.84
                );
                vec2 sc_creative_direction0 = normalize(light0.xy);
                vec2 sc_creative_direction1 = normalize(light1.xy);
                vec2 sc_creative_direction2 = normalize(light2.xy);
                vec2 sc_creative_direction3 = normalize(light3.xy);
                // A flat sprite's reconstructed normals can all lean toward
                // the viewer.  Creative separation therefore also uses the
                // pixel's direction across the character silhouette, giving
                // distinct lamps distinct regions to paint.
                vec2 sc_form_direction = relative_form_position
                    / max(length(relative_form_position), 0.08);
                vec2 sc_creative_surface = normalize(
                    normal.xy + sc_form_direction * sc_creative_spread * 1.35
                );
                float sc_creative_lobe0 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction0), 0.035, 1.0
                );
                float sc_creative_lobe1 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction1), 0.035, 1.0
                );
                float sc_creative_lobe2 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction2), 0.035, 1.0
                );
                float sc_creative_lobe3 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction3), 0.035, 1.0
                );
                float sc_creative_influence0 = pow(
                    mix(max(lambert0, 0.035), sc_creative_lobe0, sc_creative_spread)
                        * sc_creative_weight0,
                    sc_creative_power
                );
                float sc_creative_influence1 = pow(
                    mix(max(lambert1, 0.035), sc_creative_lobe1, sc_creative_spread)
                        * sc_creative_weight1,
                    sc_creative_power
                );
                float sc_creative_influence2 = pow(
                    mix(max(lambert2, 0.035), sc_creative_lobe2, sc_creative_spread)
                        * sc_creative_weight2,
                    sc_creative_power
                );
                float sc_creative_influence3 = pow(
                    mix(max(lambert3, 0.035), sc_creative_lobe3, sc_creative_spread)
                        * sc_creative_weight3,
                    sc_creative_power
                );
                // When hue-family sources are available, they are the
                // separated artistic lights.  Do not count the already-fused
                // physical key a second time or warm scenes collapse back to
                // a single orange tint.
                float sc_creative_source_count =
                    (1.0 - step(0.001, sc_light1_data.w))
                        * step(0.001, sc_light1_extra.x)
                    + (1.0 - step(0.001, sc_light2_data.w))
                        * step(0.001, sc_light2_extra.x)
                    + (1.0 - step(0.001, sc_light3_data.w))
                        * step(0.001, sc_light3_extra.x);
                // With one colored source, retain the neutral aggregate in
                // this mix so the two sources paint different body regions.
                // With multiple hue families, omit the already-fused primary
                // exactly as before.
                float sc_multiple_creative_sources = step(
                    1.5,
                    sc_creative_source_count
                );
                sc_creative_influence0 *= 1.0 - sc_multiple_creative_sources;
                float sc_creative_total = max(
                    sc_creative_influence0 + sc_creative_influence1
                        + sc_creative_influence2 + sc_creative_influence3,
                    0.001
                );
                vec3 sc_separated_source_chroma = scenelight_unit_energy(
                    (
                        sc_creative_influence0 * sc_light0_color.rgb
                        + sc_creative_influence1 * sc_light1_color.rgb
                        + sc_creative_influence2 * sc_light2_color.rgb
                        + sc_creative_influence3 * sc_light3_color.rgb
                    ) / sc_creative_total
                );
                float sc_separated_source_mix = clamp(
                    sc_individual_light_colors * key_amount * (0.42 + 0.48 * lambert),
                    0.0,
                    0.95
                );
                source_tint = mix(
                    source_tint,
                    clamp(sc_separated_source_chroma, vec3(0.34), vec3(2.85)),
                    sc_separated_source_mix
                );
            }
            vec3 lit = base * exposure * u_sc_calibration0.z
                * ambient_tint * source_tint * form_light * (1.0 - occlusion);

            // Colored shadow transport is independent from source tint. It
            // keeps the unlit side anchored to the measured environment
            // instead of multiplying the entire character by one scene hue.
            float shadow_mix = clamp((0.78 - lambert) * 0.56 * key_amount, 0.0, 0.52);
            shadow_mix *= 0.34 + 0.66 * material_response;
            shadow_mix *= u_sc_calibration4.x / 0.62;
            vec3 sc_shadow_tint = mix(
                vec3(1.0),
                clamp(shadow_chroma, vec3(0.55), vec3(1.75)),
                sc_environment_adaptation
            );
            lit *= mix(vec3(1.0), sc_shadow_tint, shadow_mix);

            // The exact eight directional probes measured by the CPU scene
            // analysis are cheap uniforms; no four-sample background-color
            // approximation is needed on the GPU.
            vec3 probe_rgb = vec3(0.0);
            float probe_weight = 0.0;
            vec3 ground_rgb = vec3(0.0);
            float ground_energy = 0.0;
            float probe_local_reference = local_luminance + 0.025;
            vec4 transport_probe0 = scenelight_transport_at(15.0, v_sc_center);
            vec4 transport_probe1 = scenelight_transport_at(16.0, v_sc_center);
            vec4 transport_probe2 = scenelight_transport_at(17.0, v_sc_center);
            vec4 transport_probe3 = scenelight_transport_at(18.0, v_sc_center);
            vec4 transport_probe4 = scenelight_transport_at(19.0, v_sc_center);
            vec4 transport_probe5 = scenelight_transport_at(20.0, v_sc_center);
            vec4 transport_probe6 = scenelight_transport_at(21.0, v_sc_center);
            vec4 transport_probe7 = scenelight_transport_at(22.0, v_sc_center);
            vec3 transport_probe_scalar0 = scenelight_transport_at(23.0, v_sc_center).rgb;
            vec3 transport_probe_scalar1 = scenelight_transport_at(24.0, v_sc_center).rgb;
            vec3 transport_probe_scalar2 = scenelight_transport_at(25.0, v_sc_center).rgb;
            scenelight_accumulate_probe(
                mix(u_sc_probe0_data, vec4(-1.0, 0.0, transport_probe_scalar0.r, 1.0), transport_mix),
                mix(u_sc_probe0_color, transport_probe0.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe1_data, vec4(-0.7071, -0.7071, transport_probe_scalar0.g, 1.0), transport_mix),
                mix(u_sc_probe1_color, transport_probe1.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe2_data, vec4(0.0, -1.0, transport_probe_scalar0.b, 1.0), transport_mix),
                mix(u_sc_probe2_color, transport_probe2.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe3_data, vec4(0.7071, -0.7071, transport_probe_scalar1.r, 1.0), transport_mix),
                mix(u_sc_probe3_color, transport_probe3.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe4_data, vec4(1.0, 0.0, transport_probe_scalar1.g, 1.0), transport_mix),
                mix(u_sc_probe4_color, transport_probe4.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe5_data, vec4(0.7071, 0.7071, transport_probe_scalar1.b, 1.0), transport_mix),
                mix(u_sc_probe5_color, transport_probe5.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe6_data, vec4(0.0, 1.0, transport_probe_scalar2.r, 1.0), transport_mix),
                mix(u_sc_probe6_color, transport_probe6.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe7_data, vec4(-0.7071, 0.7071, transport_probe_scalar2.g, 1.0), transport_mix),
                mix(u_sc_probe7_color, transport_probe7.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            vec3 probe_tint = probe_rgb / max(probe_weight, 0.001);
            probe_tint = scenelight_unit_energy(probe_tint);
            probe_tint = mix(vec3(1.0), probe_tint, sc_environment_adaptation);
            float probe_mix = clamp(u_sc_calibration2.z * 0.16 * (probe_weight / 4.0), 0.0, 0.22) * u_sc_strength;
            lit *= mix(vec3(1.0), clamp(probe_tint, vec3(0.58), vec3(1.9)), probe_mix);

            // Low-frequency color below the final screen position provides a
            // restrained ground/floor bounce, strongest on the lower body.
            float lower_body = clamp((relative_form_position.y + 0.30) * 1.45, 0.0, 1.0);
            float downward_facing = clamp(normal.y * 0.70 + (1.0 - normal.z) * 0.22, 0.0, 1.0);
            float bounce = (0.24 * lower_body + 0.76 * downward_facing)
                * u_sc_calibration2.w * 0.16 * u_sc_strength;
            vec3 ground_chroma = clamp(ground_rgb / max(ground_energy, 0.001), vec3(0.52), vec3(2.2));
            ground_chroma = mix(vec3(1.0), ground_chroma, sc_environment_adaptation);
            lit += base * exposure * ground_chroma * bounce;

            float saturation = max(base_srgb.r, max(base_srgb.g, base_srgb.b)) - min(base_srgb.r, min(base_srgb.g, base_srgb.b));
            vec3 half0 = normalize(center_light_vector0 + vec3(0.0, 0.0, 1.0));
            vec3 half1 = normalize(center_light_vector1 + vec3(0.0, 0.0, 1.0));
            vec3 half2 = normalize(center_light_vector2 + vec3(0.0, 0.0, 1.0));
            vec3 half3 = normalize(center_light_vector3 + vec3(0.0, 0.0, 1.0));
            float specular_power = 22.0 + sc_live_sharpness * 34.0;
            vec3 specular_field = (
                pow(max(dot(normal, half0), 0.0), specular_power) * (1.0 - ray_shadow * u_sc_calibration2.x) * light0.w * sc_light0_color.rgb
                + pow(max(dot(normal, half1), 0.0), specular_power) * (1.0 - secondary_ray_shadow * u_sc_calibration2.x) * light1.w * sc_light1_color.rgb
                + pow(max(dot(normal, half2), 0.0), specular_power) * light2.w * sc_light2_color.rgb
                + pow(max(dot(normal, half3), 0.0), specular_power) * light3.w * sc_light3_color.rgb
            ) / total_light_weight;
            float dielectric = clamp(0.18 + (1.0 - saturation) * 0.82, 0.18, 1.0);
            float specular_material = dielectric * (0.14 + 0.86 * material_response);
            float sc_specular_luma = dot(specular_field, vec3(0.2126, 0.7152, 0.0722));
            specular_field = mix(
                vec3(sc_specular_luma),
                specular_field,
                sc_environment_adaptation
            );
            // Reconstructed normals can contain broad mathematical ridges on
            // otherwise flat painted regions. They remain useful for diffuse
            // form, but may create a sharp fake specular band unless the source
            // art has nearby structure capable of receiving that highlight.
            lit += specular_field * specular_material * u_sc_calibration3.x * 0.13
                * form_detail_visibility * u_sc_strength;

            float fallback_edge = max(
                alpha - texture2D(
                    tex0,
                    clamp(v_tex_coord + light_direction * sprite_texel * 3.5, vec2(0.0), vec2(1.0)),
                    u_lod_bias
                ).a,
                0.0
            );
            float form_edge = mix(
                fallback_edge,
                texture2D(tex3, clamp(v_tex_coord, vec2(0.0), vec2(1.0))).b,
                step(0.5, u_sc_has_form)
            );
            float rim_facing = pow(max(dot(normal.xy, primary_light_vector.xy), 0.0), 0.7);
            float rim = form_edge * rim_facing * u_sc_calibration3.y * confidence * u_sc_strength;
            rim *= 0.12 + 0.88 * material_response;
            rim *= 0.42 + 0.58 * (1.0 - mix(u_sc_source_size, sc_light0_data.z, transport_mix));
            vec3 sc_rim_chroma = mix(
                vec3(1.0),
                clamp(sc_light0_color.rgb, vec3(0.55), vec3(2.2)),
                sc_environment_adaptation
            );
            lit += sc_rim_chroma * rim * 0.52;

            // In creative mode, secondary lights also receive a colored edge
            // response instead of being compressed into the primary rim. The
            // chroma is normalized before addition so saturated lamp colors do
            // not create an accidental exposure increase.
            if (sc_individual_light_colors > 0.0001) {
                float sc_rim_facing0 = rim_facing;
                float sc_rim_facing1 = pow(max(dot(normal.xy, light1.xy), 0.0), 0.7);
                float sc_rim_facing2 = pow(max(dot(normal.xy, light2.xy), 0.0), 0.7);
                float sc_rim_facing3 = pow(max(dot(normal.xy, light3.xy), 0.0), 0.7);
                float sc_multi_rim_weight = (
                    sc_rim_facing0 * sc_creative_weight0
                    + sc_rim_facing1 * sc_creative_weight1
                    + sc_rim_facing2 * sc_creative_weight2
                    + sc_rim_facing3 * sc_creative_weight3
                );
                vec3 sc_multi_rim_color = scenelight_unit_energy(
                    (
                        sc_rim_facing0 * sc_creative_weight0 * sc_light0_color.rgb
                        + sc_rim_facing1 * sc_creative_weight1 * sc_light1_color.rgb
                        + sc_rim_facing2 * sc_creative_weight2 * sc_light2_color.rgb
                        + sc_rim_facing3 * sc_creative_weight3 * sc_light3_color.rgb
                    ) / max(sc_multi_rim_weight, 0.001)
                );
                float sc_multi_rim = form_edge
                    * clamp(sc_multi_rim_weight / total_light_weight, 0.0, 1.0)
                    * u_sc_calibration3.y * confidence
                    * (0.12 + 0.88 * material_response)
                    * sc_individual_light_colors;
                lit += clamp(sc_multi_rim_color, vec3(0.34), vec3(2.85))
                    * sc_multi_rim * 0.24;
            }

            // Exact desktop environment wrap: only the distance-field edge
            // and semitransparent pixels receive the low-frequency scene
            // color. Interior paint is never replaced by the pixel directly
            // behind the character.
            vec3 environment_wrap = scenelight_srgb_to_linear(
                scenelight_wrap_at(v_sc_screen)
            );
            float sc_wrap_luma = dot(environment_wrap, vec3(0.2126, 0.7152, 0.0722));
            environment_wrap = mix(
                vec3(sc_wrap_luma),
                environment_wrap,
                sc_environment_adaptation
            );
            float opaque_wrap = 0.12 + 0.88 * material_response;
            float wrap_weight = 0.25 * alpha * opaque_wrap + (1.0 - alpha);
            float wrap = clamp(form_edge * wrap_weight * u_sc_calibration3.z * u_sc_strength, 0.0, 0.64);
            lit = mix(lit, environment_wrap, wrap);

            // Preserve authored reflectance chroma on bright, nearly neutral
            // paint under the broad-diffuse camera condition above. The target
            // is normalized to the current generated luminance, so exposure,
            // normals, AO, self-shadow, rim, and motion remain unchanged.
            float sc_neutral_material = 1.0 - smoothstep(0.16, 0.36, saturation);
            float sc_bright_material = smoothstep(0.10, 0.38, base_luma);
            float sc_chroma_preservation = u_sc_calibration0.w
                * sc_chroma_guard
                * sc_neutral_material
                * sc_bright_material
                * auto_amount;
            float sc_preserved_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            vec3 sc_source_chroma = clamp(
                base / max(base_luma, 0.001),
                vec3(0.55),
                vec3(1.80)
            );
            lit = mix(
                lit,
                sc_preserved_luma * sc_source_chroma,
                sc_chroma_preservation
            );

            // Match the CPU contrast stage around a palette-derived pivot.
            // This pivot changes only the contrast curve, never exposure.
            float precontrast_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            float desired_contrast = clamp(0.84 + local_contrast * 0.35, 0.76, 1.24);
            float contrast_power = 1.0 + (
                (desired_contrast - 1.0) * u_sc_calibration1.x
                    * auto_amount * sc_environment_adaptation * u_sc_debug_contrast
            );
            float contrast_mid = max(u_sc_form_contrast_mid * exposure, 0.006);
            float contrast_ratio = pow(
                (precontrast_luma + 0.018) / (contrast_mid + 0.018),
                contrast_power - 1.0
            );
            lit *= clamp(contrast_ratio, 0.55, 1.70);

            // Scene saturation matching stays in linear light and never uses
            // the sprite's global palette as an exposure meter.
            float lit_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            vec3 lit_gray = vec3(lit_luma);
            float target_sat_scale = clamp(0.72 + local_saturation * 1.05, 0.68, 1.30);
            float sat_scale = 1.0 + (target_sat_scale - 1.0)
                * u_sc_calibration1.y * auto_amount * sc_environment_adaptation;
            lit = lit_gray + (lit - lit_gray) * sat_scale;

            // Match the desktop filmic shoulder exactly. It is applied after
            // contrast and saturation, without re-injecting the source art.
            float generated_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            float shoulder_excess = max(generated_luma - 0.46, 0.0);
            float shoulder_luma = 0.46 + shoulder_excess / (
                1.0 + shoulder_excess * (1.7 * u_sc_calibration1.z)
            );
            lit *= shoulder_luma / max(generated_luma, shoulder_luma);
            float peak = max(lit.r, max(lit.g, lit.b));
            float peak_excess = max(peak - 0.82, 0.0);
            float compressed_peak = 0.82 + peak_excess / (1.0 + peak_excess / 0.18);
            float gamut_strength = clamp(u_sc_calibration1.z / 1.2, 0.0, 1.0);
            lit *= mix(
                1.0,
                compressed_peak / max(peak, compressed_peak),
                step(0.82, peak) * gamut_strength
            );

            // Optional effects are applied only after the approved physical
            // relighting result exists. Each branch is a strict identity when
            // its intensity is zero, preserving exact disabled parity.
            if (u_sc_rain_data.x > 0.0001 && alpha > 0.001) {
                float rain_intensity = u_sc_rain_data.x;
                float wetness = u_sc_rain_data.y;
                float rain_time = u_sc_effect_time * u_sc_rain_data.w;
                float streak = scenelight_fx_rain_streak(
                    v_tex_coord,
                    rain_time,
                    u_sc_rain_data.z,
                    u_sc_rain_color_scale.w
                );
                float upward_facing = clamp(normal.z * 0.72 - normal.y * 0.28, 0.0, 1.0);
                float wet_mask = clamp(
                    wetness * rain_intensity * (0.28 + 0.72 * upward_facing),
                    0.0,
                    1.0
                );
                lit *= 1.0 - wet_mask * 0.105;
                vec3 rain_color = scenelight_srgb_to_linear(u_sc_rain_color_scale.rgb);
                float wet_specular = pow(
                    max(dot(normal, normalize(primary_light_vector)), 0.0),
                    18.0
                );
                lit += rain_color * wet_specular * wet_mask * 0.34;
                lit += rain_color * streak * rain_intensity * (0.18 + 0.34 * form_edge);
            }

            if (sc_glitch_intensity > 0.0001 && alpha > 0.001) {
                float sc_line = 0.5 + 0.5 * sin(
                    (v_sc_screen.y * max(res0.y, 1.0) + u_sc_effect_time * 37.0) * 3.14159265359
                );
                lit *= 1.0 - u_sc_glitch_extra.y * sc_glitch_intensity * sc_line * 0.12;
                float sc_block = scenelight_fx_hash(
                    floor(v_tex_coord * vec2(24.0, 36.0) / max(u_sc_glitch_data.z, 0.25))
                    + floor(u_sc_effect_time * u_sc_glitch_data.w * 12.0)
                    + u_sc_glitch_extra.w
                );
                float sc_corrupt = step(0.90 - 0.25 * sc_glitch_intensity, sc_block);
                vec3 sc_luma = vec3(dot(lit, vec3(0.2126, 0.7152, 0.0722)));
                lit = mix(lit, sc_luma.bgr * vec3(0.82, 1.14, 1.28), sc_corrupt * 0.36);
                float sc_fragment = step(
                    u_sc_glitch_extra.z * sc_glitch_intensity * 0.24,
                    scenelight_fx_hash(
                        floor(v_tex_coord * vec2(160.0, 96.0))
                        + floor(u_sc_effect_time * 20.0)
                    )
                );
                alpha *= sc_fragment;
            }

            if (u_sc_has_form > 0.5 && sc_live_grain > 0.015) {
                float form_noise = (form_aux.b * 2.0 - 1.0) * u_sc_noise_range;
                float post_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
                float grain_weight = clamp(1.0 - abs(post_luma - 0.35) * 1.8, 0.24, 1.0);
                lit += vec3(
                    form_noise * sc_live_grain * u_sc_calibration3.w * 0.018 * grain_weight
                );
            }

                vec3 output_srgb = scenelight_linear_to_srgb(clamp(lit, 0.0, 1.0));
                float original_view = step(0.5, u_sc_compare_mode)
                    * (1.0 - step(1.5, u_sc_compare_mode));
                original_view += step(1.5, u_sc_compare_mode)
                    * (1.0 - step(0.5, v_tex_coord.x));
                output_srgb = mix(output_srgb, base_srgb, original_view);
                float output_alpha = mix(alpha, source.a, original_view);
                gl_FragColor = vec4(output_srgb * output_alpha, output_alpha);
            } else {
                // A subtle light-directed contact shadow lives inside the
                // transparent 960x960 sprite canvas and moves with the model.
                vec2 shadow_center = vec2(0.5, 0.925) - light_direction * vec2(0.030, 0.012);
                vec2 shadow_delta = (v_tex_coord - shadow_center) / vec2(0.145, 0.018);
                float contact = exp(-dot(shadow_delta, shadow_delta) * 2.2);
                contact *= 0.20 * (u_sc_calibration4.x / 0.62)
                    * u_sc_strength * smoothstep(0.0, 0.25, emitter_sample.a);
                float original_view = step(0.5, u_sc_compare_mode)
                    * (1.0 - step(1.5, u_sc_compare_mode));
                original_view += step(1.5, u_sc_compare_mode)
                    * (1.0 - step(0.5, v_tex_coord.x));
                contact *= 1.0 - original_view;
                gl_FragColor = vec4(vec3(0.018) * contact, contact);
            }
        """)

    if _SCENELIGHT_SHADER_AVAILABLE:
        renpy.register_shader(
            "scenelight.dynamic_sprite",
            variables=_scenelight_shader_variables,
            vertex_150=_scenelight_shader_vertex_150,
            fragment_functions=_scenelight_shader_fragment_functions,
            fragment_350=_scenelight_shader_fragment_350,
        )

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
            self.form_entry = _scenelight_resolve_form_entry(
                self.form_key,
                self.base_form_key,
            )
            self.has_form = self.form_entry is not None
            form_assets = self.form_entry if self.has_form else SCENELIGHT_FORM_FALLBACK
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
            self.irradiance = _scenelight_texture(SCENELIGHT_ATLAS["irradiance"])
            self.emitter = _scenelight_texture(SCENELIGHT_ATLAS["emitter"])
            self.form_normal_noise = _scenelight_texture(form_assets["normal_noise"])
            self.form_height_ao_edge = _scenelight_texture(form_assets["height_ao_edge"])
            self.form_response = _scenelight_texture(form_assets["response"])
            self.wrap_atlas = _scenelight_texture(
                SCENELIGHT_ATLAS.get("wrap", SCENELIGHT_ATLAS["irradiance"])
            )
            self.transport_atlas = _scenelight_texture(
                SCENELIGHT_TRANSPORT_ATLAS.get("texture", SCENELIGHT_ATLAS["irradiance"])
            )

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
            # scene router has already wrapped it; otherwise retain this tag.
            if isinstance(child, SceneLightSprite):
                return child
            rv = self._copy()
            rv.child = child
            return rv

        def _live_scene(self):
            return _scenelight_live_scene()

        def _live_scene_entry(self):
            return _scenelight_live_scene_entry()

        def _live_lighting_state(self):
            """Resolve a complete state even before this displayable's first frame."""
            scene_key, scene = self._live_scene_entry()
            if scene is not None:
                controls = _scenelight_control_snapshot(
                    scene_key,
                    self.image_name[0],
                    self.form_key,
                )
            else:
                controls = {"enabled": True, "strength": 1.0, "calibration": {}}
            enabled = bool(getattr(persistent, "scenelight_enabled", True)) and bool(
                controls["enabled"]
            )
            authored_strength = (
                float(controls["strength"])
                if controls.get("strength_override")
                else SCENELIGHT_PROFILE_STRENGTH
            )
            strength = float(
                getattr(persistent, "scenelight_strength", 1.0)
            ) * authored_strength
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
            rv._sc_frozen_screen_rect = self._scenelight_screen_rect()
            rv._sc_transition_screen_rect = None
            return rv

        def render(self, width, height, st, at):
            child_render = renpy.render(self.child, width, height, st, at)

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
            if not scene:
                return _scenelight_custom_effect_render(
                    child_render,
                    active_custom_effects,
                )
            if not enabled and not effects_active:
                return child_render

            # This render-to-texture boundary is intentional. Never copy a
            # child's shaders, uniforms, or GL properties onto SceneLight's
            # model: an image-declared custom shader must finish in its own
            # pass, while a `show ... at CustomShader` mesh transform remains
            # a later outer pass. That keeps both stacks independent.
            result = renpy.Render(*child_render.get_size())
            result.blit(child_render, (0, 0))
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
            result.add_shader("scenelight.dynamic_sprite")
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
            return _scenelight_custom_effect_render(
                result,
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
        tag = str(tag).split()[0]
        if not tag or tag == "bg":
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
            return _scenelight_route_scene_mutation(original, owner, args, kwargs)

        return routed

    def _scenelight_install_scene_router():
        scene_lists = _scenelight_scene_lists_class()
        if scene_lists is None or hasattr(scene_lists, "_scenelight_original_add"):
            return
        original_add = scene_lists.add

        def routed_add(owner, *args, **kwargs):
            return _scenelight_route_scene_add(original_add, owner, args, kwargs)

        scene_lists._scenelight_original_add = original_add
        scene_lists.add = routed_add
        for method_name in ("remove", "clear"):
            original = getattr(scene_lists, method_name, None)
            if original is None:
                continue
            setattr(scene_lists, "_scenelight_original_" + method_name, original)
            setattr(scene_lists, method_name, _scenelight_mutation_router(original))


init 999 python:
    # Character(image="tag") declarations opt in automatically. The set only
    # decides which displayables are routed through SceneLight; character names
    # and sprite pixels never affect exposure or any shader coefficient.
    if _SCENELIGHT_SHADER_AVAILABLE:
        _scenelight_movie_texture = getattr(renpy.display.video, "get_movie_texture", None)
        if callable(_scenelight_movie_texture):
            if getattr(_scenelight_movie_texture, "_scenelight_movie_hook", False):
                _scenelight_movie_texture = _scenelight_movie_texture._scenelight_original
            renpy.display.video.get_movie_texture = _scenelight_movie_texture_hook(_scenelight_movie_texture)
        for _scenelight_value in list(vars(renpy.store).values()):
            if not isinstance(_scenelight_value, renpy.character.ADVCharacter):
                continue
            _scenelight_tag = _scenelight_value.image_tag
            if not _scenelight_tag:
                _scenelight_tag = _scenelight_value.show_args.get("image")
            if isinstance(_scenelight_tag, str) and _scenelight_tag:
                SCENELIGHT_CHARACTER_TAGS.add(_scenelight_tag.split()[0])

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
