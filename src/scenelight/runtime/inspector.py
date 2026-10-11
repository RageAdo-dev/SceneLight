"""Lighting provenance and temporary edits, shared with Ren'Py 7 (Python 2).

Session instances live on renpy.display, outside the save/rollback store. They
never mutate authored rules, a game save, or persistent player preferences.
"""

import copy
import hashlib
import io
import json
import math
import os
import re
import time
import uuid
import zipfile


def escape(value):
    # Ren'Py 7 distributions can omit xml.sax and newer html modules.
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def key(background, tag, image):
    return (background or "unknown", tag or "", image or "")


class Session(object):
    def __init__(self):
        self.overrides = {}
        self.master = {}
        self.selected = None
        self.targets = []
        self.report = {}
        self.tab = "settings"
        self.edit_name = None
        self.edit_text = ""
        self.message = ""
        self.notes = ""
        self.include_screenshot = False
        self.recording = False
        self.history = []
        self.record_started = 0.0

    def start_recording(self):
        self.recording = True
        self.history = []
        self.record_started = time.time()

    def record(self, targets):
        if not self.recording:
            return
        elapsed = time.time() - self.record_started
        fields = (
            "background",
            "tag",
            "image",
            "values",
            "effective_strength",
            "effective_enabled",
            "master",
            "last_drawn",
            "screen_rect",
            "passes",
        )
        sample = {
            "elapsed": round(elapsed, 3),
            "sprites": [
                {name: copy.deepcopy(target.get(name)) for name in fields}
                for target in targets[:32]
            ],
        }
        # Bound reports even when a mod generates huge rule lists or registries.
        if len(json.dumps(sample)) > 131072:
            sample = {"elapsed": round(elapsed, 3), "omitted": "Sample exceeded 128 KiB"}
        self.history.append(sample)
        if elapsed >= 10.0 or len(self.history) >= 100:
            self.recording = False

    def values(self, background, tag, image):
        return copy.deepcopy(self.overrides.get(key(background, tag, image), {}))

    def apply(self, background, tag, image, controls):
        values = self.values(background, tag, image)
        if not values:
            return controls
        result = copy.deepcopy(controls)
        for name, value in values.items():
            if name in ("enabled", "strength"):
                result[name] = value
                if name == "strength":
                    result["strength_override"] = True
            else:
                result.setdefault("calibration", {})[name] = value
        return result

    def update(self, target, values):
        self.overrides.setdefault(tuple(target), {}).update(copy.deepcopy(values))

    def clear(self, target=None, name=None):
        if target is None:
            self.overrides.clear()
            self.master.clear()
        elif name is None:
            self.overrides.pop(tuple(target), None)
        else:
            values = self.overrides.get(tuple(target), {})
            if name == "light_color":
                for channel in ("red", "green", "blue"):
                    values.pop("light_color_" + channel, None)
            else:
                values.pop(name, None)
            if not values:
                self.overrides.pop(tuple(target), None)

    def active(self):
        return bool(self.overrides or self.master)

    def serializable(self):
        return {
            "master": copy.deepcopy(self.master),
            "sprites": [
                {
                    "background": target[0],
                    "tag": target[1],
                    "image": target[2],
                    "settings": copy.deepcopy(values),
                }
                for target, values in sorted(self.overrides.items())
            ],
        }


