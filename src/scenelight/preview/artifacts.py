"""Content-addressed scene and sprite analysis for the GPU preview."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..project import SpriteSpec
from ..sidecar import storage_root
from .core import (
    FORM_MAP_VERSION,
    TRANSPORT_CHARACTER_HEIGHT,
    TRANSPORT_GRID_SIZE,
    TRANSPORT_PLANES,
    TRANSPORT_SUBJECT_Y_MAX,
    SharedPreparedSceneInfo,
    _analysis_shape_for_path,
    _scene_maps,
    _transport_light_layout,
    _transport_maps,
    _transport_maps_accelerated,
    _transport_maps_cuda,
    _wrap_map,
    allocate_shared_prepared_buffer,
    build_sprite_form_maps,
    cuda_available,
    detect_transport_bundle_image,
    initialize_component_worker,
    materialize_shared_prepared_scene,
    warm_cuda_backend,
)
from .hardware import (
    HardwarePlan,
    HardwareProfile,
    TemporalCalibration,
    calibrate_temporal_plan,
    derive_hardware_plan,
    detect_hardware_profile,
)

SCENE_CACHE_VERSION = b"scenelight-gpu-studio-scene-v17-spatial-radiance-basis\0"
TEMPORAL_CACHE_VERSION = b"scenelight-gpu-studio-temporal-scene-v14-spatial-radiance-basis\0"
FORM_CACHE_VERSION = f"scenelight-gpu-studio-composited-form-v{FORM_MAP_VERSION}\0".encode()
# Stable namespace for the v8 derived-map schema. It intentionally does not
# follow later shader-only edits: scene/form analysis remains reusable when a
# fragment-stage correction changes but the map encoding does not.
DERIVED_MAP_SCHEMA = bytes.fromhex(
    "7427d63c7a6a7736e59576e487bd6ec2caa69cbb0851218d6c24f1276a6da327"
)

TEMPORAL_COMPONENT_THREADS = 1


def _temporal_worker_analyze(source: Path, prepared_buffer):
    """Produce both exact CPU products after decoding an anchor in one worker."""

    with Image.open(source) as opened:
        source_image = opened.convert("RGB")
        source_image.load()
    bundle, prepared = detect_transport_bundle_image(
        source_image,
        grid_size=TRANSPORT_GRID_SIZE,
        subject_y_max=TRANSPORT_SUBJECT_Y_MAX,
        character_height=TRANSPORT_CHARACTER_HEIGHT,
        crop_components=True,
        prepared_buffer=prepared_buffer,
        scene_fixed_components=True,
    )
    return bundle, _scene_maps(
        source,
        source_image=source_image,
        prepared_scene=prepared,
    )


def _temporal_worker_analyze_cpu(source: Path):
    """Produce the same complete exact anchor on a machine without CUDA."""

    _name, planes = _transport_maps(
        "temporal",
        str(source),
        TRANSPORT_GRID_SIZE,
        scene_fixed_components=True,
    )
    transport = np.concatenate([planes[plane] for plane in range(TRANSPORT_PLANES)], axis=1)
    return transport, _scene_maps(source)


@dataclass(frozen=True, slots=True)
class SceneArtifacts:
    root: Path
    metadata: dict[str, object]
    cached: bool
    build_seconds: float

    def image(self, name: str) -> Path:
        return self.root / f"{name}.png"


@dataclass(frozen=True, slots=True)
class FormArtifacts:
    root: Path
    metadata: dict[str, object]
    cached: bool
    build_seconds: float

    def image(self, name: str) -> Path:
        return self.root / f"{name}.png"


@dataclass(frozen=True, slots=True)
class TemporalSceneArtifacts:
    root: Path
    irradiance: np.ndarray
    emitter: np.ndarray
    transport: np.ndarray
    metadata: dict[str, object]
    cached: bool
    build_seconds: float

    def image(self, name: str) -> Path:
        return self.root / f"{name}.png"


def _digest(path: Path, prefix: bytes) -> str:
    digest = hashlib.sha256(prefix)
    digest.update(DERIVED_MAP_SCHEMA)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_complete(root: Path) -> dict[str, object] | None:
    marker = root / "metadata.json"
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = payload.get("required", ())
    if not isinstance(required, list) or not all((root / item).is_file() for item in required):
        return None
    return payload


def _read_preview(root: Path) -> dict[str, object] | None:
    marker = root / "preview_metadata.json"
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = payload.get("required", ())
    if not isinstance(required, list) or not all((root / item).is_file() for item in required):
        return None
    return payload


class ArtifactCache:
    def __init__(
        self,
        root: Path | None = None,
        *,
        hardware_profile: HardwareProfile | None = None,
        hardware_plan: HardwarePlan | None = None,
    ):
        self.root = (root or storage_root().parent / "preview-cache").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._temporal_pool_lock = threading.Lock()
        self._temporal_component_executor: ProcessPoolExecutor | None = None
        self._temporal_store_executor: ThreadPoolExecutor | None = None
        if hardware_plan is not None:
            self.hardware_plan = hardware_plan
            self._cuda_available = hardware_plan.profile.cuda
        else:
            cuda = hardware_profile.cuda if hardware_profile is not None else cuda_available()
            profile = hardware_profile or detect_hardware_profile(cuda=cuda)
            self.hardware_plan = derive_hardware_plan(profile)
            self._cuda_available = profile.cuda
        self._temporal_calibration: TemporalCalibration | None = None

    def _ensure_temporal_pool(
        self,
    ) -> tuple[ProcessPoolExecutor, ThreadPoolExecutor]:
        with self._temporal_pool_lock:
            if self._temporal_component_executor is None:
                self._temporal_component_executor = ProcessPoolExecutor(
                    max_workers=self.hardware_plan.process_workers,
                    initializer=initialize_component_worker,
                    initargs=(TEMPORAL_COMPONENT_THREADS,),
                )
            if self._temporal_store_executor is None:
                self._temporal_store_executor = ThreadPoolExecutor(
                    max_workers=self.hardware_plan.store_workers,
                    thread_name_prefix="scenelight-temporal-store",
                )
            return self._temporal_component_executor, self._temporal_store_executor

    def prepare_temporal_backend(self) -> HardwarePlan:
        """Initialize the selected exact backend without running throwaway scenes.

        Worker processes are intentionally left lazy: the first submitted work
        is the user's real look-ahead rather than a synthetic calibration wave.
        The hardware-derived plan already bounds concurrency by CPU and memory,
        while CUDA context creation is paid in the background once.
        """

        if self._cuda_available:
            warm_cuda_backend()
        self._ensure_temporal_pool()
        return self.hardware_plan

    def warm_temporal_backend(self) -> TemporalCalibration:
        """Measure a complete exact-anchor wave on the live analysis backend."""

        # Geometry/context creation is a one-time launch concern, not sustained
        # anchor throughput. Pay it before timing the same CPU classification +
        # CUDA transport sequence used by temporal_scene_batch.
        if self._cuda_available:
            warm_cuda_backend()
        component_executor, _store_executor = self._ensure_temporal_pool()
        with self._temporal_pool_lock:
            if self._temporal_calibration is not None:
                return self._temporal_calibration
            warm_root = self.root / "warmup"
            warm_root.mkdir(parents=True, exist_ok=True)
            warm_source = warm_root / "exact_worker_warmup.bmp"
            if not warm_source.is_file():
                yy, xx = np.mgrid[0:360, 0:640]
                warm_rgb = np.empty((360, 640, 3), dtype=np.uint8)
                warm_rgb[..., 0] = (25 + xx * 180 // 639).astype(np.uint8)
                warm_rgb[..., 1] = (18 + yy * 145 // 359).astype(np.uint8)
                warm_rgb[..., 2] = np.where(
                    (xx - 470) ** 2 + (yy - 85) ** 2 < 34**2,
                    248,
                    52,
                ).astype(np.uint8)
                Image.fromarray(warm_rgb, "RGB").save(warm_source, format="BMP")
            worker_count = self.hardware_plan.process_workers
            dummy_source = Image.new("RGB", (1, 1))

            def run_exact_wave() -> None:
                allocations = []
                try:
                    if self._cuda_available:
                        allocations = [
                            allocate_shared_prepared_buffer(
                                _analysis_shape_for_path(warm_source),
                                TRANSPORT_CHARACTER_HEIGHT,
                            )
                            for _index in range(worker_count)
                        ]
                        futures = [
                            component_executor.submit(
                                _temporal_worker_analyze,
                                warm_source,
                                allocation.spec,
                            )
                            for allocation in allocations
                        ]
                    else:
                        futures = [
                            component_executor.submit(_temporal_worker_analyze_cpu, warm_source)
                            for _index in range(worker_count)
                        ]

                    if self._cuda_available:
                        for future, allocation in zip(futures, allocations, strict=True):
                            bundle, _scene_result = future.result()
                            if not isinstance(bundle.prepared, SharedPreparedSceneInfo):
                                raise TypeError(
                                    "Temporal calibration worker did not return shared data"
                                )
                            prepared = materialize_shared_prepared_scene(
                                bundle.prepared,
                                allocation,
                            )
                            _transport_maps_cuda(
                                "calibration",
                                str(warm_source),
                                TRANSPORT_GRID_SIZE,
                                source_components=bundle.components,
                                prepared_source=(dummy_source, prepared),
                            )
                    else:
                        [future.result() for future in futures]
                finally:
                    for allocation in allocations:
                        allocation.close()

            # The first complete wave pays Windows process spawn, module import,
            # and first CUDA kernel/JIT costs. Those are launch warm-up, not the
            # steady throughput that must stay ahead of playing media.
            run_exact_wave()
            started = time.perf_counter()
            run_exact_wave()
            self._temporal_calibration = calibrate_temporal_plan(
                self.hardware_plan,
                warm_seconds=time.perf_counter() - started,
                completed_tasks=worker_count,
            )
        assert self._temporal_calibration is not None
        return self._temporal_calibration

    def scene(self, source: Path) -> SceneArtifacts:
        source = source.resolve(strict=True)
        started = time.perf_counter()
        key = _digest(source, SCENE_CACHE_VERSION)
        root = self.root / "scenes" / key
        existing = _read_complete(root)
        if existing is not None:
            return SceneArtifacts(root, existing["scene"], True, time.perf_counter() - started)

        root.mkdir(parents=True, exist_ok=True)
        component_threads = self.hardware_plan.component_threads
        preview = _read_preview(root)
        # Scene-wide fields and position transport are independent exact
        # products. Build them concurrently so first use is bounded by the
        # slowest real analysis instead of their sum. No provisional result is
        # exposed to the view.
        # These are three independent exact products. A small-memory/low-core
        # host runs fewer at once; capable hosts still overlap all three.
        with ThreadPoolExecutor(max_workers=min(3, component_threads)) as executor:
            transport_future = executor.submit(
                _transport_maps_accelerated,
                "scene",
                str(source),
                TRANSPORT_GRID_SIZE,
                component_threads=component_threads,
            )
            scene_future = executor.submit(_scene_maps, source) if preview is None else None
            wrap_future = executor.submit(_wrap_map, source) if preview is None else None
            _name, transport = transport_future.result()
            if scene_future is not None and wrap_future is not None:
                irradiance, emitter, metadata = scene_future.result()
                wrap = wrap_future.result()
        transport_strip = np.concatenate(
            [transport[plane] for plane in range(TRANSPORT_PLANES)], axis=1
        )
        # Re-check after transport finishes so the exact path can reuse a quick
        # scene-wide preview made immediately before it. A direct SDK caller
        # that did not request a preview still gets the same complete analysis.
        if preview is None:
            assert scene_future is not None and wrap_future is not None
        else:
            metadata = dict(preview["scene"])
            metadata.pop("transport_preview", None)
        metadata = dict(metadata)
        metadata["light_transport_layout"] = _transport_light_layout(transport_strip)
        # These are local, content-addressed GPU cache textures, not release
        # artwork. A low PNG compression level decodes to identical bytes and
        # avoids spending several seconds searching for a slightly smaller
        # file on every first import.
        if preview is None:
            Image.fromarray(irradiance, "RGBA").save(root / "irradiance.png", compress_level=1)
            Image.fromarray(emitter, "RGBA").save(root / "emitter.png", compress_level=1)
            Image.fromarray(wrap, "RGB").save(root / "wrap.png", compress_level=1)
        Image.fromarray(transport_strip, "RGBA").save(root / "transport.png", compress_level=1)
        payload = {
            "kind": "scene",
            "source": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "grid_size": list(TRANSPORT_GRID_SIZE),
            "planes": TRANSPORT_PLANES,
            "analysis_backend": "cuda" if cuda_available() else "cpu",
            "analysis_workers": component_threads,
            "scene": metadata,
            "required": ["irradiance.png", "emitter.png", "wrap.png", "transport.png"],
        }
        (root / "metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return SceneArtifacts(root, metadata, False, time.perf_counter() - started)

    def scene_preview(self, source: Path) -> SceneArtifacts:
        """Compatibility alias that now returns only complete exact lighting."""

        return self.scene(source)

    def temporal_scene(self, source: Path, cache_key: str) -> TemporalSceneArtifacts:
        """Build every background-dependent input for one exact temporal anchor.

        ``cache_key`` includes the media content digest and frame index, so a
        reopened video can reuse the full scene state without retaining its
        temporary full-resolution decoded frame. Scene-wide light detection
        runs beside the CUDA transport solve because the products are
        independent and the live result must include both.
        """

        source = source.resolve(strict=True)
        started = time.perf_counter()
        root = self._temporal_root(cache_key)
        cached = self.temporal_scene_cached(cache_key)
        if cached is not None:
            return TemporalSceneArtifacts(
                cached.root,
                cached.irradiance,
                cached.emitter,
                cached.transport,
                cached.metadata,
                True,
                time.perf_counter() - started,
            )

        root.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(
            max_workers=min(2, self.hardware_plan.component_threads)
        ) as executor:
            transport_future = executor.submit(
                _transport_maps_accelerated,
                "temporal",
                str(source),
                TRANSPORT_GRID_SIZE,
                component_threads=self.hardware_plan.component_threads,
                scene_fixed_components=True,
            )
            scene_future = executor.submit(_scene_maps, source)
            _name, planes = transport_future.result()
            irradiance, emitter, metadata = scene_future.result()
        transport = np.concatenate([planes[plane] for plane in range(TRANSPORT_PLANES)], axis=1)
        return self._store_temporal_scene(
            cache_key,
            irradiance,
            emitter,
            transport,
            metadata,
            started=started,
        )

    def temporal_scene_batch(
        self,
        items: tuple[tuple[int, Path, str], ...],
        cancelled: threading.Event | None = None,
    ):
        """Yield exact temporal artifacts from a persistent CPU/GPU pipeline.

        CPU component classification is the expensive, independently
        parallel part. A hardware-sized persistent process pool avoids paying
        Windows spawn cost per video or chunk. CUDA hosts use zero-copy shared
        preparations; CPU-only hosts run the same complete reference analyzer
        in parallel. Every yielded artifact is the same
        complete product as :meth:`temporal_scene`; no reduced preview exists.
        """

        if not items:
            return
        component_executor, store_executor = self._ensure_temporal_pool()
        allocations = {}
        component_futures = {}
        item_started = {}
        store_futures = []
        dummy_source = Image.new("RGB", (1, 1))
        try:
            for index, source, cache_key in items:
                source = source.resolve(strict=True)
                started = time.perf_counter()
                item_started[index] = started
                if self._cuda_available:
                    allocation = allocate_shared_prepared_buffer(
                        _analysis_shape_for_path(source),
                        TRANSPORT_CHARACTER_HEIGHT,
                    )
                    allocations[index] = allocation
                    component_future = component_executor.submit(
                        _temporal_worker_analyze,
                        source,
                        allocation.spec,
                    )
                else:
                    component_future = component_executor.submit(
                        _temporal_worker_analyze_cpu,
                        source,
                    )
                component_futures[component_future] = (index, source, cache_key)

            for future in as_completed(component_futures):
                index, source, cache_key = component_futures[future]
                if self._cuda_available:
                    bundle, scene_result = future.result()
                    if not isinstance(bundle.prepared, SharedPreparedSceneInfo):
                        raise TypeError("Temporal worker did not return shared prepared-scene data")
                    allocation = allocations[index]
                    prepared = materialize_shared_prepared_scene(bundle.prepared, allocation)
                    _name, planes = _transport_maps_cuda(
                        "temporal",
                        str(source),
                        TRANSPORT_GRID_SIZE,
                        source_components=bundle.components,
                        prepared_source=(dummy_source, prepared),
                    )
                    transport = np.concatenate(
                        [planes[plane] for plane in range(TRANSPORT_PLANES)],
                        axis=1,
                    )
                else:
                    transport, scene_result = future.result()
                irradiance, emitter, metadata = scene_result
                metadata = dict(metadata)
                metadata["light_transport_layout"] = _transport_light_layout(transport)
                root = self._temporal_root(cache_key)
                artifacts = TemporalSceneArtifacts(
                    root,
                    irradiance,
                    emitter,
                    transport,
                    metadata,
                    False,
                    time.perf_counter() - item_started[index],
                )
                store_futures.append(
                    store_executor.submit(
                        self._persist_temporal_scene,
                        cache_key,
                        irradiance,
                        emitter,
                        transport,
                        metadata,
                    )
                )
                allocation = allocations.pop(index, None)
                if allocation is not None:
                    allocation.close()
                if cancelled is None or not cancelled.is_set():
                    yield index, artifacts
        finally:
            # A cancelled chunk must keep parent-owned mappings alive until
            # workers finish writing them. Drain submitted work, then release
            # every mapping deterministically.
            for future in component_futures:
                if not future.done():
                    future.cancel()
            for future in component_futures:
                if not future.cancelled():
                    future.exception()
            for allocation in allocations.values():
                allocation.close()
            for future in store_futures:
                future.result()

    def _store_temporal_scene(
        self,
        cache_key: str,
        irradiance: np.ndarray,
        emitter: np.ndarray,
        transport: np.ndarray,
        metadata: dict[str, object],
        *,
        started: float,
    ) -> TemporalSceneArtifacts:
        metadata = dict(metadata)
        metadata["light_transport_layout"] = _transport_light_layout(transport)
        self._persist_temporal_scene(
            cache_key,
            irradiance,
            emitter,
            transport,
            metadata,
        )
        return TemporalSceneArtifacts(
            self._temporal_root(cache_key),
            irradiance,
            emitter,
            transport,
            metadata,
            False,
            time.perf_counter() - started,
        )

    def _persist_temporal_scene(
        self,
        cache_key: str,
        irradiance: np.ndarray,
        emitter: np.ndarray,
        transport: np.ndarray,
        metadata: dict[str, object],
    ) -> None:
        root = self._temporal_root(cache_key)
        root.mkdir(parents=True, exist_ok=True)
        Image.fromarray(irradiance, "RGBA").save(root / "irradiance.png", compress_level=1)
        Image.fromarray(emitter, "RGBA").save(root / "emitter.png", compress_level=1)
        Image.fromarray(transport, "RGBA").save(root / "transport.png", compress_level=1)
        (root / "metadata.json").write_text(
            json.dumps(
                {
                    "kind": "temporal_scene",
                    "cache_key": cache_key,
                    "grid_size": list(TRANSPORT_GRID_SIZE),
                    "planes": TRANSPORT_PLANES,
                    "analysis_backend": "cuda" if cuda_available() else "cpu",
                    "scene": metadata,
                    "required": ["irradiance.png", "emitter.png", "transport.png"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _temporal_root(self, cache_key: str) -> Path:
        digest = hashlib.sha256(TEMPORAL_CACHE_VERSION)
        digest.update(DERIVED_MAP_SCHEMA)
        digest.update(cache_key.encode("utf-8"))
        return self.root / "temporal" / digest.hexdigest()

    def temporal_scene_cached(self, cache_key: str) -> TemporalSceneArtifacts | None:
        """Read one complete temporal state without decoding its source frame."""

        started = time.perf_counter()
        root = self._temporal_root(cache_key)
        existing = _read_complete(root)
        if existing is None:
            return None
        arrays: dict[str, np.ndarray] = {}
        for name in ("irradiance", "emitter", "transport"):
            with Image.open(root / f"{name}.png") as image:
                arrays[name] = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        return TemporalSceneArtifacts(
            root,
            arrays["irradiance"],
            arrays["emitter"],
            arrays["transport"],
            dict(existing["scene"]),
            True,
            time.perf_counter() - started,
        )

    def temporal_transport(self, source: Path, cache_key: str) -> TemporalSceneArtifacts:
        """Backward-compatible alias for the now-complete temporal solve."""

        return self.temporal_scene(source, cache_key)

    @staticmethod
    def warm_backend() -> bool:
        """Import and initialize CUDA before the user selects a background."""

        return warm_cuda_backend()

    def shutdown(self) -> None:
        """Release persistent analyzer workers after in-flight chunks stop."""

        with self._temporal_pool_lock:
            component_executor = self._temporal_component_executor
            store_executor = self._temporal_store_executor
            self._temporal_component_executor = None
            self._temporal_store_executor = None
            self._temporal_calibration = None
        if store_executor is not None:
            store_executor.shutdown(wait=True, cancel_futures=True)
        if component_executor is not None:
            component_executor.shutdown(wait=True, cancel_futures=True)

    def form(self, source: Path) -> FormArtifacts:
        source = source.resolve(strict=True)
        started = time.perf_counter()
        key = _digest(source, FORM_CACHE_VERSION)
        root = self.root / "forms" / key
        existing = _read_complete(root)
        if existing is not None:
            return FormArtifacts(root, existing["form"], True, time.perf_counter() - started)

        root.mkdir(parents=True, exist_ok=True)
        # Match installation's transparent-canvas composition. Hidden RGB in
        # zero-alpha pixels must not leak into the reconstructed surface.
        maps = build_sprite_form_maps(SpriteSpec(source.stem, (source,)).compose())
        maps.normal_noise.save(root / "normal_noise.png", compress_level=1)
        maps.height_ao_edge.save(root / "height_ao_edge.png", compress_level=1)
        maps.response.save(root / "response.png", compress_level=1)
        payload = {
            "kind": "form",
            "source": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "form": maps.metadata,
            "required": ["normal_noise.png", "height_ao_edge.png", "response.png"],
        }
        (root / "metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return FormArtifacts(root, maps.metadata, False, time.perf_counter() - started)
