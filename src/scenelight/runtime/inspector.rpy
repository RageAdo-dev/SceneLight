# SceneLight's diagnostic UI. Test edits never enter save or persistent state.
init 1001 python:
    _sc_inspector_module = _scenelight_runtime_module("inspector")
    renpy.display._scenelight_inspector = _sc_inspector_module.Session()

    def _scenelight_inspector_session():
        return renpy.display._scenelight_inspector

    def _scenelight_inspector_text(value):
        try:
            text_type = unicode
        except NameError:
            text_type = str
        return text_type(value).replace("{", "{{")

    def _scenelight_inspector_targets():
        targets = []
        background, scene = _scenelight_live_scene_entry()
        background = _scenelight_control_name(background or "unknown", "background")
        scene = scene or {}
        rules = _scenelight_control_current_state()
        owner = renpy.game.context().scene_lists
        for entry in owner.layers.get("master", ()):
            tag = str(getattr(entry, "tag", "") or "")
            name = getattr(entry, "name", ()) or (tag,)
            name = name if isinstance(name, _SCENELIGHT_STRING_TYPES) else " ".join(name)
            normalized = name[3:] if name.startswith("bg ") else name
            if not tag or tag == "bg" or normalized in SCENELIGHT_SCENES or normalized in SCENELIGHT_SCENE_SEQUENCES:
                continue
            pending = [getattr(entry, "displayable", None)]
            seen = set()
            sprites = []
            while pending and len(seen) < 4096:
                current = pending.pop()
                if current is None or id(current) in seen:
                    continue
                seen.add(id(current))
                if isinstance(current, SceneLightSprite):
                    sprites.append(current)
                    pending.append(getattr(current, "child", None))
                    continue
                try:
                    pending.extend(current.visit() or ())
                except (AttributeError, TypeError):
                    pass
            for sprite in sprites or [None]:
                image = _scenelight_control_name(sprite.form_key if sprite is not None else name, "image")
                target_tag = _scenelight_control_name(sprite.image_name[0] if sprite is not None else tag, "character")
                visible_name = _scenelight_control_name(name, "image")
                report = _sc_inspector_module.describe(
                    _SCENELIGHT_CALIBRATION_DEFAULTS, SCENELIGHT_PROFILE_STRENGTH,
                    SCENELIGHT_MANIFEST.get("calibration", {}), scene.get("calibration", {}),
                    rules, background, target_tag, image,
                    getattr(persistent, "scenelight_enabled", True),
                    getattr(persistent, "scenelight_strength", 1.0), _scenelight_inspector_session())
                report["key"] = (background, target_tag, image)
                report["managed"] = sprite is not None
                report["visible_name"] = visible_name
                if sprite is None:
                    report["effective_enabled"] = False
                    report["note"] = "Not routed through SceneLight. Check Characters in Setup and update the game."
                else:
                    # Whole-image aliases take glow/emission rules from the shown name.
                    visible = _sc_inspector_module.describe(
                        _SCENELIGHT_CALIBRATION_DEFAULTS, SCENELIGHT_PROFILE_STRENGTH,
                        SCENELIGHT_MANIFEST.get("calibration", {}), scene.get("calibration", {}),
                        rules, background, target_tag, visible_name,
                        getattr(persistent, "scenelight_enabled", True),
                        getattr(persistent, "scenelight_strength", 1.0), _scenelight_inspector_session())
                    for field in ("values", "origins", "chains", "locations"):
                        for setting in visible[field]:
                            if setting.startswith(("glow_", "emission_")):
                                report[field][setting] = visible[field][setting]
                    if not visible["values"]["enabled"]:
                        for setting, value in (("glow_strength", 0.0), ("emission_strength", 0.0), ("glow_rules", [])):
                            report["values"][setting] = value
                            report["origins"][setting] = "Shown image disabled"
                            report["locations"][setting] = visible["locations"].get("enabled")
                            report["chains"][setting].append({"source": "Shown image disabled", "value": value})
                    report["mapped_form"] = bool(getattr(sprite, "has_form", False))
                    report["authored_color_grade"] = getattr(sprite, "authored_grade_strength", 0.0)
                    report["frozen_transition"] = bool(getattr(sprite, "_sc_snapshot_frozen", False))
                    report["exposure_owner"] = bool(getattr(sprite, "_sc_exposure_owner", True))
                    report["screen_rect"] = sprite._scenelight_screen_rect()
                    group = report.get("group")
                    report["group_anchor"] = _scenelight_control_group_anchor(group) if group else None
                    report["last_drawn"] = {
                        "enabled": getattr(sprite, "_sc_last_rendered_enabled", report["effective_enabled"]),
                        "strength": getattr(sprite, "_sc_last_rendered_strength", report["effective_strength"]),
                        "controls": copy.deepcopy(getattr(sprite, "_sc_last_rendered_controls", None)),
                    }
                    report["note"] = ("Transition snapshot: last drawn values can differ from current rules."
                        if report["frozen_transition"] else "External color grading detected on this sprite."
                        if report["authored_color_grade"] else "Exact form map" if report["mapped_form"] else "Generic form map (update this sprite's analysis)")
                    if not scene or not _SCENELIGHT_SHADER_AVAILABLE:
                        report["effective_enabled"] = False
                        report["note"] = "Lighting unavailable: no recognized background or supported shader."
                report["passes"] = [{setting: copy.deepcopy(report.get(setting)) for setting in (
                    "mapped_form", "authored_color_grade", "frozen_transition", "exposure_owner", "last_drawn")}] if sprite is not None else []
                duplicate = next((previous for previous in targets if previous["key"] == report["key"]), None)
                if duplicate is not None:
                    duplicate["passes"].extend(report["passes"])
                else:
                    targets.append(report)
        return targets

    def _scenelight_inspector_refresh():
        session = _scenelight_inspector_session()
        session.targets = _scenelight_inspector_targets()
        keys = [target["key"] for target in session.targets]
        if session.selected not in keys:
            session.selected = keys[0] if keys else None
        session.report = next((target for target in session.targets if target["key"] == session.selected), {})

    def _scenelight_inspect(tag=None):
        if tag is not None:
            tag = _scenelight_control_name(tag, "character")
        _scenelight_inspector_refresh()
        session = _scenelight_inspector_session()
        report = {"version": 2, "background": (_scenelight_live_scene_entry()[0] or "unknown"),
            "sprites": copy.deepcopy([target for target in session.targets if tag is None or target["tag"] == tag]),
            "authored_rules": scenelight.state(), "test_changes": session.serializable(),
            "renderer": renpy.get_renderer_info(), "live_error": renpy.display._scenelight_live_error,
            "manifest_version": SCENELIGHT_MANIFEST.get("version"),
            "notes": session.notes, "recording": copy.deepcopy(session.history),
            "sampling": "Up to 10 seconds at 10 Hz; not a frame-by-frame GPU trace.",
            "virtual_size": [config.screen_width, config.screen_height]}
        report["findings"] = _sc_inspector_module.findings(report)
        return report

    def _scenelight_inspector_start_recording():
        _scenelight_inspector_session().start_recording()
        renpy.hide_screen("scenelight_inspector")
        renpy.show_screen("scenelight_inspector_recording")

    def _scenelight_inspector_record_tick():
        session = _scenelight_inspector_session()
        _scenelight_inspector_refresh()
        session.record(session.targets)
        if not session.recording:
            _scenelight_inspector_stop_recording()

    def _scenelight_inspector_stop_recording():
        session = _scenelight_inspector_session()
        session.recording = False
        session.message = "Recorded %d samples. Export the report to include them." % len(session.history)
        renpy.hide_screen("scenelight_inspector_recording")
        _scenelight_open_inspector()

    def _scenelight_inspector_select(target):
        _scenelight_inspector_session().selected = tuple(target)
        _scenelight_inspector_refresh()

    def _scenelight_inspector_changed():
        _scenelight_redraw_visible_sprites()
        _scenelight_inspector_refresh()
        if _scenelight_inspector_session().active():
            renpy.show_screen("scenelight_inspector_indicator")
        else:
            renpy.hide_screen("scenelight_inspector_indicator")
        renpy.restart_interaction()

    def _scenelight_inspector_reset(name=None, all_changes=False):
        session = _scenelight_inspector_session()
        if name in ("master_enabled", "master_strength"):
            session.master.pop(name[7:], None)
        else:
            target = session.selected
            if target is not None and session.report:
                visible = (target[0], target[1], session.report["visible_name"])
                if name is None:
                    session.clear(visible)
                elif name.startswith(("glow_", "emission_")):
                    target = visible
            session.clear(None if all_changes else target, name)
        session.message = "Original settings restored."
        _scenelight_inspector_changed()

    def _scenelight_inspector_edit(name):
        session = _scenelight_inspector_session()
        session.edit_name = name
        if name == "report_note":
            value = session.notes
        elif name == "master_strength":
            value = _scenelight_master_strength()
        elif name == "master_enabled":
            value = _scenelight_master_enabled()
        elif name == "light_color":
            values = session.report["values"]
            value = "#%02X%02X%02X" % tuple(int(round(values["light_color_" + channel] * 255)) for channel in ("red", "green", "blue"))
        else:
            value = session.report["values"][name]
        session.edit_text = value if name in ("light_color", "report_note") else json.dumps(value)
        session.message = ""
        renpy.show_screen("scenelight_inspector_edit")

    def _scenelight_inspector_value_target(name):
        session = _scenelight_inspector_session()
        target = session.selected
        if target is not None and name.startswith(("glow_", "emission_")):
            target = (target[0], target[1], session.report["visible_name"])
        return target

    def _scenelight_inspector_set_value(name, value, target=None):
        session = _scenelight_inspector_session()
        if name.startswith("master_"):
            session.master[name[7:]] = value
        else:
            target = target if target is not None else _scenelight_inspector_value_target(name)
            if target is None:
                raise ValueError("Select a visible sprite first")
            session.update(target, _scenelight_control_values({name: value}))

    class _SceneLightInspectorValue(BarValue):
        def __init__(self, name, value, enabled=True):
            self.name = name
            self.value = value
            self.enabled = enabled
            self.target = _scenelight_inspector_value_target(name)
            self.low, self.high = _sc_inspector_module.number_range(name)

        def get_adjustment(self):
            return ui.adjustment(value=self.value - self.low, range=self.high - self.low,
                changed=self.changed if self.enabled else None, adjustable=self.enabled, step=0.01)

        def changed(self, value):
            if not self.enabled:
                return
            value = _sc_inspector_module.finite_number(round(value + self.low, 3), self.low, self.high)
            self.value = value
            _scenelight_inspector_set_value(self.name, value, self.target)
            _scenelight_inspector_session().message = "Temporary change applied. Your original rules are unchanged."
            _scenelight_inspector_changed()

    def _scenelight_inspector_apply_edit():
        session = _scenelight_inspector_session()
        name = session.edit_name
        try:
            if name == "report_note":
                session.notes = session.edit_text.strip()
                session.message = "Notes saved for the support report."
                renpy.hide_screen("scenelight_inspector_edit")
                return
            if name in ("enabled", "master_enabled"):
                text = session.edit_text.strip().lower()
                if text not in ("true", "false", "on", "off", "1", "0"):
                    raise ValueError("Enter true or false")
                value = text in ("true", "on", "1")
            elif name == "light_color":
                value = session.edit_text.strip()
            elif name == "glow_rules":
                value = json.loads(session.edit_text)
            else:
                low, high = _sc_inspector_module.number_range(name)
                value = _sc_inspector_module.finite_number(session.edit_text, low, high)
            _scenelight_inspector_set_value(name, value)
            session.message = "Temporary change applied. Your original rules are unchanged."
            renpy.hide_screen("scenelight_inspector_edit")
            _scenelight_inspector_changed()
        except (ValueError, TypeError) as error:
            session.message = str(error)

    def _scenelight_inspector_export():
        session = _scenelight_inspector_session()
        try:
            report = _scenelight_inspect()
            report["time"] = _sc_diagnostic_time.time()
            report["renpy"] = getattr(renpy, "version_string", "unknown")
            screenshot = renpy.screenshot_to_bytes((1280, int(1280.0 * config.screen_height / config.screen_width))) if session.include_screenshot else None
            filename = _sc_inspector_module.write_support_bundle(config.basedir, report, screenshot)
            _scenelight_record_diagnostic("inspector.export", {"filename": filename})
            session.message = "Saved support ZIP beside the game folder: " + filename
        except (OSError, IOError, TypeError, ValueError) as error:
            session.message = "Could not export: " + str(error)

    def _scenelight_open_inspector():
        _scenelight_inspector_refresh()
        renpy.show_screen("scenelight_inspector")
        renpy.restart_interaction()

    def _scenelight_inspector_clear_session():
        _scenelight_inspector_session().clear()
        _scenelight_inspector_session().edit_name = None
        _scenelight_inspector_session().recording = False
        _scenelight_inspector_session().history = []
        renpy.hide_screen("scenelight_inspector")
        renpy.hide_screen("scenelight_inspector_edit")
        renpy.hide_screen("scenelight_inspector_indicator")
        renpy.hide_screen("scenelight_inspector_recording")

    config.keymap.setdefault("scenelight_inspector", ["shift_K_F9"])
    config.underlay.append(renpy.Keymap(scenelight_inspector=Function(_scenelight_open_inspector)))
    config.after_load_callbacks.append(_scenelight_inspector_clear_session)
    config.start_callbacks.append(_scenelight_inspector_clear_session)