def describe(
    defaults,
    profile_strength,
    profile,
    scene_profile,
    rules,
    background,
    tag,
    image,
    player_enabled,
    player_strength,
    session=None,
):
    """Explain each layer, including shadowed values and the hard scene bypass."""
    initial = dict(defaults)
    initial.update(enabled=True, strength=profile_strength)
    values = {}
    origins = {}
    chains = {}
    locations = {}
    sites = rules.get("call_sites", {})

    def apply(label, settings, call_sites=None):
        if not isinstance(settings, dict):
            return
        for name, value in settings.items():
            if name not in initial:
                continue
            values[name] = copy.deepcopy(value)
            origins[name] = label
            chains.setdefault(name, []).append({"source": label, "value": copy.deepcopy(value)})
            locations[name] = copy.deepcopy((call_sites or {}).get(name))
            if locations[name]:
                chains[name][-1]["location"] = locations[name]

    apply("Built-in default", initial)
    # Strength comes from the installed profile, even without an authored rule.
    origins["strength"] = "Installed profile"
    chains["strength"][0]["source"] = "Installed profile"
    apply("Installed profile", profile)
    apply("Background profile: " + background, scene_profile)
    apply("Project defaults", rules.get("defaults", {}), sites.get("defaults"))
    apply(
        "Background: " + background,
        rules.get("backgrounds", {}).get(background, {}),
        sites.get("backgrounds", {}).get(background),
    )
    scene = rules.get("scene", {})
    apply("Scene override", scene, sites.get("scene"))
    shared = copy.deepcopy(values)
    group_name, group = next(
        (
            (name, group)
            for name, group in rules.get("groups", {}).items()
            if tag in group.get("members", ())
        ),
        (None, None),
    )
    apply(
        "Character: " + tag,
        rules.get("characters", {}).get(tag, {}),
        sites.get("characters", {}).get(tag),
    )
    apply(
        "Image: " + image,
        rules.get("images", {}).get(image, {}),
        sites.get("images", {}).get(image),
    )
    if group is not None:
        shared = {
            name: value
            for name, value in shared.items()
            if not name.startswith(("glow_", "emission_"))
        }
        shared.update(group.get("settings", {}))
        apply("Lighting group: " + group_name, shared, sites.get("groups", {}).get(group_name))
        if any(
            rules.get(scope, {}).get(name, {}).get("enabled") is False
            for scope, name in (("characters", tag), ("images", image))
        ):
            apply("Member disabled", {"enabled": False})
    if scene.get("enabled") is False:
        apply("Scene off (hard bypass)", {"enabled": False}, sites.get("scene"))
    temporary = session.values(background, tag, image) if session else {}
    apply("Temporary inspector edit", temporary)
    master = session.master if session else {}
    enabled = bool(master.get("enabled", player_enabled))
    strength = float(master.get("strength", player_strength))
    return {
        "background": background,
        "tag": tag,
        "image": image,
        "group": dict(copy.deepcopy(group), name=group_name) if group is not None else None,
        "values": values,
        "origins": origins,
        "chains": chains,
        "locations": locations,
        "player": {"enabled": bool(player_enabled), "strength": float(player_strength)},
        "master": {
            "enabled": enabled,
            "strength": strength,
            "source": "Temporary inspector edit" if master else "Saved player preference",
        },
        "effective_enabled": enabled and bool(values["enabled"]),
        "effective_strength": float(values["strength"]) * strength,
        "temporary": temporary,
    }


def finite_number(text, low, high):
    number = float(text)
    if math.isnan(number) or math.isinf(number):
        raise ValueError("Enter a finite number")
    if number < low or number > high:
        raise ValueError("Enter a value from %s to %s" % (low, high))
    return number


def number_range(name):
    if name == "exposure_bias":
        return (-4.0, 4.0)
    if name == "light_color_amount":
        return (-1.0, 1.0)
    if name == "glow_strength":
        return (0.0, 10.0)
    if name == "master_strength":
        return (0.0, 1.5)
    if name in (
        "light_color_red",
        "light_color_green",
        "light_color_blue",
        "light_color_tolerance",
        "glow_red",
        "glow_green",
        "glow_blue",
        "glow_color_mix",
    ):
        return (0.0, 1.0)
    return (0.0, 2.0)


def value_text(value):
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, (list, tuple)):
        return "%d rules" % len(value)
    if isinstance(value, (int, float)):
        return "%.3f" % value
    return str(value)


def findings(report):
    """Report observed conditions, not an unproven diagnosis."""
    result = []

    def add(level, message):
        result.append({"level": level, "message": message})

    if report.get("live_error"):
        add("error", "Live lighting reported: " + str(report["live_error"]))
    if not report.get("sprites"):
        add("warning", "No visible sprites were captured. Export during the affected scene.")
    if not report.get("notes"):
        add("info", "No reproduction notes. Describe what happened and what you expected.")
    for sprite in report.get("sprites", []):
        prefix = sprite.get("image", "sprite") + ": "
        if not sprite.get("managed", True):
            add("warning", prefix + "not routed through SceneLight; check character selection.")
        if not sprite.get("effective_enabled", True):
            add(
                "warning",
                prefix
                + "lighting is disabled or unavailable; inspect Enabled and master controls.",
            )
        master = sprite.get("master", {})
        if master.get("strength", 1) != 1:
            add("info", prefix + "master multiplier is " + str(master.get("strength")) + ".")
        chain = sprite.get("chains", {}).get("strength", [])
        if len(set(str(layer.get("value")) for layer in chain)) > 1:
            add(
                "info",
                prefix
                + "strength differs across scopes; "
                + sprite.get("origins", {}).get("strength", "the last rule")
                + " wins.",
            )
        if sprite.get("managed") and not sprite.get("mapped_form"):
            add("warning", prefix + "using a generic surface map instead of an exact sprite map.")
        if sprite.get("authored_color_grade"):
            add("info", prefix + "the game also applies external color grading.")
        if len(sprite.get("passes", [])) > 1:
            add(
                "info",
                prefix
                + "nested lighting passes detected; compare exposure ownership in All sources.",
            )
        drawn = sprite.get("last_drawn") or {}
        if drawn.get("strength", sprite.get("effective_strength")) != sprite.get(
            "effective_strength"
        ):
            add(
                "info",
                prefix
                + "last drawn strength differs from current rules; a transition or pending redraw may explain this.",
            )
    if not result:
        add(
            "info",
            "No listed conflict was detected. This does not rule out a rendering or game-script issue.",
        )
    return result


