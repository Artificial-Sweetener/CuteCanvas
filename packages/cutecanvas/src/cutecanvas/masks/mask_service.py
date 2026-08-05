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

"""Mask domain service and autosave coordination utilities."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPixmap
from qpane.sdk.execution import ExecutionScope
from qpane.sdk.types import DiagnosticRecord

from cutecanvas.coverage import CoverageItem, CoverageSnapshot

from ..composition.layers import CompositionLayerInstance
from ..core.config import Config
from ..core.config_features import MaskConfigSlice, require_mask_config
from ..painting import BrushStrokeSegment
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..types import DiagnosticsDomain
from .activation import MaskActivationController
from .autosave_coordination import MaskAutosaveCoordinator
from .component_adjustment import MaskComponentAdjustmentTool
from .generated_edits import MaskGeneratedEditService
from .layer_coordination import MaskLayerCoordinator
from .layer_workflows import MaskLayerWorkflow
from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .mask_diagnostics import MaskStrokeDiagnostics
from .mask_undo import MaskUndoState
from .projection import MaskCanvasProjectionService
from .render_coordination import (
    SNIPPET_ASYNC_THRESHOLD_PX,
    MaskRenderWorkCoordinator,
)
from .stroke_constraints import MaskStrokeConstraint
from .strokes import MaskStrokeDebugSnapshot, MaskStrokePipeline

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..canvas import CuteCanvas
    from ..scene.mutations import SceneMutationCoordinator
logger = logging.getLogger(__name__)


class MaskService:
    """Facade around mask domain operations, keeping CuteCanvas lightweight."""

    def __init__(
        self,
        *,
        qpane: CuteCanvas,
        mask_assets: MaskAssetStore,
        mask_controller: MaskController,
        config: Config,
        mask_config: MaskConfigSlice | None = None,
        view_execution_scope: ExecutionScope,
        document_execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        stroke_diagnostics: MaskStrokeDiagnostics | None = None,
    ) -> None:
        """Bind mask collaborators to their view and document lifetimes."""
        self._qpane = qpane
        self._assets = mask_assets
        self._component_adjustment = MaskComponentAdjustmentTool(mask_assets)
        mask_config = mask_config or require_mask_config(config)
        self._assets.set_undo_limit(mask_config.mask_undo_limit)
        self._mask_controller = mask_controller
        self._config_source = config
        self._config: MaskConfigSlice = mask_config
        self._projection = MaskCanvasProjectionService(
            assets=mask_assets,
            active_scene=qpane.sceneMutationCoordinator().active_scene,
        )
        self._generated_edits = MaskGeneratedEditService(
            projection=self._projection,
            edits=mask_controller.edits,
            renders=mask_controller.renders,
        )
        self._autosave = MaskAutosaveCoordinator(
            qpane=qpane,
            mask_controller=mask_controller,
            execution_scope=document_execution_scope,
            latest_requests=latest_requests,
            snapshot_provider=self._projection.deferred,
            publish_status=self._record_status,
        )
        self._status_messages: deque[tuple[str, str]] = deque(maxlen=8)
        self._history_actions_after_stroke: dict[
            uuid.UUID,
            deque[Callable[[], None]],
        ] = {}
        self._layers = MaskLayerCoordinator(
            layers=qpane.compositionService().layers,
            layer_edits=qpane.compositionService().layer_edits,
            assets=mask_assets,
            controller=mask_controller,
            current_composition_id=qpane.currentCompositionID,
        )
        self._mask_controller.set_color_resolver(self._layers.color)
        self._render_work = MaskRenderWorkCoordinator(
            assets=mask_assets,
            controller=mask_controller,
            execution_scope=view_execution_scope,
            mask_ids_for_composition=self._layers.mask_ids_for_composition,
            composition_ids_for_mask=self._layers.composition_ids_for_mask,
            current_composition_id=qpane.currentCompositionID,
            current_zoom=self._current_zoom,
            should_defer_prefetch=lambda active_id, next_id: (
                self._activation.should_defer(active_id, next_id)
            ),
            is_mask_busy=lambda mask_id: self._stroke_pipeline.is_mask_busy(mask_id),
            publish_status=self._record_status,
        )
        self._mask_controller.renders.set_async_handler(
            self._render_work.request_async_colorize,
            threshold_px=SNIPPET_ASYNC_THRESHOLD_PX,
        )
        self._activation = MaskActivationController(
            controller=mask_controller,
            assets=mask_assets,
            mask_ids_for_composition=self._layers.mask_ids_for_composition,
            invalidate_jobs=self._invalidate_pending_mask_jobs,
            prefetch=self._render_work.prefetch,
            prefetch_pending=self._render_work.is_prefetch_pending,
            publish_status=self._record_status,
            resume=lambda _image_id=None: qpane.resumeOverlays(),
            resume_and_update=lambda _image_id=None: qpane.resumeOverlaysAndUpdate(),
        )
        self._stroke_pipeline = MaskStrokePipeline(
            assets=mask_assets,
            controller=mask_controller,
            execution_scope=view_execution_scope,
            mask_feature_available=lambda: (
                qpane._masks_controller.mask_feature_available()
            ),
            current_composition_id=qpane.currentCompositionID,
            ensure_active=self._activation.ensure_active,
            mask_ids_for_composition=self._layers.mask_ids_for_composition,
            view=qpane.view,
            update_region=self._render_work.update_region,
            diagnostics=stroke_diagnostics,
            compositor=qpane.paintingCoordinator().compositor,
        )
        self._stroke_pipeline.set_idle_callback(self._handle_stroke_idle)
        self._layer_workflow = MaskLayerWorkflow(
            qpane=qpane,
            assets=mask_assets,
            controller=mask_controller,
            layers=self._layers,
            render_work=self._render_work,
            activate_mask=self._activation.activate,
            reset_strokes=self._reset_pending_strokes,
            invalidate_jobs=self._invalidate_pending_mask_jobs,
            commit_image=self._commit_mask_image,
            publish_status=self._record_status,
        )
        qpane.diagnosticsDomainToggled.connect(self._handle_diagnostics_domain_toggled)
        if stroke_diagnostics is not None:
            try:
                is_enabled = qpane.diagnosticsDomainEnabled(DiagnosticsDomain.MASK)
                stroke_diagnostics.enabled = is_enabled
            except ValueError:
                pass

    @property
    def controller(self) -> MaskController:
        """Expose the active MaskController for callers that need it."""
        return self._mask_controller

    @property
    def render_work(self) -> MaskRenderWorkCoordinator:
        """Expose the owner of asynchronous mask render work."""
        return self._render_work

    def applyStrokeSegment(
        self,
        segment: BrushStrokeSegment,
    ) -> None:
        """Handle a brush segment emitted by the tool manager."""
        active_mask_id = self._mask_controller.get_active_mask_id()
        if active_mask_id is not None and not self._stroke_pipeline.is_mask_busy(
            active_mask_id
        ):
            self._render_work.prioritize_interaction(active_mask_id)
        self._stroke_pipeline.apply_stroke_segment(segment)

    def prepareBrushInteraction(self) -> None:
        """Stop derived render work that could compete with direct brush input."""
        active_mask_id = self._mask_controller.get_active_mask_id()
        if active_mask_id is not None:
            self._render_work.prioritize_interaction(active_mask_id)

    def commitStroke(self) -> None:
        """Flush the currently recorded stroke to the controller."""
        self._stroke_pipeline.commit_active_stroke()

    def cancelStroke(self) -> None:
        """Discard the currently recorded provisional stroke."""
        self._stroke_pipeline.cancel_active_stroke()

    def resetStrokePipeline(
        self,
        mask_id: uuid.UUID | None = None,
        *,
        clear_counter: bool = False,
        request_redraw: bool = True,
    ) -> None:
        """Expose a direct reset hook for delegates/tests."""
        self._stroke_pipeline.reset_state(
            mask_id,
            clear_counter=clear_counter,
            request_redraw=request_redraw,
        )

    def defer_history_action(
        self,
        mask_id: uuid.UUID,
        action: Callable[[], None],
    ) -> bool:
        """Run one chronological history action after a pending stroke commits."""
        if not self._stroke_pipeline.is_mask_busy(mask_id):
            return False
        self._history_actions_after_stroke.setdefault(mask_id, deque()).append(action)
        return True

    def has_pending_stroke(self, mask_id: uuid.UUID) -> bool:
        """Return whether provisional or worker stroke state remains for a mask."""
        return self._stroke_pipeline.is_mask_busy(mask_id)

    def _handle_stroke_idle(self, mask_id: uuid.UUID) -> None:
        """Resume derived work and replay history intents after stroke commit."""
        self._render_work.handle_mask_idle(mask_id)
        actions = self._history_actions_after_stroke.pop(mask_id, ())
        for action in actions:
            try:
                action()
            except Exception:  # pragma: no cover - defensive Qt callback boundary
                logger.exception(
                    "Deferred history action failed after mask stroke %s",
                    mask_id,
                )

    def strokeDebugSnapshot(self) -> MaskStrokeDebugSnapshot:
        """Return a snapshot of pending preview/job state for tests."""
        return self._stroke_pipeline.debug_snapshot()

    def hasPendingRenderWork(self) -> bool:
        """Return whether mask pixels can still change from queued render work."""
        stroke_snapshot = self._stroke_pipeline.debug_snapshot()
        return bool(
            stroke_snapshot.preview_state_ids
            or stroke_snapshot.preview_tokens
            or stroke_snapshot.pending_jobs
            or self._render_work.has_pending_work()
            or self._mask_controller.renders.has_pending_async()
        )

    def configureStrokeDiagnostics(
        self, config: Config | MaskConfigSlice | None = None
    ) -> None:
        """Refresh stroke diagnostics toggles after settings changes."""
        if config is not None:
            settings = require_mask_config(config)
            self._config = settings
        else:
            settings = self._config
        self._stroke_pipeline.configure_diagnostics(
            enabled=None,
        )

    def _handle_diagnostics_domain_toggled(self, domain: str, enabled: bool) -> None:
        """Update stroke diagnostics state when the mask domain toggles."""
        if domain == DiagnosticsDomain.MASK.value:
            self._stroke_pipeline.configure_diagnostics(
                enabled=enabled,
            )

    def strokeDiagnosticsSnapshot(self):
        """Return the latest stroke diagnostics snapshot when available."""
        return self._stroke_pipeline.diagnostics_snapshot()

    def set_activation_resume_hooks(
        self,
        resume: Callable[[uuid.UUID | None], None] | None,
        resume_and_update: Callable[[uuid.UUID | None], None] | None,
        on_pending: Callable[[uuid.UUID | None], None] | None,
    ) -> None:
        """Configure host callbacks for deferred activation."""
        self._activation.set_resume_hooks(resume, resume_and_update, on_pending)

    @property
    def assets(self) -> MaskAssetStore:
        """Expose the mask asset store."""
        return self._assets

    @property
    def layers(self) -> MaskLayerCoordinator:
        """Expose the owner of mask layer instances and scene routing."""
        return self._layers

    def mask_ids_for_composition(
        self,
        composition_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Return mask asset IDs in composition-owned z-order."""
        return self._layers.mask_ids_for_composition(composition_id)

    def composition_ids_for_mask(self, mask_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return composition documents containing an instance of one mask."""
        return self._layers.composition_ids_for_mask(mask_id)

    def layer_instances_for_composition(
        self,
        composition_id: uuid.UUID,
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return one composition's complete authoritative layer stack."""
        return self._layers.instances_for_composition(composition_id)

    def layer_instance_for_mask(
        self,
        mask_id: uuid.UUID,
        composition_id: uuid.UUID | None = None,
    ) -> CompositionLayerInstance | None:
        """Return one presentation instance for a mask asset."""
        return self._layers.instance_for_mask(mask_id, composition_id)

    def mask_color(self, mask_id: uuid.UUID) -> QColor | None:
        """Return the composition-owned tint for one mask instance."""
        return self._layers.color(mask_id)

    def adjust_mask_component(
        self, mask_id: uuid.UUID, point, *, grow: bool
    ) -> CoverageSnapshot | None:
        """Build a reusable connected-component edit for any mask-aware tool."""
        return self._component_adjustment.adjusted_surface(
            mask_id,
            point,
            grow=grow,
        )

    def apply_mask_image(self, mask_id: uuid.UUID, image: QImage) -> bool:
        """Apply a complete image through the transactional edit owner."""
        return self._mask_controller.edits.apply_mask_image(mask_id, image)

    def apply_mask_surface(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageSnapshot,
    ) -> bool:
        """Apply complete raster structure through the transactional edit owner."""
        return self._mask_controller.edits.apply_mask_surface(mask_id, snapshot)

    def applyMaskCoverageItem(
        self,
        mask_id: uuid.UUID,
        item: CoverageItem,
    ) -> bool:
        """Commit one retained coverage item to a mask through its edit owner."""
        return self._mask_controller.edits.apply_coverage_item(mask_id, item)

    def scene_provider_revision(self) -> tuple[object, ...]:
        """Return mask order and render revisions for scene compilation."""
        return self._layers.scene_provider_revision()

    def setSceneMutationCoordinator(
        self, coordinator: SceneMutationCoordinator | None
    ) -> None:
        """Register mask layer mutations with the internal scene coordinator."""
        self._layers.set_scene_mutation_coordinator(coordinator)

    def setStrokeConstraintProvider(
        self,
        provider: Callable[[uuid.UUID], MaskStrokeConstraint | None] | None,
    ) -> None:
        """Bind composition selection coverage used to constrain mask strokes."""
        self._stroke_pipeline.set_selection_constraint(provider)

    def shutdown(self) -> None:
        """Stop view-local mask workers during widget teardown."""
        self._stroke_pipeline.shutdown()
        self._render_work.shutdown()

    def _scope_for_mask(self, mask_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve a mask asset to its active or first owning composition."""
        composition_ids = self._layers.composition_ids_for_mask(mask_id)
        if not composition_ids:
            return None
        current_id = self._qpane.currentCompositionID()
        return current_id if current_id in composition_ids else composition_ids[0]

    def connectUndoStackChanged(self, slot: Callable[[uuid.UUID], None]) -> None:
        """Register slot for undo stack change notifications."""
        self._mask_controller.undo_stack_changed.connect(slot)

    def disconnectUndoStackChanged(self, slot: Callable[[uuid.UUID], None]) -> None:
        """Detach slot from undo stack change notifications."""
        try:
            self._mask_controller.undo_stack_changed.disconnect(slot)
        except (TypeError, RuntimeError) as exc:
            logger.warning("Failed to disconnect undo stack listener: %s", exc)

    def getUndoState(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Return the undo/redo stack depth for mask_id when available."""
        return self._assets.get_undo_state(mask_id)

    def getActiveMaskId(self) -> uuid.UUID | None:
        """Get the identifier of the mask currently selected for editing."""
        return self._mask_controller.get_active_mask_id()

    def getActiveMaskColor(self) -> QColor | None:
        """Get the color assigned to the active mask layer."""
        return self._mask_controller.get_active_mask_color()

    def getActiveMaskImage(self) -> QImage | None:
        """Get the rendered image backing the active mask layer."""
        mask_id = self._mask_controller.get_active_mask_id()
        return None if mask_id is None else self._projection.project(mask_id)

    def clearRenderCache(self) -> None:
        """Clear the cached colorized mask previews maintained by the controller."""
        self._mask_controller.renders.clear()

    def setPrefetchEnabled(self, enabled: bool) -> None:
        """Enable or disable asynchronous mask render prefetch."""
        self._render_work.set_enabled(enabled)

    def prefetchColorizedMasks(
        self,
        composition_id: uuid.UUID | None,
        *,
        reason: str = "navigation",
        scales: Sequence[float] | None = None,
    ) -> bool:
        """Warm mask renders for one composition using the background executor."""
        return self._render_work.prefetch(
            composition_id,
            reason=reason,
            scales=scales,
        )

    def cancelPrefetch(self, composition_id: uuid.UUID | None) -> bool:
        """Cancel queued mask prefetch work for one composition."""
        return self._render_work.cancel_prefetch(composition_id)

    def activateMask(self, mask_id: uuid.UUID | None) -> bool:
        """Select the mask edited by tools."""
        return self._activation.activate(mask_id)

    def ensureActiveMaskForComposition(
        self,
        composition_id: uuid.UUID | None,
    ) -> bool:
        """Align editable-mask selection with one composition."""
        return self._activation.ensure_active(composition_id)

    def isActivationPending(self, composition_id: uuid.UUID | None) -> bool:
        """Return whether deferred activation remains pending for a document."""
        return self._activation.is_pending(composition_id)

    def undoActiveMaskEdit(self) -> bool:
        """Undo the most recent edit on the active mask layer."""
        result = self._mask_controller.edits.undo()
        if result:
            mask_id = self._mask_controller.get_active_mask_id()
            composition_id = self._composition_id_for_mask(mask_id)
            if composition_id is not None:
                self.prefetchColorizedMasks(composition_id, reason="undo")
        return result

    def redoActiveMaskEdit(self) -> bool:
        """Redo the previously undone edit on the active mask layer."""
        result = self._mask_controller.edits.redo()
        if result:
            mask_id = self._mask_controller.get_active_mask_id()
            composition_id = self._composition_id_for_mask(mask_id)
            if composition_id is not None:
                self.prefetchColorizedMasks(composition_id, reason="redo")
        return result

    def pushActiveMaskState(self) -> bool:
        """Push the current active mask image onto its undo stack."""
        return self._mask_controller.edits.begin_stroke()

    def invalidateActiveMaskCache(self) -> None:
        """Invalidate the colorized pixmap cache for the active mask."""
        mask_id = self._mask_controller.get_active_mask_id()
        self._mask_controller.renders.invalidate(mask_id)
        if mask_id is not None:
            self._qpane.view().invalidate_content_cache()
            self._mask_controller.render_dirty.emit(mask_id, QRect())

    def invalidateMaskCache(self, mask_id: uuid.UUID | None) -> None:
        """Invalidate cached mask renders for mask_id when present."""
        self._mask_controller.renders.invalidate(mask_id)
        if mask_id is not None:
            self._qpane.view().invalidate_content_cache()
            self._mask_controller.render_dirty.emit(mask_id, QRect())

    def invalidateMaskCachesForComposition(
        self,
        composition_id: uuid.UUID | None,
    ) -> None:
        """Invalidate cached mask renders for one composition."""
        if composition_id is None:
            return
        for mask_id in self.mask_ids_for_composition(composition_id):
            self._mask_controller.renders.invalidate(
                mask_id,
                reason="composition_invalidate",
            )

    def updateMaskRegion(
        self,
        dirty_image_rect: QRect,
        mask_layer: MaskLayer,
        *,
        sub_mask_image: QImage | None = None,
        force_async_colorize: bool = False,
    ) -> None:
        """Propagate a region update through the render-work owner."""
        self._render_work.update_region(
            dirty_image_rect,
            mask_layer,
            sub_mask_image=sub_mask_image,
            force_async_colorize=force_async_colorize,
        )
        self._mask_controller.mask_updated.emit(
            mask_layer.mask_id,
            QRect(dirty_image_rect),
        )

    def invalidateMaskRenderRegion(
        self,
        dirty_image_rect: QRect,
        mask_layer: MaskLayer,
    ) -> None:
        """Invalidate derived products after a durable canonical pixel edit."""
        if mask_layer is None or dirty_image_rect.isNull():
            return
        mask_id = mask_layer.mask_id
        self._mask_controller.renders.invalidate(
            mask_id,
            reason="durable_pixel_edit",
        )
        self._mask_controller.render_dirty.emit(mask_id, QRect(dirty_image_rect))
        self._mask_controller.mask_updated.emit(mask_id, QRect(dirty_image_rect))

    def handleGeneratedMask(
        self,
        mask_array_uint8: np.ndarray | None,
        bbox: np.ndarray,
        erase_mode: bool,
    ) -> None:
        """Merge a generated mask array into the active layer or clear stale overlays."""
        composition_id = self._qpane.currentCompositionID()
        if not self.ensureActiveMaskForComposition(composition_id):
            logger.info(
                "Mask generation skipped: no active mask available for document %s.",
                composition_id,
            )
            return
        mask_id = self.getActiveMaskId()
        if mask_id is None:
            return
        self.handleGeneratedMaskFor(
            mask_id,
            mask_array_uint8,
            bbox,
            erase_mode,
        )

    def handleGeneratedMaskFor(
        self,
        mask_id: uuid.UUID,
        mask_array_uint8: np.ndarray | None,
        bbox: np.ndarray,
        erase_mode: bool,
    ) -> None:
        """Merge generated coverage into the exact mask captured by a request."""
        del bbox
        update = self._generated_edits.apply(
            mask_id,
            mask_array_uint8,
            erase=erase_mode,
        )
        if update is None:
            return
        updated_mask_id, changed = update
        if not changed:
            self._mask_controller.mask_updated.emit(updated_mask_id, QRect())

    def getColorizedMask(
        self, mask_layer: MaskLayer, *, scale: float | None = None
    ) -> QPixmap | None:
        """Get the colorized pixmap for ``mask_layer`` when available."""
        return self._mask_controller.renders.get_with_live_preview(
            mask_layer,
            scale=scale,
        )

    def getColorizedMaskById(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Get the colorized pixmap for ``mask_id`` when available."""
        return self._mask_controller.renders.get_by_id_with_live_preview(
            mask_id,
            scale=scale,
        )

    def get_latest_status_message(self, *labels: str) -> tuple[str, str] | None:
        """Return the most recent status message filtered by labels when provided."""
        if not self._status_messages:
            return None
        if labels:
            label_set = set(labels)
            for label, message in reversed(self._status_messages):
                if label in label_set:
                    return label, message
        return self._status_messages[-1]

    def _commit_mask_image(
        self, mask_id: uuid.UUID, image: QImage, *, before: QImage | None = None
    ) -> bool:
        """Apply ``image`` to the mask controller and emit an update signal."""
        if not self._mask_controller.edits.apply_mask_image(
            mask_id, image, before=before
        ):
            return False
        self._mask_controller.mask_updated.emit(mask_id, QRect())
        return True

    def applyConfig(
        self, config: Config, mask_config: MaskConfigSlice | None = None
    ) -> None:
        """Refresh service dependencies after a configuration update."""
        mask_config = mask_config or require_mask_config(config)
        self._config_source = config
        self._config = mask_config
        self._assets.set_undo_limit(mask_config.mask_undo_limit)
        self._mask_controller.renders.apply_config(config, mask_config)
        self._autosave.applyConfig(mask_config)
        self.setPrefetchEnabled(mask_config.mask_prefetch_enabled)
        self.configureStrokeDiagnostics(mask_config)

    @staticmethod
    def _format_uuid(value: uuid.UUID | None) -> str:
        """Return a short, diagnostics-friendly representation of value."""
        if isinstance(value, uuid.UUID):
            return value.hex[:8].upper()
        return "None"

    def _composition_id_for_mask(
        self,
        mask_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Return the most relevant document for a mask asset."""
        if mask_id is None:
            return None
        composition_ids = self.composition_ids_for_mask(mask_id)
        if composition_ids:
            return composition_ids[-1]
        return self._qpane.currentCompositionID()

    def _current_zoom(self) -> float:
        """Adapt the host viewport zoom for render-work policy."""
        try:
            viewport = self._qpane.view().viewport
        except AttributeError:
            viewport = getattr(self._qpane, "viewport", None)
        return float(getattr(viewport, "zoom", 1.0) or 1.0)

    def _reset_pending_strokes(
        self,
        mask_id: uuid.UUID | None,
        *,
        clear_counter: bool = False,
        request_redraw: bool = True,
    ) -> None:
        """Cancel pending stroke jobs using the pipeline-owned state."""
        self._stroke_pipeline.reset_state(
            mask_id,
            clear_counter=clear_counter,
            request_redraw=request_redraw,
        )

    def _invalidate_pending_mask_jobs(
        self,
        mask_id: uuid.UUID | None,
        *,
        reason: str,
        request_redraw: bool = True,
    ) -> None:
        """Cancel queued stroke work without changing durable mask identity."""
        if mask_id is None:
            logger.info(
                "Skipped mask job invalidation because mask id was None (reason=%s)",
                reason,
            )
            return
        logger.info(
            "Invalidating pending mask jobs for %s (reason=%s, redraw=%s)",
            mask_id,
            reason,
            request_redraw,
        )
        self._render_work.discard_deferred(mask_id)
        self._stroke_pipeline.reset_state(
            mask_id,
            preserve_committed=True,
            request_redraw=request_redraw,
        )

    def _diagnostics_provider(self, _: CuteCanvas) -> Sequence[DiagnosticRecord]:
        """Surface recent mask service status messages for diagnostics overlays."""
        records: list[DiagnosticRecord] = []
        suppressed_labels = {"Mask", "Mask Autosave"}
        filtered: list[tuple[str, str]] = []
        if self._status_messages:
            filtered = [
                (label, message)
                for label, message in self._status_messages
                if label not in suppressed_labels
            ]
        label_counts: dict[str, int] = {}
        latest_messages: dict[str, str] = {}
        ordered_labels: list[str] = []
        for label, message in filtered:
            if label in ordered_labels:
                ordered_labels.remove(label)
            ordered_labels.append(label)
            label_counts[label] = label_counts.get(label, 0) + 1
            latest_messages[label] = message
        prefetch_messages = [
            message for label, message in filtered if label == "Mask Prefetch"
        ]
        display_labels = [label for label in ordered_labels if label != "Mask Prefetch"]
        for label in display_labels[-3:]:
            message = latest_messages[label]
            count = label_counts.get(label, 0)
            if count > 1:
                message = f"{message} (+{count - 1} earlier)"
            records.append(DiagnosticRecord(label, message))
        stats = self._render_work.stats
        summary_line = self._render_work.diagnostics_summary()
        detail_parts = []
        if stats.scheduled or stats.completed or stats.skipped or stats.failed:
            detail_parts.append(
                f"scheduled={stats.scheduled} completed={stats.completed} "
                f"skipped={stats.skipped} failed={stats.failed}"
            )
        hidden_events = max(len(prefetch_messages) - 1, 0)
        if hidden_events:
            plural = "s" if hidden_events > 1 else ""
            detail_parts.append(f"{hidden_events} earlier event{plural} hidden")
        value = summary_line
        if detail_parts:
            value = f"{summary_line} | {' | '.join(detail_parts)}"
        records.append(DiagnosticRecord("Mask|Prefetch", value))
        return tuple(records)

    def _record_status(self, message: str, *, label: str) -> None:
        """Cache a status update so diagnostics surfaces the latest mask activity."""
        self._status_messages.append((label, message))

    def loadMaskFromPath(
        self,
        path: str,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Import a mask and optionally record its document admission."""
        return self._layer_workflow.load_from_path(path, undoable=undoable)

    def updateMaskFromPath(self, mask_id: uuid.UUID, path: str) -> bool:
        """Replace mask pixels for mask_id with data from path."""
        return self._layer_workflow.update_from_path(mask_id, path)

    def updateMaskFromImage(self, mask_id: uuid.UUID, image: QImage) -> bool:
        """Replace mask pixels for mask_id with host-provided image data."""
        return self._layer_workflow.update_from_image(mask_id, image)

    def createBlankMask(
        self,
        size: QSize,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Create a blank mask and optionally record its document admission."""
        return self._layer_workflow.create_blank(size, undoable=undoable)

    def removeMaskFromComposition(
        self,
        composition_id: uuid.UUID,
        mask_id: uuid.UUID,
    ) -> bool:
        """Remove a mask instance and refresh edit/render lifecycle state."""
        return self._layer_workflow.remove_from_composition(composition_id, mask_id)

    def setMaskProperties(
        self,
        mask_id: uuid.UUID,
        *,
        color: QColor | None = None,
        opacity: float | None = None,
    ) -> bool:
        """Update composition-owned presentation for a mask layer."""
        return self._layer_workflow.set_properties(
            mask_id,
            color=color,
            opacity=opacity,
        )

    def cycleMasks(
        self,
        composition_id: uuid.UUID | None,
        *,
        forward: bool,
    ) -> None:
        """Cycle mask ordering for one document or the active document."""
        self._layer_workflow.cycle(composition_id, forward=forward)

    def promoteMaskToTop(self, mask_id: uuid.UUID) -> bool:
        """Bring mask_id to the top of the active composition's mask stack."""
        return self._layer_workflow.promote_to_top(mask_id)

    def refreshAutosavePolicy(self) -> None:
        """Re-evaluate autosave wiring and report its current state."""
        self._autosave.refresh_and_report()

    def handleMaskRegionUpdate(
        self, dirty_image_rect: QRect, mask_layer_supplier: Callable[[], object]
    ) -> None:
        """Notify controller of paint updates after external edits."""
        self._layer_workflow.handle_region_update(
            dirty_image_rect,
            mask_layer_supplier,
        )
