"""OpenGL preview that executes the production SceneLight shader verbatim."""

from __future__ import annotations

import ctypes
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from OpenGL import GL
from PIL import Image
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..calibration import Calibration, color_glow_blur_steps
from ..runtime.live_gpu import Analysis
from ..runtime.shader_stages import supported
from .artifacts import FormArtifacts, SceneArtifacts
from .core import (
    CHROMA_RANGE,
    REFERENCE_ART_MID,
    TILE_SIZE,
    TRANSPORT_GRID_SIZE,
    TRANSPORT_PLANES,
    TRANSPORT_SUBJECT_Y_MAX,
)
from .library import Actor
from .shader_source import (
    BACKGROUND_FRAGMENT,
    BACKGROUND_VERTEX,
    color_glow_fragment_source,
    fragment_source,
    production_shader_sha256,
    transport_blend_fragment_source,
    vertex_source,
)
from .temporal import TemporalSceneBlend, TemporalSceneFrame

CANVAS_SIZE = (1280, 720)


@dataclass
class SceneSprite:
    actor: Actor
    rgba: np.ndarray
    artifacts: FormArtifacts

    def bounds(self) -> tuple[float, float, float, float]:
        height = self.actor.height
        width = height * CANVAS_SIZE[1] / CANVAS_SIZE[0] * self.rgba.shape[1] / self.rgba.shape[0]
        center = self.artifacts.metadata.get("center", (0.5, 0.5))
        return (
            self.actor.horizontal - center[0] * width,
            self.actor.baseline - height,
            width,
            height,
        )


def scene_emitters(sprites: list[SceneSprite], receiver_id: str):
    sources = []
    for sprite in sprites:
        actor = sprite.actor
        light = actor.calibration
        if (
            not actor.visible
            or actor.id == receiver_id
            or light.emission_strength <= 0
            or light.emission_radius <= 0
        ):
            continue
        x, y, width, height = sprite.bounds()
        sources.append(
            (
                actor.id,
                (x + width * 0.5, y + height * 0.5, light.emission_radius, light.emission_strength),
                (light.emission_red, light.emission_green, light.emission_blue),
            )
        )
    sources.sort(key=lambda source: (-source[1][3], source[0]))
    return tuple((data, color) for _id, data, color in sources[:4])


REQUIRED_SHADER_FUNCTIONS = (
    "glCreateShader",
    "glShaderSource",
    "glCompileShader",
    "glCreateProgram",
    "glLinkProgram",
    "glGenVertexArrays",
    "glBindVertexArray",
)


def _require_shader_api() -> None:
    """Fail clearly when a VM exposes a window but no shader-capable OpenGL."""

    missing: list[str] = []
    for name in REQUIRED_SHADER_FUNCTIONS:
        function = getattr(GL, name, None)
        try:
            available = function is not None and bool(function)
        except (TypeError, ValueError):
            available = False
        if not available:
            missing.append(name)
    if missing:
        raise RuntimeError(
            "This computer's graphics driver does not expose the OpenGL shader functions "
            "SceneLight Preview needs. Windows Sandbox can show a desktop while still "
            "providing only legacy OpenGL. Preview requires a normal GPU driver or a full "
            "virtual machine with working 3D acceleration."
        )


def _compile_shader(kind: int, source: str) -> int:
    shader = GL.glCreateShader(kind)
    GL.glShaderSource(shader, source)
    GL.glCompileShader(shader)
    if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(shader)
        GL.glDeleteShader(shader)
        raise RuntimeError(log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log))
    return shader


def _link_program(vertex: str, fragment: str) -> int:
    vertex_shader = _compile_shader(GL.GL_VERTEX_SHADER, vertex)
    try:
        fragment_shader = _compile_shader(GL.GL_FRAGMENT_SHADER, fragment)
    except BaseException:
        GL.glDeleteShader(vertex_shader)
        raise
    program = GL.glCreateProgram()
    GL.glAttachShader(program, vertex_shader)
    GL.glAttachShader(program, fragment_shader)
    GL.glLinkProgram(program)
    GL.glDeleteShader(vertex_shader)
    GL.glDeleteShader(fragment_shader)
    if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(program)
        GL.glDeleteProgram(program)
        raise RuntimeError(log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log))
    return program


def _sprite_program() -> int:
    try:
        if supported(
            int(GL.glGetIntegerv(GL.GL_MAX_FRAGMENT_INPUT_COMPONENTS)),
            int(GL.glGetIntegerv(GL.GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS)),
        ):
            return _link_program(
                vertex_source(center_samples=True), fragment_source(center_samples=True)
            )
    except Exception:
        pass  # A driver may advertise limits that this complete shader exceeds.
    return _link_program(vertex_source(), fragment_source())


