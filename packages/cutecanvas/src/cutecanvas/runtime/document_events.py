#    CuteCanvas - High-performance layered image editor
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""DocumentEvents behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from PySide6.QtCore import (
    QLineF,
    QPointF,
    QRect,
    QRectF,
)
from PySide6.QtGui import (
    QColor,
    QTransform,
)
from qpane.sdk.catalog import CatalogImageReference, CatalogMutationEvent
from qpane.sdk.compare import (
    ComparisonChange,
    ComparisonChangeKind,
)
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
)
from qpane.sdk.rendering import ViewportZoomMode
from qpane.sdk.scene import LayerDescriptor, RasterLayerRenderItem, SceneDescriptor
from qpane.sdk.types import (
    ComparisonOrientation,
)

from cutecanvas.composition import CompositionRecord
from cutecanvas.composition.layers import CompositionLayerInstance
from cutecanvas.composition.public_policy import (
    public_layer_policy,
)
from cutecanvas.masks.source_reference import MaskAssetReference
from cutecanvas.painting import PaintTargetIdentity
from cutecanvas.placed.workflow import PlacedAssetCompletion
from cutecanvas.scene.layer_selection import (
    SceneLayerSelection,
)
from cutecanvas.scene.raster_mutations import (
    RasterBoundsCompletion,
)
from cutecanvas.selection import PixelSelectionState
from cutecanvas.types import (
    CompositionLayerClip,
    LayerSnapshot,
    PaintTargetKind,
    PixelSelectionSnapshot,
    SceneSnapshot,
)
from cutecanvas.vector.conversion import (
    VectorConversionCompletion,
    VectorConversionKind,
)


