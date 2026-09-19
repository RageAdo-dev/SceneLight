"""Qt shell for the GPU SceneLight preview."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psutil
from PIL import Image
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..branding import ICON_PNG
from ..calibration import (
    Calibration,
    CalibrationProfile,
    lighting_mode_preset,
    load_profile,
    merge_profile_into_config,
    profile_path,
    save_profile,
)
from ..prepared import engine_identity, source_identity
from ..runtime.prepared import Reader as PreparedReader
from .artifacts import (
    ArtifactCache,
    FormArtifacts,
    SceneArtifacts,
    TemporalSceneArtifacts,
)
from .calibration_dialog import CalibrationDialog
from .exporter import GIFWriter, MP4Writer, composite_gif_timeline, export_extension
from .gpu_view import SceneLightGPUView
from .media import MediaClip, MediaFrame, environment_wrap
from .playback import VideoPlayback
from .temporal import TemporalSceneFrame, interpolated_scene, scene_blend


def _active_light_count(metadata: dict[str, object]) -> int:
    count = 0
    for light in metadata.get("light_transport", ()):
        if not isinstance(light, dict):
            continue
        position = light.get("position_radius_intensity", (0.0, 0.0, 0.0, 0.0))
        extra = light.get("emission_enabled", (0.0, 0.0))
        if float(position[3]) > 0.001 or float(extra[0]) > 0.001:
            count += 1
    return count


def _export_checkpoint(progress: QProgressDialog, cancelled: threading.Event) -> None:
    """Keep the export dialog responsive and turn Cancel into an interruption."""

    QApplication.processEvents()
    if progress.wasCanceled():
        cancelled.set()
    if cancelled.is_set():
        raise InterruptedError


def _wait_for_export_future(
    future: Future,
    progress: QProgressDialog,
    cancelled: threading.Event,
):
    """Wait for live analysis without hiding or freezing the export Cancel button."""

    while not future.done():
        try:
            _export_checkpoint(progress, cancelled)
        except InterruptedError:
            future.cancel()
            raise
        time.sleep(0.02)
    _export_checkpoint(progress, cancelled)
    return future.result()


@dataclass(frozen=True, slots=True)
class TemporalPlan:
    anchors: tuple[int, ...]
    known_through: int
    complete: bool
    allow_playback: bool = True
    requires_full_warmup: bool = False
    lookahead_seconds: float = 2.0


class _WorkerSignals(QObject):
    videoFrameReady = Signal(int)
    sceneReady = Signal(int, object, object, object)
    formReady = Signal(int, object, object, object)
    temporalPlanReady = Signal(int, object)
    temporalReady = Signal(int, int, object)
    temporalComplete = Signal(int, object, object)
    failed = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path | None = None):
        super().__init__()
        self.setWindowTitle("SceneLight Preview & Calibrator")
        self.setWindowIcon(QIcon(str(ICON_PNG)))
        self.resize(1600, 940)
        self._project_root = project_root.expanduser().resolve() if project_root else None
        self._profile_path = profile_path(self._project_root) if self._project_root else None
        profile_error = None
        try:
            self._calibration_profile = (
                load_profile(self._profile_path)
                if self._profile_path is not None
                else CalibrationProfile()
            )
        except (OSError, ValueError) as error:
            profile_error = str(error)
            self._calibration_profile = CalibrationProfile()
        self._calibration = self._calibration_profile.calibration
        self._cache = ArtifactCache()
        # Keep first-use background analysis independent from animated-sprite
        # form warm-up. A long GIF must never queue ahead of exact scene work.
        self._scene_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="scenelight-scene"
        )
        self._form_executor = ThreadPoolExecutor(
            max_workers=self._cache.hardware_plan.form_workers,
            thread_name_prefix="scenelight-form",
        )
        self._temporal_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="scenelight-temporal"
        )
        self._video_decode_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="scenelight-video-decode"
        )
        # Start the decoder thread while the Preview window is being prepared.
        # Creating a Windows worker on the first playback tick can itself take
        # long enough to miss several frames even though decoding is async.
        self._video_decode_executor.submit(lambda: None)
        # The CPU temporal fallback initializes its backend only when used.
        # Prepared/live GL playback does not need a second CUDA context.
        self._signals = _WorkerSignals()
        self._signals.sceneReady.connect(self._on_scene_ready)
        self._signals.videoFrameReady.connect(self._on_video_frame_ready, Qt.QueuedConnection)
        self._signals.formReady.connect(self._on_form_ready)
        self._signals.temporalPlanReady.connect(self._on_temporal_plan_ready)
        self._signals.temporalReady.connect(self._on_temporal_ready)
        self._signals.temporalComplete.connect(self._on_temporal_complete)
        self._signals.failed.connect(self._on_failed)
        self._scene_generation = 0
        self._form_generation = 0
        self._background_path: Path | None = None
        self._sprite_path: Path | None = None
        self._background_media: MediaClip | None = None
        self._sprite_media: MediaClip | None = None
        now = time.perf_counter()
        self._background_animation_epoch = now
        self._sprite_animation_epoch = now
        self._form_artifacts_by_frame: dict[int, FormArtifacts] = {}
        self._form_frame_indices: dict[Path, int] = {}
        self._queued_form_generation = -1
        self._scene_artifacts: SceneArtifacts | None = None
        self._temporal_scenes: dict[int, TemporalSceneFrame] = {}
        self._temporal_anchors: tuple[int, ...] = (0,)
        self._temporal_plan_complete = False
        self._temporal_plan_known_through = 0
        self._temporal_ready_through = 0
        self._temporal_playback_started = False
        self._temporal_start_allowed = True
        self._temporal_requires_full_warmup = False
        self._temporal_lookahead_seconds = self._cache.hardware_plan.nominal_lookahead_seconds
        self._temporal_cancel = threading.Event()
        self._temporal_future = None
        self._current_background_index = 0
        self._background_playback: VideoPlayback | None = None
        self._background_decode_generation = 0
        self._background_animation_ready = True
        self._gpu_live_background = False
        self._prepared_reader = None
        self._preparation_process = None
        self._preparation_dialog = None
        self._last_live_status = 0.0
        self._sprite_animation_ready = True

        self._view = SceneLightGPUView()
        self._view.set_calibration(self._calibration)
        self._view.set_strength(self._calibration_profile.normalized_strength())
        self._view.placementChanged.connect(self._sync_placement)
        self._view.frameTimeChanged.connect(self._on_frame_time)
        self._view.rendererReady.connect(self._on_renderer_ready)
        self._view.liveAnalysisFailed.connect(self._on_live_analysis_failed)
        self._view.liveAnalysisFinished.connect(self._on_live_analysis_finished)
        self._view.rendererError.connect(lambda message: self._on_failed("GPU shader", message))

        self._background_label = QLabel("No background loaded")
        self._sprite_label = QLabel("No sprite loaded")
        self._analysis_label = QLabel(
            "Open a background and a transparent sprite to preview the lighting."
        )
        self._analysis_label.setWordWrap(True)
        self._gpu_label = QLabel("Creating OpenGL 3.3 renderer…")
        self._frame_label = QLabel("GPU frame: —")

        self._horizontal_slider = self._slider(-25, 125, 50, self._placement_from_controls)
        self._baseline_slider = self._slider(20, 140, 104, self._placement_from_controls)
        self._height_slider = self._slider(10, 135, 92, self._placement_from_controls)
        profile_strength = self._calibration_profile.normalized_strength()
        self._strength_slider = self._slider(
            0, 150, round(profile_strength * 100.0), self._strength_changed
        )
        self._lighting_look = QComboBox()
        self._lighting_look.addItems(("Custom", "Physical", "Cinematic", "Separate colored lights"))
        self._lighting_look.setToolTip(
            "Choose a lighting preset. Cinematic reduces lighting strength and exposure."
        )
        self._lighting_look.currentIndexChanged.connect(self._lighting_look_changed)
        self._horizontal_value = QLabel("50%")
        self._baseline_value = QLabel("104%")
        self._height_value = QLabel("92%")
        self._strength_value = QLabel(f"{profile_strength:.0%}")

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)
        toolbar = QHBoxLayout()
        open_background = QPushButton("Open background  Ctrl+O")
        open_background.clicked.connect(self.open_background)
        open_sprite = QPushButton("Open sprite / animation")
        open_sprite.clicked.connect(self.open_sprite)
        export = QPushButton("Export PNG / GIF / video")
        export.clicked.connect(self.export)
        calibrate = QPushButton("Calibrate")
        calibrate.clicked.connect(self._open_calibration)
        save_calibration = QPushButton("Save profile")
        save_calibration.clicked.connect(self._save_calibration_profile)
        export_config = QPushButton("Export config")
        export_config.clicked.connect(self._export_calibration_config)
        compare = QComboBox()
        compare.addItems(("Relit", "Original", "Split comparison"))
        compare.setToolTip("Compare the unchanged sprite with the SceneLight result")
        compare.currentIndexChanged.connect(self._view.set_compare_mode)
        toolbar.addWidget(open_background)
        toolbar.addWidget(open_sprite)
        toolbar.addWidget(calibrate)
        toolbar.addWidget(save_calibration)
        toolbar.addWidget(export_config)
        toolbar.addWidget(compare)
        toolbar.addStretch(1)
        toolbar.addWidget(export)
        outer.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._view, 1)
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(360)
        panel_layout = QVBoxLayout(panel)
        title = QLabel("SceneLight Preview")
        title.setObjectName("title")
        subtitle = QLabel("Adjust lighting and character placement")
        subtitle.setObjectName("subtitle")
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)
        panel_layout.addSpacing(12)
        panel_layout.addWidget(self._section("Background", self._background_label))
        panel_layout.addWidget(self._section("Sprite", self._sprite_label))
        panel_layout.addWidget(self._section("Automatic analysis", self._analysis_label))

        form = QFormLayout()
        form.addRow("Horizontal", self._control(self._horizontal_slider, self._horizontal_value))
        form.addRow("Baseline", self._control(self._baseline_slider, self._baseline_value))
        form.addRow("Character height", self._control(self._height_slider, self._height_value))
        form.addRow("Lighting preset", self._lighting_look)
        form.addRow("Lighting strength", self._control(self._strength_slider, self._strength_value))
        controls = QFrame()
        controls.setObjectName("section")
        controls.setLayout(form)
        panel_layout.addWidget(controls)
        panel_layout.addWidget(self._section("GPU", self._gpu_label))
        panel_layout.addWidget(self._frame_label)
        panel_layout.addStretch(1)
        hint = QLabel("Drag or arrows/WASD move · mouse wheel scales · Shift = fine movement")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        panel_layout.addWidget(hint)
        body.addWidget(panel)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")
        if profile_error:
            self.statusBar().showMessage(f"Calibration profile ignored: {profile_error}")
        self._install_shortcuts(open_background)
        self.setStyleSheet(self._style())
        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.PreciseTimer)
        self._animation_timer.setSingleShot(True)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._animation_timer.start()

    def _set_calibration(self, calibration: Calibration) -> None:
        self._calibration = calibration.normalized()
        self._view.set_calibration(self._calibration)
        if hasattr(self, "_lighting_look") and self._lighting_look.currentIndex() != 0:
            self._lighting_look.blockSignals(True)
            self._lighting_look.setCurrentIndex(0)
            self._lighting_look.blockSignals(False)

    def _lighting_look_changed(self, index: int) -> None:
        if index <= 0:
            return
        name = ("physical", "cinematic", "separate")[index - 1]
        strength, calibration = lighting_mode_preset(name)
        self._strength_slider.blockSignals(True)
        self._strength_slider.setValue(round(strength * 100.0))
        self._strength_slider.blockSignals(False)
        self._strength_value.setText(f"{strength:.0%}")
        self._view.set_strength(strength)
        self._calibration = calibration
        self._view.set_calibration(calibration)
        self.statusBar().showMessage(
            f"{self._lighting_look.currentText()} lighting applied to the live preview"
        )

    def _open_calibration(self) -> None:
        dialog = CalibrationDialog(self._calibration, self._set_calibration, self)
        if dialog.exec():
            self._set_calibration(dialog.calibration)
            self.statusBar().showMessage(
                "Calibration applied to the live preview; save it to use in Ren'Py"
            )

    def _current_profile(self) -> CalibrationProfile:
        return CalibrationProfile(
            calibration=self._calibration,
            scenes=dict(self._calibration_profile.scenes or {}),
            strength=self._strength_slider.value() / 100.0,
        )

    def _save_calibration_profile(self) -> None:
        if self._profile_path is None:
            selected, _filter = QFileDialog.getSaveFileName(
                self,
                "Save SceneLight profile",
                "scenelight-profile.json",
                "JSON (*.json)",
            )
            if not selected:
                return
            destination = Path(selected)
        else:
            destination = self._profile_path
        try:
            self._calibration_profile = self._current_profile()
            save_profile(destination, self._calibration_profile)
        except (OSError, ValueError) as error:
            self._on_failed("Save calibration", str(error))
            return
        self.statusBar().showMessage(f"Calibration profile saved to {destination}")

    def _export_calibration_config(self) -> None:
        default = (
            self._project_root / "scenelight.json"
            if self._project_root is not None
            else Path("scenelight.json")
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export SceneLight project config",
            str(default),
            "JSON (*.json)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.is_file():
            choice = QMessageBox.question(
                self,
                "Update existing config?",
                "This preserves asset-discovery settings and updates only lighting values.",
            )
            if choice != QMessageBox.Yes:
                return
        try:
            self._calibration_profile = self._current_profile()
            merge_profile_into_config(destination, self._calibration_profile)
        except (OSError, ValueError) as error:
            self._on_failed("Export calibration", str(error))
            return
        self.statusBar().showMessage(f"Project config exported to {destination}")

    @staticmethod
    def _slider(minimum: int, maximum: int, value: int, callback) -> QSlider:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(callback)
        return slider

    @staticmethod
    def _control(slider: QSlider, value: QLabel) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider, 1)
        value.setFixedWidth(48)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(value)
        return widget

    @staticmethod
    def _section(title: str, content: QLabel) -> QFrame:
        frame = QFrame()
        frame.setObjectName("section")
        layout = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        content.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(content)
        return frame

    @staticmethod
    def _install_shortcuts(open_background: QPushButton) -> None:
        open_background.setShortcut("Ctrl+O")

    def open_background(self) -> None:
        start = str(
            self._background_path.parent
            if self._background_path
            else self._project_root or Path.home()
        )
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Open background",
            start,
            "Backgrounds (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.apng *.mp4 *.m4v "
            "*.mov *.avi *.webm *.mkv *.ogv);;All files (*)",
        )
        if not selected:
            return
        path = Path(selected)
        try:
            media = MediaClip(path, self._cache.root / "media")
        except Exception as error:  # noqa: BLE001 - decoder errors must reach the GUI.
            self._on_failed("Background media", str(error))
            return
        self._stop_preparation()
        self._temporal_cancel.set()
        self._stop_background_decode()
        if self._background_media is not None:
            self._background_media.close()
        self._background_media = media
        self._background_animation_epoch = time.perf_counter()
        first_frame = media.frame_at(0.0)
        self._view.clear_scene()
        self._gpu_live_background = self._view.live_analysis_supported
        self._view.set_live_analysis_enabled(self._gpu_live_background)
        self._view.set_live_background(media.animated)
        self._view.set_background_frame(
            first_frame.rgba,
            None if self._gpu_live_background else environment_wrap(first_frame.rgba),
        )
        self._scene_generation += 1
        generation = self._scene_generation
        self._scene_artifacts = None
        self._temporal_scenes.clear()
        self._temporal_anchors = (0,)
        self._temporal_plan_complete = False
        self._temporal_plan_known_through = 0
        self._temporal_ready_through = 0
        self._temporal_playback_started = False
        self._temporal_start_allowed = not media.animated
        self._temporal_requires_full_warmup = False
        self._temporal_lookahead_seconds = self._cache.hardware_plan.nominal_lookahead_seconds
        self._temporal_cancel = threading.Event()
        self._temporal_future = None
        self._current_background_index = 0
        self._background_animation_ready = not media.animated
        self._background_path = path
        media_text = (
            f"{media.kind} · {media.frame_count} frames" if media.animated else "still image"
        )
        self._background_label.setText(f"{path.name}\n{media_text}")
        if (
            self._gpu_live_background
            and media.animated
            and getattr(self, "_prepare_animated", True)
        ):
            self._view.set_live_analysis_enabled(False)
            self._start_preparation(media)
            return
        if self._gpu_live_background:
            self._background_animation_ready = not media.animated
            self._temporal_playback_started = False
            self._temporal_start_allowed = True
            self._background_animation_epoch = time.perf_counter()
            self._analysis_label.setText("Lighting follows the displayed background frame.")
            self.statusBar().showMessage("Background opened · live lighting active")
            return
        self.statusBar().showMessage(f"Preparing lighting for {path.name}…")
        analysis_path = media.reference_path
        # Display the unmodified background while the exact 16x9 transport is
        # computed. Never install an approximate transport field that visibly
        # changes into the final lighting a moment later.
        future = self._scene_executor.submit(self._cache.scene, analysis_path)
        future.add_done_callback(
            lambda completed: self._scene_finished(generation, analysis_path, completed)
        )

    def _stop_preparation(self) -> None:
        process = self._preparation_process
        self._preparation_process = None
        if process is not None:
            descendants = []
            if process.processId():
                try:
                    descendants = psutil.Process(process.processId()).children(recursive=True)
                except psutil.NoSuchProcess:
                    pass
                for child in reversed(descendants):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            process.kill()
            process.waitForFinished(3000)
            # A Windows venv launcher may exit before its Python child has
            # released the cache file and graphics context.
            psutil.wait_procs(descendants, timeout=3)
            partial = getattr(process, "_scenelight_partial", None)
            if partial is not None:
                partial.unlink(missing_ok=True)
            process.deleteLater()
        if self._preparation_dialog is not None:
            dialog = self._preparation_dialog
            self._preparation_dialog = None
            dialog.canceled.disconnect()
            dialog.close()
            dialog.deleteLater()
        if self._prepared_reader is not None:
            self._prepared_reader.close()
            self._prepared_reader = None

    def _start_preparation(self, media: MediaClip) -> None:
        destination = (
            self._cache.root / "prepared" / (media.identity + "-" + engine_identity() + ".slframes")
        )
        process = QProcess(self)
        self._preparation_process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert(
            "PYTHONPATH",
            str(Path(__file__).resolve().parents[2]) + os.pathsep + environment.value("PYTHONPATH"),
        )
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.MergedChannels)
        dialog = QProgressDialog(
            "Preparing every video frame…", "Cancel", 0, media.frame_count, self
        )
        dialog.setWindowTitle("Preparing full-quality lighting")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        self._preparation_dialog = dialog
        output = bytearray()
        errors = []

        def receive():
            output.extend(bytes(process.readAllStandardOutput()))
            while b"\n" in output:
                line, _, rest = output.partition(b"\n")
                output[:] = rest
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    errors.append(line.decode("utf-8", errors="replace")[-1000:])
                    del errors[:-8]
                    continue
                if "temporary" in value:
                    partial = Path(value["temporary"])
                    if (
                        partial.parent == destination.parent
                        and partial.name.startswith(destination.name + ".")
                        and partial.suffix == ".partial"
                    ):
                        process._scenelight_partial = partial
                if "done" in value and self._preparation_process is process:
                    dialog.setValue(value["done"])
                    dialog.setLabelText(
                        "Preparing lighting: %d / %d frames" % (value["done"], value["total"])
                    )

        def finished(code, _status):
            if self._preparation_process is not process:
                return
            self._preparation_process = None
            dialog.canceled.disconnect()
            dialog.close()
            dialog.deleteLater()
            self._preparation_dialog = None
            process.deleteLater()
            if code != 0:
                partial = getattr(process, "_scenelight_partial", None)
                if partial is not None:
                    partial.unlink(missing_ok=True)
                self._analysis_label.setText("Preparation failed; reopen the video to retry.")
                self._on_failed("Lighting preparation", "\n".join(errors) or process.errorString())
                return
            try:
                self._prepared_reader = PreparedReader(
                    str(destination),
                    {
                        "engine": engine_identity(),
                        "preview": True,
                        "frame_count": media.frame_count,
                    },
                )
                self._view._cleanup_live_analysis()
                self._view.set_prepared_fields(self._prepared_reader.frame(0))
            except (OSError, ValueError, KeyError) as error:
                self._on_failed("Prepared lighting", str(error))
                return
            self._background_animation_ready = True
            self._temporal_playback_started = True
            self._restart_background_animation()
            self._analysis_label.setText("Lighting prepared for every frame.")
            self.statusBar().showMessage("Prepared playback ready")

        def cancel():
            self._stop_preparation()
            self._analysis_label.setText("Preparation cancelled; reopen the video to retry.")

        process.readyReadStandardOutput.connect(receive)
        process.finished.connect(finished)
        process.errorOccurred.connect(
            lambda error: finished(1, None) if error == QProcess.FailedToStart else None
        )
        dialog.canceled.connect(cancel)
        process.start(
            sys.executable, ["-u", "-m", "scenelight.prepared", str(media.source), str(destination)]
        )
        self._analysis_label.setText("Preparing video lighting. This is only needed once…")

    def _scene_finished(self, generation: int, path: Path, future) -> None:
        try:
            artifacts = future.result()
        except Exception as error:  # noqa: BLE001 - worker failures must reach the GUI.
            self._signals.failed.emit("Background analysis", str(error))
            return
        self._signals.sceneReady.emit(generation, path, artifacts, artifacts.metadata)

    def _on_scene_ready(
        self, generation: int, path: Path, artifacts: SceneArtifacts, metadata: dict
    ) -> None:
        if generation != self._scene_generation:
            return
        if metadata.get("transport_preview"):
            # Legacy cache compatibility only: never install provisional
            # transport into the viewport. Keep the untouched background up
            # until the byte-identical final field is available.
            self.statusBar().showMessage("Finishing background analysis…")
            future = self._scene_executor.submit(self._cache.scene, path)
            future.add_done_callback(
                lambda completed: self._scene_finished(generation, path, completed)
            )
            return
        self._view.set_scene(path, artifacts)
        self._scene_artifacts = artifacts
        self._temporal_scenes[0] = self._scene_frame_from_artifacts(artifacts)
        self._update_temporal_horizon()
        cache_text = (
            "cache hit" if artifacts.cached else f"analyzed in {artifacts.build_seconds:.2f}s"
        )
        self._analysis_label.setText(f"{_active_light_count(metadata)} lights · {cache_text}")
        self.statusBar().showMessage(f"Background ready · {cache_text}")
        media = self._background_media
        if media is not None and media.animated:
            self._analysis_label.setText(
                f"{_active_light_count(metadata)} lights · preparing animation lighting…"
            )
            self._temporal_start_allowed = True
            self._maybe_start_background_animation()
            self._start_temporal_analysis(generation, media)

    def _start_temporal_analysis(self, generation: int, media: MediaClip) -> None:
        """Start future-frame analysis only after the first visible frame is ready."""
        if self._temporal_future is not None or self._temporal_cancel.is_set():
            return
        self._temporal_future = self._temporal_executor.submit(
            self._warm_temporal_scenes,
            generation,
            media.source,
            self._cache.root / "media",
            self._temporal_cancel,
        )
        self._temporal_future.add_done_callback(
            lambda completed: self._temporal_finished(generation, completed)
        )

    def _temporal_finished(self, generation: int, future) -> None:
        try:
            future.result()
        except Exception as error:  # noqa: BLE001 - worker failures must reach the GUI.
            if generation == self._scene_generation:
                self._signals.failed.emit("Animated background analysis", str(error))

    @staticmethod
    def _scene_frame_from_artifacts(artifacts: SceneArtifacts) -> TemporalSceneFrame:
        arrays: dict[str, np.ndarray] = {}
        for name in ("irradiance", "emitter", "transport"):
            with Image.open(artifacts.image(name)) as image:
                arrays[name] = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        return TemporalSceneFrame(
            arrays["irradiance"],
            arrays["emitter"],
            arrays["transport"],
            dict(artifacts.metadata),
        )

    @staticmethod
    def _scene_frame_from_temporal(artifacts: TemporalSceneArtifacts) -> TemporalSceneFrame:
        return TemporalSceneFrame(
            artifacts.irradiance,
            artifacts.emitter,
            artifacts.transport,
            dict(artifacts.metadata),
        )

    def _warm_temporal_scenes(
        self,
        generation: int,
        source: Path,
        media_cache: Path,
        cancelled: threading.Event,
    ) -> tuple[tuple[int, ...], dict[int, TemporalSceneFrame]]:
        clip = MediaClip(source, media_cache)
        built: dict[int, TemporalSceneFrame] = {}
        anchors: tuple[int, ...] = (0,)
        try:
            plan = self._cache.prepare_temporal_backend()
            lookahead_seconds = plan.nominal_lookahead_seconds
            batch_size = plan.temporal_batch_size
            initial_batch_size = plan.process_workers
            regular = clip.temporal_anchor_indices(detect_changes=False)

            def load_cached(indices: tuple[int, ...]) -> list[int]:
                missing: list[int] = []
                for index in indices:
                    if cancelled.is_set():
                        return missing
                    if index == 0 or index in built:
                        continue
                    cached = self._cache.temporal_scene_cached(clip.temporal_cache_key(index))
                    if cached is None:
                        missing.append(index)
                        continue
                    built[index] = self._scene_frame_from_temporal(cached)
                    self._signals.temporalReady.emit(generation, index, cached)
                return missing

            def build_indices(indices: tuple[int, ...], chunk_size: int) -> None:
                for offset in range(0, len(indices), chunk_size):
                    if cancelled.is_set():
                        return
                    batch_indices = indices[offset : offset + chunk_size]
                    prepared: list[tuple[int, Path, str]] = []
                    transient_paths: list[Path] = []
                    try:
                        for frame in clip.iter_frames(batch_indices):
                            path, transient = clip.analysis_frame_path(frame)
                            prepared.append(
                                (frame.index, path, clip.temporal_cache_key(frame.index))
                            )
                            if transient:
                                transient_paths.append(path)
                        for index, artifacts in self._cache.temporal_scene_batch(
                            tuple(prepared),
                            cancelled,
                        ):
                            built[index] = self._scene_frame_from_temporal(artifacts)
                            self._signals.temporalReady.emit(generation, index, artifacts)
                    finally:
                        for path in transient_paths:
                            path.unlink(missing_ok=True)

            if clip.kind == "video" and clip.fps > 12.0:
                # Scan and solve in hardware-calibrated exact prefixes. The previous
                # implementation scanned the entire file before allowing its
                # first frame to move, even though the analyzer only needs a
                # bounded future neighborhood. This streaming plan preserves
                # every metric, threshold, cut pair, and artifact byte while
                # making cold playback behave like a warmed pass.
                anchor_set = {0}
                regular_position = 0
                window_frames = max(
                    2,
                    round(clip.fps * lookahead_seconds) + 1,
                )
                for scanned_through, changes in clip.iter_video_change_windows(window_frames):
                    if cancelled.is_set():
                        return anchors, built
                    while (
                        regular_position < len(regular)
                        and regular[regular_position] <= scanned_through
                    ):
                        anchor_set.add(regular[regular_position])
                        regular_position += 1
                    anchor_set.update(changes)
                    anchors = tuple(sorted(anchor_set))
                    complete = scanned_through >= clip.frame_count - 1
                    missing = tuple(load_cached(anchors))
                    build_indices(missing, batch_size)
                    self._signals.temporalPlanReady.emit(
                        generation,
                        TemporalPlan(
                            anchors,
                            scanned_through,
                            complete,
                            allow_playback=True,
                            requires_full_warmup=False,
                            lookahead_seconds=lookahead_seconds,
                        ),
                    )
                self._signals.temporalComplete.emit(generation, anchors, built)
                return anchors, built

            # Animated-image and low-frame-rate inputs already have a complete
            # authored frame plan. Analyze their first exact look-ahead while
            # the (normally trivial) plan is finalized.
            with ThreadPoolExecutor(max_workers=1) as scan_executor:
                change_future = scan_executor.submit(
                    clip.temporal_anchor_indices,
                    detect_changes=True,
                )
                missing_regular = load_cached(regular)
                initial = tuple(missing_regular[:initial_batch_size])
                build_indices(initial, initial_batch_size)
                if cancelled.is_set():
                    return anchors, built
                anchors = change_future.result()
                self._signals.temporalPlanReady.emit(
                    generation,
                    TemporalPlan(
                        anchors,
                        clip.frame_count - 1,
                        True,
                        lookahead_seconds=lookahead_seconds,
                    ),
                )

                extra_missing = tuple(
                    index for index in load_cached(anchors) if index not in regular
                )
                remaining_regular = tuple(missing_regular[len(initial) :])
                remaining = tuple(sorted(set(extra_missing) | set(remaining_regular)))
                build_indices(remaining, batch_size)
        finally:
            clip.close()
        self._signals.temporalComplete.emit(generation, anchors, built)
        return anchors, built

    def _on_temporal_plan_ready(self, generation: int, plan: TemporalPlan) -> None:
        if generation != self._scene_generation:
            return
        anchors = plan.anchors
        self._temporal_anchors = anchors
        self._temporal_plan_known_through = plan.known_through
        self._temporal_plan_complete = plan.complete
        self._temporal_start_allowed = plan.allow_playback
        self._temporal_requires_full_warmup = plan.requires_full_warmup
        self._temporal_lookahead_seconds = plan.lookahead_seconds
        self._update_temporal_horizon()
        self._analysis_label.setText(
            f"Preparing animation lighting: {len(self._temporal_scenes)}/{len(anchors)} samples"
        )
        self._maybe_start_background_animation()

    def _on_temporal_ready(
        self,
        generation: int,
        frame_index: int,
        artifacts: TemporalSceneArtifacts,
    ) -> None:
        if generation != self._scene_generation:
            return
        self._temporal_scenes[frame_index] = self._scene_frame_from_temporal(artifacts)
        self._update_temporal_horizon()
        ready = len(self._temporal_scenes)
        total = len(self._temporal_anchors)
        state = "Video playing" if self._temporal_playback_started else "Video ready"
        self._analysis_label.setText(f"{state} · lighting samples ready: {ready}/{total}")
        self._maybe_start_background_animation()

    def _on_temporal_complete(
        self,
        generation: int,
        anchors: tuple[int, ...],
        built: dict[int, TemporalSceneFrame],
    ) -> None:
        if generation != self._scene_generation:
            return
        self._temporal_anchors = anchors
        self._temporal_plan_complete = True
        self._temporal_start_allowed = True
        media = self._background_media
        self._temporal_plan_known_through = (
            media.frame_count - 1 if media is not None else anchors[-1]
        )
        self._temporal_scenes.update(built)
        self._update_temporal_horizon()
        if len(self._temporal_scenes) < len(anchors):
            return
        self._background_animation_ready = True
        self._maybe_start_background_animation()
        self._analysis_label.setText(f"Animation lighting ready · {len(anchors)} samples saved")
        self.statusBar().showMessage("Animation ready")

    def _apply_temporal_scene(self, frame_index: int) -> None:
        if getattr(self, "_prepared_reader", None) is not None:
            self._view.set_prepared_fields(self._prepared_reader.frame(frame_index))
            return
        if getattr(self, "_gpu_live_background", False):
            return
        scene = scene_blend(self._temporal_scenes, frame_index)
        if scene is not None:
            self._view.set_live_scene_blend(scene)

    def _update_temporal_horizon(self) -> None:
        if not self._temporal_anchors:
            self._temporal_ready_through = 0
            return
        horizon = 0
        for index in self._temporal_anchors:
            if index not in self._temporal_scenes:
                break
            horizon = index
        self._temporal_ready_through = horizon

    def _maybe_start_background_animation(self) -> None:
        media = self._background_media
        if media is None or not media.animated or self._scene_artifacts is None:
            return
        if not getattr(self, "_temporal_start_allowed", True):
            return
        self._background_animation_ready = True
        if not self._temporal_playback_started:
            self._temporal_playback_started = True
            self._restart_background_animation()
            self.statusBar().showMessage("Video playing · preparing lighting in the background")

    def _restart_background_animation(self) -> None:
        if getattr(self, "_exporting_animation", False):
            return
        if self._background_animation_ready:
            self._stop_background_decode()
            self._background_animation_epoch = time.perf_counter()
            self._current_background_index = 0
            if getattr(self, "_animation_timer", None) is not None:
                self._animation_timer.start(0)

    def _restart_sprite_animation(self) -> None:
        if getattr(self, "_exporting_animation", False):
            return
        if self._sprite_animation_ready:
            self._sprite_animation_epoch = time.perf_counter()
            if getattr(self, "_animation_timer", None) is not None:
                self._animation_timer.start(0)

    def open_sprite(self) -> None:
        start = str(
            self._sprite_path.parent if self._sprite_path else self._project_root or Path.home()
        )
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Open transparent sprite",
            start,
            "Sprites (*.png *.webp *.gif *.apng);;All files (*)",
        )
        if not selected:
            return
        path = Path(selected)
        try:
            media = MediaClip(path, self._cache.root / "media")
        except Exception as error:  # noqa: BLE001 - decoder errors must reach the GUI.
            self._on_failed("Sprite media", str(error))
            return
        if media.kind == "video":
            media.close()
            self._on_failed(
                "Sprite media",
                "Video sprites need an alpha channel; use animated GIF, APNG, or WebP.",
            )
            return
        if self._sprite_media is not None:
            self._sprite_media.close()
        self._sprite_media = media
        self._sprite_animation_epoch = time.perf_counter()
        self._sprite_animation_ready = not media.animated
        first_frame = media.frame_at(0.0)
        self._view.clear_sprite()
        self._view.set_sprite_frame(first_frame.rgba)
        self._form_generation += 1
        generation = self._form_generation
        self._sprite_path = path
        self._form_artifacts_by_frame.clear()
        self._form_frame_indices = {
            frame_path.resolve(): index for index, frame_path in enumerate(media.frame_paths)
        }
        self._queued_form_generation = -1
        media_text = (
            f"animated image · {media.frame_count} frames" if media.animated else "still image"
        )
        self._sprite_label.setText(f"{path.name}\n{media_text}")
        self.statusBar().showMessage(f"Preparing surface maps for {path.name}…")
        form_path = media.reference_path
        future = self._form_executor.submit(self._cache.form, form_path)
        future.add_done_callback(
            lambda completed: self._form_finished(generation, form_path, completed)
        )

    def _form_finished(self, generation: int, path: Path, future) -> None:
        try:
            artifacts = future.result()
        except Exception as error:  # noqa: BLE001 - worker failures must reach the GUI.
            self._signals.failed.emit("Sprite analysis", str(error))
            return
        self._signals.formReady.emit(generation, path, artifacts, artifacts.metadata)

    def _on_form_ready(
        self, generation: int, path: Path, artifacts: FormArtifacts, metadata: dict
    ) -> None:
        if generation != self._form_generation:
            return
        media = self._sprite_media
        frame_index = self._form_frame_indices.get(path.resolve(), 0)
        self._form_artifacts_by_frame[frame_index] = artifacts
        if media is None or not media.animated:
            self._view.set_sprite(path, artifacts)
        else:
            first_artifacts = self._form_artifacts_by_frame.get(0)
            if first_artifacts is not None:
                # Animated playback remains on its exact first sprite/form pair
                # until every authored frame has a matching reconstruction.
                first = media.frame_at(0.0)
                self._view.set_sprite_frame(first.rgba, first_artifacts)
            if self._queued_form_generation != generation:
                self._queued_form_generation = generation
                for next_index in range(1, media.frame_count):
                    next_path = media.frame_path(next_index)
                    future = self._form_executor.submit(self._cache.form, next_path)
                    future.add_done_callback(
                        lambda completed, queued_path=next_path: self._form_finished(
                            generation, queued_path, completed
                        )
                    )
        cache_text = (
            "cache hit" if artifacts.cached else f"analyzed in {artifacts.build_seconds:.2f}s"
        )
        size = metadata.get("source_size", (0, 0))
        if media is not None and media.animated:
            ready = len(self._form_artifacts_by_frame)
            if ready == media.frame_count:
                self._sprite_animation_ready = True
                self._restart_sprite_animation()
            self._sprite_label.setText(
                f"{self._sprite_path.name if self._sprite_path else path.name}\n"
                f"{size[0]}×{size[1]} · animated forms {ready}/{media.frame_count}"
            )
            self.statusBar().showMessage(f"Sprite frames prepared: {ready}/{media.frame_count}")
        else:
            self._sprite_label.setText(
                f"{self._sprite_path.name if self._sprite_path else path.name}\n"
                f"{size[0]}×{size[1]} · {cache_text}"
            )
            self.statusBar().showMessage(f"Sprite ready · {cache_text} · live GPU lighting active")

    def _advance_animation(self) -> None:
        if getattr(self, "_exporting_animation", False):
            return
        now = time.perf_counter()
        if (
            self._background_animation_ready
            and self._background_media is not None
            and self._background_media.animated
        ):
            background_elapsed_ms = (now - self._background_animation_epoch) * 1000.0
            if getattr(self._background_media, "kind", "") == "video":
                frame = self._poll_background_video_frame(
                    self._background_media, background_elapsed_ms
                )
            else:
                frame = self._background_media.changed_at(background_elapsed_ms)
            if frame is not None:
                self._current_background_index = frame.index
                self._view.set_background_frame(
                    frame.rgba,
                    None
                    if getattr(self, "_gpu_live_background", False)
                    else environment_wrap(frame.rgba),
                )
                self._apply_temporal_scene(frame.index)
        if (
            self._sprite_animation_ready
            and self._sprite_media is not None
            and self._sprite_media.animated
        ):
            sprite_elapsed_ms = (now - self._sprite_animation_epoch) * 1000.0
            frame = self._sprite_media.changed_at(sprite_elapsed_ms)
            artifacts = (
                self._form_artifacts_by_frame.get(frame.index) if frame is not None else None
            )
            if frame is not None and artifacts is not None:
                self._view.set_sprite_frame(frame.rgba, artifacts)
        MainWindow._schedule_animation_tick(self)

    def _schedule_animation_tick(self) -> None:
        timer = getattr(self, "_animation_timer", None)
        if timer is None:
            return
        now = time.perf_counter()
        delays = []
        for media, enabled, epoch, is_background in (
            (
                self._background_media,
                self._background_animation_ready,
                self._background_animation_epoch,
                True,
            ),
            (self._sprite_media, self._sprite_animation_ready, self._sprite_animation_epoch, False),
        ):
            if media is None or not media.animated or not enabled:
                continue
            elapsed = max(0.0, (now - epoch) * 1000.0)
            if is_background and media.kind == "video":
                playback = self._background_playback
                if playback is None:
                    delays.append(0)
                elif playback.future is not None and playback.future.done():
                    delays.append(
                        max(1, math.ceil(playback.requested * 1000.0 / media.fps - elapsed))
                    )
                # The decoder's queued completion signal supplies the next wake
                # when work is outstanding. No busy polling or extra timer tick.
            elif media.kind == "animated-image":
                index = media.index_at(elapsed)
                remaining = media.cumulative_ms[index] - elapsed % media.duration_ms
                delays.append(max(1, math.ceil(remaining)))
            else:
                delays.append(max(1, math.ceil(1000.0 / max(media.fps, 1.0))))
        if delays:
            timer.start(min(delays))
        else:
            timer.stop()

    def _on_video_frame_ready(self, generation: int) -> None:
        if (
            generation == self._background_decode_generation
            and self._background_animation_ready
            and not getattr(self, "_exporting_animation", False)
        ):
            self._advance_animation()

    def _poll_background_video_frame(
        self, media: MediaClip, elapsed_ms: float
    ) -> MediaFrame | None:
        """Present timestamped frames while the serial decoder stays one ahead."""
        if self._background_playback is None:
            generation = self._background_decode_generation
            signal = getattr(getattr(self, "_signals", None), "videoFrameReady", None)
            callback = (lambda: signal.emit(generation)) if signal is not None else None
            self._background_playback = VideoPlayback(
                media,
                self._video_decode_executor,
                on_ready=callback,
                initially_presented=0 if self._current_background_index == 0 else -1,
            )
        try:
            return self._background_playback.poll(elapsed_ms)
        except Exception as error:  # noqa: BLE001 - decoder errors must reach the GUI.
            self._background_animation_ready = False
            self._signals.failed.emit("Video playback", str(error))
            return None

    def _stop_background_decode(self) -> None:
        self._background_decode_generation += 1
        playback = self._background_playback
        self._background_playback = None
        for future in playback.stop() if playback is not None else ():
            if future.cancel():
                continue
            try:
                future.result()
            except Exception:
                # Drain obsolete seeks before closing their decoder too.
                pass

    def _on_failed(self, operation: str, message: str) -> None:
        self.statusBar().showMessage(f"{operation} failed")
        QMessageBox.critical(self, operation, message)

    def _on_live_analysis_finished(self, milliseconds: float) -> None:
        if getattr(self, "_exporting_animation", False):
            return
        now = time.perf_counter()
        if self._gpu_live_background and not self._temporal_playback_started:
            media = self._background_media
            if media is not None and media.animated:
                self._temporal_playback_started = True
                self._background_animation_ready = True
                self._restart_background_animation()
        if not self._gpu_live_background or now - self._last_live_status < 0.5:
            return
        self._last_live_status = now
        self._analysis_label.setText("Live lighting active")

    def _on_live_analysis_failed(self, message: str) -> None:
        self._gpu_live_background = False
        self._view.set_live_analysis_enabled(False)
        self._view.clear_scene()
        self._background_animation_ready = False
        media = self._background_media
        if media is None:
            return
        self.statusBar().showMessage(f"Using compatible cached analysis: {message}")
        generation = self._scene_generation
        future = self._scene_executor.submit(self._cache.scene, media.reference_path)
        future.add_done_callback(
            lambda completed: self._scene_finished(generation, media.reference_path, completed)
        )

    def _placement_from_controls(self) -> None:
        horizontal = self._horizontal_slider.value() / 100.0
        baseline = self._baseline_slider.value() / 100.0
        height = self._height_slider.value() / 100.0
        self._horizontal_value.setText(f"{horizontal:.0%}")
        self._baseline_value.setText(f"{baseline:.0%}")
        self._height_value.setText(f"{height:.0%}")
        self._view.set_placement(horizontal, baseline, height)

    def _strength_changed(self) -> None:
        strength = self._strength_slider.value() / 100.0
        self._strength_value.setText(f"{strength:.0%}")
        self._view.set_strength(strength)
        if self._lighting_look.currentIndex() != 0:
            self._lighting_look.blockSignals(True)
            self._lighting_look.setCurrentIndex(0)
            self._lighting_look.blockSignals(False)

    def _sync_placement(self, horizontal: float, baseline: float, height: float) -> None:
        for slider, value in (
            (self._horizontal_slider, horizontal),
            (self._baseline_slider, baseline),
            (self._height_slider, height),
        ):
            slider.blockSignals(True)
            slider.setValue(round(value * 100))
            slider.blockSignals(False)
        self._horizontal_value.setText(f"{horizontal:.0%}")
        self._baseline_value.setText(f"{baseline:.0%}")
        self._height_value.setText(f"{height:.0%}")

    def _on_renderer_ready(self, renderer: str) -> None:
        self._gpu_label.setText(
            f"{renderer}\nShader {self._view.shader_sha256[:12]} · 8 bound textures"
        )

    def _on_frame_time(self, milliseconds: float) -> None:
        now = time.perf_counter()
        if now - getattr(self, "_last_frame_label_update", 0.0) < 0.5:
            return
        self._last_frame_label_update = now
        self._frame_label.setText(f"GPU frame submission: {milliseconds:.2f} ms")

    def export(self) -> None:
        if self._background_path is None or self._sprite_path is None:
            QMessageBox.information(
                self, "Nothing to export", "Load a background and sprite first."
            )
            return
        media = self._background_media
        sprite_media = self._sprite_media
        if media is None or sprite_media is None:
            return
        sizes = {
            "1080p (1920 × 1080)": (1920, 1080),
            "720p (1280 × 720)": (1280, 720),
            "4K (3840 × 2160)": (3840, 2160),
        }
        resolution, accepted = QInputDialog.getItem(
            self, "Export", "Resolution", list(sizes), 0, False
        )
        if not accepted:
            return
        size = sizes[resolution]
        extension = export_extension(media.kind, sprite_media.kind)
        suggested = self._background_path.with_name(
            f"{self._background_path.stem}_{self._sprite_path.stem}_gpu_relit{extension}"
        )
        filters = {
            ".png": "PNG image (*.png)",
            ".gif": "Animated GIF (*.gif)",
            ".mp4": "H.264 video (*.mp4)",
        }
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export composite",
            str(suggested),
            filters[extension],
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != extension:
            destination = destination.with_suffix(extension)
        try:
            if extension == ".png":
                self._view.export_png(destination, size)
            else:
                self._export_animation(destination, size)
            record = {
                "shader_sha256": self._view.shader_sha256,
                "analysis_sha256": engine_identity(),
                "background_sha256": source_identity(self._background_path),
                "sprite_sha256": source_identity(self._sprite_path),
                "size": list(size),
                "source_frames": media.frame_count,
                "source_fps": media.fps,
                "calibration": self._view._calibration.as_dict(),
                "strength": self._view._strength,
                "placement": [
                    self._view._horizontal,
                    self._view._baseline,
                    self._view._character_height,
                ],
                "form_version": self._view._form_artifacts.metadata["version"],
            }
            destination.with_suffix(destination.suffix + ".json").write_text(
                json.dumps(record, indent=2) + "\n", encoding="utf-8"
            )
        except InterruptedError:
            self.statusBar().showMessage("Animation export cancelled")
            return
        except Exception as error:  # noqa: BLE001 - OpenGL errors must reach the GUI.
            self._on_failed("Export", str(error))
            return
        self.statusBar().showMessage(f"Saved {destination}")

    def _export_animation(self, destination: Path, size: tuple[int, int] = (1920, 1080)) -> None:
        assert self._background_path is not None
        assert self._sprite_path is not None
        self._exporting_animation = True
        self._animation_timer.stop()
        self._stop_background_decode()
        self._temporal_cancel.set()
        progress: QProgressDialog | None = None
        background: MediaClip | None = None
        sprite: MediaClip | None = None
        export_cancel = threading.Event()
        try:
            progress = QProgressDialog(
                "Stopping live analysis before export…",
                "Cancel export",
                0,
                0,
                self,
            )
            progress.setWindowTitle("Exporting SceneLight animation")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.canceled.connect(export_cancel.set)
            progress.show()
            _export_checkpoint(progress, export_cancel)
            while self._preparation_process is not None:
                progress.setLabelText("Preparing movie lighting before export…")
                _export_checkpoint(progress, export_cancel)
                time.sleep(0.01)
            if (
                self._gpu_live_background
                and not self._view._live_analysis_enabled
                and self._prepared_reader is None
            ):
                raise RuntimeError(
                    "Movie lighting is not ready; reopen the background to prepare it before exporting"
                )
            if self._temporal_future is not None:
                warmed_anchors, built = _wait_for_export_future(
                    self._temporal_future,
                    progress,
                    export_cancel,
                )
                self._temporal_anchors = warmed_anchors
                self._temporal_scenes.update(built)
            background = MediaClip(self._background_path, self._cache.root / "media")
            sprite = MediaClip(self._sprite_path, self._cache.root / "media")
            _export_checkpoint(progress, export_cancel)

            live = getattr(self, "_gpu_live_background", False)
            if self._scene_artifacts is None and not live:
                self._scene_artifacts = self._cache.scene(background.reference_path)
                self._view.set_scene(background.reference_path, self._scene_artifacts)
                self._temporal_scenes[0] = self._scene_frame_from_artifacts(self._scene_artifacts)

            anchors = () if live else background.temporal_anchor_indices(detect_changes=True)
            missing_anchors = [index for index in anchors if index not in self._temporal_scenes]
            form_by_frame = dict(self._form_artifacts_by_frame)
            missing_forms = [
                index for index in range(sprite.frame_count) if index not in form_by_frame
            ]
            if background.kind == "video":
                timeline_ms = tuple(
                    index * 1000.0 / background.fps for index in range(background.frame_count)
                )
                timeline_durations = tuple(
                    max(1, round(1000.0 / background.fps))
                    for _index in range(background.frame_count)
                )
            else:
                timeline_ms, timeline_durations = composite_gif_timeline(background, sprite)
            total_work = len(missing_anchors) + len(missing_forms) + len(timeline_ms)
            progress.setRange(0, max(total_work, 1))
            progress.setLabelText("Preparing animation lighting…")
            progress.setValue(0)
            completed = 0

            uncached_anchors: list[int] = []
            prepared_anchors = 0
            for index in missing_anchors:
                _export_checkpoint(progress, export_cancel)
                cached = self._cache.temporal_scene_cached(background.temporal_cache_key(index))
                if cached is None:
                    uncached_anchors.append(index)
                    continue
                self._temporal_scenes[index] = self._scene_frame_from_temporal(cached)
                prepared_anchors += 1
                completed += 1
                progress.setValue(completed)
                progress.setLabelText(f"Lighting sample {prepared_anchors}/{len(missing_anchors)}")
                _export_checkpoint(progress, export_cancel)

            for offset in range(0, len(uncached_anchors), 16):
                batch_indices = uncached_anchors[offset : offset + 16]
                prepared: list[tuple[int, Path, str]] = []
                transient_paths: list[Path] = []
                try:
                    for frame in background.iter_frames(batch_indices):
                        _export_checkpoint(progress, export_cancel)
                        path, transient = background.analysis_frame_path(frame)
                        prepared.append(
                            (
                                frame.index,
                                path,
                                background.temporal_cache_key(frame.index),
                            )
                        )
                        if transient:
                            transient_paths.append(path)
                    for frame_index, artifacts in self._cache.temporal_scene_batch(
                        tuple(prepared),
                        export_cancel,
                    ):
                        _export_checkpoint(progress, export_cancel)
                        self._temporal_scenes[frame_index] = self._scene_frame_from_temporal(
                            artifacts
                        )
                        prepared_anchors += 1
                        completed += 1
                        progress.setValue(completed)
                        progress.setLabelText(
                            f"Lighting sample {prepared_anchors}/{len(missing_anchors)}"
                        )
                        _export_checkpoint(progress, export_cancel)
                finally:
                    for path in transient_paths:
                        path.unlink(missing_ok=True)

            for position, index in enumerate(missing_forms, start=1):
                _export_checkpoint(progress, export_cancel)
                form_by_frame[index] = self._cache.form(sprite.frame_path(index))
                completed += 1
                progress.setValue(completed)
                progress.setLabelText(f"Preparing sprite frame {position}/{len(missing_forms)}")
                _export_checkpoint(progress, export_cancel)

            # Export may be the operation that finishes warming an animation.
            # Keep those exact artifacts in the live viewport too, otherwise a
            # cancelled background worker could leave playback paused even
            # though export just built every required scene and form.
            self._temporal_anchors = anchors
            self._temporal_plan_known_through = background.frame_count - 1
            self._temporal_plan_complete = True
            self._form_artifacts_by_frame.update(form_by_frame)
            self._background_animation_ready = all(
                index in self._temporal_scenes for index in anchors
            )
            self._sprite_animation_ready = all(
                index in self._form_artifacts_by_frame for index in range(sprite.frame_count)
            )

            def render_frames(write_frame) -> None:
                nonlocal completed
                for output_index, timestamp_ms in enumerate(timeline_ms):
                    _export_checkpoint(progress, export_cancel)
                    if output_index == 0:
                        self._view.reset_live_history()
                    frame = (
                        background.frame_by_index(output_index)
                        if background.kind == "video"
                        else background.frame_at(timestamp_ms)
                    )
                    self._view.set_background_frame(
                        frame.rgba,
                        None if self._gpu_live_background else environment_wrap(frame.rgba),
                    )
                    scene = (
                        None
                        if self._gpu_live_background
                        else interpolated_scene(self._temporal_scenes, frame.index)
                    )
                    if scene is not None:
                        self._view.set_live_scene_frame(scene)
                    if self._prepared_reader is not None:
                        self._view.set_prepared_fields(self._prepared_reader.frame(frame.index))
                    sprite_frame = sprite.frame_at(timestamp_ms)
                    self._view.set_sprite_frame(
                        sprite_frame.rgba,
                        form_by_frame[sprite_frame.index],
                    )
                    write_frame(self._view.render_rgba(size))
                    completed += 1
                    progress.setValue(completed)
                    progress.setLabelText(
                        f"GPU rendering frame {output_index + 1}/{len(timeline_ms)}"
                    )
                    _export_checkpoint(progress, export_cancel)

            if background.kind == "video":
                with MP4Writer(
                    destination,
                    background.source,
                    size,
                    background.fps,
                    frames=len(timeline_ms),
                ) as writer:
                    render_frames(writer.write)
            else:
                with GIFWriter(destination, timeline_durations) as writer:
                    render_frames(writer.write)
        finally:
            export_cancel.set()
            if progress is not None:
                progress.close()
            if background is not None:
                background.close()
            if sprite is not None:
                sprite.close()
            if self._background_media is not None:
                self._view.reset_live_history()
                first = self._background_media.frame_by_index(0)
                self._view.set_background_frame(
                    first.rgba, None if self._gpu_live_background else environment_wrap(first.rgba)
                )
                self._current_background_index = 0
                self._apply_temporal_scene(0)
            if self._sprite_media is not None:
                first = self._sprite_media.frame_by_index(0)
                self._view.set_sprite_frame(first.rgba, self._form_artifacts_by_frame.get(0))
            self._exporting_animation = False
            self._restart_background_animation()
            self._restart_sprite_animation()
            self._animation_timer.start()

    def closeEvent(self, event) -> None:
        self._stop_preparation()
        self._animation_timer.stop()
        self._temporal_cancel.set()
        self._stop_background_decode()
        if self._background_media is not None:
            self._background_media.close()
        if self._sprite_media is not None:
            self._sprite_media.close()
        self._temporal_executor.shutdown(wait=True, cancel_futures=True)
        self._video_decode_executor.shutdown(wait=True, cancel_futures=True)
        self._cache.shutdown()
        self._scene_executor.shutdown(wait=False, cancel_futures=True)
        self._form_executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    @staticmethod
    def _style() -> str:
        return """
            QMainWindow, QWidget { background: #0a1018; color: #dbe8f7; font-size: 13px; }
            QPushButton { background: #20334a; border: 1px solid #34516f; padding: 9px 13px; }
            QPushButton:hover { background: #294563; }
            QPushButton:pressed { background: #4d82ff; }
            QTabWidget::pane { background: #0a1018; border: 1px solid #34516f; }
            QTabBar::tab {
                background: #172638; color: #dbe8f7;
                border: 1px solid #34516f; border-bottom: 3px solid #34516f;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
                padding: 9px 14px; margin-right: 3px;
            }
            QTabBar::tab:hover { background: #25405a; color: #ffffff; }
            QTabBar::tab:selected {
                background: #294563; color: #ffffff;
                border-bottom: 3px solid #74d5f3; font-weight: 600;
            }
            QTabBar::tab:focus { border-color: #b4e6ff; }
            QGroupBox { border: 1px solid #34516f; border-radius: 4px; margin-top: 12px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #ffffff; }
            QFrame#panel { background: #101a27; border: 1px solid #1f3045; }
            QFrame#section { background: #172638; border: 1px solid #22364e; padding: 4px; }
            QLabel#title { color: white; font-size: 25px; font-weight: 700; }
            QLabel#subtitle { color: #76a8d7; font-size: 12px; }
            QLabel#sectionTitle { color: #ffffff; font-size: 15px; font-weight: 650; }
            QLabel#hint { color: #7e9aba; }
            QSlider::groove:horizontal { height: 5px; background: #2a3d54; }
            QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #dce8f6; }
            QStatusBar { color: #83a6c8; }
        """
