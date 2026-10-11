"""Conservative Ren'Py project discovery.

This parser resolves static declarations without executing game code.
Dynamic declarations are reported for the in-engine capture pass.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .calibration import Calibration, CalibrationProfile
from .source_types import VIDEO_SOURCE_SUFFIXES

IMAGE_LINE = re.compile(r"^\s*image\s+([^=:\n]+?)\s*=\s*(.+)$", re.IGNORECASE)
IMAGE_BLOCK = re.compile(r"^(\s*)image\s+([^=:\n]+?)\s*:\s*$", re.IGNORECASE)
LAYERED_IMAGE_BLOCK = re.compile(r"^\s*layeredimage\s+([^:\n]+?)\s*:\s*$", re.IGNORECASE)
QUOTED_FILE = re.compile(r"[\"']([^\"']+\.(?:png|jpe?g|webp))[\"']", re.IGNORECASE)
QUOTED_IMAGE = re.compile(r"[\"']([A-Za-z_]\w*(?:\s+[A-Za-z0-9_]+)+)[\"']")
MOVIE_DECLARATION = re.compile(
    r"(?m)^\s*image\s+([^=:\n]+?)\s*=\s*Movie\s*\(",
    re.IGNORECASE,
)


def _declared_movies(source: str):
    """Read literal play arguments without evaluating authored expressions."""
    for match in MOVIE_DECLARATION.finditer(source):
        tail = source[match.end() - 1 :]
        lines = tail.splitlines(keepends=True)
        depth = 0
        try:
            for token in tokenize.generate_tokens(io.StringIO(tail).readline):
                if token.type != tokenize.OP:
                    continue
                if token.string == "(":
                    depth += 1
                elif token.string == ")":
                    depth -= 1
                    if depth == 0:
                        end = sum(map(len, lines[: token.end[0] - 1])) + token.end[1]
                        call = ast.parse("Movie" + tail[:end], mode="eval").body
                        for keyword in call.keywords:
                            if (
                                keyword.arg == "play"
                                and isinstance(keyword.value, ast.Constant)
                                and isinstance(keyword.value.value, str)
                                and Path(keyword.value.value).suffix.lower()
                                in VIDEO_SOURCE_SUFFIXES
                            ):
                                yield match.group(1), keyword.value.value
                        break
        except (SyntaxError, tokenize.TokenError):
            continue


PLAY_MOVIE_USE = re.compile(
    r"^\s*play\s+movie\s+[\"']([^\"']+\.(?:mp4|m4v|mov|avi|webm|mkv|ogv))[\"']",
    re.IGNORECASE,
)
STOP_MOVIE_USE = re.compile(r"^\s*stop\s+movie\b", re.IGNORECASE)
SCENE_USE = re.compile(r"^\s*scene\s+bg\s+([A-Za-z0-9_]+)", re.IGNORECASE)
SHOW_USE = re.compile(r"^\s*show\s+([A-Za-z_]\w*)(.*)$", re.IGNORECASE)
HIDE_USE = re.compile(r"^\s*hide\s+([A-Za-z_]\w*)", re.IGNORECASE)
LABEL_LINE = re.compile(r"^\s*label\s+[A-Za-z_]\w*", re.IGNORECASE)
CHARACTER_IMAGE = re.compile(
    r"(?:Character|DynamicCharacter)\s*\([^\n]*?\bimage\s*=\s*[\"']([A-Za-z_]\w*)[\"']",
    re.IGNORECASE,
)
CHARACTER_DECLARATION = re.compile(
    r"^\s*define\s+([A-Za-z_]\w*)\s*=\s*(?:Character|DynamicCharacter)\s*\([^\n]*?"
    r"\bimage\s*=\s*[\"']([A-Za-z_]\w*)[\"']",
    re.IGNORECASE | re.MULTILINE,
)
CHARACTER_SAY_USE = re.compile(
    r'^\s*([A-Za-z_]\w*)\s+((?:-?[A-Za-z0-9_]+\s+)+)"',
    re.IGNORECASE,
)
SHOW_STOP = {"at", "as", "behind", "onlayer", "zorder", "with"}


def _normal_name(value: str) -> str:
    return " ".join(value.lower().split())


@dataclass(frozen=True, slots=True)
class SpriteSpec:
    name: str
    layers: tuple[Path, ...]
    positions: tuple[tuple[int, int], ...] = ()
    canvas_size: tuple[int, int] | None = None
    renderer_alpha: bool = False

    def compose(self) -> Image.Image:
        if not self.layers:
            raise ValueError(f"{self.name!r} has no image layers")
        if self.positions or self.canvas_size is not None:
            if self.canvas_size is None or len(self.positions) != len(self.layers):
                raise ValueError(f"Invalid positioned layers in {self.name}")
            width, height = self.canvas_size
            if width < 1 or height < 1 or width > 16384 or height > 16384:
                raise ValueError(f"Invalid sprite canvas in {self.name}: {self.canvas_size}")
            canvas = np.zeros((height, width, 4), dtype=np.uint8)
            for path, position in zip(self.layers, self.positions, strict=True):
                with Image.open(path) as image:
                    layer = np.asarray(image.convert("RGBA"), dtype=np.uint8)
                _sprite_alpha_blit(canvas, layer, position)
            if self.renderer_alpha:
                source = canvas.astype(np.uint16)
                canvas = ((source * source[..., 3:4]) >> 8).astype(np.uint8)
            return Image.fromarray(canvas, mode="RGBA")
        images = [Image.open(path).convert("RGBA") for path in self.layers]
        canvas = Image.new("RGBA", images[0].size, (0, 0, 0, 0))
        for image in images:
            if image.size != canvas.size:
                raise ValueError(
                    f"Layer size mismatch in {self.name}: {image.size} != {canvas.size}"
                )
            canvas = Image.alpha_composite(canvas, image)
        return canvas


def _sprite_alpha_blit(
    destination: np.ndarray,
    source: np.ndarray,
    position: tuple[int, int],
) -> None:
    """Match the Pygame 1.9/pygame_sdl2 SRCALPHA composition used by Ren'Py."""

    x, y = position
    source_height, source_width = source.shape[:2]
    destination_height, destination_width = destination.shape[:2]
    target_x0 = max(0, x)
    target_y0 = max(0, y)
    target_x1 = min(destination_width, x + source_width)
    target_y1 = min(destination_height, y + source_height)
    if target_x0 >= target_x1 or target_y0 >= target_y1:
        return
    source_x0 = target_x0 - x
    source_y0 = target_y0 - y
    source_view = source[
        source_y0 : source_y0 + target_y1 - target_y0,
        source_x0 : source_x0 + target_x1 - target_x0,
    ]
    destination_view = destination[target_y0:target_y1, target_x0:target_x1]
    source_alpha = source_view[..., 3:4].astype(np.int32)
    destination_alpha = destination_view[..., 3:4].astype(np.int32)
    empty = destination_alpha[..., 0] == 0
    destination_view[empty] = source_view[empty]
    blend = (~empty) & (source_alpha[..., 0] != 0)
    if not np.any(blend):
        return
    source_i32 = source_view[blend].astype(np.int32)
    destination_i32 = destination_view[blend].astype(np.int32)
    source_blend_alpha = source_i32[:, 3:4]
    destination_blend_alpha = destination_i32[:, 3:4]
    destination_view[blend, :3] = (
        (
            (destination_i32[:, :3] << 8)
            + (source_i32[:, :3] - destination_i32[:, :3]) * source_blend_alpha
            + source_i32[:, :3]
        )
        >> 8
    ).astype(np.uint8)
    destination_view[blend, 3:4] = (
        source_blend_alpha
        + destination_blend_alpha
        - (source_blend_alpha * destination_blend_alpha // 255)
    ).astype(np.uint8)


@dataclass(slots=True)
class ProjectDiscovery:
    project_root: Path
    game_root: Path
    scenes: dict[str, Path]
    sprites: dict[str, SpriteSpec]
    character_tags: list[str]
    calibration: Calibration = Calibration()
    scene_calibration: dict[str, Calibration] = field(default_factory=dict)
    strength: float = 1.0
    runtime_sprite_names: list[str] = field(default_factory=list)
    runtime_sprite_sequences: list[list[str]] = field(default_factory=list)
    explicit_character_tags: list[str] = field(default_factory=list)
    excluded_character_tags: list[str] = field(default_factory=list)
    character_candidates: dict[str, str | None] = field(default_factory=dict)
    suggested_character_tags: list[str] = field(default_factory=list)
    character_selection: str = "automatic"
    requires_runtime_inventory: bool = False
    scene_sequences: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    scene_frame_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    scene_sequence_metadata: dict[str, dict[str, object]] = field(default_factory=dict)
    scene_media: dict[str, Path] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    skipped_sprites: list[dict[str, str]] = field(default_factory=list)
    scene_analysis: str = "live"

    def summary(self) -> dict[str, object]:
        return {
            "project": str(self.project_root),
            "scenes": {name: str(path) for name, path in sorted(self.scenes.items())},
            "sprites": {
                name: [str(path) for path in spec.layers]
                for name, spec in sorted(self.sprites.items())
            },
            "character_tags": self.character_tags,
            "calibration": self.calibration.as_dict(),
            "strength": self.strength,
            "scene_calibration": {
                name: value.as_dict() for name, value in sorted(self.scene_calibration.items())
            },
            "runtime_sprite_names": self.runtime_sprite_names,
            "runtime_sprite_sequences": self.runtime_sprite_sequences,
            "explicit_character_tags": self.explicit_character_tags,
            "excluded_character_tags": self.excluded_character_tags,
            "auto_include_new_characters": self.character_selection == "automatic",
            "character_candidates": self.character_candidates,
            "suggested_character_tags": self.suggested_character_tags,
            "character_selection": self.character_selection,
            "requires_runtime_inventory": self.requires_runtime_inventory,
            "scene_sequences": self.scene_sequences,
            "scene_analysis": self.scene_analysis,
            "scene_media": {name: str(path) for name, path in sorted(self.scene_media.items())},
            "unsupported": self.unsupported,
            "skipped_sprites": self.skipped_sprites,
        }


def _resolve_asset(
    project_root: Path, game_root: Path, declaration_file: Path, value: str
) -> Path | None:
    relative = Path(value.replace("\\", "/"))
    candidates = (
        game_root / relative,
        game_root / "images" / relative,
        declaration_file.parent / relative,
        project_root / relative,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _load_config(project_root: Path, config_path: Path | None) -> dict[str, object]:
    from .configuration import resolve_project_settings

    return resolve_project_settings(project_root, config_path).values


def _looks_like_foreground_character(layers: tuple[Path, ...], reference_height: int) -> bool:
    """Conservatively distinguish a character sprite from transparent UI art."""
    return _looks_like_foreground_sprite(SpriteSpec("candidate", layers), reference_height)


def _looks_like_foreground_sprite(spec: SpriteSpec, reference_height: int) -> bool:
    """Conservatively distinguish a composed character from UI/CG art."""

    try:
        canvas = spec.compose()
        alpha = canvas.getchannel("A")
        if alpha.getextrema()[0] == 255:
            return False
        bounds = alpha.getbbox()
        if bounds is None:
            return False
        visible_width = bounds[2] - bounds[0]
        visible_height = bounds[3] - bounds[1]
        minimum_height = max(96, int(reference_height * 0.35))
        return (
            visible_height >= minimum_height
            and float(visible_width) / float(max(1, visible_height)) <= 1.05
        )
    except (OSError, ValueError):
        return False


def discover_project(
    project: str | Path, config_path: str | Path | None = None
) -> ProjectDiscovery:
    project_root = Path(project).expanduser().resolve()
    game_root = project_root / "game"
    if not game_root.is_dir():
        raise FileNotFoundError(f"Ren'Py game directory not found: {game_root}")
    source_files = sorted(game_root.rglob("*.rpy"))
    source_texts = {
        path: path.read_text(encoding="utf-8", errors="replace") for path in source_files
    }
    image_files: dict[str, tuple[Path, ...]] = {}
    aliases: dict[str, str] = {}
    layered_images: set[str] = set()
    used_scenes: set[str] = set()
    used_sprites: set[str] = set()
    attributed_show_counts: dict[str, int] = {}
    hidden_tags: set[str] = set()
    character_image_tags: set[str] = set()
    character_variables: dict[str, str] = {}
    runtime_sprite_sequences_raw: list[list[str]] = []
    unsupported: list[str] = []
    movie_sources: dict[str, Path] = {}
    manual_movie_scenes: dict[str, Path] = {}

    for source in source_texts.values():
        active_source = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for variable, tag in CHARACTER_DECLARATION.findall(active_source):
            character_variables[variable.lower()] = tag.lower()
            character_image_tags.add(tag.lower())

    for source_path in source_files:
        source = source_texts[source_path]
        active_source = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for movie_name, movie_path in _declared_movies(active_source):
            resolved_movie = _resolve_asset(
                project_root,
                game_root,
                source_path,
                movie_path,
            )
            if resolved_movie is not None:
                movie_sources[_normal_name(movie_name)] = resolved_movie
        character_image_tags.update(
            match.lower() for match in CHARACTER_IMAGE.findall(active_source)
        )
        lines = source.splitlines()
        source_sequence: list[str] = []
        source_sequence_full: list[str] = []
        active_movie_source: Path | None = None
        index = 0
        while index < len(lines):
            line = lines[index]
            if LABEL_LINE.match(line) and source_sequence:
                runtime_sprite_sequences_raw.append(source_sequence)
                source_sequence = []
            scene_match = SCENE_USE.match(line)
            if scene_match:
                scene_name = scene_match.group(1).lower()
                used_scenes.add(scene_name)
                if active_movie_source is not None:
                    manual_movie_scenes.setdefault(scene_name, active_movie_source)
                source_sequence.append("scene")
                source_sequence_full.append("scene")
            play_movie_match = PLAY_MOVIE_USE.match(line)
            if play_movie_match:
                active_movie_source = _resolve_asset(
                    project_root,
                    game_root,
                    source_path,
                    play_movie_match.group(1),
                )
            elif STOP_MOVIE_USE.match(line):
                active_movie_source = None
            hide_match = HIDE_USE.match(line)
            if hide_match:
                hide_event = f"hide {hide_match.group(1).lower()}"
                hidden_tags.add(hide_match.group(1).lower())
                source_sequence.append(hide_event)
                source_sequence_full.append(hide_event)
            show_match = SHOW_USE.match(line)
            if show_match:
                tag = show_match.group(1).lower()
                if tag not in {"screen", "expression", "layer"}:
                    parts = show_match.group(2).strip().split()
                    attrs: list[str] = []
                    for part in parts:
                        if part.lower() in SHOW_STOP:
                            break
                        if re.fullmatch(r"[A-Za-z0-9_]+", part):
                            attrs.append(part.lower())
                        else:
                            break
                    show_name = " ".join((tag, *attrs))
                    show_event = f"show {show_name}"
                    source_sequence.append(show_event)
                    source_sequence_full.append(show_event)
                    if attrs:
                        used_sprites.add(show_name)
                        attributed_show_counts[tag] = attributed_show_counts.get(tag, 0) + 1
            say_match = CHARACTER_SAY_USE.match(line)
            if say_match and say_match.group(1).lower() in character_variables:
                tag = character_variables[say_match.group(1).lower()]
                raw_attrs = say_match.group(2).strip().split()
                if raw_attrs and all(re.fullmatch(r"-?[A-Za-z0-9_]+", part) for part in raw_attrs):
                    say_name = " ".join((tag, *(part.lower() for part in raw_attrs)))
                    say_event = f"show {say_name}"
                    source_sequence.append(say_event)
                    source_sequence_full.append(say_event)
                    used_sprites.add(say_name)

            declaration = IMAGE_LINE.match(line)
            if declaration:
                name = _normal_name(declaration.group(1))
                values = QUOTED_FILE.findall(declaration.group(2))
                resolved = tuple(
                    path
                    for value in values
                    if (path := _resolve_asset(project_root, game_root, source_path, value))
                    is not None
                )
                if values and len(resolved) == len(values):
                    image_files[name] = resolved
                elif values:
                    unsupported.append(f"unresolved image {name} in {source_path.name}")
                else:
                    alias = QUOTED_IMAGE.search(declaration.group(2))
                    if alias:
                        aliases[name] = _normal_name(alias.group(1))

            layered = LAYERED_IMAGE_BLOCK.match(line)
            if layered:
                layered_images.add(_normal_name(layered.group(1)))

            block = IMAGE_BLOCK.match(line)
            if block:
                indent = len(block.group(1))
                name = _normal_name(block.group(2))
                body: list[str] = []
                cursor = index + 1
                while cursor < len(lines):
                    candidate = lines[cursor]
                    if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                        break
                    body.append(candidate)
                    cursor += 1
                alias = QUOTED_IMAGE.search("\n".join(body))
                if alias:
                    aliases[name] = _normal_name(alias.group(1))
                elif name.startswith("bg "):
                    unsupported.append(f"dynamic background {name} in {source_path.name}")
                index = cursor - 1
            index += 1
        if source_sequence:
            runtime_sprite_sequences_raw.append(source_sequence)
        # Also preserve the source file's straight-line order. This supplies
        # incoming image state to branch labels that are textually adjacent to
        # their jump/call sites, while the per-label sequences above still
        # cover labels entered independently.
        if source_sequence_full:
            runtime_sprite_sequences_raw.append(source_sequence_full)

    for name, target in list(aliases.items()):
        seen = {name}
        while target in aliases and target not in seen:
            seen.add(target)
            target = aliases[target]
        if target in image_files:
            image_files[name] = image_files[target]

    # Many titles use plain ``Character("Name")`` declarations and explicit
    # ``show eileen happy`` statements, leaving no Character.image value from
    # which to recover the image tag. Infer those families from story use, but
    # keep title/date cards and small transparent UI art out of the character
    # set. Layered images and foreground-scale transparent declarations provide
    # independent evidence that the tag is a sprite.
    background_heights: list[int] = []
    for name, layers in image_files.items():
        if not name.startswith("bg ") or not layers:
            continue
        try:
            with Image.open(layers[0]) as background:
                background_heights.append(background.height)
        except (OSError, ValueError):
            pass
    reference_height = max(background_heights, default=720)
    layered_tags = {name.split()[0] for name in layered_images}
    candidate_tags = {name.split()[0] for name in used_sprites}
    for tag in candidate_tags:
        foreground_geometry = False
        for name, layers in image_files.items():
            if name.split()[0] != tag:
                continue
            if _looks_like_foreground_character(layers, reference_height):
                foreground_geometry = True
                break
        if tag in layered_tags or foreground_geometry:
            character_image_tags.add(tag)

    config = _load_config(project_root, Path(config_path).resolve() if config_path else None)
    scene_analysis = config.get("scene_analysis", "live")
    if not isinstance(scene_analysis, str) or scene_analysis not in {"live", "cached"}:
        raise ValueError("scene_analysis must be 'live' or 'cached'")
    profile = CalibrationProfile.from_payload(config)
    configured_scenes = config.get("scenes", {})
    if isinstance(configured_scenes, dict):
        for name, value in configured_scenes.items():
            path = _resolve_asset(project_root, game_root, game_root, str(value))
            if path is None:
                raise FileNotFoundError(f"Configured scene {name!r} was not found: {value}")
            image_files[f"bg {_normal_name(str(name))}"] = (path,)
            used_scenes.add(_normal_name(str(name)))

    configured_sprites = config.get("sprites", {})
    if isinstance(configured_sprites, dict):
        for name, values in configured_sprites.items():
            value_list = [values] if isinstance(values, str) else list(values)
            layers: list[Path] = []
            for value in value_list:
                path = _resolve_asset(project_root, game_root, game_root, str(value))
                if path is None:
                    raise FileNotFoundError(
                        f"Configured sprite layer for {name!r} was not found: {value}"
                    )
                layers.append(path)
            normalized = _normal_name(str(name))
            image_files[normalized] = tuple(layers)
            used_sprites.add(normalized)

    all_scene_names = {name[3:] for name in image_files if name.startswith("bg ")}
    selected_scene_names = used_scenes & all_scene_names
    if not selected_scene_names:
        selected_scene_names = all_scene_names
    scenes = {
        name: image_files[f"bg {name}"][0]
        for name in sorted(selected_scene_names)
        if f"bg {name}" in image_files
    }
    scene_media = {
        name[3:]: path
        for name, path in movie_sources.items()
        if name.startswith("bg ") and name[3:] in used_scenes
    }
    scene_media.update(manual_movie_scenes)

    inferred_character_tags = set(character_image_tags)
    representative_by_tag: dict[str, str | None] = {}
    review_tags = set(candidate_tags) | inferred_character_tags | layered_tags
    for tag in sorted(review_tags):
        representative = next(
            (
                str(layers[0])
                for name, layers in sorted(image_files.items())
                if not name.startswith("bg ") and name.split()[0] == tag and layers
            ),
            None,
        )
        representative_by_tag[tag] = representative

    explicit_character_tags: set[str] = set()
    configured_tags = config.get("character_tags", [])
    if isinstance(configured_tags, list):
        for raw_tag in configured_tags:
            parts = _normal_name(str(raw_tag)).split()
            if parts:
                explicit_character_tags.add(parts[0])
    selection_mode = str(config.get("character_selection", "automatic")).strip().lower()
    if selection_mode not in {"automatic", "manual"}:
        raise ValueError("character_selection must be 'automatic' or 'manual'")
    auto_include = config.get("auto_include_new_characters")
    if auto_include is not None:
        if not isinstance(auto_include, bool):
            raise ValueError("auto_include_new_characters must be true or false")
        selection_mode = "automatic" if auto_include else "manual"
    excluded_character_tags = set()
    excluded = config.get("excluded_character_tags", [])
    if isinstance(excluded, list):
        excluded_character_tags = {
            parts[0] for value in excluded if (parts := _normal_name(str(value)).split())
        }
    explicit_character_tags.difference_update(excluded_character_tags)
    if selection_mode == "manual":
        character_image_tags = set(explicit_character_tags)
    else:
        character_image_tags.update(explicit_character_tags)
    character_image_tags.difference_update(excluded_character_tags)
    for tag in explicit_character_tags:
        representative_by_tag.setdefault(tag, None)

    if selection_mode == "manual":
        exact_used = {
            name
            for name in image_files
            if not name.startswith("bg ") and name.split()[0] in character_image_tags
        }
    else:
        exact_used = {
            name
            for name in used_sprites & image_files.keys()
            if name.split()[0] in character_image_tags
        }
        if not exact_used:
            exact_used = {
                name
                for name in image_files
                if not name.startswith("bg ") and name.split()[0] in character_image_tags
            }
        # Checking an unusual/effect family is an explicit opt-in even if its
        # forms are not reached by the conservative story parser.
        exact_used.update(
            name
            for name in image_files
            if not name.startswith("bg ") and name.split()[0] in explicit_character_tags
        )
    configured_include = config.get("sprite_include")
    if isinstance(configured_include, list):
        requested = {_normal_name(str(name)) for name in configured_include}
        missing = sorted(requested - image_files.keys())
        if missing:
            raise KeyError("Configured sprite declarations were not found: " + ", ".join(missing))
        exact_used = {name for name in requested if name.split()[0] not in excluded_character_tags}
    sprites = {
        name: SpriteSpec(name, image_files[name])
        for name in sorted(exact_used)
        if not name.startswith("bg ")
    }
    character_tags = sorted(character_image_tags)
    runtime_sprite_names = sorted(
        {
            name
            for name in used_sprites
            if name.split()[0] in character_image_tags and name not in image_files
        }
        | {name for name in layered_images if name.split()[0] in character_image_tags}
    )
    runtime_sprite_sequences: list[list[str]] = []
    for sequence in runtime_sprite_sequences_raw:
        filtered: list[str] = []
        has_character_show = False
        for event in sequence:
            command, _, value = event.partition(" ")
            if command == "scene":
                filtered.append(event)
            elif value.split()[0] in character_image_tags:
                filtered.append(event)
                has_character_show = has_character_show or command == "show"
        if has_character_show:
            runtime_sprite_sequences.append(filtered)

    return ProjectDiscovery(
        project_root=project_root,
        game_root=game_root,
        scenes=scenes,
        sprites=sprites,
        character_tags=character_tags,
        calibration=profile.calibration,
        scene_calibration=dict(profile.scenes or {}),
        strength=profile.normalized_strength(),
        runtime_sprite_names=runtime_sprite_names,
        runtime_sprite_sequences=runtime_sprite_sequences,
        explicit_character_tags=sorted(explicit_character_tags),
        excluded_character_tags=sorted(excluded_character_tags),
        character_candidates=representative_by_tag,
        suggested_character_tags=sorted(inferred_character_tags),
        character_selection=selection_mode,
        requires_runtime_inventory=not source_files or not scenes or not character_tags,
        scene_media=scene_media,
        scene_analysis=scene_analysis,
        unsupported=sorted(set(unsupported)),
    )
