"""Notify a running developer project after Setup finishes a live update."""

import hashlib
import json
import os
import threading
import time
import uuid
import zipfile
from collections import OrderedDict


def signal_path(project):
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    name = os.path.normcase(os.path.realpath(project))
    if not isinstance(name, bytes):
        name = name.encode("utf-8")
    return os.path.join(root, "SceneLight", "live-edit", hashlib.sha256(name).hexdigest())


def _revision(path):
    try:
        with open(path, "rb") as stream:
            return stream.read(33)
    except (IOError, OSError):
        return None


def _artwork_changes(path, previous):
    try:
        with open(path, "rb") as stream:
            revision = stream.read(33).strip()
            if len(revision) != 32 or revision == previous:
                return previous, []
            history = json.loads(stream.read(1024 * 1024).decode("utf-8"))
        names = set()
        for batch, files in reversed(history):
            if batch.encode("ascii") == previous:
                break
            names.update(files)
        return revision, sorted(names)
    except (IOError, OSError, ValueError, AttributeError, TypeError):
        return previous, []


def script_matches(game, scripts):
    if not scripts or len(scripts) > 48:
        return False
    root = os.path.normcase(os.path.realpath(game)) + os.sep
    for name, expected in scripts.items():
        path = os.path.normcase(os.path.realpath(os.path.join(game, name)))
        if not path.startswith(root) or not path.endswith(".rpy"):
            return False
        try:
            if not os.path.exists(path) and expected == hashlib.sha256(b"").hexdigest():
                continue
            with open(path, "rb") as stream:
                if hashlib.sha256(stream.read(24 * 1024 * 1024 + 1)).hexdigest() != expected:
                    return False
        except (IOError, OSError):
            return False
    return True


def read_install(project):
    try:
        with open(os.path.join(project, ".scenelight_developer_install.json"), "rb") as stream:
            return json.loads(stream.read().decode("utf8"))
    except (IOError, OSError, ValueError):
        return None


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


class _NewerSave(Exception):
    pass


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def loaded_bytecode(project, install, scripts):
    """Remember paired bytecode that was present when Ren'Py loaded the edited story."""
    result = {}
    remaining = 64 * 1024 * 1024
    sources = set((install or {}).get("source_state", {}))
    sources.update("game/" + name for name in scripts)
    for source in sorted(sources):
        if not source.startswith("game/") or not source.endswith(".rpy"):
            continue
        name = source + "c"
        path = os.path.join(project, name)
        try:
            size = os.path.getsize(path)
            if size <= min(remaining, 24 * 1024 * 1024):
                result[name] = _file_hash(path)
                remaining -= size
        except (OSError, IOError):
            continue
    return result


def sprite_commit(
    project, before, after, manifest, forms, applied, active_tags, recent_art=(), compiled=None
):
    """Compute a bounded in-place update from the installer's verified inventories."""
    if not before or not after:
        raise ValueError("Installation inventory unavailable")
    if any(
        before.get(k) != after.get(k)
        for k in (
            "release",
            "namespace",
            "inspector_enabled",
            "selection_settings",
        )
    ):
        raise ValueError("Installation settings changed")
    root = "game/scenelight_runtime/"
    outputs = _changed(before["files"], after["files"])
    indexes = {
        root + n
        for n in (
            "manifest.json",
            "sprite_form_manifest.json",
            "install_report.json",
            "REMOVE-SCENELIGHT.txt",
        )
    }
    textures = outputs - indexes
    if len(textures) > 384 or any(not p.startswith(root + "sprite_form/") for p in textures):
        raise ValueError("Scene textures or runtime files changed")
    old, new = before["source_state"], after["source_state"]
    changed = {k for k in _changed(old, new) if old.get(k, [None])[-1] != new.get(k, [None])[-1]}
    if len(changed) > 128:
        raise ValueError("Large source update")
    scripts, artwork = {}, []
    for key in changed:
        if not key.startswith("game/") or key not in new:
            raise ValueError("A project source was removed")
        name = key[5:]
        if name.endswith(".rpy"):
            scripts[name] = new[key][-1]
        elif name.endswith(".rpyc") and key[:-1] in new:
            if not compiled or compiled.get(key) != _file_hash(os.path.join(project, key)):
                raise ValueError("Compiled script differs from the running playtest")
        elif name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            artwork.append(name)
        else:
            raise ValueError("Additional project sources changed")
    if not all(applied.get(name) == digest for name, digest in scripts.items()):
        raise ValueError("Updated scripts have not loaded in this playtest")
    if scripts and not script_matches(os.path.join(project, "game"), scripts):
        raise _NewerSave()
    for name in set(artwork) | set(recent_art):
        expected = new.get("game/" + name)
        if not expected:
            raise _NewerSave()
        if _file_hash(os.path.join(project, "game", name)) != expected[-1]:
            raise _NewerSave()

    def index(name):
        path = root + name
        with open(os.path.join(project, path), "rb") as stream:
            raw = stream.read()
        if hashlib.sha256(raw).hexdigest() != after["files"][path]:
            raise ValueError("Install changed while reading " + name)
        return json.loads(raw.decode("utf8"))

    current = index("manifest.json")
    if _changed(manifest, current) - {"character_tags"}:
        raise ValueError("Scene lighting parameters changed")
    if set(current["character_tags"]) != set(active_tags):
        raise ValueError("Registered character selection changed")
    inventory = index("sprite_form_manifest.json")
    if _changed(forms, inventory) - {"sprites", "cache", "skipped"}:
        raise ValueError("Surface map format changed")
    entries = inventory["sprites"]
    delta = _changed(forms["sprites"], entries)
    channels = ("normal_noise", "height_ao_edge", "response")
    textures = {p[5:] for p in textures}
    delta.update(
        name for name, value in entries.items() if any(value[c] in textures for c in channels)
    )
    if len(delta) > 2048:
        raise ValueError("Large surface map update")
    return (
        after,
        current["character_tags"],
        {k: entries.get(k) for k in delta},
        artwork + sorted(textures),
        inventory.get("cache", {}),
        inventory.get("skipped", {}),
    )