class DocumentEventsMixin:
    """Group documentevents facade behavior."""

    def _emit_viewport_rect_if_changed(self, *, force: bool = False) -> None:
        """Emit the physical viewport rectangle when it differs from the last snapshot."""
        try:
            rect = QRectF(self.physicalViewportRect())
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        if not force and self._last_viewport_rect == rect:
            return
        self._last_viewport_rect = rect
        self.viewportRectChanged.emit(rect)

    def _handle_catalog_mutation(self, event: CatalogMutationEvent) -> None:
        """Relay catalog mutations through the CuteCanvas signal surface."""
        self.view().invalidate_content_cache()
        removed_ids = self._removed_catalog_ids(event)
        compositions_changed = self._sync_compositions_with_catalog()
        compare = self.compare_service
        if compare is not None:
            if removed_ids:
                compare.remove_catalog_images(removed_ids)
            compare.reconcile_catalog()
        affected_ids = set(event.affected_ids)
        comparison_source_id = (
            compare.state().source_id if compare is not None else None
        )
        if (
            self.catalog().currentImageID() in affected_ids
            or comparison_source_id in affected_ids
        ):
            self._sync_viewport_content_geometry()
            self.view().mark_dirty(None)
            self.update()
        self.catalogChanged.emit(event)
        self._maybe_emit_link_groups_changed()
        if compositions_changed:
            self._emit_composition_changed()

    @staticmethod
    def _removed_catalog_ids(event: CatalogMutationEvent) -> set[uuid.UUID]:
        """Return affected IDs only for catalog mutations that remove entries."""
        if event.reason in {"removeImageByID", "removeImagesByID", "clearImages"}:
            return set(event.affected_ids)
        return set()

    def _handle_comparison_changed(
        self,
        change: ComparisonChange | None = None,
    ) -> None:
        """Refresh rendering and signals after comparison state changes."""
        try:
            self.view().invalidate_content_cache()
            if change is None or change.kind in {
                ComparisonChangeKind.SOURCE,
                ComparisonChangeKind.ENABLED,
            }:
                self._sync_viewport_content_geometry()
            if change is not None and change.kind == ComparisonChangeKind.SPLIT:
                dirty_rect = self._comparison_split_dirty_rect(change)
            else:
                dirty_rect = None
            self.view().mark_dirty(dirty_rect)
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        state = self._comparison_service().state()
        if not state.enabled:
            self.comparisonDividerInteraction().cancel_drag()
        self.comparisonChanged.emit(state)
        self.refreshCursor()
        self.update()

    def _comparison_split_dirty_rect(self, change: ComparisonChange) -> QRect | None:
        """Return the bounded dirty rect for a pure comparison split change."""
        previous = change.previous
        current = change.current
        if (
            not previous.enabled
            or not current.enabled
            or previous.source_id != current.source_id
            or previous.orientation != current.orientation
        ):
            return None
        plan = self.view().calculateRenderPlan(
            is_blank=getattr(self, "_is_blank", False)
        )
        if plan is None:
            return None
        compare_item = next(
            (
                item
                for item in plan.render_items
                if isinstance(item, RasterLayerRenderItem)
                and item.descriptor.hit_test.role == "comparison-image"
            ),
            None,
        )
        if compare_item is None:
            return None
        previous_line = self._comparison_split_line(
            compare_item,
            plan.scene_bounds,
            previous.split_position,
            current.orientation,
        )
        current_line = self._comparison_split_line(
            compare_item,
            plan.scene_bounds,
            current.split_position,
            current.orientation,
        )
        if previous_line is None or current_line is None:
            return None
        bounds = QRectF(previous_line.p1(), previous_line.p2()).normalized()
        bounds = bounds.united(
            QRectF(current_line.p1(), current_line.p2()).normalized()
        )
        hit_width = self.comparisonDividerInteraction().state().hit_width
        return bounds.adjusted(
            -hit_width,
            -hit_width,
            hit_width,
            hit_width,
        ).toAlignedRect()

    @staticmethod
    def _comparison_split_line(
        item: RasterLayerRenderItem,
        scene_bounds,
        split_position: float,
        orientation: ComparisonOrientation,
    ) -> QLineF | None:
        """Project a normalized comparison split into widget coordinates."""
        placement = item.placement
        source_width = item.source_image.width()
        source_height = item.source_image.height()
        if (
            source_width <= 0
            or source_height <= 0
            or placement.width <= 0.0
            or placement.height <= 0.0
        ):
            return None
        if orientation == ComparisonOrientation.HORIZONTAL:
            scene_y = scene_bounds.y + scene_bounds.height * split_position
            source_y = (scene_y - placement.y) * source_height / placement.height
            source_line = QLineF(
                QPointF(0.0, source_y),
                QPointF(float(source_width), source_y),
            )
        else:
            scene_x = scene_bounds.x + scene_bounds.width * split_position
            source_x = (scene_x - placement.x) * source_width / placement.width
            source_line = QLineF(
                QPointF(source_x, 0.0),
                QPointF(source_x, float(source_height)),
            )
        return QLineF(
            item.transform.map(source_line.p1()),
            item.transform.map(source_line.p2()),
        )

    def _sync_compositions_with_catalog(self) -> bool:
        """Ensure composition records match the current catalog inventory."""
        service = self.compositionService()
        previous_id = service.current_composition_id()
        changed = service.sync_catalog(
            self.catalog().imageIDs(),
            path_lookup=self.imagePath,
            size_lookup=lambda image_id: self._image_catalog.getImage(image_id).size(),
        )
        active = service.active_record()
        current_id = self.catalog().currentImageID()
        if active is None and current_id is not None:
            try:
                active = service.open_default_for_image(current_id)
            except KeyError:
                return changed
            self._open_composition_record(active)
            return True
        current_composition_id = service.current_composition_id()
        if current_composition_id != previous_id:
            if active is not None:
                self._open_composition_record(active)
            else:
                self._emit_composition_selection_changed(current_composition_id)
                self._emit_scene_changed()
        return changed

    def _activate_default_composition_for_image(self, image_id: uuid.UUID) -> None:
        """Open the generated default composition for a catalog image."""
        service = self.compositionService()
        previous_id = service.current_composition_id()
        record = service.open_default_for_image(image_id)
        if previous_id != record.composition_id:
            self._emit_composition_selection_changed(record.composition_id)
            self._handle_comparison_changed()
            self._emit_scene_changed()

    def _open_composition_record(
        self,
        record: CompositionRecord,
        *,
        fit_view: bool = True,
    ) -> None:
        """Open one composition document and synchronize legacy navigation state."""
        self._cancel_floating_pixels_for_context_change()
        image_id = record.navigation_image_id
        if image_id is not None and self.catalog().currentImageID() != image_id:
            self.interaction.suspend_overlays_for_navigation()
            self.catalog().setCurrentImageID(image_id)
        self._is_blank = False
        self.view().invalidate_content_cache()
        self._emit_composition_selection_changed(record.composition_id)
        self._handle_comparison_changed()
        if record.policy.removable:
            self._sync_view_to_scene_bounds(fit_view=fit_view)
        self._emit_scene_changed()

    def _refresh_active_scene_content(self, *, fit_view: bool) -> None:
        """Refresh rendering after the active scene payload changes in place."""
        self.view().invalidate_content_cache()
        self._sync_view_to_scene_bounds(fit_view=fit_view)
        self._emit_scene_changed()

    def _default_mask_paint_target_available(self) -> bool:
        """Return whether legacy catalog painting can provision its default mask."""
        return self._masks is not None and self.catalog().currentImageID() is not None

    def _emit_composition_changed(self) -> None:
        """Emit the latest composition snapshot."""
        self.compositionChanged.emit(self.getCompositionSnapshot())

    def _emit_composition_selection_changed(
        self, composition_id: uuid.UUID | None
    ) -> None:
        """Emit composition selection changes for host browsers."""
        self.compositionSelectionChanged.emit(composition_id)

    def _emit_scene_changed(self) -> None:
        """Emit the current normalized scene snapshot."""
        if self._editor_movement_interaction is not None:
            self._editor_movement_interaction.synchronize_context()
        resolved_scene = self.sceneMutationCoordinator().active_scene()
        if self._scene_movement is not None:
            self._scene_movement.synchronize_scene(resolved_scene)
        self._scene_selection.validate(resolved_scene)
        if self._vector_editor is not None:
            self._vector_editor.synchronize_selection()
        scene_id = self._active_resolved_scene_id()
        state = (
            None
            if scene_id is None
            else self.editorInteraction().pixel_selection_state(scene_id)
        )
        self._editor_overlays.set_selection(state)
        self.sceneChanged.emit(self._current_scene_snapshot(resolved_scene))
        if self._scene_mutations is not None:
            self.sceneEditHistoryChanged.emit(
                self.sceneEditUndoAvailable(),
                self.sceneEditRedoAvailable(),
            )

    def _handle_raster_structure_changed(self) -> None:
        """Refresh scene geometry and public state after a raster source change."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_scene_source_changed(self) -> None:
        """Refresh render inputs after pixels change without scene geometry changes."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()

    def _handle_placed_asset_changed(self, _scope_id: uuid.UUID) -> None:
        """Refresh source products and public state after a placed-asset change."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_placed_asset_completion(
        self, completion: PlacedAssetCompletion
    ) -> None:
        """Publish one typed internal placed completion through the facade signal."""
        public_scene = self.currentScene()
        public_scene_id = (
            completion.scope_id
            if public_scene is None
            or completion.scope_id != public_scene.composition_id
            else public_scene.scene_id
        )
        self.placedAssetRequestCompleted.emit(
            completion.request_id,
            public_scene_id,
            completion.layer_id,
            completion.succeeded,
            completion.message,
        )

    def _handle_vector_conversion_completion(
        self,
        completion: VectorConversionCompletion,
    ) -> None:
        """Publish one terminal vector conversion through the public signal."""
        self.vectorRequestCompleted.emit(
            completion.request_id,
            completion.scene_id,
            completion.layer_id,
            VectorConversionKind(completion.kind).value,
            completion.succeeded,
            completion.message,
        )

    def _handle_raster_bounds_completion(
        self,
        completion: RasterBoundsCompletion,
    ) -> None:
        """Map one internal completion to the public active-scene identifier."""
        public_scene_id = self._raster_request_public_scenes.pop(
            completion.request_id,
            completion.scene_id,
        )
        self.rasterBoundsRequestCompleted.emit(
            completion.request_id,
            public_scene_id,
            completion.layer_id,
            completion.succeeded,
            completion.message,
        )

    def _current_scene_snapshot(
        self,
        resolved: SceneDescriptor | None = None,
    ) -> SceneSnapshot | None:
        """Return a public scene snapshot for the active composition."""
        service = self.compositionService()
        record = service.active_record()
        if record is None:
            return None
        resolved = resolved or self.view().current_scene_descriptor()
        if resolved is None:
            return None
        return SceneSnapshot(
            composition_id=record.composition_id,
            scene_id=record.composition_id,
            title=record.title,
            bounds=QRectF(
                resolved.bounds.x,
                resolved.bounds.y,
                resolved.bounds.width,
                resolved.bounds.height,
            ),
            layers=tuple(
                self._public_resolved_layer(
                    layer,
                    service.layers.layer(record.composition_id, layer.layer_id),
                )
                for layer in resolved.layers
            ),
        )

    @staticmethod
    def _public_resolved_layer(
        layer: LayerDescriptor,
        instance: CompositionLayerInstance | None = None,
    ) -> LayerSnapshot:
        """Convert one resolved source descriptor into a public layer snapshot."""
        source = layer.source
        if isinstance(source, CatalogImageReference):
            image_id = source.image_id
        else:
            image_id = None
        durable_transform = layer.transform if instance is None else instance.transform
        placement = (
            layer.placement
            if instance is None or layer.raster_bounds is None
            else durable_transform.map_bounds(layer.raster_bounds)
        )
        return LayerSnapshot(
            layer_id=layer.layer_id,
            image_id=image_id,
            placement=QRectF(
                placement.x,
                placement.y,
                placement.width,
                placement.height,
            ),
            visible=layer.visible,
            opacity=layer.opacity,
            tint=(
                None
                if instance is None or instance.tint is None
                else QColor(instance.tint)
            ),
            clip=(
                None
                if instance is None or instance.clip is None
                else CompositionLayerClip(
                    coordinate_space=instance.clip.coordinate_space.value,
                    rect=QRectF(
                        instance.clip.x,
                        instance.clip.y,
                        instance.clip.width,
                        instance.clip.height,
                    ),
                )
            ),
            hit_test=layer.hit_test.enabled,
            role=layer.hit_test.role,
            metadata={} if instance is None else instance.metadata,
            interaction=public_layer_policy(layer.interaction),
            source_kind=source.kind,
            source_id=source.resource_id,
            label=layer.label,
            transform=(
                QTransform()
                if durable_transform is None
                else durable_transform.to_qtransform()
            ),
        )

    def _handle_internal_scene_content_changed(
        self, dirty_rect: QRect | QRectF | None = None
    ) -> None:
        """Refresh rendering after private scene content changes."""
        try:
            self.view().mark_dirty(dirty_rect)
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        self.update()

    def _handle_pixel_selection_changed(self, state: PixelSelectionState) -> None:
        """Refresh active selection presentation and edit availability."""
        if state.scene_id != self._active_resolved_scene_id():
            return
        self._editor_overlays.set_selection(state)
        self.pixelSelectionChanged.emit(self._public_pixel_selection_state(state))

    def _handle_composition_edit_history_changed(
        self,
        scope_id: uuid.UUID,
    ) -> None:
        """Publish undo and redo availability for the active edit scope."""
        if scope_id != self._active_resolved_scene_id():
            return
        self.sceneEditHistoryChanged.emit(
            self.sceneEditUndoAvailable(),
            self.sceneEditRedoAvailable(),
        )

    def _handle_composition_layers_changed(
        self,
        _composition_id: uuid.UUID,
    ) -> None:
        """Publish the detached browser snapshot after a stored stack mutation."""
        self._emit_composition_changed()

    def _handle_selected_layer_changed(
        self,
        selection: SceneLayerSelection | None,
    ) -> None:
        """Publish selected-layer identity and refresh direct-edit feedback."""
        painting = self.paintingCoordinator()
        active_target = painting.identity
        if selection is None:
            if (
                active_target is not None
                and active_target.kind is PaintTargetKind.LAYER
            ):
                painting.clear()
        elif not (
            active_target is not None
            and active_target.kind is PaintTargetKind.LAYER
            and active_target.scene_id == selection.scene_id
            and active_target.layer_id == selection.layer_id
        ):
            selected = painting.select_layer(selection.scene_id, selection.layer_id)
            if (
                not selected
                and active_target is not None
                and active_target.kind is PaintTargetKind.LAYER
            ):
                painting.clear()
        self.selectedLayerChanged.emit(self.selectedLayer())
        self.update()

    def _handle_paint_target_changed(
        self,
        _target: PaintTargetIdentity | None,
    ) -> None:
        """Refresh brush feedback after the source-local paint target changes."""
        self.refreshCursor()
        self.paintTargetChanged.emit(self.paintTargetState())
        self.update()

    def _handle_vector_selection_changed(self) -> None:
        """Publish vector-object selection without disturbing raster selection."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.selection_state()
        )
        self.vectorSelectionChanged.emit(state)
        self.update()

    def _handle_vector_node_selection_changed(self) -> None:
        """Publish vector control-point selection without changing object selection."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.node_selection_state()
        )
        self.vectorNodeSelectionChanged.emit(state)
        self.update()

    def _handle_vector_text_edit_changed(self) -> None:
        """Publish the detached active semantic text session."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.text_edit_state()
        )
        self.vectorTextEditChanged.emit(state)
        self.update()

    def _handle_vector_options_changed(self) -> None:
        """Publish the contextual vector creation options."""
        interaction = self._vector_interaction
        if interaction is None:
            return
        self.vectorToolOptionsChanged.emit(interaction.shape, interaction.style)
        self.refreshCursor()

    def _publish_vector_content_change(self) -> None:
        """Refresh public scene presentation after vector document mutation."""
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _synchronize_active_mask_layer_selection(self) -> None:
        """Make the actively edited mask the generic selected scene layer."""
        active_mask_id = self.activeMaskID()
        scene = self.view().current_scene_descriptor()
        current = self._scene_selection.current
        if scene is None:
            return
        active_layer = next(
            (
                layer
                for layer in scene.layers
                if isinstance(layer.source, MaskAssetReference)
                and layer.source.mask_id == active_mask_id
            ),
            None,
        )
        if active_layer is not None:
            self.paintingCoordinator().select_layer(
                scene.scene_id,
                active_layer.layer_id,
                require_policy=False,
            )
            if active_layer.interaction.selectable:
                self._scene_selection.select(scene.scene_id, active_layer.layer_id)
            return
        if active_mask_id is not None or current is None:
            return
        selected_layer = next(
            (layer for layer in scene.layers if layer.layer_id == current.layer_id),
            None,
        )
        if selected_layer is not None and isinstance(
            selected_layer.source,
            MaskAssetReference,
        ):
            self._scene_selection.clear()

    def _public_pixel_selection_state(
        self,
        state: PixelSelectionState,
    ) -> PixelSelectionSnapshot:
        """Convert internal selection coverage to a detached public snapshot."""
        coverage = state.coverage
        current_scene = self.currentScene()
        public_scene_id = (
            state.scene_id if current_scene is None else current_scene.scene_id
        )
        return PixelSelectionSnapshot(
            scene_id=public_scene_id,
            revision=state.revision,
            bounds=None if coverage is None else coverage.bounds.to_qrect(),
            coverage=(
                None
                if coverage is None
                else numpy_to_qimage_grayscale8(coverage.pixels)
            ),
        )

    def _sync_view_to_scene_bounds(self, *, fit_view: bool) -> None:
        """Refresh viewport geometry after private scene layout changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        view.viewport.setContentSize(snapshot.base_image_size)
        if fit_view:
            view.viewport.setZoomFit()
        self.setMinimumSize(self.minimumSizeHint())
        view.allocate_buffers()
        view.mark_dirty()
        view.ensure_view_alignment(force=True)
        self.update()

    def _sync_viewport_content_geometry(self) -> None:
        """Refresh viewport content size after renderable scene geometry changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        viewport = view.viewport
        viewport.setContentSize(snapshot.base_image_size)
        if viewport.get_zoom_mode() == ViewportZoomMode.FIT:
            viewport.setZoomFit()
        else:
            viewport.setPan(viewport.pan)
        self.setMinimumSize(self.minimumSizeHint())

    def _emit_catalog_mutation(
        self, reason: str, *, affected_ids: Iterable[uuid.UUID] | None = None
    ) -> None:
        """Emit a catalog mutation event through the CuteCanvas surface."""
        current_id: uuid.UUID | None
        try:
            current_id = self.catalog().currentImageID()
        except RuntimeError:
            current_id = None
        event = CatalogMutationEvent(
            reason=reason,
            affected_ids=tuple(affected_ids or ()),
            current_id=current_id,
        )
        self._handle_catalog_mutation(event)

    def _normalized_link_groups(
        self,
    ) -> tuple[tuple[uuid.UUID, tuple[uuid.UUID, ...]], ...]:
        """Return normalized link-group definitions for change detection."""
        normalized: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = []
        for group in self.linkedGroups():
            normalized.append((group.group_id, tuple(sorted(group.members))))
        normalized.sort(key=lambda item: item[0].hex)
        return tuple(normalized)

    def _maybe_emit_link_groups_changed(self) -> None:
        """Emit link-group changes when the current definition differs."""
        groups = self._normalized_link_groups()
        if groups == self._last_link_groups:
            return
        self._last_link_groups = groups
        self.linkGroupsChanged.emit()

    def _emit_catalog_selection_changed(self, image_id: uuid.UUID | None) -> None:
        """Emit catalog selection changes for the active image."""
        self.catalogSelectionChanged.emit(image_id)

    def _handle_current_image_changed_signal(self, image_id: uuid.UUID) -> None:
        """Emit selection updates when the active image changes."""
        self._emit_catalog_selection_changed(image_id)

    def _handle_diagnostics_overlay_toggled(self, enabled: bool) -> None:
        """Emit overlay toggle changes while avoiding duplicate signals."""
        self.diagnosticsOverlayToggled.emit(enabled)

    def _handle_diagnostics_detail_toggled(self, domain: str, enabled: bool) -> None:
        """Emit diagnostics domain detail toggle changes."""
        self.diagnosticsDomainToggled.emit(domain, enabled)
