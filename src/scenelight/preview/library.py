"""Portable recipes and a private local library of copied Preview media."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from ..calibration import Calibration
from ..sidecar import storage_root


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class Layer:
    path: str
    x: int = 0
    y: int = 0
    opacity: float = 1.0
    visible: bool = True
    name: str = ""


def compose_layers(layers: list[Layer], size: tuple[int, int] | None = None) -> Image.Image:
    if not layers or len(layers) > 64:
        raise ValueError("Use between 1 and 64 sprite layers.")
    images = []
    for layer in layers:
        with Image.open(layer.path) as image:
            if getattr(image, "n_frames", 1) > 1:
                raise ValueError(
                    "Layer pieces must be still images. Add animated sprites directly to the scene."
                )
            images.append(image.convert("RGBA"))
    if size is None:
        size = (
            max(image.width + max(0, layer.x) for image, layer in zip(images, layers)),
            max(image.height + max(0, layer.y) for image, layer in zip(images, layers)),
        )
    if min(size) < 1 or max(size) > 8192 or size[0] * size[1] > 32_000_000:
        raise ValueError(
            "Sprite canvas must be 1–8192 pixels per edge and at most 32 million pixels."
        )
    canvas = Image.new("RGBA", size)
    for image, layer in zip(images, layers):
        if not layer.visible:
            continue
        opacity = max(0.0, min(float(layer.opacity), 1.0))
        if opacity < 1.0:
            image.putalpha(image.getchannel("A").point(lambda value: round(value * opacity)))
        canvas.alpha_composite(image, (int(layer.x), int(layer.y)))
    return canvas


@dataclass
class Actor:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Character"
    source: str = ""
    image_name: str = ""
    horizontal: float = 0.5
    baseline: float = 1.04
    height: float = 0.92
    strength: float = 1.0
    calibration: Calibration = field(default_factory=Calibration)
    visible: bool = True

    def payload(self) -> dict:
        value = asdict(self)
        value["calibration"] = self.calibration.as_dict()
        return value

    @classmethod
    def from_payload(cls, value: dict) -> "Actor":
        allowed = cls.__dataclass_fields__
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise ValueError("Invalid saved character settings.")
        values = dict(value)
        values["calibration"] = Calibration.from_mapping(values.get("calibration"))
        for name, low, high in (
            ("horizontal", -0.25, 1.25),
            ("baseline", 0.2, 1.4),
            ("height", 0.1, 1.35),
            ("strength", 0, 2),
        ):
            raw = float(values.get(name, allowed[name].default))
            if not math.isfinite(raw):
                raise ValueError(f"Invalid {name}")
            values[name] = max(low, min(raw, high))
        for name in ("id", "name", "source", "image_name"):
            if name in values and not isinstance(values[name], str):
                raise ValueError(f"Invalid character {name}")
        return cls(**values)


class Library:
    def __init__(self, root: Path | None = None):
        self.root = root or storage_root().parent / "preview-library"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "library.json"

    def entries(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("entries"), list):
            raise ValueError("Unsupported Preview library format.")
        return payload["entries"]

    def _copy(self, source: Path) -> Path:
        source = source.resolve(strict=True)
        with source.open("rb") as stream:
            digest = (
                hashlib.file_digest(stream, "sha256").hexdigest()
                if hasattr(hashlib, "file_digest")
                else _digest(stream)
            )
        folder = self.root / "media"
        folder.mkdir(exist_ok=True)
        dest = folder / (digest + source.suffix.lower())
        if not dest.exists():
            temporary = dest.with_suffix(dest.suffix + "." + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, dest)
            finally:
                temporary.unlink(missing_ok=True)
        return dest

    def add(
        self,
        kind: str,
        source: Path,
        *,
        name: str | None = None,
        actor: Actor | None = None,
        layers: list[Layer] | None = None,
        canvas: tuple[int, int] | None = None,
    ) -> dict:
        if kind not in {"sprite", "background"}:
            raise ValueError("Library type must be sprite or background.")
        if kind == "sprite":
            with Image.open(source) as image:
                image.verify()
        copied = self._copy(source)
        entry = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "name": name or source.stem,
            "source": copied.relative_to(self.root).as_posix(),
        }
        if actor is not None:
            entry["actor"] = actor.payload()
            entry["actor"]["source"] = entry["source"]
        if layers is not None:
            entry["layers"] = [
                {
                    **asdict(layer),
                    "name": layer.name or Path(layer.path).name,
                    "path": self._copy(Path(layer.path)).relative_to(self.root).as_posix(),
                }
                for layer in layers
            ]
            entry["canvas"] = list(canvas) if canvas else None
        try:
            with Image.open(copied) as image:
                thumb = image.convert("RGBA")
                thumb.thumbnail((96, 96))
                folder = self.root / "thumbnails"
                folder.mkdir(exist_ok=True)
                target = folder / (entry["id"] + ".png")
                thumb.save(target)
                entry["thumbnail"] = target.relative_to(self.root).as_posix()
        except OSError:
            pass  # Videos use their name and type when no still thumbnail is available.
        entries = self.entries()
        entries.append(entry)
        atomic_json(self.index_path, {"version": 1, "entries": entries})
        return entry

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ValueError("Saved library media is missing or outside the library. Reimport it.")
        return path

    def remove(self, entry_id: str) -> None:
        # Media is content-addressed and may be shared with another entry/scene.
        atomic_json(
            self.index_path,
            {"version": 1, "entries": [e for e in self.entries() if e["id"] != entry_id]},
        )


def _digest(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def save_scene(path: Path, background: str | None, actors: list[Actor]) -> None:
    def relative(source):
        if not source:
            return None
        try:
            return os.path.relpath(source, path.parent).replace("\\", "/")
        except ValueError:
            # Windows cannot express a relative path across drive letters.
            return str(Path(source).resolve())

    atomic_json(
        path,
        {
            "version": 1,
            "background": relative(background),
            "actors": [dict(actor.payload(), source=relative(actor.source)) for actor in actors],
        },
    )


def load_scene(path: Path) -> tuple[Path | None, list[Actor]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("version") != 1
        or not isinstance(payload.get("actors"), list)
        or len(payload["actors"]) > 16
    ):
        raise ValueError("Unsupported scene or more than 16 characters.")
    actors = [Actor.from_payload(value) for value in payload["actors"]]
    if len({a.id for a in actors}) != len(actors):
        raise ValueError("Scene has duplicate character IDs.")
    for actor in actors:
        actor.source = str((path.parent / actor.source).resolve(strict=True))
    background = (
        (path.parent / payload["background"]).resolve(strict=True)
        if payload.get("background")
        else None
    )
    return background, actors


def author_rules(actors: list[Actor]) -> str:
    lines = [
        "# Generated per-image lighting. Include these tags in SceneLight's selection.",
        "init python:",
    ]
    seen = set()
    for actor in actors:
        name = " ".join(actor.image_name.strip().split())
        if not re.fullmatch(r"[\w-]+(?: [\w-]+)*", name, flags=re.UNICODE):
            raise ValueError(
                f"Enter the Ren'Py image name for {actor.name} (for example: hero happy)."
            )
        if name in seen:
            raise ValueError(
                "Two characters use the same image name. Use distinct image names for distinct rules."
            )
        seen.add(name)
        values = {"strength": actor.strength, **actor.calibration.as_dict()}
        lines.append(f"    scenelight.image({name!r},")
        lines.extend(f"        {key}={value!r}," for key, value in values.items())
        lines[-1] = lines[-1].rstrip(",") + ")"
    return "\n".join(lines) + "\n"
