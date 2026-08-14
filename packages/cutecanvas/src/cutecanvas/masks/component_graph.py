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
"""Construct and own the mask service's collaborating component graph."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from qpane.sdk.execution import ExecutionScope

from ..types import DiagnosticsDomain
from .activation import MaskActivationController
from .autosave_coordination import MaskAutosaveCoordinator
from .component_adjustment import MaskComponentAdjustmentTool
from .generated_edits import MaskGeneratedEditService
from .layer_coordination import MaskLayerCoordinator
from .layer_workflows import MaskLayerWorkflow
from .mask import MaskAssetStore
from .mask_controller import MaskController
from .mask_diagnostics import MaskStrokeDiagnostics
from .projection import MaskCanvasProjectionService
from .render_coordination import (
    SNIPPET_ASYNC_THRESHOLD_PX,
    MaskRenderWorkCoordinator,
)
from .spatial_paint import MaskSpatialPaintNormalizer
from .spatial_paint_history import MaskSpatialPaintHistory
from .status_diagnostics import MaskStatusDiagnostics
from .stroke_interactions import MaskStrokeInteractionCoordinator
from .strokes import MaskStrokePipeline

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..canvas import CuteCanvas
    from ..core.config_features import MaskConfigSlice
    from ..runtime.latest_requests import DocumentLatestRequestRegistry

logger = logging.getLogger(__name__)


class MaskServiceComponents:
    """Own construction, wiring, and teardown for mask service collaborators."""

    def __init__(
        self,
        *,
        qpane: CuteCanvas,
        assets: MaskAssetStore,
        controller: MaskController,
        mask_config: MaskConfigSlice,
        view_execution_scope: ExecutionScope,
        document_execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        stroke_diagnostics: MaskStrokeDiagnostics | None,
    ) -> None:
        """Assemble the mask graph against view and document lifetimes."""
        self._qpane = qpane
        self.assets = assets
        self.controller = controller
        self.component_adjustment = MaskComponentAdjustmentTool(assets)
        self.projection = MaskCanvasProjectionService(
            assets=assets,
            active_scene=qpane.sceneMutationCoordinator().active_scene,
        )
        self.generated_edits = MaskGeneratedEditService(
            projection=self.projection,
            edits=controller.edits,
            renders=controller.renders,
        )
        self.status = MaskStatusDiagnostics()
        self.autosave = MaskAutosaveCoordinator(
            qpane=qpane,
            mask_controller=controller,
            execution_scope=document_execution_scope,
            latest_requests=latest_requests,
            snapshot_provider=self.projection.deferred,
            publish_status=self.status.record,
        )
        self.layers = MaskLayerCoordinator(
            layers=qpane.compositionService().layers,
            layer_edits=qpane.compositionService().layer_edits,
            assets=assets,
            controller=controller,
            current_composition_id=qpane.currentCompositionID,
        )
        controller.set_color_resolver(self.layers.color)
        self.spatial_paint_history = MaskSpatialPaintHistory(
            assets=assets,
            layers=self.layers.store,
            controller=controller,
        )
        assets.set_history_command_decorator(self.spatial_paint_history.decorate)
        self.spatial_paint = MaskSpatialPaintNormalizer(
            assets=assets,
            layers=self.layers,
            controller=controller,
            history=self.spatial_paint_history,
            current_composition_id=qpane.currentCompositionID,
            execution_scope=view_execution_scope,
        )
        self.render_work = MaskRenderWorkCoordinator(
            assets=assets,
            controller=controller,
            execution_scope=view_execution_scope,
            mask_ids_for_composition=self.layers.mask_ids_for_composition,
            composition_ids_for_mask=self.layers.composition_ids_for_mask,
            current_composition_id=qpane.currentCompositionID,
            current_zoom=self._current_zoom,
            should_defer_prefetch=lambda active_id, next_id: (
                self.activation.should_defer(active_id, next_id)
            ),
            is_mask_busy=lambda mask_id: self.stroke_pipeline.is_mask_busy(mask_id),
            publish_status=self.status.record,
        )
        controller.renders.set_async_handler(
            self.render_work.request_async_colorize,
            threshold_px=SNIPPET_ASYNC_THRESHOLD_PX,
        )
        self.activation = MaskActivationController(
            controller=controller,
            assets=assets,
            mask_ids_for_composition=self.layers.mask_ids_for_composition,
            invalidate_jobs=self._invalidate_pending_mask_jobs,
            prefetch=self.render_work.prefetch,
            prefetch_pending=self.render_work.is_prefetch_pending,
            publish_status=self.status.record,
            resume=lambda _image_id=None: qpane.resumeOverlays(),
            resume_and_update=lambda _image_id=None: qpane.resumeOverlaysAndUpdate(),
        )
        self.stroke_pipeline = MaskStrokePipeline(
            assets=assets,
            controller=controller,
            execution_scope=view_execution_scope,
            mask_feature_available=lambda: (
                qpane._masks_controller.mask_feature_available()
            ),
            current_composition_id=qpane.currentCompositionID,
            ensure_active=self.activation.ensure_active,
            mask_ids_for_composition=self.layers.mask_ids_for_composition,
            view=qpane.view,
            update_region=self.render_work.update_region,
            diagnostics=stroke_diagnostics,
            compositor=qpane.paintingCoordinator().compositor,
        )
        self.stroke_interactions = MaskStrokeInteractionCoordinator(
            pipeline=self.stroke_pipeline,
            render_work=self.render_work,
            controller=controller,
            spatial_paint=self.spatial_paint,
            spatial_history=self.spatial_paint_history,
            refresh_coordinates=qpane.view().coordinate_scene_descriptor,
            active_scene=qpane.sceneMutationCoordinator().active_scene,
            prioritize_rendering=qpane.view().prioritize_interaction,
            assets=assets,
            execution_scope=view_execution_scope,
        )
        self.stroke_pipeline.set_idle_callback(self.stroke_interactions.handle_idle)
        self.layer_workflow = MaskLayerWorkflow(
            qpane=qpane,
            assets=assets,
            controller=controller,
            layers=self.layers,
            render_work=self.render_work,
            activate_mask=self.activation.activate,
            reset_strokes=self._reset_pending_strokes,
            invalidate_jobs=self._invalidate_pending_mask_jobs,
            commit_image=self._commit_mask_image,
            publish_status=self.status.record,
        )
        qpane.diagnosticsDomainToggled.connect(self._handle_diagnostics_domain_toggled)
        if stroke_diagnostics is not None:
            try:
                stroke_diagnostics.enabled = qpane.diagnosticsDomainEnabled(
                    DiagnosticsDomain.MASK
                )
            except ValueError:
                pass

    def shutdown(self) -> None:
        """Stop every view-local mask worker in dependency order."""
        self.stroke_interactions.shutdown()
        self.stroke_pipeline.shutdown()
        self.render_work.shutdown()

    def _handle_diagnostics_domain_toggled(self, domain: str, enabled: bool) -> None:
        """Apply host mask-diagnostics policy to the stroke pipeline."""
        if domain == DiagnosticsDomain.MASK.value:
            self.stroke_pipeline.configure_diagnostics(enabled=enabled)

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
        """Cancel pending stroke jobs through the pipeline owner."""
        self.stroke_pipeline.reset_state(
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
        """Cancel queued mask work without changing durable mask identity."""
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
        self.render_work.discard_deferred(mask_id)
        self.stroke_pipeline.reset_state(
            mask_id,
            preserve_committed=True,
            request_redraw=request_redraw,
        )

    def _commit_mask_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before: QImage | None = None,
    ) -> bool:
        """Apply one image through the edit owner and publish its update."""
        if not self.controller.edits.apply_mask_image(mask_id, image, before=before):
            return False
        self.controller.mask_updated.emit(mask_id, QRect())
        return True


__all__ = ["MaskServiceComponents"]