class VisibleForms(object):
    """Transient playtest bindings. Installed maps and save data stay on disk separately."""

    def __init__(self, project):
        self.project = project
        self.layer_tags = set()
        self.recent_art = set()
        self.compiled = {}
        self.generation = 0
        self.commit_job = None
        self.install = None
        self.signal = signal_path(project)
        self.workspace = None
        self.bindings = OrderedDict()
        self.pending = {}
        self.deferred = set()
        self.evicted = set()
        self.status = ""
        self.until = 0

    def check_commit(self, manifest, inventory, scripts, tags):
        job = []
        self.commit_job = job
        recent_art = tuple(self.recent_art)

        def verify():
            try:
                patch = sprite_commit(
                    self.project,
                    self.install,
                    read_install(self.project),
                    manifest,
                    inventory,
                    scripts,
                    tags,
                    recent_art,
                    self.compiled,
                )
            except _NewerSave:
                job.append(("newer", None))
            except Exception as error:
                job.append(("reload", str(error)))
            else:
                job.append(("apply", patch))

        worker = threading.Thread(target=verify)
        worker.daemon = True
        worker.start()

    def connect(self, revision):
        token = revision.decode("ascii")
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            return
        workspace = self.signal + ".forms-" + token[:16]
        if workspace != self.workspace:
            self.pending.clear()
            self.deferred.clear()
            self.evicted.clear()
            self.bindings.clear()
        self.workspace = workspace

    def install_script_maps(self, packet, resolve, texture):
        revision, entries = packet
        self.connect(revision.encode("ascii"))
        tags = set()
        if not self.workspace or len(entries) > 12:
            return tags
        for name, (filename, digest) in entries.items():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                continue
            try:
                if not resolve(name, filename, digest):
                    continue
                path = os.path.join(self.workspace, digest[:24] + ".bundle")
                self.bindings[name] = self.read_maps(path, texture, digest)
                tags.add(name.split()[0])
            except (IOError, OSError, ValueError, KeyError, zipfile.BadZipfile):
                continue
        return tags

    @staticmethod
    def read_maps(path, texture, digest=None):
        with zipfile.ZipFile(path) as archive:
            if digest is not None and archive.read("artwork.sha256").decode("ascii") != digest:
                raise ValueError("The preview artwork has changed")
            metadata = json.loads(archive.read("form.json").decode("utf-8"))
            return (metadata,) + tuple(
                texture(archive.read(n + ".png"), n + ".png")
                for n in ("normal_noise", "height_ao_edge", "response")
            )

    def request(self, name, sources, snapshot, layered=False):
        prior = self.pending.pop(name, None)
        if prior:
            self.remove(prior + ".input")
        self.deferred.discard(name)
        self.bindings.pop(name, None)
        self.evicted.discard(name)
        self.bindings[name] = None
        while len(self.bindings) > 12:
            evicted, _binding = self.bindings.popitem(last=False)
            self.evicted.add(evicted)
            self.pending.pop(evicted, None)
            self.deferred.discard(evicted)
        prefix = os.path.join(self.workspace, uuid.uuid4().hex)
        temporary = prefix + ".png"
        try:
            if not snapshot(temporary):
                # Static script definitions can still be composed by Setup.
                with open(temporary, "wb"):
                    pass
            with open(prefix + ".json", "wb") as stream:
                stream.write(
                    json.dumps(
                        {
                            "name": name,
                            "sources": list(sources),
                            "layered": layered,
                        }
                    ).encode("utf-8")
                )
            os.rename(temporary, prefix + ".input")
            self.pending[name] = prefix
        finally:
            self.remove(temporary)
            self.update_status()

    @staticmethod
    def remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def form_status(self, name):
        if name in self.pending:
            return "Updating lighting"
        if (
            name in self.deferred
            or name in self.evicted
            or (name in self.bindings and self.bindings[name] is None)
        ):
            return "Lighting preview (project update pending)"
        if name in self.bindings:
            return "Lighting ready"
        return None

    def update_status(self, finished=None):
        if self.pending:
            names = sorted(self.pending)
            verb = "Updating lighting"
        elif self.deferred:
            names = sorted(self.deferred)
            verb = "Lighting preview (project update pending)"
        elif finished:
            names = sorted(finished)
            verb = "Lighting ready"
        else:
            self.status = ""
            return
        subject = names[0][:64] if len(names) == 1 else "%d sprites" % len(names)
        self.status = verb + " - " + subject
        self.until = time.time() + 3 if not (self.pending or self.deferred) else 0

    def poll(self, texture):
        if self.workspace and self.status and not self.until and not os.path.isdir(self.workspace):
            self.pending.clear()
            self.deferred.clear()
            self.status = "Live updates paused"
            self.until = time.time() + 3
            return True
        if self.until and time.time() >= self.until:
            self.until = 0
            self.status = ""
            return True
        if not (self.pending or self.deferred):
            return False
        if not os.path.isdir(self.workspace):
            self.pending.clear()
            self.deferred.clear()
            self.status = "Live updates paused"
            self.until = time.time() + 3
            return True
        finished = []
        changed = False
        for name, prefix in list(self.pending.items()):
            ready = prefix + ".ready"
            if os.path.isfile(ready):
                try:
                    self.bindings[name] = self.read_maps(ready, texture)
                    finished.append(name)
                except (IOError, OSError, ValueError, KeyError, zipfile.BadZipfile):
                    self.deferred.add(name)
                self.remove(ready)
            elif os.path.isfile(prefix + ".deferred"):
                self.deferred.add(name)
                self.remove(prefix + ".deferred")
            else:
                continue
            del self.pending[name]
            changed = True
        if changed:
            self.update_status(finished)
        return changed