def _redact(text):
    try:
        text_type = unicode
    except NameError:
        text_type = str
    if not isinstance(text, text_type):
        text = text.decode("utf-8", "replace")
    home = os.path.expanduser("~")
    for value in (home, home.replace("\\", "/"), home.replace("\\", "\\\\")):
        text = re.sub(re.escape(value), "<USER>", text, flags=re.I)
    return re.sub(
        r"(?i)((?:token|password|api[_-]?key|secret|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&]+",
        r"\1<REDACTED>",
        text,
    )


def support_files(root, report):
    report = copy.deepcopy(report)
    evidence = {}
    missing = []
    install_name = (
        ".scenelight_developer_install.json"
        if os.path.isfile(os.path.join(root, ".scenelight_developer_install.json"))
        else ".scenelight_install.json"
    )
    for name in (install_name, "game/scenelight_runtime/install_report.json"):
        path = os.path.join(root, name)
        try:
            if os.path.getsize(path) > 32 * 1024 * 1024:
                raise ValueError("metadata exceeds 32 MiB")
            with io.open(path, encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                raise ValueError("metadata is not an object")
            # Preserve diagnosis/identity, without duplicating an 18,000-form
            # ownership inventory or collecting any authored script contents.
            payload.pop("source_state", None)
            owned = payload.pop("files", payload.pop("runtime_files", None))
            if isinstance(owned, dict):
                payload["owned_file_count"] = len(owned)
            evidence[name] = payload
        except (OSError, IOError, ValueError) as error:
            missing.append({"file": name, "reason": str(error)})
    code = {}
    for name in (
        "game/scenelight_runtime/bootstrap.rpy",
        "game/scenelight_runtime.rpy",
        "game/scenelight_runtime/inspector.rpy",
        "game/scenelight_runtime/inspector.txt",
    ):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            with open(path, "rb") as stream:
                code[name] = hashlib.sha256(stream.read()).hexdigest()
    report["runtime_files_sha256"] = code
    report["installation"] = evidence
    report["missing_evidence"] = missing
    report["findings"] = findings(report)
    if os.path.isfile(os.path.join(root, ".scenelight_runtime_update.json")):
        report["findings"].append(
            {
                "level": "warning",
                "message": "A runtime update was interrupted. Close the game and run Update SceneLight to recover it.",
            }
        )
    serialized = _redact(json.dumps(report, indent=2, ensure_ascii=True))
    files = {"scenelight-inspector.json": serialized}
    for name in (
        "scenelight-runtime.jsonl",
        "scenelight-runtime.jsonl.1",
        "errors.txt",
        "log.txt",
        "traceback.txt",
    ):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as stream:
            size = os.path.getsize(path)
            stream.seek(max(0, size - 2 * 1024 * 1024))
            text = stream.read(2 * 1024 * 1024).decode("utf-8", "replace")
        files["logs/" + name] = _redact(
            ("[Earlier log content omitted]\n" if size > 2 * 1024 * 1024 else "") + text
        )
    checks = "".join(
        "<li><b>%s</b>: %s</li>" % (escape(row["level"]), escape(_redact(row["message"])))
        for row in report["findings"]
    )
    files["report.html"] = (
        "<!doctype html><meta charset='utf-8'><title>SceneLight support report</title>"
        "<style>body{background:#101a26;color:#e6eef7;font:16px system-ui;max-width:1100px;margin:35px auto;padding:20px}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:12px 0}summary{cursor:pointer;padding:12px}</style>"
        "<h1>SceneLight support report</h1><p>Observed conditions, not a guaranteed diagnosis.</p><ul>"
        + checks
        + "</ul><h2>Tester notes</h2><pre>"
        + escape(_redact(report.get("notes", "") or "Not supplied"))
        + "</pre><p>JSON includes active settings, override sources, renderer, exact runtime hashes, installation details, and any recorded samples. Logs are in the logs folder. No scripts, saves, or source assets are included. A screenshot appears only when selected.</p>"
        + "<details><summary>Full diagnostic data</summary><pre>"
        + escape(serialized)
        + "</pre></details>"
    )
    return files


def write_support_bundle(root, report, screenshot=None):
    files = support_files(root, report)
    name = (
        "scenelight-support-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".zip"
    )
    path = os.path.join(root, name)
    temporary = path + ".tmp"
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, text in files.items():
                archive.writestr(filename, text.encode("utf-8"))
            if screenshot is not None:
                archive.writestr("scene.png", screenshot)
        os.rename(temporary, path)
        with io.open(
            os.path.join(root, "scenelight-inspector.json"), "w", encoding="utf-8"
        ) as stream:
            stream.write(files["scenelight-inspector.json"])
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)
    return name
