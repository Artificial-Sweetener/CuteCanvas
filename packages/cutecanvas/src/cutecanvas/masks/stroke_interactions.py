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

"""Own mask stroke preparation, settlement, and deferred history actions."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Callable

from qpane.sdk.execution import ExecutionScope
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    PiecewiseLayerTransform,
    SceneDescriptor,
)

from ..painting import BrushStrokeSegment
from ..resources import ProjectResourceReference
from .mask import MaskAssetStore
from .mask_controller import MaskController
from .paint_preparation import RetainedMaskPaintPreparation
from .render_coordination import MaskRenderWorkCoordinator
from .spatial_paint import MaskSpatialPaintNormalizer
from .spatial_paint_history import MaskSpatialPaintHistory
from .strokes import MaskStrokePipeline

logger = logging.getLogger(__name__)


class MaskStrokeInteractionCoordinator:
    """Coordinate direct mask strokes without owning their domain state."""

    def __init__(
        self,
        *,
        pipeline: MaskStrokePipeline,
        render_work: MaskRenderWorkCoordinator,
        controller: MaskController,
        spatial_paint: MaskSpatialPaintNormalizer,
        spatial_history: MaskSpatialPaintHistory,
        refresh_coordinates: Callable[[], object],
        active_scene: Callable[[], SceneDescriptor | None],
        assets: MaskAssetStore,
        execution_scope: ExecutionScope,
    ) -> None:
        """Bind stroke, render, spatial, and scene-coordinate collaborators."""
        self._pipeline = pipeline
        self._render_work = render_work
        self._controller = controller
        self._spatial_paint = spatial_paint
        self._spatial_history = spatial_history
        self._refresh_coordinates = refresh_coordinates
        self._active_scene = active_scene
        self._retained_paint = RetainedMaskPaintPreparation(
            assets,
            execution_scope,
        )
        self._history_actions: dict[uuid.UUID, deque[Callable[[], None]]] = {}

    def apply(self, segment: BrushStrokeSegment) -> None:
        """Route a brush segment while prioritizing its active mask."""
        mask_id = self._controller.get_active_mask_id()
        if mask_id is not None and not self._pipeline.is_mask_busy(mask_id):
            self._render_work.prioritize_interaction(mask_id)
        self._pipeline.apply_stroke_segment(segment)

    def prepare_brush(self) -> None:
        """Prioritize input and prepare current mask coverage in background."""
        mask_id = self._controller.get_active_mask_id()
        if mask_id is not None:
            self._render_work.prioritize_interaction(mask_id)
            scene = self._active_scene()
            layer = (
                None
                if scene is None
                else next(
                    (
                        candidate
                        for candidate in scene.layers
                        if isinstance(candidate.source, ProjectResourceReference)
                        and candidate.source.resource_id == mask_id
                    ),
                    None,
                )
            )
            if layer is not None:
                if isinstance(
                    layer.transform,
                    (BilinearLayerTransform, PiecewiseLayerTransform),
                ):
                    self._spatial_paint.warm(layer)
                else:
                    self._retained_paint.warm(mask_id)

    def paint_target_ready(self, layer: LayerDescriptor) -> bool:
        """Return whether exact current coverage is ready for immediate input."""
        if isinstance(
            layer.transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return self._spatial_paint.ready(layer)
        source = layer.source
        return not isinstance(
            source,
            ProjectResourceReference,
        ) or self._retained_paint.ready(source.resource_id)

    def begin_stroke(self, layer: LayerDescriptor) -> bool:
        """Begin one stroke with any exact retained preparation available."""
        source = layer.source
        if not isinstance(source, ProjectResourceReference):
            return False
        prepared = (
            None
            if isinstance(
                layer.transform,
                (BilinearLayerTransform, PiecewiseLayerTransform),
            )
            else self._retained_paint.take(source.resource_id)
        )
        return self._controller.edits.begin_stroke(prepared)

    def prepare_spatial_target(self, layer: LayerDescriptor) -> bool:
        """Normalize finite mask geometry before pointer resolution."""
        prepared = self._spatial_paint.prepare(layer)
        if prepared:
            self._refresh_coordinates()
        return prepared

    def commit(self) -> None:
        """Flush the active stroke into its authoritative mask."""
        self._pipeline.commit_active_stroke()

    def cancel(self) -> None:
        """Discard the active provisional stroke."""
        self._pipeline.cancel_active_stroke()

    def cancel_spatial_target(self, mask_id: uuid.UUID) -> bool:
        """Restore finite mapping when a prepared gesture is cancelled."""
        return self._spatial_history.restore_if_pending(mask_id)

    def shutdown(self) -> None:
        """Release view-local paint preparation workers."""
        self._retained_paint.shutdown()
        self._spatial_paint.shutdown()

    def reset(
        self,
        mask_id: uuid.UUID | None = None,
        *,
        clear_counter: bool = False,
        request_redraw: bool = True,
    ) -> None:
        """Reset provisional and queued state for the selected masks."""
        self._pipeline.reset_state(
            mask_id,
            clear_counter=clear_counter,
            request_redraw=request_redraw,
        )

    def defer_history_action(
        self,
        mask_id: uuid.UUID,
        action: Callable[[], None],
    ) -> bool:
        """Run a chronological action after pending stroke settlement."""
        if not self._pipeline.is_mask_busy(mask_id):
            return False
        self._history_actions.setdefault(mask_id, deque()).append(action)
        return True

    def is_busy(self, mask_id: uuid.UUID) -> bool:
        """Return whether provisional or worker state remains for a mask."""
        return self._pipeline.is_mask_busy(mask_id)

    def handle_idle(self, mask_id: uuid.UUID) -> None:
        """Restore no-op preparation and replay deferred history intents."""
        self._spatial_history.restore_if_pending(mask_id)
        self._render_work.handle_mask_idle(mask_id)
        actions = self._history_actions.pop(mask_id, ())
        for action in actions:
            try:
                action()
            except Exception:  # pragma: no cover - defensive Qt callback boundary
                logger.exception(
                    "Deferred history action failed after mask stroke %s",
                    mask_id,
                )


__all__ = ["MaskStrokeInteractionCoordinator"]
