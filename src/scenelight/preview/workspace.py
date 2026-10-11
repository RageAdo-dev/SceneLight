"""Scene editing using the shared background and media pipeline."""

from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)

from .. import diagnostics
from ..diagnostics_ui import show_preview_reports
from .gpu_view import SceneSprite
from .library import Actor, Library, author_rules, load_scene, save_scene
from .library_ui import LibraryDialog
from .media import MediaClip


class SceneWorkspace:
    def _init_workspace(self):
        self._actors = []
        self._actor_media = {}
        self._actor_forms = {}
        self._actor_epochs = {}
        self._actor_loads = {}
        self._actor_queued = set()
        self._active_actor = None
        self._selecting_actor = False
        self._library = Library()

    def _workspace_toolbar(self, layout):
        row = QHBoxLayout()
        for title, callback in (
            ("Asset library…", self._show_library),
            ("Save sprite…", self._save_sprite_asset),
            ("Save background…", self._save_background_asset),
            ("Open scene…", self._open_scene_file),
            ("Save scene…", self._save_scene_file),
            ("Export sprite rules…", self._export_sprite_rules),
            ("Logs && report…", self._show_reports),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

    def _show_reports(self):
        self._store_selected_actor()
        session = diagnostics.current_session()
        if session is not None:
            session.update(
                actors=[actor.payload() for actor in self._actors],
                background=str(self._background_path or ""),
            )
            session.event(
                "preview.snapshot",
                "Current composition",
                actors=[actor.payload() for actor in self._actors],
                forms={
                    actor.id: {
                        index: form.metadata for index, form in self._actor_forms[actor.id].items()
                    }
                    for actor in self._actors
                },
            )
        show_preview_reports(self)

    def _workspace_panel(self, layout):
        layout.addWidget(QLabel("Characters · select one to edit"))
        self._actor_list = QListWidget()
        self._actor_list.setMaximumHeight(115)
        self._actor_list.currentRowChanged.connect(self._actor_selected)
        layout.addWidget(self._actor_list)
        buttons = QHBoxLayout()
        for title, callback in (
            ("Duplicate", self._duplicate_actor),
            ("Remove", self._remove_actor),
            ("Back", lambda: self._move_actor(-1)),
            ("Front", lambda: self._move_actor(1)),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._actor_visible = QCheckBox("Show selected character")
        self._actor_visible.setChecked(True)
        self._actor_visible.toggled.connect(self._store_selected_actor)
        layout.addWidget(self._actor_visible)
        self._image_rule_name = QLineEdit()
        self._image_rule_name.setPlaceholderText("Ren'Py image name, e.g. hero happy")
        self._image_rule_name.setToolTip(
            "Used by Export sprite rules to set lighting for this exact image in-game."
        )
        self._image_rule_name.editingFinished.connect(self._store_selected_actor)
        layout.addWidget(self._image_rule_name)
        strength_row = QHBoxLayout()
        strength_row.addWidget(QLabel("Exact lighting strength"))
        self._exact_strength = QDoubleSpinBox()
        self._exact_strength.setRange(0.0, 2.0)
        self._exact_strength.setDecimals(2)
        self._exact_strength.setSingleStep(0.05)
        self._exact_strength.setValue(1.0)
        self._exact_strength.valueChanged.connect(
            lambda value: self._strength_slider.setValue(round(value * 100))
        )
        strength_row.addWidget(self._exact_strength)
        layout.addLayout(strength_row)

    def _selected_actor(self):
        return next((actor for actor in self._actors if actor.id == self._active_actor), None)

    def _sync_actor_list(self):
        self._actor_list.blockSignals(True)
        self._actor_list.clear()
        for actor in self._actors:
            item = QListWidgetItem(actor.name + (" · hidden" if not actor.visible else ""))
            item.setData(Qt.UserRole, actor.id)
            self._actor_list.addItem(item)
        self._actor_list.setCurrentRow(
            next((i for i, a in enumerate(self._actors) if a.id == self._active_actor), -1)
        )
        self._actor_list.blockSignals(False)

    def _actor_selected(self, row):
        if 0 <= row < len(self._actors):
            self._select_actor(self._actors[row].id)

    def _select_actor(self, actor_id):
        self._store_selected_actor()
        actor = next((actor for actor in self._actors if actor.id == actor_id), None)
        if actor is None:
            return
        self._active_actor = actor.id
        self._selecting_actor = True
        try:
            self._calibration = actor.calibration
            self._view.set_calibration(actor.calibration)
            self._view.set_strength(actor.strength)
            self._view.set_placement(actor.horizontal, actor.baseline, actor.height)
            self._sync_placement(actor.horizontal, actor.baseline, actor.height)
            self._strength_slider.blockSignals(True)
            self._strength_slider.setValue(round(actor.strength * 100))
            self._strength_slider.blockSignals(False)
            self._strength_value.setText(f"{actor.strength:.0%}")
            self._exact_strength.blockSignals(True)
            self._exact_strength.setValue(actor.strength)
            self._exact_strength.blockSignals(False)
            self._actor_visible.setChecked(actor.visible)
            self._image_rule_name.setText(actor.image_name)
            self._lighting_look.blockSignals(True)
            self._lighting_look.setCurrentIndex(0)
            self._lighting_look.blockSignals(False)
            self._sprite_path = Path(actor.source)
            self._sprite_media = self._actor_media[actor.id]
            self._form_artifacts_by_frame = self._actor_forms[actor.id]
            self._sprite_animation_epoch = self._actor_epochs[actor.id]
            self._sprite_animation_ready = (
                len(self._form_artifacts_by_frame) == self._sprite_media.frame_count
            )
            self._sprite_label.setText(
                f"{actor.name}\n{len(self._form_artifacts_by_frame)}/{self._sprite_media.frame_count} surface frames ready"
            )
        finally:
            self._selecting_actor = False
        self._sync_actor_list()
        self._update_scene_frames()

    def _store_selected_actor(self, _value=None):
        if getattr(self, "_selecting_actor", False) or not hasattr(self, "_actors"):
            return
        actor = self._selected_actor()
        if actor is None:
            return
        actor.calibration = self._calibration
        actor.strength = self._strength_slider.value() / 100
        self._exact_strength.blockSignals(True)
        self._exact_strength.setValue(actor.strength)
        self._exact_strength.blockSignals(False)
        actor.horizontal = self._horizontal_slider.value() / 100
        actor.baseline = self._baseline_slider.value() / 100
        actor.height = self._height_slider.value() / 100
        actor.visible = self._actor_visible.isChecked()
        actor.image_name = self._image_rule_name.text().strip()
        self._sync_actor_list()
        self._update_scene_frames()

    def _add_actor(self, path: Path, template: Actor | None = None):
        if len(self._actors) >= 16:
            raise ValueError(
                "This scene already has 16 characters. Remove one before adding another."
            )
        media = MediaClip(path, self._cache.root / "media")
        if media.kind == "video":
            media.close()
            raise ValueError("Use PNG, GIF, APNG, or WebP for character sprites with transparency.")
        actor = (
            copy.deepcopy(template)
            if template
            else Actor(
                name=path.stem,
                calibration=self._calibration_profile.calibration,
                strength=self._calibration_profile.normalized_strength(),
            )
        )
        actor.source = str(path.resolve())
        if any(existing.id == actor.id for existing in self._actors):
            actor.id = uuid.uuid4().hex
        if template is None and self._actors:
            actor.horizontal = min(0.8, 0.35 + 0.2 * len(self._actors))
        self._actors.append(actor)
        self._actor_media[actor.id] = media
        self._actor_forms[actor.id] = {}
        self._actor_epochs[actor.id] = time.perf_counter()
        self._form_generation += 1
        generation = self._form_generation
        self._actor_loads[generation] = actor.id
        path = media.reference_path
        future = self._form_executor.submit(self._cache.form, path)
        future.add_done_callback(lambda completed: self._form_finished(generation, path, completed))
        self._select_actor(actor.id)
        diagnostics.event(
            "preview.asset",
            "Added character",
            actor=actor.payload(),
            frames=media.frame_count,
            size=media.size,
        )
        return actor

    def _actor_form_ready(self, generation, path, artifacts, metadata):
        actor_id = self._actor_loads.get(generation)
        if actor_id not in self._actor_media:
            return
        media = self._actor_media[actor_id]
        index = next(
            (i for i, p in enumerate(media.frame_paths) if p.resolve() == path.resolve()), 0
        )
        forms = self._actor_forms[actor_id]
        forms[index] = artifacts
        if generation not in self._actor_queued:
            self._actor_queued.add(generation)
            for frame_index in range(1, media.frame_count):
                frame_path = media.frame_path(frame_index)
                future = self._form_executor.submit(self._cache.form, frame_path)
                future.add_done_callback(
                    lambda completed, p=frame_path: self._form_finished(generation, p, completed)
                )
        if len(forms) == media.frame_count:
            self._actor_epochs[actor_id] = time.perf_counter()
            diagnostics.event(
                "preview.form",
                "Character surfaces ready",
                actor_id=actor_id,
                frames=len(forms),
                source_size=metadata.get("source_size"),
                cache_hit=artifacts.cached,
            )
        if actor_id == self._active_actor:
            self._sprite_animation_ready = len(forms) == media.frame_count
            self._sprite_animation_epoch = self._actor_epochs[actor_id]
            self._sprite_label.setText(
                f"{self._selected_actor().name}\n{len(forms)}/{media.frame_count} surface frames ready"
            )
        self._update_scene_frames()
        self._animation_timer.start(0)

    def _update_scene_frames(self, timestamp_ms=None):
        sprites = []
        now = time.perf_counter()
        for actor in self._actors:
            media = self._actor_media[actor.id]
            forms = self._actor_forms[actor.id]
            ready = len(forms) == media.frame_count
            elapsed = (
                (now - self._actor_epochs[actor.id]) * 1000
                if timestamp_ms is None
                else timestamp_ms
            )
            frame = media.frame_at(elapsed if ready else 0)
            artifact = forms.get(frame.index)
            if artifact is not None:
                sprites.append(SceneSprite(actor, frame.rgba, artifact))
        self._view.set_scene_sprites(sprites, self._active_actor)

    def _remove_actor(self):
        actor = self._selected_actor()
        if actor is None:
            return
        self._actors.remove(actor)
        self._actor_media.pop(actor.id).close()
        self._actor_forms.pop(actor.id, None)
        self._actor_epochs.pop(actor.id, None)
        old_generations = [key for key, value in self._actor_loads.items() if value == actor.id]
        for key in old_generations:
            self._actor_loads.pop(key, None)
            self._actor_queued.discard(key)
        self._active_actor = None
        self._sprite_media = None
        self._sprite_path = None
        self._form_artifacts_by_frame = {}
        if self._actors:
            self._select_actor(self._actors[-1].id)
        self._sync_actor_list()
        self._update_scene_frames()

    def _duplicate_actor(self):
        self._store_selected_actor()
        actor = self._selected_actor()
        if actor:
            duplicate = copy.deepcopy(actor)
            duplicate.id = uuid.uuid4().hex
            duplicate.name += " copy"
            duplicate.horizontal = min(1.25, duplicate.horizontal + 0.12)
            self._add_actor(Path(actor.source), duplicate)

    def _move_actor(self, offset):
        actor = self._selected_actor()
        if actor:
            index = self._actors.index(actor)
            target = index + offset
            if 0 <= target < len(self._actors):
                self._actors[index], self._actors[target] = (
                    self._actors[target],
                    self._actors[index],
                )
                self._sync_actor_list()
                self._update_scene_frames()

    def _show_library(self):
        dialog = LibraryDialog(self._library, self)
        if dialog.exec() and dialog.chosen:
            entry = dialog.chosen
            try:
                path = self._library.path(entry["source"])
                if entry["kind"] == "background":
                    self._load_background(path)
                else:
                    template = (
                        Actor.from_payload(entry["actor"])
                        if entry.get("actor")
                        else Actor(name=entry["name"])
                    )
                    template.name = entry["name"]
                    self._add_actor(path, template)
            except (OSError, ValueError) as error:
                self._on_failed("Load library asset", str(error))

    def _save_sprite_asset(self):
        self._store_selected_actor()
        actor = self._selected_actor()
        if actor:
            name, accepted = QInputDialog.getText(
                self, "Save sprite to library", "Name", text=actor.name
            )
            if accepted:
                try:
                    self._library.add("sprite", Path(actor.source), name=name, actor=actor)
                    self.statusBar().showMessage(
                        "Sprite and its lighting settings saved in the asset library"
                    )
                except (OSError, ValueError) as error:
                    self._on_failed("Save sprite", str(error))

    def _save_background_asset(self):
        if self._background_path:
            try:
                self._library.add("background", self._background_path)
                self.statusBar().showMessage("Background saved in the asset library")
            except (OSError, ValueError) as error:
                self._on_failed("Save background", str(error))

    def _save_scene_file(self):
        self._store_selected_actor()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Preview scene", "scenelight-scene.json", "Scene (*.json)"
        )
        if path:
            try:
                # Retain media in the library before saving references. Reopening
                # this scene should survive the original Downloads file moving.
                saved_actors = copy.deepcopy(self._actors)
                for actor in saved_actors:
                    actor.source = str(self._library._copy(Path(actor.source)))
                background = (
                    str(self._library._copy(self._background_path))
                    if self._background_path
                    else None
                )
                save_scene(
                    Path(path),
                    background,
                    saved_actors,
                )
                self.statusBar().showMessage(
                    "Scene saved with character placements and individual lighting"
                )
            except (OSError, ValueError) as error:
                self._on_failed("Save scene", str(error))

    def _open_scene_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Preview scene", "", "Scene (*.json)")
        if not path:
            return
        try:
            background, actors = load_scene(Path(path))
            # Validate all media before replacing the current composition.
            sources = [(Path(a.source), True) for a in actors] + (
                [(background, False)] if background else []
            )
            for source, is_sprite in sources:
                clip = MediaClip(source, self._cache.root / "media")
                invalid = is_sprite and clip.kind == "video"
                clip.close()
                if invalid:
                    raise ValueError(
                        "A saved character references a video; use GIF, APNG, WebP, or PNG sprites."
                    )
            for actor in list(self._actors):
                self._active_actor = actor.id
                self._remove_actor()
            if background:
                self._load_background(background)
            for actor in actors:
                self._add_actor(Path(actor.source), actor)
        except (OSError, ValueError) as error:
            self._on_failed("Open scene", str(error))

    def _export_sprite_rules(self):
        self._store_selected_actor()
        if not self._actors:
            return
        scope, accepted = QInputDialog.getItem(
            self,
            "Export lighting rules",
            "Which characters?",
            ("Selected character", "All characters"),
            0,
            False,
        )
        if not accepted:
            return
        actors = (
            [self._selected_actor()]
            if scope == "Selected character" and self._selected_actor()
            else self._actors
        )
        try:
            text = author_rules(actors)
        except ValueError as error:
            QMessageBox.information(self, "Image names needed", str(error))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export per-image lighting rules",
            "scenelight_sprite_rules.rpy",
            "Ren'Py script (*.rpy)",
        )
        if path:
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.statusBar().showMessage(
                    "Rules exported · place the file under game/ with the SceneLight developer API installed"
                )
            except OSError as error:
                self._on_failed("Export sprite rules", str(error))
