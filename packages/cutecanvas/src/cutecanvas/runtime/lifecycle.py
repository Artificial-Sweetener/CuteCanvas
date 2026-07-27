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
"""CanvasLifecycle behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QTimer,
)
from PySide6.QtGui import (
    QImage,
)
from PySide6.QtWidgets import QWidget
from qpane.sdk.cache import CacheRegistry
from qpane.sdk.diagnostics import DiagnosticsSnapshot
from qpane.sdk.rendering import ViewportZoomMode

from cutecanvas import ui
from cutecanvas.core import (
    FeatureFailure,
    FeatureFallbacks,
)
from cutecanvas.document import DocumentChange, DocumentChangeKind
from cutecanvas.editor.composition_root import (
    EditorCompositionRoot,
    EditorRootCallbacks,
    EditorRootInputs,
)
from cutecanvas.masks.descriptor_factory import MaskLayerDescriptorFactory
from cutecanvas.masks.floating_layers import MaskFloatingLayerOwner
from cutecanvas.masks.paint_target import MaskCoveragePaintTargetOwner
from cutecanvas.masks.pixel_edits import (
    MaskLayerPixelMutationOwner,
    MaskPixelRenderSynchronizer,
)
from cutecanvas.masks.source_resolver import MaskSourceCapabilities
from cutecanvas.masks.workflow import MaskActivationSyncResult
from cutecanvas.persistence import CompositionPersistenceService
from cutecanvas.resources import ProjectResourceKind
from cutecanvas.resources.layer_operations import ResourceForkOwner
from cutecanvas.types import DiagnosticsDomain
from cutecanvas.vector.facade import VectorHostFacade

if TYPE_CHECKING:
    from qpane.sdk.rendering import Renderer

    from cutecanvas.masks.autosave import AutosaveManager
    from cutecanvas.masks.mask import MaskLayer
    from cutecanvas.masks.mask_service import MaskService
    from cutecanvas.sam.manager import SamManager


class CanvasLifecycleMixin:
    """Group canvaslifecycle facade behavior."""

    def _init_core_components(self) -> None:
        """Build and install the always-on viewer and editor collaboration graph."""
        self._state.cache_coordinator = self._state.build_cache_coordinator()
        self._state.cache_registry = CacheRegistry(self._state.cache_coordinator)
        self._document_unsubscribe = self.document().events.subscribe(
            self._handle_document_change
        )
        components = EditorCompositionRoot().build(
            EditorRootInputs(
                qpane=self,
                document=self.document(),
                state=self._state,
                settings=self.settings,
                execution_scope=self._execution_binding.scope,
                document_execution_scope=(
                    self._execution_binding.document_runtime.execution_scope
                ),
                latest_requests=(
                    self._execution_binding.document_runtime._latest_request_registry
                ),
                cache_registry=self._state.cache_registry,
                diagnostics=self._diagnostics_manager,
                layer_selection=self._scene_selection,
                transform_preview=self._scene_transform_preview,
                selection_projections=self._selection_layer_projections,
                floating_promotions=self._floating_layer_promotions,
                editor_policy=self._editor_policy,
                callbacks=EditorRootCallbacks(
                    composition_history_changed=(
                        self._handle_composition_edit_history_changed
                    ),
                    composition_layers_changed=(
                        self._handle_composition_layers_changed
                    ),
                    pixel_selection_changed=self._handle_pixel_selection_changed,
                    transform_changed=self._publish_scene_layer_change,
                    transform_preview_changed=self._refresh_scene_transform_preview,
                    raster_structure_changed=self._handle_raster_structure_changed,
                    raster_bounds_completed=self._handle_raster_bounds_completion,
                    scene_content_changed=lambda _bounds: (
                        self._handle_internal_scene_content_changed()
                    ),
                    resource_content_changed=self._handle_resource_content_changed,
                    pixel_move_preview_changed=(
                        self._refresh_selected_pixel_move_preview
                    ),
                    active_mask_id=lambda: (
                        None if self._masks is None else self._masks.active_mask_id()
                    ),
                    placed_asset_completed=self._handle_placed_asset_completion,
                    layer_rasterization_completed=(
                        self._handle_layer_rasterization_completion
                    ),
                    current_composition_id=(
                        lambda: self.viewSession().active_composition_id
                    ),
                    current_edit_scope_id=self._active_resolved_scene_id,
                    paint_target_changed=self._handle_paint_target_changed,
                    clone_stamp_changed=self.cloneStampChanged.emit,
                    default_paint_target_available=(
                        self._default_mask_paint_target_available
                    ),
                    vector_selection_changed=self._handle_vector_selection_changed,
                    vector_node_selection_changed=(
                        self._handle_vector_node_selection_changed
                    ),
                    vector_text_edit_changed=self._handle_vector_text_edit_changed,
                    vector_content_changed=self._publish_vector_content_change,
                    vector_options_changed=self._handle_vector_options_changed,
                    vector_conversion_completed=(
                        self._handle_vector_conversion_completion
                    ),
                ),
            )
        )
        self._scene_provider_registry = components.scene_providers
        self._source_capabilities = components.render_source_capabilities
        self._editor_source_capabilities = components.editor_source_capabilities
        self._project_resources = components.project_resources
        self._project_resource_descriptors = components.project_resource_descriptors
        self._project_resource_capabilities = components.project_resource_capabilities
        self._project_resource_lifecycle = components.project_resource_lifecycle
        self._composition_service = components.compositions
        self._editable_raster_assets = components.editable_raster_assets
        self._editable_raster_layers = components.editable_raster_layers
        self._placed_assets = components.placed_assets
        self._image_documents = components.image_documents
        self._active_raster = components.active_raster
        self._layer_resource_operations = components.layer_resource_operations
        self._placed_asset_workflow = components.placed_asset_workflow
        self._placed_asset_rasterization = components.placed_asset_rasterization
        self._composition_rasterization = components.composition_rasterization
        self._resource_rasterization = components.resource_rasterization
        self.destroyed.connect(
            lambda _obj=None, workflow=components.placed_asset_workflow: (
                workflow.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None, service=components.placed_asset_rasterization: (
                service.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None, service=components.composition_rasterization: (
                service.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None, service=components.vector.conversions: (
                service.shutdown()
            )
        )
        self._pixel_selection = components.pixel_selection
        self._layer_geometry = components.layer_geometry
        self._scene_rasterizer = components.scene_rasterizer
        self._painting = components.painting
        self._clone_stamp = components.clone_stamp
        self._paint_bucket = components.paint_bucket
        self._selection_fill = components.selection_fill
        self._snap_configuration = components.snap_configuration
        self._coverage_shape_configuration = components.coverage_shape_configuration
        self.destroyed.connect(
            lambda _obj=None, coordinator=components.paint_bucket: (
                coordinator.shutdown()
            )
        )
        self._vector_editor = VectorHostFacade(
            compositions=components.compositions,
            assets=components.vector.assets,
            layers=components.vector.layers,
            edits=components.vector.edits,
            selection=components.vector.selection,
            current_scene=components.view.current_scene_descriptor,
            current_public_scene_id=self._active_public_scene_id,
            current_composition_id=lambda: self.viewSession().active_composition_id,
            changed=self._publish_vector_content_change,
            conversions=components.vector.conversions,
            masks=components.vector.masks,
            targets=components.vector.targets,
            layer_selection=self._scene_selection,
            nodes=components.vector.nodes,
            texts=components.vector.texts,
        )
        self._vector_interaction = components.vector.interaction
        self._vector_nodes = components.vector.nodes
        self._vector_text = components.vector.texts
        self._persistence_service = CompositionPersistenceService(
            compositions=components.compositions,
            masks=lambda: (
                None if self.mask_service is None else self.mask_service.assets
            ),
            rasters=components.editable_raster_assets,
            placed_assets=components.placed_assets,
            vectors=components.vector.assets,
        )
        self._composition_layer_assembler = components.layer_assembler
        self._view = components.view
        self._scene_mutations = components.scene_mutations
        self._scene_movement = components.scene_movement
        self._scene_movement_interaction = components.scene_movement_interaction
        self._scene_transform_interaction = components.scene_transform_interaction
        self._raster_mutations = components.raster_mutations
        self._layer_pixel_owners = components.pixel_owners
        self._layer_pixel_mutations = components.pixel_mutations
        self._editor_interaction = components.editor_interaction
        self._raster_floating_layer_owner = components.raster_floating_owner
        self._selected_pixel_movement = components.selected_pixel_movement
        self.destroyed.connect(
            lambda _obj=None, movement=components.selected_pixel_movement: (
                movement.shutdown()
            )
        )
        self._editor_movement_interaction = components.editor_movement_interaction
        self._operation_resolver = components.operation_resolver
        self._paint_destination = components.paint_destination
        self._active_mask_coordinates = components.active_mask_coordinates
        self._composition_scene_adapter = components.composition_scene_adapter
        self._tools = components.tools
        tool_signals = components.tools.signals
        tool_signals.stroke_applied.connect(components.painting.apply)
        tool_signals.stroke_completed.connect(components.painting.commit)
        tool_signals.stroke_cancelled.connect(components.painting.cancel)
        tool_signals.undo_state_push_requested.connect(components.painting.begin)
        tool_signals.brush_size_changed.connect(self.setBrushSize)
        self.cursor_builder = components.cursor_builder
        self.mask_service = None
        self.mask_controller = None
        self._sam_manager = None
        self._autosave_manager = None
        self.destroyed.connect(lambda _obj=None: self._document_unsubscribe())

    def _handle_document_change(self, change: DocumentChange) -> None:
        """Refresh this mounted view after one shared durable document change."""
        if change.kind is DocumentChangeKind.HISTORY:
            if change.composition_id is not None:
                self._handle_composition_edit_history_changed(change.composition_id)
            return
        if change.kind is DocumentChangeKind.LAYERS:
            if change.composition_id is not None:
                self._handle_composition_layers_changed(change.composition_id)
                if change.composition_id == self.viewSession().active_composition_id:
                    self._refresh_active_scene_content(fit_view=False)
            return
        if change.kind is DocumentChangeKind.SELECTION:
            if change.payload is not None:
                self._handle_pixel_selection_changed(change.payload)
            return
        if (
            change.kind is DocumentChangeKind.RESOURCE
            and change.resource_id is not None
        ):
            self._handle_resource_content_changed(
                change.resource_id,
                change.payload,
            )

    def _wire_facade_signals(self) -> None:
        """Connect facade-level diagnostics signals."""
        controller = self.diagnosticsOverlayController()
        controller.setOverlayChangedCallback(self._handle_diagnostics_overlay_toggled)
        controller.setDetailChangedCallback(self._handle_diagnostics_detail_toggled)

    def _schedule_initial_view_signals(self) -> None:
        """Ensure the first zoom/viewport signals emit once Qt shows the widget."""
        if self._initial_view_signals_scheduled:
            return
        self._initial_view_signals_scheduled = True
        QTimer.singleShot(0, self, self._emit_initial_view_signals)

    def _emit_initial_view_signals(self) -> None:
        """Emit initial zoom and viewport snapshots after the widget initializes."""
        self._initial_view_signals_scheduled = False
        self._emit_zoom_snapshot()
        self._emit_viewport_rect_if_changed(force=True)

    def featureFallbacks(self) -> FeatureFallbacks:
        """Expose the fallback tracker used to log optional feature availability."""
        return self._state.fallbacks

    def failedFeatures(self) -> Mapping[str, FeatureFailure]:
        """Return recorded feature installation failures keyed by feature name."""
        return self._state.failed_features

    def gatherDiagnostics(self) -> DiagnosticsSnapshot:
        """Collect a diagnostic snapshot for this CuteCanvas instance."""
        return self.diagnostics().gather()

    def createStatusOverlay(self, *, parent: QWidget | None = None):
        """Create a status overlay widget bound to this CuteCanvas."""
        return ui.create_status_overlay(self, parent=parent)

    def applyCacheSettings(self) -> None:
        """Propagate cache configuration to view-managed controllers."""
        self._state.apply_cache_settings()

    def _apply_diagnostics_overlay_preferences(self) -> None:
        """Synchronize overlay visibility and detail toggles with settings.

        Raises:
            ValueError: When configured diagnostics domains are not available.
        """
        controller = self.diagnosticsOverlayController()
        settings = self.settings
        enabled_domains = tuple(
            getattr(settings, "diagnostics_domains_enabled", ()) or ()
        )
        available_domains = set(controller.domains())
        unknown = tuple(
            domain for domain in enabled_domains if domain not in available_domains
        )
        if unknown:
            raise ValueError(
                f"Diagnostics domains not available for this qpane: {', '.join(unknown)}"
            )
        for domain in available_domains:
            controller.setDomainEnabled(domain, domain in enabled_domains)
        overlay_enabled = bool(getattr(settings, "diagnostics_overlay_enabled", False))
        controller.setOverlayEnabled(overlay_enabled)

    def _normalize_diagnostics_domain(self, domain: str | DiagnosticsDomain) -> str:
        """Return a canonical diagnostics domain or raise when unavailable."""
        controller = self.diagnosticsOverlayController()
        available = set(controller.domains())
        candidate = (
            domain.value if isinstance(domain, DiagnosticsDomain) else str(domain)
        )
        canonical = candidate.strip().lower()
        if canonical not in available:
            raise ValueError(
                f"Diagnostics domain '{candidate}' is not available for this qpane"
            )
        return canonical

    def attachAutosaveManager(self, manager: AutosaveManager) -> None:
        """Install the autosave manager used by optional features.

        Replaces any existing manager; masking hooks detach it automatically when autosave is disabled.
        """
        self.hooks.attachAutosaveManager(manager)

    def detachAutosaveManager(self) -> None:
        """Remove the currently attached autosave manager, if any.

        Missing managers are ignored so callers can always invoke this during teardown.
        """
        self.hooks.detachAutosaveManager()

    def autosaveManager(self) -> AutosaveManager | None:
        """Return the currently attached autosave manager, if any."""
        return self._autosave_manager

    def _set_autosave_manager(self, manager: AutosaveManager | None) -> None:
        """Internal helper used by hooks to manage autosave state."""
        self._autosave_manager = manager

    def attachMaskService(self, service: MaskService) -> None:
        """Attach the mask service facade and refresh autosave hooks.

        Side effects:
            Registers coverage rendering, editing, and resource capabilities.
        """
        self._masks_controller.attachMaskService(service)
        service.bindCompositionEdits(self.compositionService().edit_controller)
        self.destroyed.connect(lambda _obj=None, attached=service: attached.shutdown())
        service.setStrokeConstraintProvider(
            self.editorInteraction().mask_stroke_constraint
        )
        factory = MaskLayerDescriptorFactory(
            assets=service.assets,
            renders=service.controller.renders,
        )
        descriptors = self._project_resource_descriptors
        if descriptors is None:
            raise RuntimeError("project resource descriptor registry is unavailable")
        descriptors.register(ProjectResourceKind.COVERAGE, factory)
        self._mask_descriptor_factory = factory
        capabilities = MaskSourceCapabilities(
            assets=service.assets,
            renders=service.controller.renders,
        )
        resource_capabilities = self._project_resource_capabilities
        if resource_capabilities is None:
            raise RuntimeError("project resource capability registry is unavailable")
        resource_capabilities.register(ProjectResourceKind.COVERAGE, capabilities)
        self._mask_source_capabilities = capabilities
        from cutecanvas.masks.raster_mutations import MaskRasterMutationOwner

        raster_owner = MaskRasterMutationOwner(
            assets=service.assets,
            edits=service.controller.edits,
            renders=service.controller.renders,
            execution_scope=(self._execution_binding.document_runtime.execution_scope),
            latest_requests=(
                self._execution_binding.document_runtime._latest_request_registry
            ),
            mask_changed=service.controller.mask_updated.emit,
            undo_changed=service.controller.undo_stack_changed.emit,
            scene_changed=self._handle_raster_structure_changed,
            completed=self._handle_raster_bounds_completion,
        )
        if self._raster_mutations is not None:
            self._raster_mutations.register_owner(raster_owner)
        self._mask_raster_mutation_owner = raster_owner
        render_synchronizer = MaskPixelRenderSynchronizer(
            service.assets,
            service.invalidateMaskRenderRegion,
        )
        pixel_owner = MaskLayerPixelMutationOwner(
            service.assets,
            changed=render_synchronizer.refresh,
            structure_changed=self._handle_raster_structure_changed,
        )
        if self._layer_pixel_owners is not None:
            self._layer_pixel_owners.register(pixel_owner)
        self._mask_pixel_edit_owner = pixel_owner
        mask_floating_owner = MaskFloatingLayerOwner(
            assets=service.assets,
            layers=self.compositionService().layers,
            current_composition_id=lambda: self.viewSession().active_composition_id,
            changed=lambda _mask_id: self._handle_raster_structure_changed(),
        )
        self._floating_layer_promotions.register(mask_floating_owner)
        self._mask_floating_layer_owner = mask_floating_owner
        resource_lifecycle = self._project_resource_lifecycle
        if resource_lifecycle is None:
            raise RuntimeError("project resource lifecycle registry is unavailable")
        resource_lifecycle.register(
            ProjectResourceKind.COVERAGE,
            service.assets.delete_mask,
        )
        resource_operations = self._layer_resource_operations
        if resource_operations is None:
            raise RuntimeError("project resource operations are unavailable")
        fork_owner = ResourceForkOwner(
            fork=service.assets.fork,
            remove=service.assets.delete_mask,
        )
        resource_operations.register_fork_owner(
            ProjectResourceKind.COVERAGE,
            fork_owner,
        )
        self._mask_resource_fork_owner = fork_owner
        paint_owner = MaskCoveragePaintTargetOwner(service)
        self.paintingCoordinator().registry.register(paint_owner)
        self.paintingCoordinator().registry.register_idle_feedback(
            paint_owner,
            paint_owner.idle_preview_color,
        )
        self._mask_paint_target_owner = paint_owner

    def detachMaskService(self) -> None:
        """Detach the mask service and tear down autosave wiring.

        Side effects:
            Removes coverage rendering, editing, and resource capabilities.
        """
        service = self.mask_service
        if service is not None:
            service.setStrokeConstraintProvider(None)
        raster_owner = self._mask_raster_mutation_owner
        if raster_owner is not None and self._raster_mutations is not None:
            self._raster_mutations.unregister_owner(raster_owner)
        self._mask_raster_mutation_owner = None
        pixel_owner = self._mask_pixel_edit_owner
        if pixel_owner is not None and self._layer_pixel_owners is not None:
            self._layer_pixel_owners.unregister(pixel_owner)
        self._mask_pixel_edit_owner = None
        floating_owner = self._mask_floating_layer_owner
        if floating_owner is not None:
            self._floating_layer_promotions.unregister(floating_owner)
        self._mask_floating_layer_owner = None
        resource_lifecycle = self._project_resource_lifecycle
        if resource_lifecycle is not None and service is not None:
            resource_lifecycle.unregister(
                ProjectResourceKind.COVERAGE,
                service.assets.delete_mask,
            )
        fork_owner = self._mask_resource_fork_owner
        resource_operations = self._layer_resource_operations
        if fork_owner is not None and resource_operations is not None:
            resource_operations.unregister_fork_owner(
                ProjectResourceKind.COVERAGE,
                fork_owner,
            )
        self._mask_resource_fork_owner = None
        paint_owner = self._mask_paint_target_owner
        if paint_owner is not None:
            self.paintingCoordinator().registry.unregister(paint_owner)
        self._mask_paint_target_owner = None
        factory = self._mask_descriptor_factory
        descriptors = self._project_resource_descriptors
        if factory is not None and descriptors is not None:
            descriptors.unregister(ProjectResourceKind.COVERAGE, factory)
        self._mask_descriptor_factory = None
        capabilities = self._mask_source_capabilities
        if capabilities is not None:
            resource_capabilities = self._project_resource_capabilities
            if resource_capabilities is not None:
                resource_capabilities.unregister(
                    ProjectResourceKind.COVERAGE,
                    capabilities,
                )
            self._mask_source_capabilities = None
        self._masks_controller.detachMaskService()

    def attachSamManager(self, sam_manager: SamManager) -> None:
        """Attach a SamManager instance and wire its signals."""
        self._masks_controller.attachSamManager(sam_manager)

    def detachSamManager(self) -> None:
        """Detach the SAM manager and cancel outstanding predictor work."""
        self._masks_controller.detachSamManager()

    def samManager(self) -> SamManager | None:
        """Return the active SAM manager when installed."""
        return self._sam_manager

    def _set_sam_manager(self, manager: SamManager | None) -> None:
        """Internal helper for workflow/hooks to track SAM managers."""
        self._sam_manager = manager

    def updateMaskFromFile(self, mask_id: uuid.UUID, file_path: str) -> bool:
        """Replace a mask layer's pixels from ``file_path`` while preserving metadata.

        Args:
            mask_id: Identifier of the mask layer to update.
            file_path: Filesystem path to the replacement mask image.

        Returns:
            True when the layer was updated successfully.
        """
        return self._masks_controller.update_mask_from_file(mask_id, file_path)

    def invalidateActiveMaskCache(self):
        """Invalidate the colorized pixmap cache for the currently active mask.

        External tools that mutate mask images directly should call this to keep previews in sync.
        """
        return self._masks_controller.invalidate_active_mask_cache()

    def updateMaskRegion(
        self,
        dirty_image_rect: QRect,
        active_mask_layer: MaskLayer,
        *,
        sub_mask_image: QImage | None = None,
        force_async_colorize: bool = False,
    ) -> bool:
        """Forward mask-region updates to refresh cached mask renders.

        Args:
            dirty_image_rect: Image-space rectangle that was modified.
            active_mask_layer: Layer owning the updated pixels.
            sub_mask_image: Optional pre-updated snippet to reuse instead of copying from the layer.
            force_async_colorize: Queue high-resolution colorization even when previews are decimated.

        Returns:
            True when the region update is dispatched successfully.
        """
        return self._masks_controller.update_mask_region(
            dirty_image_rect,
            active_mask_layer,
            sub_mask_image=sub_mask_image,
            force_async_colorize=force_async_colorize,
        )

    def generateAndApplyMask(self, bbox: np.ndarray, erase_mode: bool = False):
        """Generate a mask from ``bbox`` and apply it through the mask workflow."""
        return self._masks_controller.generate_and_apply_mask(
            bbox, erase_mode=erase_mode
        )

    def _sync_mask_activation_for_composition(
        self, composition_id: uuid.UUID | None
    ) -> MaskActivationSyncResult:
        """Synchronize mask activation for a composition."""
        return self._masks_controller.sync_mask_activation_for_composition(
            composition_id
        )

    def isMaskActivationPending(self, composition_id: uuid.UUID | None = None) -> bool:
        """Return True while deferred mask activation remains outstanding."""
        return self._masks_controller.is_activation_pending(composition_id)

    def refreshMaskAutosavePolicy(self) -> None:
        """Re-evaluate mask autosave wiring after feature state changes."""
        self._masks_controller.refreshMaskAutosavePolicy()

    def resetActiveSamPredictor(self) -> None:
        """Clear any cached predictor so SAM requests start fresh."""
        self._masks_controller.resetActiveSamPredictor()

    def refreshCursor(self) -> None:
        """Refresh the QWidget cursor via the interaction delegate."""
        self.interaction.update_cursor()

    def updateBrushCursor(self, erase_indicator: bool = False) -> None:
        """Delegate brush cursor updates to the mask bridge via the interaction layer."""
        self.interaction.update_brush_cursor(erase_indicator=erase_indicator)

    def updateModifierKeyCursor(self) -> None:
        """Update modifier-sensitive cursors via the interaction delegate."""
        self.interaction.update_modifier_key_cursor()

    def setPanZoomLocked(self, locked: bool):
        """Delegate pan/zoom lock state to the viewport."""
        self.view().viewport.set_locked(bool(locked))

    def blank(self):
        """Blank the qpane without clearing caches."""
        self.interaction.blank()

    def getPan(self) -> QPointF:
        """Return the current pan offset."""
        return self.view().viewport.pan

    def setPan(self, pan: QPointF):
        """Delegate pan updates to the viewport."""
        self.view().viewport.setPan(pan)

    def getZoomMode(self) -> ViewportZoomMode:
        """Expose the active zoom mode reported by the viewport."""
        return self.view().viewport.get_zoom_mode()

    def markDirty(self, dirty_rect: QRect | QRectF | None = None):
        """Mark a region of the qpane as dirty by delegating to the renderer.

        Passing ``None`` marks the entire qpane dirty.
        """
        self.view().mark_dirty(dirty_rect)

    def _apply_zoom_interpolated(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = None,
    ) -> None:
        """Apply a clamped zoom request using the viewport interpolation path."""
        new_zoom = self._normalize_zoom_request(requested_zoom)
        if new_zoom is None:
            return
        self.view().viewport.applyZoomInterpolated(new_zoom, anchor=anchor)

    def _apply_zoom_interpolated_with_mode(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None,
        target_mode: ViewportZoomMode,
    ) -> None:
        """Apply an interpolated zoom request while setting the target mode."""
        if target_mode == ViewportZoomMode.FIT:
            if not self._can_apply_zoom():
                return
            new_zoom = requested_zoom
            if new_zoom <= 0:
                return
        else:
            reinterpret_one = target_mode != ViewportZoomMode.FIT
            new_zoom = self._normalize_zoom_request(
                requested_zoom, reinterpret_one_as_native=reinterpret_one
            )
            if new_zoom is None:
                return
        target_pan = None
        fit_zoom = None
        if target_mode == ViewportZoomMode.FIT:
            target_pan = QPointF(0, 0)
            fit_zoom = new_zoom
        elif target_mode == ViewportZoomMode.ONE_TO_ONE:
            target_pan = None if anchor is not None else QPointF(0, 0)
        self.view().viewport.applyZoomInterpolatedWithMode(
            new_zoom,
            anchor=anchor,
            target_mode=target_mode,
            target_pan=target_pan,
            fit_zoom=fit_zoom,
        )

    def _apply_zoom_fit_interpolated(self) -> None:
        """Fit the viewport using an interpolated transition."""
        if not self._can_apply_zoom():
            return
        self.view().viewport.setZoomFitInterpolated()

    def _apply_zoom_one_to_one_interpolated(
        self, anchor: QPoint | QPointF | None = None
    ) -> None:
        """Snap to 1:1 zoom using an interpolated transition."""
        if not self._can_apply_zoom():
            return
        self.view().viewport.setZoom1To1Interpolated(anchor=anchor)

    def nativeZoom(self) -> float:
        """Return the zoom level where one image pixel equals one device pixel."""
        return self.view().viewport.nativeZoom()

    def isDragOutAllowed(self) -> bool:
        """Return True when drag-out is enabled and the image fits the viewport."""
        if not getattr(self.settings, "drag_out_enabled", True):
            return False
        content_snapshot = self.view().current_content_snapshot()
        if content_snapshot is None:
            return False
        return ui.is_drag_out_allowed(
            image_size=content_snapshot.base_image_size,
            zoom=self.view().viewport.zoom,
            zoom_mode=self.view().viewport.get_zoom_mode(),
            viewport_size=self.physicalViewportRect().size(),
        )

    def replaceRenderer(self, renderer: Renderer) -> None:
        """Swap the active renderer while keeping presenter/view state aligned."""
        self.view().replace_renderer(renderer)
