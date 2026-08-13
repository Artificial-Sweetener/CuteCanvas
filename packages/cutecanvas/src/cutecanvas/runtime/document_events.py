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
from contextlib import nullcontext

from PySide6.QtCore import (
    QRect,
    QRectF,
)
from PySide6.QtGui import QColor

from cutecanvas.composition import CompositionRecord
from cutecanvas.composition.layers import CompositionLayerInstance
from cutecanvas.composition.public_layer_mapping import detached_public_layer_mapping
from cutecanvas.composition.public_policy import (
    public_layer_policy,
)
from cutecanvas.masks.mask_undo import MaskHistoryChange
from cutecanvas.masks.resource_changes import MaskResourceChange
from cutecanvas.painting import PaintTargetIdentity
from cutecanvas.placed.workflow import PlacedAssetCompletion
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.resources.rasterization import LayerRasterizationCompletion
from cutecanvas.scene.layer_selection import (
    SceneLayerSelection,
)
from cutecanvas.scene.pixel_edits import LayerPixelContentChange
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
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
)
from qpane.sdk.rendering import ViewportZoomMode
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from .scene_interaction_sync import synchronize_scene_interactions
from .viewport_activation import resolve_viewport_activation


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

    def _open_composition_record(
        self,
        record: CompositionRecord,
        *,
        fit_view: bool = True,
        force_context_refresh: bool = False,
    ) -> None:
        """Activate a composition, refreshing only a reconciled successor."""
        session = self.viewSession()
        inspection_available = (
            session.inspection.state_for(record.composition_id) is not None
        )
        activation = resolve_viewport_activation(
            fit_requested=fit_view,
            inspection_available=inspection_available,
        )
        binding = self._inspection_binding
        publication_guard = (
            nullcontext() if binding is None else binding.suspend_publication()
        )
        with publication_guard:
            viewport_changed = session.set_viewport_spec(
                None,
                composition_id=record.composition_id,
            )
            activation_changed = session.activate(
                record.composition_id,
                available_ids=self.compositionService().composition_ids(),
            )
            if (
                not activation_changed
                and not viewport_changed
                and not force_context_refresh
            ):
                return
            self._cancel_floating_pixels_for_context_change()
            self._is_blank = False
            self.view().invalidate_content_cache()
            self._emit_composition_selection_changed(record.composition_id)
            self._sync_view_to_scene_bounds(
                fit_view=activation.fit_view,
                restore_inspection=activation.restore_inspection,
            )
        if binding is not None and not activation.restore_inspection:
            binding.publish()
        self._masks_controller.sync_mask_activation_for_composition(
            record.composition_id
        )
        self._emit_scene_changed()

    def _refresh_active_scene_content(self, *, fit_view: bool) -> None:
        """Refresh rendering after the active scene payload changes in place."""
        self.view().invalidate_content_cache()
        self._sync_view_to_scene_bounds(fit_view=fit_view)
        self._emit_scene_changed()

    def _default_mask_paint_target_available(self) -> bool:
        """Return whether the current document can provision a mask target."""
        return self._masks is not None and self.currentCompositionID() is not None

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
        resolved_scene = self.sceneMutationCoordinator().active_scene()
        synchronize_scene_interactions(
            resolved_scene,
            movement_interaction=self._editor_movement_interaction,
            snapping=self._snapping,
            movement=self._scene_movement,
            transform=self._scene_transform,
            affine=self._scene_transform_interaction,
        )
        self._scene_selection.validate(resolved_scene)
        self._reconcile_selected_paint_target()
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

    def _reconcile_selected_paint_target(self) -> None:
        """Resolve a newly paint-capable source without requiring reselection."""
        selection = self._scene_selection.current
        painting = self.paintingCoordinator()
        if selection is None or painting.identity is not None:
            return
        painting.select_layer(selection.scene_id, selection.layer_id)

    def _handle_raster_structure_changed(self) -> None:
        """Refresh scene geometry and public state after a raster source change."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_scene_source_changed(self) -> None:
        """Refresh render inputs after pixels change without scene geometry changes."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()

    def _handle_resource_content_changed(
        self,
        resource_id: uuid.UUID,
        dirty_region: object | None = None,
    ) -> None:
        """Refresh source products and public state after a resource change."""
        if isinstance(dirty_region, LayerPixelContentChange):
            self._handle_layer_pixels_changed(dirty_region)
        if isinstance(dirty_region, MaskResourceChange):
            service = self.mask_service
            if (
                service is not None
                and dirty_region.origin is service.controller.presentation_identity
            ):
                return
            dirty_region = dirty_region.detail
        if isinstance(dirty_region, MaskHistoryChange):
            service = self.mask_service
            if service is not None:
                structure_changed = service.controller.edits.present_history_change(
                    dirty_region
                )
                if not structure_changed:
                    self._emit_scene_changed()
                return
        if isinstance(dirty_region, RasterBounds):
            refreshed = self._masks_controller.refresh_mask_resource(
                resource_id,
                dirty_region,
            )
            if refreshed:
                self._emit_scene_changed()
                return
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_layer_pixels_changed(self, change: LayerPixelContentChange) -> None:
        """Publish one source-neutral durable layer-pixel mutation."""
        source = change.source
        if isinstance(source, ProjectResourceReference):
            self.layerPixelsChanged.emit(
                change.scene_id,
                change.layer_id,
                source.resource_id,
            )

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

    def _handle_layer_rasterization_completion(
        self,
        completion: LayerRasterizationCompletion,
    ) -> None:
        """Publish one source-neutral layer rasterization completion."""
        self.layerRasterizationCompleted.emit(
            completion.request_id,
            completion.scene_id,
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
        if completion.kind is VectorConversionKind.EDITABLE_RASTER:
            self._handle_layer_rasterization_completion(
                LayerRasterizationCompletion(
                    completion.request_id,
                    completion.scene_id,
                    completion.layer_id,
                    completion.succeeded,
                    completion.message,
                )
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
        composition_id = self.viewSession().active_composition_id
        if composition_id is None:
            return None
        try:
            record = service.record(composition_id)
        except KeyError:
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

    def _public_resolved_layer(
        self,
        layer: LayerDescriptor,
        instance: CompositionLayerInstance | None = None,
    ) -> LayerSnapshot:
        """Convert one resolved source descriptor into a public layer snapshot."""
        source = layer.source
        durable_transform = layer.transform if instance is None else instance.transform
        placement = (
            layer.placement
            if instance is None or layer.raster_bounds is None
            else durable_transform.map_bounds(layer.raster_bounds)
        )
        return LayerSnapshot(
            layer_id=layer.layer_id,
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
            source_kind=self.compositionService().source_kind(source),
            source_id=source.resource_id,
            label=layer.label,
            transform=detached_public_layer_mapping(durable_transform),
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
        self._publish_editor_transform_state()
        self.refreshCursor()

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
        selections: tuple[SceneLayerSelection, ...],
    ) -> None:
        """Publish layer selection and refresh active direct-edit feedback."""
        selection = selections[-1] if selections else None
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
        self.selectedLayersChanged.emit(self.selectedLayers())
        self._publish_editor_transform_state()
        self.refreshCursor()
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
        self._handle_scene_source_changed()
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
                if isinstance(layer.source, ProjectResourceReference)
                and layer.source.resource_id == active_mask_id
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
        service = self.mask_service
        if (
            selected_layer is not None
            and service is not None
            and isinstance(selected_layer.source, ProjectResourceReference)
            and service.assets.get_layer(selected_layer.source.resource_id) is not None
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

    def _sync_view_to_scene_bounds(
        self,
        *,
        fit_view: bool,
        restore_inspection: bool | None = None,
    ) -> None:
        """Refresh viewport geometry after private scene layout changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        binding = self._inspection_binding
        restore = not fit_view if restore_inspection is None else restore_inspection
        publication_guard = (
            nullcontext() if binding is None else binding.suspend_publication()
        )
        with publication_guard:
            viewport = view.viewport
            content_size_changed = viewport.content_size != snapshot.base_image_size
            viewport.setContentSize(snapshot.base_image_size)
            if fit_view:
                viewport.setZoomFit()
            self.setMinimumSize(self.minimumSizeHint())
            view.mark_dirty()
            if content_size_changed:
                view.allocate_buffers()
                view.ensure_view_alignment(force=True)
            if binding is not None:
                binding.refresh_target(restore=restore)
        if binding is not None and not restore:
            binding.publish()
        self.update()

    def _sync_viewport_content_geometry(self) -> None:
        """Refresh viewport content size after renderable scene geometry changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        binding = self._inspection_binding
        publication_guard = (
            nullcontext() if binding is None else binding.suspend_publication()
        )
        with publication_guard:
            viewport = view.viewport
            viewport.setContentSize(snapshot.base_image_size)
            if viewport.get_zoom_mode() == ViewportZoomMode.FIT:
                viewport.setZoomFit()
            else:
                viewport.setPan(viewport.pan)
            self.setMinimumSize(self.minimumSizeHint())
            if binding is not None:
                binding.refresh_target()

    def _handle_diagnostics_overlay_toggled(self, enabled: bool) -> None:
        """Emit overlay toggle changes while avoiding duplicate signals."""
        self.diagnosticsOverlayToggled.emit(enabled)

    def _handle_diagnostics_detail_toggled(self, domain: str, enabled: bool) -> None:
        """Emit diagnostics domain detail toggle changes."""
        self.diagnosticsDomainToggled.emit(domain, enabled)