style sc_inspector_text is default:
    font "DejaVuSans.ttf"
    size 17
    color "#e6eef7"
    outlines []
style sc_inspector_button is button:
    background Solid("#253b50")
    hover_background Solid("#355d79")
    selected_background Solid("#256d82")
    padding (10, 7)
style sc_inspector_button_text is sc_inspector_text:
    hover_color "#ffffff"
    selected_color "#ffffff"
    insensitive_color "#8e9aa7"
style sc_inspector_input is input:
    font "DejaVuSans.ttf"
    size 20
    color "#ffffff"
style sc_inspector_vscrollbar is vscrollbar:
    xsize 12
    base_bar Solid("#172635")
    thumb Solid("#568ba3")
style sc_inspector_slider is bar:
    ysize 18
    left_bar Solid("#4facc2")
    right_bar Solid("#253b50")
    thumb Solid("#e6eef7", xysize=(12, 18))
    hover_thumb Solid("#ffffff", xysize=(12, 18))
    left_gutter 6
    right_gutter 6

screen scenelight_inspector():
    modal True
    zorder 2100
    style_prefix "sc_inspector"
    key "game_menu" action Hide("scenelight_inspector")
    key "scenelight_inspector" action Hide("scenelight_inspector")
    timer 0.4 repeat True action Function(_scenelight_inspector_refresh)
    $ session = _scenelight_inspector_session()
    $ info = session.report
    frame:
        xalign 0.99 yalign 0.5
        xsize min(620, config.screen_width - 30)
        ysize config.screen_height - 30
        background Solid("#101a26f5")
        padding (18, 16)
        vbox:
            spacing 9
            hbox:
                spacing 14
                text "Lighting inspector" size 25
                textbutton "Close" action Hide("scenelight_inspector")
                textbutton "Export report" action Function(_scenelight_inspector_export)
            text "Live test edits · Shift+F9" color "#98b4c8" size 14
            hbox:
                spacing 8
                textbutton "Applied settings" action SetField(session, "tab", "settings") selected session.tab == "settings"
                textbutton "All sources" action SetField(session, "tab", "sources") selected session.tab == "sources"
                textbutton "Color" action SetField(session, "tab", "color") selected session.tab == "color"
                textbutton "Checks" action SetField(session, "tab", "checks") selected session.tab == "checks"
            viewport:
                ysize 58
                mousewheel "horizontal"
                draggable True
                hbox:
                    spacing 6
                    for target in session.targets:
                        button:
                            action Function(_scenelight_inspector_select, target["key"])
                            selected session.selected == target["key"]
                            text _scenelight_inspector_text(target["image"]) substitute False style "sc_inspector_button_text"
            if info:
                text ("Background: " + _scenelight_inspector_text(info["background"])) substitute False color "#98b4c8"
                if info.get("group"):
                    text ("Lighting group: " + _scenelight_inspector_text(info["group"]["name"])) substitute False color "#8bdeef" size 15
                    text ("Shared position: " + _scenelight_inspector_text(info.get("group_anchor"))) substitute False color "#98b4c8" size 13
                text ("Effective: %s · %.3f × %.3f = %.3f" % ("ON" if info["effective_enabled"] else "OFF", info["values"]["strength"], info["master"]["strength"], info["effective_strength"])) size 18
                text _scenelight_inspector_text(info["note"]) substitute False color "#e9c883" size 14
            else:
                text "No visible sprites. Open this during a scene." color "#e9c883"
            viewport:
                ysize max(100, config.screen_height - 450 - (42 if info and info.get("group") else 0))
                scrollbars "vertical"
                mousewheel True
                draggable True
                vbox:
                    spacing 8
                    if session.tab == "checks":
                        textbutton "Describe the issue" action Function(_scenelight_inspector_edit, "report_note")
                        textbutton "Include screenshot" action ToggleField(session, "include_screenshot") selected session.include_screenshot
                        text "Export includes active settings, build identity, engine logs and checks. Screenshot is optional." color "#98b4c8" size 14
                        for finding in _sc_inspector_module.findings({"sprites": session.targets, "notes": session.notes, "live_error": renpy.display._scenelight_live_error}):
                            text _scenelight_inspector_text(finding["level"].upper() + ": " + finding["message"]) substitute False color "#e9c883" size 15
                    elif info:
                        if session.tab in ("settings", "color"):
                            hbox:
                                spacing 8
                                if session.tab == "settings":
                                    textbutton "Master on/off" action Function(_scenelight_inspector_edit, "master_enabled")
                                textbutton "Color hex" action Function(_scenelight_inspector_edit, "light_color") sensitive info["managed"]
                            text "Negative color influence reduces a cast; positive increases it. Similar colors widens the match." color "#98b4c8" size 14
                            if session.tab == "color":
                                text ("Target: #%02X%02X%02X" % tuple(int(round(info["values"]["light_color_" + channel] * 255)) for channel in ("red", "green", "blue"))) color "#8bdeef"
                            $ fields = ["light_color_amount", "light_color_tolerance"] if session.tab == "color" else ["master_strength", "enabled", "strength"] + sorted(_SCENELIGHT_CALIBRATION_DEFAULTS)
                            for name in fields:
                                $ value = info["master"]["strength"] if name == "master_strength" else info["values"][name]
                                $ editable = info["managed"] or name == "master_strength"
                                frame:
                                    background Solid("#172838")
                                    padding (10, 8)
                                    xfill True
                                    vbox:
                                        spacing 4
                                        hbox:
                                            spacing 8
                                            fixed:
                                                xysize (245, 24)
                                                text name.replace("_", " ").capitalize() size 16
                                            fixed:
                                                xysize (75, 24)
                                                text _sc_inspector_module.value_text(value) size 16
                                            textbutton "Edit" id ("sc_inspector_edit_" + name) action Function(_scenelight_inspector_edit, name) sensitive editable text_size 14
                                            textbutton "Reset" id ("sc_inspector_reset_" + name) action Function(_scenelight_inspector_reset, name) text_size 14
                                        if name not in ("enabled", "glow_rules"):
                                            bar id ("sc_inspector_slider_" + name) value _SceneLightInspectorValue(name, value, editable) style "sc_inspector_slider"
                                        text _scenelight_inspector_text(info["master"]["source"] if name == "master_strength" else info["origins"][name]) substitute False size 13 color "#98b4c8"
                                        if info["locations"].get(name):
                                            text _scenelight_inspector_text("%s:%s" % (info["locations"][name]["file"], info["locations"][name]["line"])) substitute False size 12 color "#8bdeef"
                        else:
                            text "Order below: last value wins. Scene off is a hard bypass. Temporary test edits are applied last." color "#98b4c8" size 14
                            text ("Saved player: enabled=%s, strength=%.3f" % (info["player"]["enabled"], info["player"]["strength"])) size 15
                            if info.get("last_drawn"):
                                text ("Last drawn: enabled=%s, strength=%.3f" % (info["last_drawn"]["enabled"], info["last_drawn"]["strength"])) size 15
                            for pass_index, drawing in enumerate(info.get("passes", [])):
                                text ("Pass %d: exposure owner=%s, external grade=%s, frozen=%s" % (pass_index + 1, drawing.get("exposure_owner"), drawing.get("authored_color_grade"), drawing.get("frozen_transition"))) size 13 color "#98b4c8"
                            for name in ["enabled", "strength"] + sorted(_SCENELIGHT_CALIBRATION_DEFAULTS):
                                text name.replace("_", " ").capitalize() color "#8bdeef" size 17
                                for layer in info["chains"][name]:
                                    text (_scenelight_inspector_text(layer["source"]) + ": " + _sc_inspector_module.value_text(layer["value"])) substitute False size 14
                                    if isinstance(layer["value"], (list, tuple)) and layer["value"]:
                                        text _scenelight_inspector_text(json.dumps(layer["value"], indent=2, ensure_ascii=False)) substitute False size 12 color "#adc5d6"
                                    if layer.get("location"):
                                        text _scenelight_inspector_text("%s:%s" % (layer["location"]["file"], layer["location"]["line"])) substitute False size 12 color "#98b4c8"
            text _scenelight_inspector_text(session.message) substitute False color "#e9c883" size 14 ysize 32
            hbox:
                spacing 8
                textbutton "Reset this sprite" action Function(_scenelight_inspector_reset) sensitive bool(info)
                textbutton "Clear all test edits" action Function(_scenelight_inspector_reset, all_changes=True)
            text "Changes are temporary. New game, loading, or restarting clears them. Export before clearing." size 13 color "#98b4c8"