class SceneLightGPUView(QOpenGLWidget):
    placementChanged = Signal(float, float, float)
    frameTimeChanged = Signal(float)
    rendererReady = Signal(str)
    rendererError = Signal(str)
    liveAnalysisFailed = Signal(str)
    liveAnalysisFinished = Signal(float)
    spriteSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 360)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._program = 0
        self._color_glow_program = 0
        self._color_glow_mask_program = 0
        self._color_glow_blur_program = 0
        self._flat_sprite_program = 0
        self._color_glow_fbo = 0
        self._color_glow_targets = ()
        self._color_glow_size = None
        self._color_glow_target_cache = OrderedDict()
        self._scene_sprites: list[SceneSprite] | None = None
        self._scene_active_id: str | None = None
        self._scene_texture_cache = OrderedDict()
        self._background_program = 0
        self._transport_blend_program = 0
        self._transport_fbo = 0
        self._transport_rendered_key = None
        self._vao = 0
        self._vbo = 0
        self._textures: dict[str, int] = {}
        self._texture_sizes: dict[str, tuple[int, int]] = {}
        self._uniform_locations: dict[tuple[int, str], int] = {}
        self._uniform_values: dict[tuple[int, str], tuple[float, ...]] = {}
        self._sampler_units: dict[tuple[int, str], int] = {}
        self._background_path: Path | None = None
        self._sprite_path: Path | None = None
        self._background_frame: np.ndarray | None = None
        self._background_wrap_frame: np.ndarray | None = None
        self._irradiance_frame: np.ndarray | None = None
        self._emitter_frame: np.ndarray | None = None
        self._transport_frame: np.ndarray | None = None
        self._live_scene_metadata: dict[str, object] | None = None
        self._scene_blend: TemporalSceneBlend | None = None
        self._sprite_frame: np.ndarray | None = None
        self._form_frame_cache: OrderedDict[Path, dict[str, np.ndarray]] = OrderedDict()
        self._form_texture_cache: OrderedDict[Path, dict[str, tuple[int, tuple[int, int]]]] = (
            OrderedDict()
        )
        self._sprite_frame_cache: OrderedDict[Path, np.ndarray] = OrderedDict()
        self._scene_artifacts: SceneArtifacts | None = None
        self._form_artifacts: FormArtifacts | None = None
        self._sprite_source_size = (1, 1)
        self._horizontal = 0.50
        self._baseline = 1.04
        self._character_height = 0.92
        self._strength = 1.0
        self._calibration = Calibration()
        self._sprite_emitters = ()
        self._compare_mode = 0.0
        self._live_background = False
        self._drag_origin: QPointF | None = None
        self._viewport_qt = (0.0, 0.0, 1.0, 1.0)
        self._initialized = False
        self._analyzer: Analysis | None = None
        self._live_analysis_supported = False
        self._live_analysis_enabled = False
        self._using_live_analysis = False
        self._live_analysis_error = ""
        self._borrowed_textures: set[str] = set()
        self._background_generation = 0
        self._background_dirty = False
        self._analyzed_generation = -1
        self._live_history: tuple[int, ...] = ()
        self._prepared_fields = None
        self._prepared_dirty = False

    @property
    def live_analysis_supported(self) -> bool:
        return self._live_analysis_supported

    def set_sprite_emitters(self, emitters) -> None:
        """Set up to four (x, y, radius, strength), RGB source pairs for rendering."""
        self._sprite_emitters = tuple(emitters)[:4]
        self.update()

    def set_scene_sprites(
        self, sprites: list[SceneSprite] | None, active_id: str | None = None
    ) -> None:
        self._scene_sprites = sprites
        self._scene_active_id = active_id
        self.update()

    def set_live_analysis_enabled(self, enabled: bool) -> None:
        self._prepared_fields = None
        self._live_analysis_enabled = bool(enabled and self._live_analysis_supported)
        self._using_live_analysis = False
        self._analyzed_generation = -1
        self._live_history = ()
        self.update()

    def reset_live_history(self) -> None:
        """Start a new source/seek timeline without borrowing its previous light ordering."""
        self._live_history = ()
        self._analyzed_generation = -1

    @property
    def shader_sha256(self) -> str:
        return production_shader_sha256()

    def set_scene(self, source: Path, artifacts: SceneArtifacts) -> None:
        self._background_path = source
        self._scene_artifacts = artifacts
        self._irradiance_frame = None
        self._emitter_frame = None
        self._transport_frame = None
        self._live_scene_metadata = None
        self._scene_blend = None
        self._transport_rendered_key = None
        self._reload_if_ready()

    def clear_scene(self) -> None:
        """Stop drawing a sprite until artifacts for a newly loaded scene arrive."""

        self._scene_artifacts = None
        self._prepared_fields = None
        self._using_live_analysis = False
        self._irradiance_frame = None
        self._emitter_frame = None
        self._transport_frame = None
        self._live_scene_metadata = None
        self._scene_blend = None
        self.update()

    def set_sprite(self, source: Path, artifacts: FormArtifacts) -> None:
        self._sprite_path = source
        with Image.open(source) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        self.set_sprite_frame(rgba, artifacts)

    def clear_sprite(self) -> None:
        """Stop drawing stale form shading while a new sprite is reconstructed."""

        self._form_artifacts = None
        self.update()

    def set_live_background(self, enabled: bool) -> None:
        self._live_background = bool(enabled)
        self.update()

    def set_background_frame(self, rgba: np.ndarray, wrap: np.ndarray | None = None) -> None:
        self._background_frame = np.ascontiguousarray(rgba, dtype=np.uint8)
        self._background_generation += 1
        self._background_dirty = True
        self._background_wrap_frame = (
            np.ascontiguousarray(wrap, dtype=np.uint8) if wrap is not None else None
        )
        # Upload in paintGL's existing context. Switching contexts here for
        # every decoded frame forces extra driver synchronization before paint.
        self.update()

    def set_prepared_fields(self, fields: dict[str, bytes]) -> None:
        """Queue exact GPU analyzer bytes alongside the decoded background frame."""
        self._live_analysis_enabled = False
        self._scene_blend = None
        self._prepared_fields = fields
        self._prepared_dirty = True
        self.update()

    def set_live_scene_frame(self, scene: TemporalSceneFrame) -> None:
        """Replace every background-dependent shader input at animation time."""

        self._scene_blend = None
        self._transport_rendered_key = None
        self._irradiance_frame = np.ascontiguousarray(scene.irradiance, dtype=np.uint8)
        self._emitter_frame = np.ascontiguousarray(scene.emitter, dtype=np.uint8)
        self._transport_frame = np.ascontiguousarray(scene.transport, dtype=np.uint8)
        self._live_scene_metadata = dict(scene.metadata)
        if self._initialized:
            self.makeCurrent()
            try:
                self._replace_texture("irradiance", self._irradiance_frame)
                self._replace_texture("emitter", self._emitter_frame)
                self._replace_texture("transport", self._transport_frame)
            finally:
                self.doneCurrent()
        self.update()

    def set_live_scene_blend(self, scene: TemporalSceneBlend) -> None:
        """Retain endpoint textures; animation ticks change only the blend uniforms."""
        previous = self._scene_blend
        self._scene_blend = scene
        self._live_scene_metadata = scene.metadata
        if previous is None or previous.left is not scene.left or previous.right is not scene.right:
            for name in ("irradiance", "emitter", "transport"):
                left, right = getattr(scene.left, name), getattr(scene.right, name)
                value = left if scene.left is scene.right else np.concatenate((left, right), axis=1)
                setattr(self, f"_{name}_frame", np.ascontiguousarray(value, dtype=np.uint8))
            if self._initialized:
                self.makeCurrent()
                try:
                    for name in ("irradiance", "emitter", "transport"):
                        key = "transport_pair" if name == "transport" else name
                        self._replace_texture(key, getattr(self, f"_{name}_frame"))
                finally:
                    self.doneCurrent()
        self.update()

    def set_live_transport_frame(self, transport: np.ndarray) -> None:
        """Compatibility path for an encoded transport-only caller."""

        self._transport_frame = np.ascontiguousarray(transport, dtype=np.uint8)
        if self._initialized:
            self.makeCurrent()
            try:
                self._replace_texture("transport", self._transport_frame)
            finally:
                self.doneCurrent()
        self.update()

    def set_sprite_frame(
        self,
        rgba: np.ndarray,
        artifacts: FormArtifacts | None = None,
    ) -> None:
        self._sprite_frame = np.ascontiguousarray(rgba, dtype=np.uint8)
        if artifacts is not None:
            self._form_artifacts = artifacts
        if self._initialized:
            self.makeCurrent()
            try:
                self._replace_texture(
                    "source",
                    self._sprite_upload_frame(self._sprite_frame, artifacts),
                )
                self._sprite_source_size = (
                    int(self._sprite_frame.shape[1]),
                    int(self._sprite_frame.shape[0]),
                )
                if artifacts is not None:
                    self._activate_form_textures(artifacts)
            finally:
                self.doneCurrent()
        self.update()

    def set_placement(self, horizontal: float, baseline: float, character_height: float) -> None:
        self._horizontal = min(max(float(horizontal), -0.25), 1.25)
        self._baseline = min(max(float(baseline), 0.20), 1.40)
        self._character_height = min(max(float(character_height), 0.10), 1.35)
        self.update()

    def set_strength(self, strength: float) -> None:
        self._strength = min(max(float(strength), 0.0), 2.0)
        self.update()

    def set_calibration(self, calibration: Calibration) -> None:
        self._calibration = calibration.normalized()
        self.update()

    def set_compare_mode(self, mode: int) -> None:
        self._compare_mode = float(min(max(int(mode), 0), 2))
        self.update()

    def initializeGL(self) -> None:
        try:
            _require_shader_api()
            # Framebuffer names belong to the context, unlike shared textures.
            # Qt can recreate the widget context when it changes top-level window.
            self._transport_fbo = 0
            self._color_glow_fbo = 0
            self._color_glow_targets = ()
            self._color_glow_size = None
            self._color_glow_target_cache.clear()
            self._transport_rendered_key = None
            self._program = _sprite_program()
            self._background_program = _link_program(BACKGROUND_VERTEX, BACKGROUND_FRAGMENT)
            self._flat_sprite_program = _link_program(
                vertex_source(), BACKGROUND_FRAGMENT.replace("v_uv", "v_tex_coord")
            )
            self._color_glow_program = _link_program(
                BACKGROUND_VERTEX.replace("v_uv", "v_tex_coord").replace(
                    "1.0 - in_unit.y * 2.0", "in_unit.y * 2.0 - 1.0"
                ),
                color_glow_fragment_source(),
            )
            for field, stage in (
                ("_color_glow_mask_program", "mask"),
                ("_color_glow_blur_program", "blur"),
            ):
                setattr(
                    self,
                    field,
                    _link_program(
                        BACKGROUND_VERTEX.replace("v_uv", "v_tex_coord").replace(
                            "1.0 - in_unit.y * 2.0", "in_unit.y * 2.0 - 1.0"
                        ),
                        color_glow_fragment_source(stage),
                    ),
                )
            self._transport_blend_program = _link_program(
                BACKGROUND_VERTEX.replace("v_uv", "v_tex_coord").replace(
                    "1.0 - in_unit.y * 2.0", "in_unit.y * 2.0 - 1.0"
                ),
                transport_blend_fragment_source(),
            )
            self._uniform_locations.clear()
            self._uniform_values.clear()
            self._sampler_units.clear()
            vertices = np.asarray(
                (
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                ),
                dtype=np.float32,
            )
            self._vao = GL.glGenVertexArrays(1)
            self._vbo = GL.glGenBuffers(1)
            GL.glBindVertexArray(self._vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)
            for program in (
                self._program,
                self._background_program,
                self._transport_blend_program,
                self._color_glow_program,
                self._flat_sprite_program,
                self._color_glow_mask_program,
                self._color_glow_blur_program,
            ):
                for name, offset in (("in_unit", 0), ("in_uv", 2 * vertices.itemsize)):
                    location = GL.glGetAttribLocation(program, name)
                    if location >= 0:
                        GL.glEnableVertexAttribArray(location)
                        GL.glVertexAttribPointer(
                            location,
                            2,
                            GL.GL_FLOAT,
                            GL.GL_FALSE,
                            4 * vertices.itemsize,
                            ctypes.c_void_p(offset),
                        )
            GL.glBindVertexArray(0)
            self._initialized = True
            self._load_all_textures()
            self._prepared_dirty = self._prepared_fields is not None
            try:
                self._analyzer = Analysis()
                self._live_analysis_supported = True
                self.context().aboutToBeDestroyed.connect(self._cleanup_live_analysis)
            except Exception as error:
                if self._analyzer is not None:
                    self._analyzer.device.close()
                self._analyzer = None
                self._live_analysis_supported = False
                if self._live_analysis_enabled:
                    self._live_analysis_enabled = False
                    self._live_analysis_error = str(error)
                    self.liveAnalysisFailed.emit(str(error))
            vendor = GL.glGetString(GL.GL_VENDOR).decode("utf-8", "replace")
            renderer = GL.glGetString(GL.GL_RENDERER).decode("utf-8", "replace")
            self.rendererReady.emit(f"{vendor} · {renderer}")
        except Exception as error:  # OpenGL errors need to reach the visible UI.
            self.rendererError.emit(str(error))
            raise

    def _reload_if_ready(self) -> None:
        if not self._initialized:
            return
        self.makeCurrent()
        try:
            self._load_all_textures()
        finally:
            self.doneCurrent()
        self.update()

    def _delete_textures(self) -> None:
        self._transport_rendered_key = None
        texture_ids = {
            value for key, value in self._textures.items() if key not in self._borrowed_textures
        }
        for cached in self._form_texture_cache.values():
            texture_ids.update(texture for texture, _size in cached.values())
        for cached in self._scene_texture_cache.values():
            texture_ids.update(texture for texture, _size in cached.values())
        if texture_ids:
            GL.glDeleteTextures(list(texture_ids))
        self._textures.clear()
        self._texture_sizes.clear()
        self._form_texture_cache.clear()
        self._scene_texture_cache.clear()
        self._borrowed_textures.clear()
        self._using_live_analysis = False
        self._analyzed_generation = -1

    def _delete_color_glow_targets(self) -> None:
        for targets in self._color_glow_target_cache.values():
            GL.glDeleteTextures(list(targets))
        self._color_glow_target_cache.clear()
        self._color_glow_targets = ()
        self._color_glow_size = None
        if self._color_glow_fbo:
            GL.glDeleteFramebuffers(1, [self._color_glow_fbo])
            self._color_glow_fbo = 0

    def _store_texture(
        self, key: str, texture: int, size: tuple[int, int], *, borrowed=False
    ) -> None:
        previous = self._textures.get(key)
        if previous and previous != texture and key not in self._borrowed_textures:
            GL.glDeleteTextures([previous])
        self._borrowed_textures.discard(key)
        if borrowed:
            self._borrowed_textures.add(key)
        self._textures[key] = texture
        self._texture_sizes[key] = size

    @staticmethod
    def _texture_rgba(rgba: np.ndarray, *, premultiply: bool = False) -> np.ndarray:
        array = np.asarray(rgba, dtype=np.uint8)
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            raise ValueError("Texture frames must be H×W RGB or RGBA arrays")
        if array.shape[2] == 3:
            alpha = np.full(array.shape[:2] + (1,), 255, dtype=np.uint8)
            array = np.concatenate((array, alpha), axis=2)
        elif premultiply:
            array = array.copy()
        if premultiply:
            alpha = array[..., 3:4].astype(np.uint16)
            array[..., :3] = ((array[..., :3].astype(np.uint16) * alpha + 127) // 255).astype(
                np.uint8
            )
        return np.ascontiguousarray(array)

    def _form_arrays(self, artifacts: FormArtifacts) -> dict[str, np.ndarray]:
        key = artifacts.root.resolve()
        cached = self._form_frame_cache.get(key)
        if cached is not None:
            self._form_frame_cache.move_to_end(key)
            return cached
        decoded: dict[str, np.ndarray] = {}
        for name in ("normal_noise", "height_ao_edge", "response"):
            with Image.open(artifacts.image(name)) as image:
                decoded[name] = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        self._form_frame_cache[key] = decoded
        self._form_frame_cache.move_to_end(key)
        while len(self._form_frame_cache) > 8:
            self._form_frame_cache.popitem(last=False)
        return decoded

    def _sprite_upload_frame(self, rgba: np.ndarray, artifacts: FormArtifacts | None) -> np.ndarray:
        if artifacts is None:
            return self._texture_rgba(rgba, premultiply=True)
        key = artifacts.root.resolve()
        cached = self._sprite_frame_cache.get(key)
        if cached is not None:
            self._sprite_frame_cache.move_to_end(key)
            return cached
        premultiplied = self._texture_rgba(rgba, premultiply=True)
        self._sprite_frame_cache[key] = premultiplied
        self._sprite_frame_cache.move_to_end(key)
        while len(self._sprite_frame_cache) > 8:
            self._sprite_frame_cache.popitem(last=False)
        return premultiplied

    def _activate_form_textures(self, artifacts: FormArtifacts) -> None:
        """Bind one frame's form maps without re-uploading warmed animation frames."""

        key = artifacts.root.resolve()
        cached = self._form_texture_cache.get(key)
        if cached is None:
            cached = {
                name: self._upload_array(array)
                for name, array in self._form_arrays(artifacts).items()
            }
            self._form_texture_cache[key] = cached
            while len(self._form_texture_cache) > 8:
                _old_key, old = self._form_texture_cache.popitem(last=False)
                GL.glDeleteTextures([texture for texture, _size in old.values()])
        else:
            self._form_texture_cache.move_to_end(key)
        for name, (texture, size) in cached.items():
            self._textures[name] = texture
            self._texture_sizes[name] = size

    @classmethod
    def _upload_array(
        cls, rgba: np.ndarray, *, premultiply: bool = False
    ) -> tuple[int, tuple[int, int]]:
        array = cls._texture_rgba(rgba, premultiply=premultiply)
        texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA8,
            array.shape[1],
            array.shape[0],
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            array,
        )
        return texture, (array.shape[1], array.shape[0])

    def _replace_texture(self, key: str, rgba: np.ndarray, *, premultiply: bool = False) -> None:
        array = self._texture_rgba(rgba, premultiply=premultiply)
        size = (array.shape[1], array.shape[0])
        if (
            key in self._textures
            and key not in self._borrowed_textures
            and self._texture_sizes.get(key) == size
        ):
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._textures[key])
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D,
                0,
                0,
                0,
                size[0],
                size[1],
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                array,
            )
            return
        texture, uploaded_size = self._upload_array(array)
        self._store_texture(key, texture, uploaded_size)

    @staticmethod
    def _upload_texture(path: Path, *, premultiply: bool = False) -> tuple[int, tuple[int, int]]:
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        return SceneLightGPUView._upload_array(rgba, premultiply=premultiply)

    def _load_all_textures(self) -> None:
        self._delete_textures()
        if self._background_frame is not None:
            texture, size = self._upload_array(self._background_frame)
            self._store_texture("background", texture, size)
            self._background_dirty = False
        elif self._background_path is not None:
            texture, _size = self._upload_texture(self._background_path)
            self._store_texture("background", texture, _size)
        if self._scene_artifacts is not None:
            for name in ("irradiance", "emitter", "wrap", "transport"):
                texture, size = self._upload_texture(self._scene_artifacts.image(name))
                self._store_texture(name, texture, size)
        if self._irradiance_frame is not None:
            texture, size = self._upload_array(self._irradiance_frame)
            self._store_texture("irradiance", texture, size)
        if self._emitter_frame is not None:
            texture, size = self._upload_array(self._emitter_frame)
            self._store_texture("emitter", texture, size)
        if self._transport_frame is not None:
            texture, size = self._upload_array(self._transport_frame)
            self._store_texture(
                "transport_pair" if self._scene_blend is not None else "transport", texture, size
            )
        if self._background_wrap_frame is not None:
            texture, size = self._upload_array(self._background_wrap_frame)
            self._store_texture("wrap", texture, size)
        if self._sprite_frame is not None:
            texture, size = self._upload_array(
                self._sprite_upload_frame(self._sprite_frame, self._form_artifacts)
            )
            self._store_texture("source", texture, size)
            self._sprite_source_size = size
        elif self._sprite_path is not None:
            texture, size = self._upload_texture(self._sprite_path, premultiply=True)
            self._store_texture("source", texture, size)
            self._sprite_source_size = size
        if self._form_artifacts is not None:
            self._activate_form_textures(self._form_artifacts)

    def _canvas_viewport(self) -> tuple[int, int, int, int]:
        device_width = max(1, int(self.width() * self.devicePixelRatioF()))
        device_height = max(1, int(self.height() * self.devicePixelRatioF()))
        target_aspect = CANVAS_SIZE[0] / CANVAS_SIZE[1]
        if device_width / device_height > target_aspect:
            height = device_height
            width = round(height * target_aspect)
        else:
            width = device_width
            height = round(width / target_aspect)
        x = (device_width - width) // 2
        y = (device_height - height) // 2
        scale = self.devicePixelRatioF()
        self._viewport_qt = (x / scale, y / scale, width / scale, height / scale)
        return x, y, width, height

    def paintGL(self) -> None:
        started = time.perf_counter()
        device_width = max(1, int(self.width() * self.devicePixelRatioF()))
        device_height = max(1, int(self.height() * self.devicePixelRatioF()))
        GL.glViewport(0, 0, device_width, device_height)
        GL.glDisable(GL.GL_BLEND)
        GL.glClearColor(0.018, 0.024, 0.032, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glViewport(*self._canvas_viewport())
        self._draw_scene()
        self.frameTimeChanged.emit((time.perf_counter() - started) * 1000.0)

    def _prepare_transport_frame(self) -> None:
        blend = self._scene_blend
        if blend is None or "transport_pair" not in self._textures:
            return
        key = (
            id(blend.left),
            id(blend.right),
            blend.amount,
            blend.layout_change,
            self._textures["transport_pair"],
        )
        if key == self._transport_rendered_key:
            return
        width, height = TRANSPORT_GRID_SIZE[0] * TRANSPORT_PLANES, TRANSPORT_GRID_SIZE[1]
        if self._texture_sizes.get("transport") != (width, height):
            self._replace_texture("transport", np.zeros((height, width, 4), dtype=np.uint8))
        if not self._transport_fbo:
            self._transport_fbo = GL.glGenFramebuffers(1)
        previous_fbo = int(GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING))
        previous_viewport = tuple(GL.glGetIntegerv(GL.GL_VIEWPORT))
        try:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._transport_fbo)
            GL.glFramebufferTexture2D(
                GL.GL_FRAMEBUFFER,
                GL.GL_COLOR_ATTACHMENT0,
                GL.GL_TEXTURE_2D,
                self._textures["transport"],
                0,
            )
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("Temporal lighting framebuffer is incomplete")
            GL.glViewport(0, 0, width, height)
            GL.glDisable(GL.GL_BLEND)
            GL.glBindVertexArray(self._vao)
            GL.glUseProgram(self._transport_blend_program)
            self._bind_texture(self._transport_blend_program, "tex1", 1, "transport_pair")
            columns = 1 if blend.left is blend.right else 2
            for name, value in (
                ("u_sc_field_left", (0.0, 0.0, 1.0 / columns, 1.0)),
                ("u_sc_field_right", (1.0 - 1.0 / columns, 0.0, 1.0 / columns, 1.0)),
            ):
                location = self._uniform_location(self._transport_blend_program, name)
                GL.glUniform4f(location, *value)
            GL.glUniform1f(
                self._uniform_location(self._transport_blend_program, "u_sc_field_amount"),
                blend.amount,
            )
            GL.glUniform1f(
                self._uniform_location(self._transport_blend_program, "u_sc_field_layout_change"),
                float(blend.layout_change),
            )
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            self._transport_rendered_key = key
        finally:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, previous_fbo)
            GL.glViewport(*previous_viewport)

    def _draw_scene(self) -> None:
        if self._background_dirty and self._background_frame is not None:
            self._replace_texture("background", self._background_frame)
            if self._background_wrap_frame is not None and not self._live_analysis_enabled:
                self._replace_texture("wrap", self._background_wrap_frame)
            self._background_dirty = False
        if self._prepared_fields is not None and self._prepared_dirty:
            for key, raw in self._prepared_fields.items():
                height, width = (10, 416) if key == "transport" else (90, 160)
                self._replace_texture(key, np.frombuffer(raw, np.uint8).reshape(height, width, 4))
            self._prepared_dirty = False
            self._using_live_analysis = True
        if self._live_analysis_enabled:
            self._prepare_live_analysis()
        else:
            self._prepare_transport_frame()
        GL.glBindVertexArray(self._vao)
        if "background" in self._textures:
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(self._background_program)
            self._bind_texture(self._background_program, "background_texture", 0, "background")
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        if self._scene_sprites is None:
            self._draw_sprite()
        else:
            self._draw_scene_sprites()

    def _draw_scene_sprites(self) -> None:
        fields = (
            "_form_artifacts",
            "_sprite_source_size",
            "_horizontal",
            "_baseline",
            "_character_height",
            "_strength",
            "_calibration",
            "_sprite_emitters",
        )
        saved = {name: getattr(self, name) for name in fields}
        textures, sizes = dict(self._textures), dict(self._texture_sizes)
        try:
            for sprite in self._scene_sprites:
                actor = sprite.actor
                if not actor.visible:
                    continue
                key = sprite.artifacts.root.resolve()
                cached = self._scene_texture_cache.get(key)
                if cached is None:
                    arrays = self._form_arrays(sprite.artifacts)
                    cached = {name: self._upload_array(array) for name, array in arrays.items()}
                    cached["source"] = self._upload_array(sprite.rgba, premultiply=True)
                    self._scene_texture_cache[key] = cached
                self._scene_texture_cache.move_to_end(key)
                for name, (texture, size) in cached.items():
                    self._textures[name], self._texture_sizes[name] = texture, size
                self._form_artifacts = sprite.artifacts
                self._sprite_source_size = (sprite.rgba.shape[1], sprite.rgba.shape[0])
                self._horizontal, self._baseline = actor.horizontal, actor.baseline
                self._character_height = actor.height
                self._strength, self._calibration = actor.strength, actor.calibration
                self._sprite_emitters = scene_emitters(self._scene_sprites, actor.id)
                self._draw_sprite()
            active = {
                sprite.artifacts.root.resolve()
                for sprite in self._scene_sprites
                if sprite.actor.visible
            }

            def texture_bytes(cached):
                return sum(size[0] * size[1] * 4 for _texture, size in cached.values())

            used_bytes = sum(texture_bytes(cached) for cached in self._scene_texture_cache.values())
            for key in list(self._scene_texture_cache):
                if len(self._scene_texture_cache) <= 32 and used_bytes <= 128 * 1024 * 1024:
                    break
                if key not in active:
                    cached = self._scene_texture_cache.pop(key)
                    used_bytes -= texture_bytes(cached)
                    GL.glDeleteTextures([texture for texture, _size in cached.values()])
        finally:
            for name, value in saved.items():
                setattr(self, name, value)
            self._textures, self._texture_sizes = textures, sizes

    def _draw_sprite(self) -> None:
        required = {
            "source",
            "irradiance",
            "emitter",
            "normal_noise",
            "height_ao_edge",
            "response",
            "wrap",
            "transport",
        }
        if (
            not required.issubset(self._textures)
            or (self._scene_artifacts is None and not self._using_live_analysis)
            or self._form_artifacts is None
        ):
            return

        GL.glEnable(GL.GL_BLEND)
        GL.glBlendEquation(GL.GL_FUNC_ADD)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glUseProgram(self._program)
        for unit, (uniform, key) in enumerate(
            (
                ("tex0", "source"),
                ("tex1", "irradiance"),
                ("tex2", "emitter"),
                ("tex3", "normal_noise"),
                ("tex4", "height_ao_edge"),
                ("tex5", "response"),
                ("tex6", "wrap"),
                ("tex7", "transport"),
            )
        ):
            self._bind_texture(self._program, uniform, unit, key)

        form = self._form_artifacts.metadata
        scene = self._live_scene_metadata or (
            self._scene_artifacts.metadata if self._scene_artifacts else {}
        )
        source_width, source_height = self._sprite_source_size
        sprite_height = CANVAS_SIZE[1] * self._character_height
        sprite_width = sprite_height * source_width / max(source_height, 1)
        form_center = tuple(form.get("center", (0.5, 0.5)))
        sprite_x = self._horizontal * CANVAS_SIZE[0] - form_center[0] * sprite_width
        sprite_y = self._baseline * CANVAS_SIZE[1] - sprite_height

        self._uniform("u_canvas_size", CANVAS_SIZE)
        self._uniform("u_sc_render_local", 0.0)
        self._uniform("u_sprite_position", (sprite_x, sprite_y))
        self._uniform("u_sprite_size", (sprite_width, sprite_height))
        self._uniform("u_sc_sprite_size", self._sprite_source_size)
        self._uniform("u_lod_bias", 0.0)
        blend = None if self._using_live_analysis else self._scene_blend
        columns = 2 if blend is not None and blend.left is not blend.right else 1
        self._uniform("u_sc_scene_uv", (0.0, 0.0, 1.0 / columns, 1.0))
        self._uniform("u_sc_wrap_uv", (0.0, 0.0, 1.0, 1.0))
        self._uniform("u_sc_wrap_uv_next", (0.0, 0.0, 1.0, 1.0))
        wrap_size = self._texture_sizes["wrap"]
        self._uniform("u_sc_wrap_texel", (1.0 / wrap_size[0], 1.0 / wrap_size[1]))
        self._uniform("u_sc_wrap_blend", 0.0)
        self._uniform("u_sc_scene_uv_next", (1.0 - 1.0 / columns, 0.0, 1.0 / columns, 1.0))
        self._uniform("u_sc_scene_blend", blend.amount if blend is not None else 0.0)
        self._uniform("u_sc_atlas_texel", (1.0 / (TILE_SIZE[0] * columns), 1.0 / TILE_SIZE[1]))
        self._uniform("u_sc_reference_mid", REFERENCE_ART_MID)
        self._uniform("u_sc_strength", self._strength)
        # Preview inputs are already the exact pixels selected by the user;
        # there is no outer Ren'Py matrixcolor transform to compensate for.
        self._uniform("u_sc_authored_grade", 0.0)
        self._uniform("u_sc_exposure_owner", 1.0)
        self._uniform("u_sc_exposure_bias_owner", 1.0)
        exposure_calibration = self._calibration.uniform_blocks()[0]
        self._uniform("u_sc_exposure_auto", exposure_calibration[0] * self._strength)
        self._uniform("u_sc_exposure_bias", exposure_calibration[1] * self._strength)
        self._uniform("u_sc_chroma_range", CHROMA_RANGE)
        self._uniform("u_sc_target_range", 0.58)
        self._uniform(
            "u_sc_has_transport",
            0.0 if scene.get("transport_preview") else 1.0,
        )
        self._uniform(
            "u_sc_transport_uv",
            (0.0, 0.0, 1.0 / TRANSPORT_PLANES, 0.9 if self._using_live_analysis else 1.0),
        )
        self._uniform("u_sc_live_analysis", 1.0 if self._using_live_analysis else 0.0)
        self._uniform("u_sc_transport_grid", TRANSPORT_GRID_SIZE)
        self._uniform("u_sc_transport_subject_y_max", TRANSPORT_SUBJECT_Y_MAX)
        self._uniform("u_sc_debug_contrast", 1.0)
        self._uniform("u_sc_compare_mode", self._compare_mode)
        self._uniform(
            "u_sc_glow_data", (self._calibration.glow_strength, self._calibration.glow_radius)
        )
        self._uniform("u_sc_glow_color", self._calibration.uniform_blocks()[7])
        self._uniform("u_sc_screen_aspect", CANVAS_SIZE[0] / CANVAS_SIZE[1])
        for index in range(4):
            data, color = (
                self._sprite_emitters[index]
                if index < len(self._sprite_emitters)
                else ((0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0))
            )
            self._uniform(f"u_sc_sprite_light{index}_data", data)
            self._uniform(f"u_sc_sprite_light{index}_color", color)
        for index, block in enumerate(self._calibration.uniform_blocks()):
            self._uniform(f"u_sc_calibration{index}", block)
        self._uniform("u_sc_live_background", 1.0 if self._live_background else 0.0)
        self._uniform("u_sc_shadow_chroma", scene.get("shadow_chroma", (1.0, 1.0, 1.0)))
        self._uniform("u_sc_local_saturation", scene.get("local_saturation", 0.26))
        self._uniform("u_sc_local_contrast", scene.get("local_contrast", 0.55))
        self._uniform("u_sc_light_confidence", scene.get("light_confidence", 0.5))
        self._uniform("u_sc_source_size", scene.get("source_size", 0.5))
        self._uniform("u_sc_grain", scene.get("grain", 0.0))
        self._uniform("u_sc_sharpness", scene.get("sharpness", 0.0))
        self._uniform("u_sc_local_luminance", scene.get("local_luminance", 0.12))
        self._uniform("u_sc_has_form", 1.0)
        self._uniform("u_sc_form_center", form_center)
        self._uniform("u_sc_mean_form_visibility", form.get("mean_form_visibility", 1.0))
        self._uniform("u_sc_form_contrast_mid", form.get("contrast_mid", REFERENCE_ART_MID))
        self._uniform("u_sc_height_range", form.get("height_range", (-0.25, 1.25)))
        self._uniform("u_sc_noise_range", form.get("noise_range", 4.0))

        lights = list(scene.get("light_transport", ()))[:4]
        while len(lights) < 4:
            lights.append(
                {
                    "position_radius_intensity": (0.5, 0.2, 1.0, 0.0),
                    "chroma_confidence": (1.0, 1.0, 1.0, 0.0),
                    "emission_enabled": (0.0, 0.0),
                }
            )
        for index, light in enumerate(lights):
            self._uniform(f"u_sc_light{index}_data", light["position_radius_intensity"])
            self._uniform(f"u_sc_light{index}_color", light["chroma_confidence"])
            self._uniform(f"u_sc_light{index}_extra", light["emission_enabled"])

        probes = list(scene.get("probe_transport", ()))[:8]
        while len(probes) < 8:
            probes.append(
                {
                    "direction_luminance_enabled": (0.0, -1.0, 0.0, 0.0),
                    "chroma": (1.0, 1.0, 1.0),
                }
            )
        for index, probe in enumerate(probes):
            self._uniform(f"u_sc_probe{index}_data", probe["direction_luminance_enabled"])
            self._uniform(f"u_sc_probe{index}_color", probe["chroma"])

        rules = tuple(
            rule for rule in self._calibration.glow_rules if rule.enabled and rule.strength > 0.0
        )
        if rules and self._compare_mode != 1.0:
            self._draw_color_glow(rules, (sprite_x, sprite_y), (sprite_width, sprite_height))
        else:
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glDisable(GL.GL_BLEND)

    def _draw_color_glow(self, rules, position, size) -> None:
        """Light once, then apply any number of rules against the original source."""
        width, height = self._sprite_source_size
        if self._color_glow_size != (width, height):
            self._color_glow_size = (width, height)
            cached = self._color_glow_target_cache.get((width, height))
            if cached is None:
                cached = tuple(int(v) for v in GL.glGenTextures(4))
                self._color_glow_target_cache[(width, height)] = cached
                for texture in cached:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
                    GL.glTexImage2D(
                        GL.GL_TEXTURE_2D,
                        0,
                        GL.GL_RGBA16F,
                        width,
                        height,
                        0,
                        GL.GL_RGBA,
                        GL.GL_FLOAT,
                        None,
                    )
            self._color_glow_target_cache.move_to_end((width, height))
            self._color_glow_targets = cached
            while len(self._color_glow_target_cache) > 2 and (
                len(self._color_glow_target_cache) > 16
                or sum(w * h * 32 for w, h in self._color_glow_target_cache) > 256 * 1024 * 1024
            ):
                _size, expired = self._color_glow_target_cache.popitem(last=False)
                GL.glDeleteTextures(list(expired))
            # Allocation changes the active texture binding; restore the main
            # shader's sampler before its one and only lighting pass.
            self._bind_texture(self._program, "tex7", 7, "transport")
        if not self._color_glow_fbo:
            self._color_glow_fbo = GL.glGenFramebuffers(1)
        previous_fbo = int(GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING))
        viewport = tuple(GL.glGetIntegerv(GL.GL_VIEWPORT))
        main_program = self._program

        def target(texture):
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._color_glow_fbo)
            GL.glFramebufferTexture2D(
                GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, texture, 0
            )
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("Selective glow framebuffer is incomplete")

        def sampler(program, name, unit, texture):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            GL.glUniform1i(self._uniform_location(program, name), unit)

        try:
            GL.glDisable(GL.GL_BLEND)
            GL.glViewport(0, 0, width, height)
            current, other, mask_a, mask_b = self._color_glow_targets
            target(current)
            self._uniform("u_sc_render_local", 1.0)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            self._uniform("u_sc_render_local", 0.0)
            for rule in rules:
                rule_data = (rule.strength, rule.radius, rule.tolerance, rule.softness)
                target(mask_a)
                self._program = self._color_glow_mask_program
                GL.glUseProgram(self._program)
                sampler(self._program, "tex0", 0, self._textures["source"])
                self._uniform("u_sc_rule_color", rule.color)
                self._uniform("u_sc_rule_data", rule_data)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                self._program = self._color_glow_blur_program
                GL.glUseProgram(self._program)
                for step in color_glow_blur_steps((width, height), rule.radius):
                    for direction in ((step / width, 0.0), (0.0, step / height)):
                        target(mask_b)
                        sampler(self._program, "tex0", 0, mask_a)
                        self._uniform("u_sc_rule_step", direction)
                        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                        mask_a, mask_b = mask_b, mask_a
                target(other)
                self._program = self._color_glow_program
                GL.glUseProgram(self._program)
                sampler(self._program, "tex0", 0, current)
                sampler(self._program, "tex1", 1, self._textures["source"])
                sampler(self._program, "tex2", 2, mask_a)
                self._uniform("u_sc_rule_color", rule.color)
                self._uniform("u_sc_rule_data", rule_data)
                self._uniform("u_sc_rule_compare", self._compare_mode)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                current, other = other, current
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, previous_fbo)
            GL.glViewport(*viewport)
            self._program = self._flat_sprite_program
            GL.glUseProgram(self._program)
            self._uniform("u_canvas_size", CANVAS_SIZE)
            self._uniform("u_sprite_position", position)
            self._uniform("u_sprite_size", size)
            self._uniform("u_sc_render_local", 0.0)
            sampler(self._program, "background_texture", 0, current)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        finally:
            self._program = main_program
            GL.glUseProgram(main_program)
            self._uniform("u_sc_render_local", 0.0)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, previous_fbo)
            GL.glViewport(*viewport)

    def _uniform_location(self, program: int, name: str) -> int:
        key = (program, name)
        location = self._uniform_locations.get(key)
        if location is None:
            location = int(GL.glGetUniformLocation(program, name))
            self._uniform_locations[key] = location
        return location

    def _bind_texture(self, program: int, uniform: str, unit: int, key: str) -> None:
        GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._textures[key])
        sampler_key = (program, uniform)
        location = self._uniform_location(program, uniform)
        if location >= 0 and self._sampler_units.get(sampler_key) != unit:
            GL.glUniform1i(location, unit)
            self._sampler_units[sampler_key] = unit

    def _uniform(self, name: str, value) -> None:
        location = self._uniform_location(self._program, name)
        if location < 0:
            return
        if isinstance(value, (int, float, np.integer, np.floating)):
            values = (float(value),)
        else:
            values = tuple(float(item) for item in value)
        cache_key = (self._program, name)
        if self._uniform_values.get(cache_key) == values:
            return
        if len(values) == 1:
            GL.glUniform1f(location, values[0])
        elif len(values) == 2:
            GL.glUniform2f(location, *values)
        elif len(values) == 3:
            GL.glUniform3f(location, *values)
        elif len(values) == 4:
            GL.glUniform4f(location, *values)
        else:
            raise ValueError(f"Unsupported uniform {name}: {value!r}")
        self._uniform_values[cache_key] = values

    def render_rgba(self, size: tuple[int, int] = CANVAS_SIZE) -> np.ndarray:
        """Render one deterministic full-resolution composite on the GPU."""

        self.makeCurrent()
        framebuffer = GL.glGenFramebuffers(1)
        color = GL.glGenTextures(1)
        try:
            GL.glBindTexture(GL.GL_TEXTURE_2D, color)
            GL.glTexImage2D(
                GL.GL_TEXTURE_2D,
                0,
                GL.GL_RGBA8,
                size[0],
                size[1],
                0,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                None,
            )
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
            GL.glFramebufferTexture2D(
                GL.GL_FRAMEBUFFER,
                GL.GL_COLOR_ATTACHMENT0,
                GL.GL_TEXTURE_2D,
                color,
                0,
            )
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("Could not create the full-resolution export framebuffer")
            GL.glViewport(0, 0, size[0], size[1])
            GL.glClearColor(0.0, 0.0, 0.0, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            expected_live = self._live_analysis_enabled
            self._draw_scene()
            if expected_live and not self._using_live_analysis:
                raise RuntimeError(
                    self._live_analysis_error or "Live scene analysis did not complete"
                )
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            pixels = GL.glReadPixels(0, 0, size[0], size[1], GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            array = np.frombuffer(pixels, dtype=np.uint8).reshape(size[1], size[0], 4)
            return np.ascontiguousarray(np.flipud(array))
        finally:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            GL.glDeleteTextures([color])
            GL.glDeleteFramebuffers(1, [framebuffer])
            self.doneCurrent()
            self.update()

    def export_png(self, destination: Path, size: tuple[int, int] = CANVAS_SIZE) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.render_rgba(size), "RGBA").save(destination)

    def benchmark_frames(self, frame_count: int = 120) -> float:
        """Measure complete live frames, including a forced GPU completion."""

        if frame_count < 1:
            raise ValueError("frame_count must be positive")
        required = {
            "background",
            "source",
            "irradiance",
            "emitter",
            "normal_noise",
            "height_ao_edge",
            "response",
            "wrap",
            "transport",
        }
        if not required.issubset(self._textures):
            raise RuntimeError("Load a background and sprite before benchmarking")
        original_horizontal = self._horizontal
        self.makeCurrent()
        try:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            width = max(1, int(self.width() * self.devicePixelRatioF()))
            height = max(1, int(self.height() * self.devicePixelRatioF()))
            GL.glFinish()
            started = time.perf_counter()
            for frame in range(frame_count):
                phase = frame / max(frame_count - 1, 1)
                self._horizontal = 0.18 + 0.64 * phase
                GL.glViewport(0, 0, width, height)
                GL.glClearColor(0.018, 0.024, 0.032, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                GL.glViewport(*self._canvas_viewport())
                self._draw_scene()
            GL.glFinish()
            return (time.perf_counter() - started) * 1000.0 / frame_count
        finally:
            self._horizontal = original_horizontal
            self.doneCurrent()
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._scene_sprites:
                vx, vy, vw, vh = self._viewport_qt
                point = (
                    (event.position().x() - vx) / max(vw, 1),
                    (event.position().y() - vy) / max(vh, 1),
                )
                for sprite in reversed(self._scene_sprites):
                    x, y, width, height = sprite.bounds()
                    if not sprite.actor.visible or not (
                        x <= point[0] < x + width and y <= point[1] < y + height
                    ):
                        continue
                    px = min(
                        sprite.rgba.shape[1] - 1, int((point[0] - x) / width * sprite.rgba.shape[1])
                    )
                    py = min(
                        sprite.rgba.shape[0] - 1,
                        int((point[1] - y) / height * sprite.rgba.shape[0]),
                    )
                    if sprite.rgba[py, px, 3] > 8:
                        self.spriteSelected.emit(sprite.actor.id)
                        break
            self._drag_origin = event.position()
            self.setFocus()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None:
            return
        _x, _y, width, height = self._viewport_qt
        delta = event.position() - self._drag_origin
        self._drag_origin = event.position()
        self.set_placement(
            self._horizontal + delta.x() / max(width, 1.0),
            self._baseline + delta.y() / max(height, 1.0),
            self._character_height,
        )
        self.placementChanged.emit(self._horizontal, self._baseline, self._character_height)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = None
            event.accept()

    def wheelEvent(self, event) -> None:
        scale = 1.0 + event.angleDelta().y() / 2400.0
        self.set_placement(
            self._horizontal,
            self._baseline,
            self._character_height * max(scale, 0.25),
        )
        self.placementChanged.emit(self._horizontal, self._baseline, self._character_height)
        event.accept()

    def keyPressEvent(self, event) -> None:
        step = 0.004 if event.modifiers() & Qt.ShiftModifier else 0.012
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_A):
            self._horizontal -= step
        elif key in (Qt.Key_Right, Qt.Key_D):
            self._horizontal += step
        elif key in (Qt.Key_Up, Qt.Key_W):
            self._baseline -= step
        elif key in (Qt.Key_Down, Qt.Key_S):
            self._baseline += step
        else:
            return super().keyPressEvent(event)
        self.set_placement(self._horizontal, self._baseline, self._character_height)
        self.placementChanged.emit(self._horizontal, self._baseline, self._character_height)

    def closeEvent(self, event) -> None:
        if self._initialized:
            self.makeCurrent()
            self._delete_textures()
            if self._analyzer is not None:
                self._analyzer.device.close()
                self._analyzer = None
            if self._program:
                GL.glDeleteProgram(self._program)
            if self._background_program:
                GL.glDeleteProgram(self._background_program)
            if self._transport_blend_program:
                GL.glDeleteProgram(self._transport_blend_program)
            if self._color_glow_program:
                GL.glDeleteProgram(self._color_glow_program)
            if self._color_glow_mask_program:
                GL.glDeleteProgram(self._color_glow_mask_program)
            if self._color_glow_blur_program:
                GL.glDeleteProgram(self._color_glow_blur_program)
            if self._flat_sprite_program:
                GL.glDeleteProgram(self._flat_sprite_program)
            self._delete_color_glow_targets()
            if self._transport_fbo:
                GL.glDeleteFramebuffers(1, [self._transport_fbo])
            self._uniform_locations.clear()
            self._uniform_values.clear()
            self._sampler_units.clear()
            if self._vbo:
                GL.glDeleteBuffers(1, [self._vbo])
            if self._vao:
                GL.glDeleteVertexArrays(1, [self._vao])
            self.doneCurrent()
        super().closeEvent(event)

    def _cleanup_live_analysis(self) -> None:
        self.reset_live_history()
        self.makeCurrent()
        self._delete_color_glow_targets()
        self.doneCurrent()
        if self._analyzer is not None:
            self.makeCurrent()
            self._analyzer.device.close()
            self._analyzer = None
            self.doneCurrent()
        for key in self._borrowed_textures:
            self._textures.pop(key, None)
            self._texture_sizes.pop(key, None)
        self._borrowed_textures.clear()
        self._using_live_analysis = False
        self._analyzed_generation = -1

    def _prepare_live_analysis(self) -> None:
        if "background" not in self._textures:
            return
        if self._analyzed_generation == self._background_generation:
            return
        started = time.perf_counter()
        try:
            if self._analyzer is None:
                self._analyzer = Analysis()
            fields = self._analyzer.evaluate(
                self._textures["background"],
                self._texture_sizes["background"],
                preview=True,
                animated=self._live_background,
                previous=self._live_history,
            )
            self._live_history = (fields.pop("_history_lights"), fields.pop("_history_image"))
            for key, texture in fields.items():
                self._store_texture(
                    key, texture, (416, 10) if key == "transport" else (160, 90), borrowed=True
                )
            self._using_live_analysis = True
            self._analyzed_generation = self._background_generation
            self.liveAnalysisFinished.emit((time.perf_counter() - started) * 1000.0)
        except Exception as error:
            self._live_analysis_error = str(error)
            self._live_analysis_enabled = False
            self._live_analysis_supported = False
            self._using_live_analysis = False
            for key in self._borrowed_textures:
                self._textures.pop(key, None)
                self._texture_sizes.pop(key, None)
            self._borrowed_textures.clear()
            if self._analyzer is not None:
                self._analyzer.device.close()
            self._analyzer = None
            self.liveAnalysisFailed.emit(str(error))