def subscribe(
    project, reload_game, ready, preview_art=None, forms=None, tick=None, script_edit=None
):
    path = signal_path(project)
    art_path = path + ".art"
    clock = getattr(time, "monotonic", time.time)
    previous = [_revision(path), 0]
    art_revision = [(_revision(art_path) or b"").strip()]

    script_path = path + ".script"
    script_revision = [_revision(script_path)]

    def poll():
        now = clock()
        if now < previous[1]:
            return
        previous[1] = now + (0.15 if preview_art else 1.0)
        revision = _revision(path)
        if revision and len(revision) == 32 and revision != previous[0] and ready():
            previous[0] = revision
            reload_game()
        elif preview_art and ready():
            if script_edit is not None:
                head = _revision(script_path)
                if head and head != script_revision[0]:
                    try:
                        with open(script_path, "rb") as stream:
                            head = stream.readline(34)
                            packet = json.loads(stream.read(65536).decode("utf-8"))
                        token = head.strip()
                        if len(token) == 32 and isinstance(packet, dict):
                            script_revision[0] = head
                            forms.connect(token)
                            script_edit(token.decode("ascii"), packet)
                    except (OSError, IOError, ValueError):
                        pass
            revision, files = _artwork_changes(art_path, art_revision[0])
            if files:
                if forms is not None:
                    forms.connect(revision)
                preview_art(files)
            art_revision[0] = revision
            if tick is not None:
                tick()

    return poll