screen scenelight_inspector_edit():
    modal True
    zorder 2200
    style_prefix "sc_inspector"
    $ session = _scenelight_inspector_session()
    key "game_menu" action Hide("scenelight_inspector_edit")
    key "K_RETURN" action Function(_scenelight_inspector_apply_edit)
    frame:
        xalign 0.5 yalign 0.5
        xsize 570
        background Solid("#152535")
        padding (24, 24)
        vbox:
            spacing 18
            text ("Test: " + str(session.edit_name).replace("_", " ")) size 24
            if session.edit_name == "report_note":
                text "Describe the scene, what happened, and what you expected." size 15 color "#adc5d6"
            elif session.edit_name in ("enabled", "master_enabled"):
                text "Enter true or false." size 15 color "#adc5d6"
            elif session.edit_name == "light_color":
                text "Enter a hex color, such as #4080FF." size 15 color "#adc5d6"
            elif session.edit_name == "glow_rules":
                text "Enter a JSON list of color-glow rules. All sources shows the full current rules." size 15 color "#adc5d6"
            else:
                $ bounds = _sc_inspector_module.number_range(session.edit_name)
                text ("Enter a value from %s to %s." % bounds) size 15 color "#adc5d6"
            input value FieldInputValue(session, "edit_text") length 16000 pixel_width 515
            text _scenelight_inspector_text(session.message) substitute False color "#ffcc91" size 15
            hbox:
                spacing 12
                textbutton "Apply test value" action Function(_scenelight_inspector_apply_edit)
                textbutton "Cancel" action Hide("scenelight_inspector_edit")

screen scenelight_inspector_indicator():
    zorder 2050
    style_prefix "sc_inspector"
    if not renpy.get_screen("scenelight_inspector"):
        frame:
            xalign 0.99 yalign 0.01
            background Solid("#172838dd")
            padding (10, 6)
            textbutton "SceneLight test edits active · Shift+F9" action Function(_scenelight_open_inspector) text_size 14

screen scenelight_inspector_recording():
    zorder 2250
    style_prefix "sc_inspector"
    timer 0.1 repeat True action Function(_scenelight_inspector_record_tick)
    frame:
        xalign 0.01 yalign 0.01
        background Solid("#172838ee")
        padding (10, 6)
        textbutton "Recording lighting · Stop and inspect" action Function(_scenelight_inspector_stop_recording) text_size 14
