#    QPane - High-performance PySide6 image viewer
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

from ..composition.edit_controller import CompositionEditController
from ..composition.layers import CompositionLayerInstance
from ..concurrency import TaskExecutorProtocol
from ..core import Config
from ..core.config_features import MaskConfigSlice, require_mask_config
from ..coverage import CoverageSnapshot
from ..scene.identity import default_scene_id
from ..types import DiagnosticRecord, DiagnosticsDomain
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
from .stroke_models import MaskStrokeSegmentPayload
from .strokes import MaskStrokeDebugSnapshot, MaskStrokePipeline

if TYPE_CHECKING:  # pragma: no cover - import cycle guard

    from ..qpane import QPane
    from ..scene.mutations import SceneMutationCoordinator
logger = logging.getLogger(__name__)


class MaskService:
    """Facade around mask domain operations, keeping QPane lightweight."""

    def __init__(
        self,
        *,
        qpane: QPane,
        mask_assets: MaskAssetStore,
        mask_controller: MaskController,
        config: Config,
        mask_config: MaskConfigSlice | None = None,
        executor: TaskExecutorProtocol,
        stroke_diagnostics: MaskStrokeDiagnostics | None = None,
    ) -> None:
        """Bind qpane collaborators plus mask, autosave, and executor plumbing."""
        self._qpane = qpane
        self._catalog = qpane.catalog()
        self._assets = mask_assets
        self._component_adjustment = MaskComponentAdjustmentTool(mask_assets)
        mask_config = mask_config or require_mask_config(config)
        self._assets.set_undo_limit(mask_config.mask_undo_limit)
        self._mask_controller = mask_controller
        self._config_source = config
        self._config: MaskConfigSlice = mask_config
        self._executor = executor
        self._projection = MaskCanvasProjectionService(
            assets=mask_assets,
            active_scene=qpane.sceneMutationCoordinator().active_scene,
        )
        self._generated_edits = MaskGeneratedEditService(
            active_mask_id=mask_controller.get_active_mask_id,
            projection=self._projection,
            edits=mask_controller.edits,
            renders=mask_controller.renders,
        )
        self._autosave = MaskAutosaveCoordinator(
            qpane=qpane,
            mask_controller=mask_controller,
            executor=executor,
            snapshot_provider=self._projection.deferred,
            publish_status=self._record_status,
        )
        self._status_messages: deque[tuple[str, str]] = deque(maxlen=8)
        self._layers = MaskLayerCoordinator(
            layers=qpane.compositionService().image_layers,
            assets=mask_assets,
            controller=mask_controller,
            current_image_id=self._catalog.currentImageID,
            remove_mask=lambda image_id, mask_id: self.removeMaskFromImage(
                image_id, mask_id
            ),
        )
        self._mask_controller.set_color_resolver(self._layers.color)
        self._render_work = MaskRenderWorkCoordinator(
            assets=mask_assets,
            controller=mask_controller,
            executor=executor,
            mask_ids_for_image=self._layers.mask_ids_for_image,
            image_ids_for_mask=self._layers.image_ids_for_mask,
            current_image_id=self._catalog.currentImageID,
            current_zoom=self._current_zoom,
            should_defer_prefetch=lambda active_id, next_id: self._activation.should_defer(
                active_id, next_id
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
            catalog=self._catalog,
            mask_ids_for_image=self._layers.mask_ids_for_image,
            invalidate_jobs=self._invalidate_pending_mask_jobs,
            promote_to_top=self.promoteMaskToTop,
            scene_stack_end=self._layers.mask_stack_end_index,
            route_reorder=self._layers.route_reorder,
            reorder=self._layers.reorder_mask_slot,
            prefetch=self._render_work.prefetch,
            prefetch_pending=self._render_work.is_prefetch_pending,
            publish_status=self._record_status,
            resume=lambda _image_id=None: qpane.resumeOverlays(),
            resume_and_update=lambda _image_id=None: qpane.resumeOverlaysAndUpdate(),
        )
        self._catalog.onNavigationStarted(self._activation.handle_navigation_started)
        self._stroke_pipeline = MaskStrokePipeline(
            assets=mask_assets,
            controller=mask_controller,
            executor=executor,
            mask_feature_available=lambda: qpane._masks_controller.mask_feature_available(),
            current_image_id=self._catalog.currentImageID,
            ensure_active=self._activation.ensure_top_active,
            mask_ids_for_image=self._layers.mask_ids_for_image,
            view=qpane.view,
            update_region=self._render_work.update_region,
            diagnostics=stroke_diagnostics,
        )
        self._stroke_pipeline.set_idle_callback(self._render_work.handle_mask_idle)
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
    def executor(self) -> TaskExecutorProtocol | None:
        """Expose the executor powering stroke/snippet workers."""
        return self._executor

    @property
    def render_work(self) -> MaskRenderWorkCoordinator:
        """Expose the owner of asynchronous mask render work."""
        return self._render_work

    def applyStrokeSegment(
        self,
        segment: MaskStrokeSegmentPayload,
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

    def mask_ids_for_image(self, image_id: uuid.UUID) -> list[uuid.UUID]:
        """Return mask asset IDs in composition-owned z-order."""
        return self._layers.mask_ids_for_image(image_id)

    def image_ids_for_mask(self, mask_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return image scenes containing an instance of one mask asset."""
        return self._layers.image_ids_for_mask(mask_id)

    def layer_instances_for_image(
        self, image_id: uuid.UUID
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return the complete composition-owned image scene stack."""
        return self._layers.instances_for_image(image_id)

    def layer_instance_for_mask(
        self,
        mask_id: uuid.UUID,
        image_id: uuid.UUID | None = None,
    ) -> CompositionLayerInstance | None:
        """Return one presentation instance for a mask asset."""
        return self._layers.instance_for_mask(mask_id, image_id)

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
        provider: Callable[[uuid.UUID], CoverageSnapshot | None] | None,
    ) -> None:
        """Bind composition selection coverage used to constrain mask strokes."""
        self._stroke_pipeline.set_selection_constraint(provider)

    def bindCompositionEdits(self, edits: CompositionEditController) -> None:
        """Bind mask commands to composition chronology after QPane attachment."""
        self._assets.bind_composition_edits(
            edits,
            lambda mask_id: self._scope_for_mask(mask_id),
            self._mask_controller.edits.present_history_change,
        )

    def _scope_for_mask(self, mask_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve a mask asset to its active or first owning image scene."""
        image_ids = self._layers.image_ids_for_mask(mask_id)
        if not image_ids:
            return None
        current_image_id = self._catalog.currentImageID()
        image_id = current_image_id if current_image_id in image_ids else image_ids[0]
        return default_scene_id(image_id)

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
        image_id: uuid.UUID | None,
        *,
        reason: str = "navigation",
        scales: Sequence[float] | None = None,
    ) -> bool:
        """Warm mask renders for image_id using the background executor."""
        return self._render_work.prefetch(
            image_id,
            reason=reason,
            scales=scales,
        )

    def cancelPrefetch(self, image_id: uuid.UUID | None) -> bool:
        """Cancel queued mask prefetch work associated with image_id."""
        return self._render_work.cancel_prefetch(image_id)

    def prepareCatalogImageRemoval(self, image_ids: Sequence[uuid.UUID]) -> None:
        """Cancel work and remove layer instances before catalog removal."""
        for image_id in tuple(dict.fromkeys(image_ids)):
            self.cancelPrefetch(image_id)
            for mask_id in tuple(self.mask_ids_for_image(image_id)):
                self._invalidate_pending_mask_jobs(
                    mask_id,
                    reason="image_removal",
                    request_redraw=False,
                )
                self._layers.remove(image_id, mask_id)

    def activateMask(self, mask_id: uuid.UUID | None) -> bool:
        """Select the mask edited by tools."""
        return self._activation.activate(mask_id)

    def ensureTopMaskActiveForImage(self, image_id: uuid.UUID | None) -> bool:
        """Align the editable mask with an image's top mask layer."""
        return self._activation.ensure_top_active(image_id)

    def isActivationPending(self, image_id: uuid.UUID | None) -> bool:
        """Return whether deferred activation remains pending for an image."""
        return self._activation.is_pending(image_id)

    def undoActiveMaskEdit(self) -> bool:
        """Undo the most recent edit on the active mask layer."""
        result = self._mask_controller.edits.undo()
        if result:
            mask_id = self._mask_controller.get_active_mask_id()
            image_id = self._image_id_for_mask(mask_id)
            if image_id is not None:
                self.prefetchColorizedMasks(image_id, reason="undo")
        return result

    def redoActiveMaskEdit(self) -> bool:
        """Redo the previously undone edit on the active mask layer."""
        result = self._mask_controller.edits.redo()
        if result:
            mask_id = self._mask_controller.get_active_mask_id()
            image_id = self._image_id_for_mask(mask_id)
            if image_id is not None:
                self.prefetchColorizedMasks(image_id, reason="redo")
        return result

    def pushActiveMaskState(self) -> bool:
        """Push the current active mask image onto its undo stack."""
        return self._mask_controller.edits.begin_stroke()

    def invalidateActiveMaskCache(self) -> None:
        """Invalidate the colorized pixmap cache for the active mask."""
        self._mask_controller.renders.invalidate(
            self._mask_controller.get_active_mask_id()
        )

    def invalidateMaskCache(self, mask_id: uuid.UUID | None) -> None:
        """Invalidate cached mask renders for mask_id when present."""
        self._mask_controller.renders.invalidate(mask_id)

    def invalidateMaskCachesForImage(self, image_id: uuid.UUID | None) -> None:
        """Invalidate cached mask renders for all masks associated with image_id."""
        if image_id is None:
            return
        for mask_id in self.mask_ids_for_image(image_id):
            self._mask_controller.renders.invalidate(
                mask_id,
                reason="image_invalidate",
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

    def handleGeneratedMask(
        self,
        mask_array_uint8: np.ndarray | None,
        bbox: np.ndarray,
        erase_mode: bool,
    ) -> None:
        """Merge a generated mask array into the active layer or clear stale overlays."""
        del bbox
        catalog = self._catalog
        current_image_id = catalog.currentImageID() if catalog else None
        if not self.ensureTopMaskActiveForImage(current_image_id):
            logger.info(
                "Mask generation skipped: no active mask available for image %s.",
                current_image_id,
            )
            return
        update = self._generated_edits.apply(
            mask_array_uint8,
            erase=erase_mode,
        )
        if update is None:
            return
        mask_id, changed = update
        if not changed:
            self._mask_controller.mask_updated.emit(mask_id, QRect())

    def getColorizedMask(
        self, mask_layer: MaskLayer, *, scale: float | None = None
    ) -> QPixmap | None:
        """Get the colorized pixmap for ``mask_layer`` when available."""
        return self._mask_controller.renders.get(mask_layer, scale=scale)

    def getColorizedMaskById(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Get the colorized pixmap for ``mask_id`` when available."""
        return self._mask_controller.renders.get_by_id(mask_id, scale=scale)

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

    def _image_id_for_mask(self, mask_id: uuid.UUID | None) -> uuid.UUID | None:
        """Return the most relevant composition image for a mask asset."""
        if mask_id is None:
            return None
        image_ids = self.image_ids_for_mask(mask_id)
        if image_ids:
            return image_ids[-1]
        try:
            return self._catalog.currentImageID()
        except RuntimeError:  # pragma: no cover - catalog teardown
            return None

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
        self._reset_pending_strokes(mask_id, request_redraw=request_redraw)

    def _diagnostics_provider(self, _: QPane) -> Sequence[DiagnosticRecord]:
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

    def loadMaskFromPath(self, path: str) -> uuid.UUID | None:
        """Import a mask from path and attach it to the current image."""
        return self._layer_workflow.load_from_path(path)

    def updateMaskFromPath(self, mask_id: uuid.UUID, path: str) -> bool:
        """Replace mask pixels for mask_id with data from path."""
        return self._layer_workflow.update_from_path(mask_id, path)

    def createBlankMask(self, size: QSize) -> uuid.UUID | None:
        """Create a blank mask layer for the current image."""
        return self._layer_workflow.create_blank(size)

    def removeMaskFromImage(self, image_id: uuid.UUID, mask_id: uuid.UUID) -> bool:
        """Remove a mask instance and refresh edit/render lifecycle state."""
        return self._layer_workflow.remove_from_image(image_id, mask_id)

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

    def cycleMasks(self, image_id: uuid.UUID, *, forward: bool) -> None:
        """Cycle mask ordering for image_id and refresh edit state."""
        self._layer_workflow.cycle(image_id, forward=forward)

    def promoteMaskToTop(self, mask_id: uuid.UUID) -> bool:
        """Bring mask_id to the top of the active image mask stack."""
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
