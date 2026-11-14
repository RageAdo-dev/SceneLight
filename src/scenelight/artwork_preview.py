"""Forward completed artwork saves to the open developer playtest."""

from __future__ import annotations

import hashlib
import io
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path

from .file_verification import open_for_preview
from .runtime.live_edit import signal_path

_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_IGNORED = {"cache", "saves", "scenelight_runtime"}


def _write_maps(maps, destination, *, artwork_digest=None):
    with zipfile.ZipFile(destination, "w") as archive:
        if artwork_digest:
            archive.writestr("artwork.sha256", artwork_digest)
        archive.writestr("form.json", json.dumps(maps.metadata))
        for name in ("normal_noise", "height_ao_edge", "response"):
            with archive.open(name + ".png", "w") as stream:
                getattr(maps, name).save(stream, format="PNG", compress_level=1)


class ArtworkPreview(threading.Thread):
    def __init__(self, project: Path, report):
        super().__init__(name="scenelight-artwork-preview", daemon=True)
        self.game = (project / "game").resolve()
        self.signal = Path(signal_path(str(project))).with_suffix(".art")
        self.session = uuid.uuid4().hex[:16]
        self.workspace = self.signal.with_suffix(".forms-" + self.session)
        self.report = report
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.scripts_changed = threading.Event()
        self.refresh_index = threading.Event()
        self.changes = queue.SimpleQueue()
        self.script_events = queue.SimpleQueue()
        self.awaiting_art = set()
        self.art_arrived = threading.Event()
        self.script_baseline = {}
        self.preview_sources = {}
        self.preview_layers = set()
        self.known_layers = set()
        self.history = deque(maxlen=24)

    def project_updated(self):
        if self.scripts_changed.is_set():
            self.scripts_changed.clear()
            self.refresh_index.set()

    def stop(self):
        self.stopped.set()

    def _source_path(self, path):
        if not path.is_relative_to(self.game):
            return False
        parts = path.relative_to(self.game).parts
        return (
            bool(parts)
            and parts[0].lower() not in _IGNORED
            and not any(
                part.lower().startswith((".sl-", ".scenelight-developer-")) for part in parts
            )
        )

    def changed(self, filename):
        path = Path(filename)
        if not self._source_path(path):
            return
        if path.suffix.lower() in {".rpy", ".rpym", ".rpa"}:
            self.scripts_changed.set()
            self.script_events.put(path.relative_to(self.game))
        if path.suffix.lower() in _IMAGE_TYPES:
            self.changes.put(path.relative_to(self.game))

    def _readable(self, relative):
        from PIL import Image

        path = self.game / relative
        try:
            target = path.resolve(strict=True)
            if not self._source_path(target) or not target.is_file():
                return False
            before = target.stat()
            with open_for_preview(target) as stream, Image.open(stream) as image:
                if getattr(image, "is_animated", False):
                    return False
                image.load()
            after = path.stat()
            return (before.st_ino, before.st_size, before.st_mtime_ns) == (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
        except (OSError, ValueError, SyntaxError, RuntimeError, Image.DecompressionBombError):
            return False

    def _publish(self, names):
        revision = self.session + uuid.uuid4().hex[:16]
        self.history.append((revision, names))
        self.signal.parent.mkdir(exist_ok=True, parents=True)
        temporary = self.signal.with_suffix("." + revision)
        try:
            temporary.write_bytes(
                revision.encode("ascii") + b"\n" + json.dumps(list(self.history)).encode("utf-8")
            )
            for attempt in range(6):
                if self.stopped.is_set():
                    return
                try:
                    temporary.replace(self.signal)
                    return
                except PermissionError:
                    # Windows can briefly hold the previous file open while Ren'Py reads it.
                    if attempt == 5:
                        raise
                    self.stopped.wait(0.025)
        finally:
            temporary.unlink(missing_ok=True)

    def _script_message(self, state, entries=None, scripts=None):
        revision = self.session + uuid.uuid4().hex[:16]
        target = self.signal.with_suffix(".script")
        temporary = self.workspace / (revision + ".tmp")
        temporary.write_bytes(
            revision.encode("ascii")
            + b"\n"
            + json.dumps(
                {
                    "state": state,
                    "entries": entries or {},
                    "layers": sorted(self.preview_layers) if state == "preview" else [],
                    "scripts": {
                        p.as_posix(): hashlib.sha256(data).hexdigest()
                        for p, data in (scripts or {}).items()
                    },
                }
            ).encode("utf8")
        )
        for attempt in range(6):
            try:
                temporary.replace(target)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                self.stopped.wait(0.025)

    def _script_source(self, path):
        path = self.game / path
        if not self._source_path(path.resolve()) or path.stat().st_size > 24 * 1024 * 1024:
            raise ValueError("Script exceeds the playtest preview limit")
        with open_for_preview(path) as stream:
            return stream.read()

    def _remember_scripts(self):
        self.script_baseline = {}
        self.known_layers = set()
        remaining = 64 * 1024 * 1024
        for path in self.game.rglob("*.rpy"):
            if self._source_path(path):
                try:
                    content = (
                        self._script_source(path) if path.stat().st_size <= remaining else None
                    )
                    self.script_baseline[path.relative_to(self.game)] = content
                    if content:
                        self.known_layers.update(
                            name.decode("ascii")
                            for name in re.findall(rb"(?m)^layeredimage +([a-zA-Z_]\w*)", content)
                        )
                    remaining -= len(content) if content else 0
                except (OSError, ValueError):
                    self.script_baseline[path.relative_to(self.game)] = None

    def _prepare_script(self, changes):
        from PIL import Image

        from .form_maps import build_sprite_form_maps
        from .script_preview import layered_changes, sprite_script_changes

        images, declared = {}, set()
        layers, shown, files = set(), set(), set()
        for path, content in changes.items():
            before = self.script_baseline.get(path, b"")
            if path.suffix.lower() != ".rpy" or before is None or content is None:
                return
            if b"layeredimage " in before or b"layeredimage " in content:
                change = layered_changes(before, content)
                if change is None:
                    return
                before, content, changed_layers, pieces = change
                layers.update(changed_layers)
                files.update(pieces)
            delta = sprite_script_changes(before, content)
            if delta is None or images.keys() & delta[0].keys():
                return
            images.update(delta[0])
            declared.update(delta[1])
            shown.update(delta[2])
        if len(images) > 12:
            return
        layers.update(self.known_layers & shown)
        if not images and not layers:
            return {}
        runtime = json.loads((self.game / "scenelight_runtime/manifest.json").read_bytes())
        selected = set(runtime["character_tags"])
        if runtime.get("auto_include_new_characters", False):
            selected.update(declared | layers)
        selected.difference_update(runtime.get("excluded_character_tags", ()))
        self.preview_layers = layers & selected
        for filename in files:
            relative = Path(filename)
            if not (self.game / relative).is_file():
                self.awaiting_art.add(relative)
                raise FileNotFoundError(filename)
        entries = {}
        for name, filename in images.items():
            if self.stopped.is_set() or name.split()[0] not in selected:
                return
            relative = Path(filename)
            self.awaiting_art.add(relative)
            path = (self.game / relative).resolve(strict=True)
            if not self._source_path(path) or path.stat().st_size > 32 * 1024 * 1024:
                self.awaiting_art.discard(relative)
                return
            with open_for_preview(path) as stream:
                raw = stream.read()
            with Image.open(io.BytesIO(raw)) as image:
                if getattr(image, "is_animated", False) or image.width * image.height > 4_194_304:
                    self.awaiting_art.discard(relative)
                    return
                sprite = Image.alpha_composite(Image.new("RGBA", image.size), image.convert("RGBA"))
            self.awaiting_art.discard(relative)
            digest = hashlib.sha256(raw).hexdigest()
            bundle = self.workspace / (digest[:24] + ".bundle")
            temporary = bundle.with_suffix(".writing")
            _write_maps(build_sprite_form_maps(sprite), temporary, artwork_digest=digest)
            temporary.replace(bundle)
            entries[name] = [filename, digest]
        return entries

    def _build_visible_forms(self):
        from PIL import Image

        from .form_maps import build_sprite_form_maps
        from .project import SpriteSpec, discover_project, renderer_surface_image

        sprites = None
        self.refresh_index.set()
        first_index = True
        changed_scripts = {}
        pending_scripts = set()
        preview_sent = False
        settle = None
        next_cleanup = time.monotonic() + 60
        while not self.stopped.wait(0.04):
            if self.refresh_index.is_set():
                self.refresh_index.clear()
                if not self.scripts_changed.is_set():
                    changed_scripts.clear()
                    preview_sent = False
                    self.preview_sources.clear()
                    self.preview_layers.clear()
                    if not first_index:
                        self._remember_scripts()
                first_index = False
                try:
                    sprites = discover_project(self.game.parent).sprites
                except Exception as error:
                    sprites = None
                    self.report(f"Visible sprite maps will use the project update. {error}")
            while not self.script_events.empty():
                path = self.script_events.get_nowait()
                pending_scripts.add(path)
                settle = time.monotonic() + 0.45
            if self.art_arrived.is_set() and settle is None:
                settle = time.monotonic()
            if settle is not None and time.monotonic() >= settle:
                settle = None
                retry = self.art_arrived.is_set()
                self.art_arrived.clear()
                updates = {}
                for path in pending_scripts:
                    try:
                        content = (
                            self._script_source(path) if path.suffix.lower() == ".rpy" else None
                        )
                    except (OSError, ValueError):
                        content = None
                    if (
                        content is None
                        and path.suffix.lower() == ".rpy"
                        and path not in self.script_baseline
                        and not (self.game / path).exists()
                    ):
                        content = b""
                    if content != changed_scripts.get(path, self.script_baseline.get(path, b"")):
                        updates[path] = content
                pending_scripts.clear()
                if updates or retry:
                    self.awaiting_art.clear()
                    changed_scripts.update(updates)
                    changed_scripts = {
                        p: data
                        for p, data in changed_scripts.items()
                        if data != self.script_baseline.get(p, b"")
                    }
                    self.preview_sources.clear()
                    self.preview_layers.clear()
                    try:
                        if changed_scripts:
                            self._script_message("checking")
                            entries = self._prepare_script(changed_scripts)
                            if entries is not None and self.scripts_changed.is_set():
                                self.preview_sources = {
                                    name: data[0] for name, data in entries.items()
                                }
                                self._script_message("preview", entries, changed_scripts)
                                preview_sent = True
                            else:
                                self._script_message("pending")
                        elif preview_sent:
                            self._script_message("preview", {}, updates)
                            preview_sent = False
                        else:
                            self._script_message("idle")
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        TypeError,
                        SyntaxError,
                        RuntimeError,
                        Image.DecompressionBombError,
                    ) as error:
                        self._script_message("waiting" if self.awaiting_art else "pending")
                        self.report(f"Script edit will use the project update. {error}")
                if not changed_scripts and self.script_events.empty():
                    self.scripts_changed.clear()
            if time.monotonic() >= next_cleanup:
                # Discard replies orphaned by a closed playtest or superseded edit.
                next_cleanup = time.monotonic() + 60
                cutoff = time.time() - 300
                for item in self.workspace.iterdir():
                    try:
                        if (
                            item.suffix in (".ready", ".deferred", ".json")
                            or (item.suffix == ".bundle" and not self.scripts_changed.is_set())
                        ) and item.stat().st_mtime < cutoff:
                            item.unlink()
                    except OSError:
                        continue
            for source in self.workspace.glob("*.input"):
                if self.stopped.is_set():
                    return
                result = source.with_suffix(".ready")
                temporary = source.with_suffix(".writing")
                try:
                    request = json.loads(source.with_suffix(".json").read_bytes())
                    if request.get("layered"):
                        spec = None
                    elif self.scripts_changed.is_set() and request["name"] in self.preview_sources:
                        spec = SpriteSpec(
                            request["name"], (self.game / self.preview_sources[request["name"]],)
                        )
                    elif sprites is None or self.scripts_changed.is_set():
                        raise ValueError("Project definitions need to finish updating")
                    else:
                        spec = sprites.get(request["name"])
                    if spec is not None:
                        sources = {
                            name.replace(chr(92), "/").lower() for name in request["sources"]
                        }
                        sources.update("images/" + name for name in tuple(sources))
                        if not all(
                            path.resolve().is_relative_to(self.game)
                            and path.resolve().relative_to(self.game).as_posix().lower() in sources
                            for path in spec.layers
                        ):
                            raise ValueError("Visible form and installed definition differ")
                        for layer in spec.layers:
                            with open_for_preview(layer) as stream, Image.open(stream) as image:
                                if image.width * image.height > 4_194_304:
                                    raise ValueError("Form exceeds the live preview size")
                        if (
                            spec.canvas_size
                            and spec.canvas_size[0] * spec.canvas_size[1] > 4_194_304
                        ):
                            raise ValueError("Form exceeds the live preview size")
                        sprite = spec.compose()
                    else:
                        if not source.stat().st_size:
                            raise ValueError("This form requires a renderer capture")
                        with Image.open(source) as image:
                            if image.width * image.height > 4_194_304:
                                raise ValueError("Form exceeds the live preview size")
                            sprite = renderer_surface_image(image)
                    maps = build_sprite_form_maps(sprite)
                    _write_maps(maps, temporary)
                    if source.exists() and not self.stopped.is_set():
                        temporary.replace(result)
                except (
                    Exception
                ) as error:  # A failed preview must leave the project update running.
                    if source.exists() and not self.stopped.is_set():
                        source.with_suffix(".deferred").touch()
                        self.report(
                            f"Visible sprite lighting will finish with the project update. {error}"
                        )
                finally:
                    source.with_suffix(".json").unlink(missing_ok=True)
                    source.unlink(missing_ok=True)
                    temporary.unlink(missing_ok=True)

    def run(self):
        observer = None
        forms = None
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            watcher = self

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    if event.event_type == "deleted" or event.event_type == "moved":
                        watcher.changed(event.src_path)
                    if not event.is_directory and event.event_type in (
                        "created",
                        "modified",
                        "moved",
                        "closed",
                    ):
                        watcher.changed(
                            event.dest_path if event.event_type == "moved" else event.src_path
                        )

            # The Windows backend waits this long for a quiet batch before delivering saves.
            observer = Observer(timeout=0.05) if os.name == "nt" else Observer()
            observer.schedule(Handler(), str(self.game), recursive=True)
            self.workspace.mkdir(parents=True)
            observer.start()
            self._remember_scripts()
            forms = threading.Thread(
                target=self._build_visible_forms, name="scenelight-visible-forms", daemon=True
            )
            forms.start()
            self.ready.set()
            pending = {}
            while not self.stopped.wait(0.05):
                now = time.monotonic()
                while True:
                    try:
                        path = self.changes.get_nowait()
                    except queue.Empty:
                        break
                    pending[path] = (now + 0.15, now + 3.0)
                batch = []
                for path, (check, expiry) in list(pending.items()):
                    if now < check:
                        continue
                    if self._readable(path):
                        batch.append(path.as_posix())
                        if path in self.awaiting_art:
                            self.art_arrived.set()
                        del pending[path]
                    elif now >= expiry:
                        del pending[path]
                    else:
                        pending[path] = (now + 0.25, expiry)
                    if len(batch) == 32 or self.stopped.is_set():
                        break
                if batch and not self.stopped.is_set():
                    self._publish(batch)
        except (ImportError, OSError, RuntimeError) as error:
            self.report(
                f"Artwork preview is unavailable. The full lighting update will still run. {error}"
            )
        finally:
            if observer is not None and observer.is_alive():
                observer.stop()
                observer.join()
            self.stopped.set()
            if forms is not None:
                forms.join()
                shutil.rmtree(self.workspace, ignore_errors=True)
