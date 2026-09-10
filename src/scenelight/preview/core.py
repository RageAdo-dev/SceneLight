"""Single-source bridge to SceneLight's production analysis code."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

PRODUCTION_CORE = Path(__file__).resolve().parents[1]

_builder = import_module("scenelight.builder")
_cuda_backend = import_module("scenelight.cuda_backend")
_engine = import_module("scenelight.engine")
_form_maps = import_module("scenelight.form_maps")

CHROMA_RANGE = _builder.CHROMA_RANGE
TILE_SIZE = _builder.TILE_SIZE
TRANSPORT_CHARACTER_HEIGHT = _builder.TRANSPORT_CHARACTER_HEIGHT
TRANSPORT_GRID_SIZE = _builder.TRANSPORT_GRID_SIZE
TRANSPORT_PLANES = _builder.TRANSPORT_PLANES
TRANSPORT_SUBJECT_Y_MAX = _builder.TRANSPORT_SUBJECT_Y_MAX
_scene_maps = _builder._scene_maps
_analysis_shape_for_path = _builder._analysis_shape_for_path
_transport_maps_cuda = _builder._transport_maps_cuda
_transport_maps_accelerated = _builder._transport_maps_accelerated
_transport_maps = _builder._transport_maps
_transport_light_layout = _builder._transport_light_layout
_wrap_map = _builder._wrap_map
warm_transport_geometry = _builder.warm_transport_geometry
REFERENCE_ART_MID = _engine.REFERENCE_ART_MID
FORM_MAP_VERSION = _form_maps.FORM_MAP_VERSION
build_sprite_form_maps = _form_maps.build_sprite_form_maps
cuda_available = _cuda_backend.cuda_available
SharedPreparedSceneInfo = _cuda_backend.SharedPreparedSceneInfo
allocate_shared_prepared_buffer = _cuda_backend.allocate_shared_prepared_buffer
detect_transport_bundle_path = _cuda_backend.detect_transport_bundle_path
detect_transport_bundle_image = _cuda_backend.detect_transport_bundle_image
initialize_component_worker = _cuda_backend.initialize_component_worker
materialize_shared_prepared_scene = _cuda_backend.materialize_shared_prepared_scene


def warm_cuda_backend() -> bool:
    """Pay the common 16:9 CUDA context/geometry cost before first import."""

    if not cuda_available():
        return False
    _cuda_backend.cuda_transport_geometry(
        (360, 640),
        TRANSPORT_GRID_SIZE,
        TRANSPORT_SUBJECT_Y_MAX,
        TRANSPORT_CHARACTER_HEIGHT,
    )
    return True


def runtime_source_path() -> Path:
    candidate = PRODUCTION_CORE / "runtime" / "scenelight_runtime.rpy"
    if candidate.is_file():
        return candidate
    raise RuntimeError("The production SceneLight runtime shader source was not found")
