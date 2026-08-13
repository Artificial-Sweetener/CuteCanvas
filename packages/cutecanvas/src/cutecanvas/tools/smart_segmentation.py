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
"""Translate rectangular SAM prompts into selection or mask requests."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, ClassVar

from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.cursor import EditorCursorIntent
from cutecanvas.sam.segmentation_request import (
    SmartSegmentationProduct,
    SmartSegmentationRequest,
)
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QWheelEvent

from qpane import PointerPhase, PointerSample, ToolInputProfile

from .base import BaseTool
from .coverage_operation import resolve_coverage_operation
from .coverage_preview import draw_clipped_marching_ants
from .cursor_feedback import ToolCursorStyle
from .modifier_snapshot import alt_is_active, shift_is_active
from .ports import (
    SmartSegmentationInteractionPort,
    SmartSegmentationPromptProjection,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .tools import ToolManagerSignals

DEFAULT_MIN_SELECTION_SIZE = 5
DEFAULT_MASK_COLOR = QColor(128, 128, 128)


class SmartSegmentationBoxTool(BaseTool):
    """Own one target-stable rectangular prompt gesture."""

    input_profile = ToolInputProfile(touch=True)
    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.PRECISE
    supports_alt_erase_indicator: ClassVar[bool] = True
    product: ClassVar[SmartSegmentationProduct]

    def __init__(self) -> None:
        """Initialize an inactive prompt gesture."""
        super().__init__()
        self._reset_dependencies()
        self._clear_gesture(repaint=False)

    def activate(self, dependencies: SmartSegmentationInteractionPort) -> None:
        """Capture the focused interaction boundary for this activation."""
        self._dependencies = dependencies

    def deactivate(self) -> None:
        """Discard transient geometry and dependency references."""
        self._clear_gesture(repaint=False)
        self._reset_dependencies()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a prompt from a primary-button press."""
        if event.button() is Qt.MouseButton.LeftButton and self._begin(
            event.position(), event.modifiers()
        ):
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update active prompt geometry."""
        if self._update(event.position()):
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit a valid prompt request on primary-button release."""
        if event.button() is Qt.MouseButton.LeftButton and self._projection is not None:
            self._finish(event.position())
            event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle native touch prompts without synthesized mouse events."""
        if sample.phase is PointerPhase.BEGIN:
            return self._begin(sample.position, sample.modifiers)
        if sample.phase is PointerPhase.UPDATE:
            return self._update(sample.position)
        if sample.phase is PointerPhase.END and self._projection is not None:
            self._finish(sample.position)
            return True
        if sample.phase is PointerPhase.CANCEL:
            active = self._projection is not None
            self._clear_gesture()
            return active
        return False

    def cursor_intent(self) -> EditorCursorIntent:
        """Request selection-style precision feedback for Smart segmentation."""

        if self._dependencies.is_alt_held():
            return EditorCursorIntent.PRECISE_SUBTRACT
        if self._dependencies.is_shift_held():
            return EditorCursorIntent.PRECISE_ADD
        return EditorCursorIntent.PRECISE

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw selection-style feedback for the active rectangular prompt."""
        projection = self._projection
        if projection is None or self._start is None or self._end is None:
            return
        start = projection.source_to_panel(self._start)
        end = projection.source_to_panel(self._end)
        if start is None or end is None:
            return
        path = QPainterPath()
        path.addRect(QRectF(start, end).normalized())
        draw_clipped_marching_ants(
            painter,
            path,
            dark_color=self._boundary_color(),
        )

    @classmethod
    def build_request(
        cls,
        *,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        resource_id: uuid.UUID,
        mask_id: uuid.UUID | None,
        bounds: tuple[float, float, float, float],
        combine_mode: CoverageCombineMode,
    ) -> SmartSegmentationRequest:
        """Build the product-specific immutable inference request."""
        return SmartSegmentationRequest(
            scene_id=scene_id,
            layer_id=layer_id,
            resource_id=resource_id,
            bounds=bounds,
            product=cls.product,
            combine_mode=combine_mode,
            mask_id=mask_id,
        )

    def _begin(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> bool:
        """Capture one raster projection and destination before inference."""
        projection = self._dependencies.resolve_prompt_projection()
        source_point = (
            None if projection is None else projection.panel_to_source(panel_point)
        )
        mask_id = self._destination_mask_id()
        if source_point is None or not self._destination_available(mask_id):
            return False
        self._projection = projection
        self._mask_id = mask_id
        self._start = source_point
        self._end = source_point
        self._combine_mode = self._resolve_combine_mode(modifiers)
        self.signals.repaint_overlay_requested.emit()
        return True

    def _update(self, panel_point: QPointF) -> bool:
        """Project a panel point through the gesture's captured raster instance."""
        projection = self._projection
        if projection is None:
            return False
        source_point = projection.panel_to_source(panel_point)
        if source_point is None:
            return False
        self._end = source_point
        self.signals.repaint_overlay_requested.emit()
        return True

    def _finish(self, panel_point: QPointF) -> None:
        """Emit one target-stable request when the prompt exceeds minimum size."""
        self._update(panel_point)
        projection = self._projection
        bounds = self._normalized_bounds()
        if projection is not None and bounds is not None:
            try:
                request = self.build_request(
                    scene_id=projection.scene_id,
                    layer_id=projection.layer_id,
                    resource_id=projection.resource_id,
                    mask_id=self._mask_id,
                    bounds=bounds,
                    combine_mode=self._combine_mode,
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid Smart segmentation request: %s", exc)
            else:
                self.signals.smart_segmentation_requested.emit(request)
        self._clear_gesture()

    def _normalized_bounds(self) -> tuple[float, float, float, float] | None:
        """Return normalized source bounds when both dimensions are large enough."""
        if self._start is None or self._end is None:
            return None
        x1 = min(self._start.x(), self._end.x())
        y1 = min(self._start.y(), self._end.y())
        x2 = max(self._start.x(), self._end.x())
        y2 = max(self._start.y(), self._end.y())
        minimum = max(0, self._dependencies.get_min_selection_size())
        if x2 - x1 <= minimum or y2 - y1 <= minimum:
            return None
        return x1, y1, x2, y2

    def _resolve_combine_mode(
        self,
        modifiers: Qt.KeyboardModifier,
    ) -> CoverageCombineMode:
        """Resolve destination algebra once at gesture start."""
        return resolve_coverage_operation(
            default=self._default_combine_mode(),
            alt_held=alt_is_active(self._dependencies.is_alt_held(), modifiers),
            shift_held=shift_is_active(self._dependencies.is_shift_held(), modifiers),
        )

    def _default_combine_mode(self) -> CoverageCombineMode:
        """Return replacement as the default selection algebra."""
        return CoverageCombineMode.REPLACE

    def _destination_mask_id(self) -> uuid.UUID | None:
        """Return no mask destination for selection products."""
        return None

    def _destination_available(self, mask_id: uuid.UUID | None) -> bool:
        """Accept the destination used by selection products."""
        return mask_id is None

    def _boundary_color(self) -> QColor | Qt.GlobalColor:
        """Return the standard dark marching-ants phase for selections."""
        return Qt.GlobalColor.black

    def _clear_gesture(self, *, repaint: bool = True) -> None:
        """Discard the captured target and all transient geometry."""
        self._projection: SmartSegmentationPromptProjection | None = None
        self._start: QPointF | None = None
        self._end: QPointF | None = None
        self._mask_id: uuid.UUID | None = None
        self._combine_mode = CoverageCombineMode.REPLACE
        if repaint:
            self.signals.repaint_overlay_requested.emit()

    def _reset_dependencies(self) -> None:
        """Restore the safe inert activation boundary."""
        self._dependencies = SmartSegmentationInteractionPort()


class SmartSelectTool(SmartSegmentationBoxTool):
    """Produce pixel-selection coverage from one segmented rectangle."""

    product = SmartSegmentationProduct.PIXEL_SELECTION


class SmartMaskTool(SmartSegmentationBoxTool):
    """Produce active-mask coverage from one segmented rectangle."""

    product = SmartSegmentationProduct.MASK_COVERAGE

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Adjust the active mask component beneath a wheel gesture."""
        point = self._dependencies.panel_to_active_mask_point(event.position())
        if point is not None and event.angleDelta().y() != 0:
            self.signals.mask_component_adjustment_requested.emit(
                point.toPoint(),
                event.angleDelta().y() > 0,
            )
        event.accept()

    def _default_combine_mode(self) -> CoverageCombineMode:
        """Add generated coverage to the active mask by default."""
        return CoverageCombineMode.ADD

    def _destination_mask_id(self) -> uuid.UUID | None:
        """Capture the exact active mask targeted by this gesture."""
        return self._dependencies.get_active_mask_id()

    def _destination_available(self, mask_id: uuid.UUID | None) -> bool:
        """Require an exact mask destination before starting a prompt."""
        return isinstance(mask_id, uuid.UUID)

    def _boundary_color(self) -> QColor:
        """Color the dark marching-ants phase with the active mask color."""
        color = self._dependencies.get_active_mask_color()
        return QColor(DEFAULT_MASK_COLOR if color is None else color)


def connect_smart_segmentation_signals(
    manager_signals: ToolManagerSignals,
    tool: BaseTool,
) -> None:
    """Connect Smart segmentation requests to the manager signal bus."""
    tool.signals.smart_segmentation_requested.connect(
        manager_signals.smart_segmentation_requested
    )
    tool.signals.mask_component_adjustment_requested.connect(
        manager_signals.mask_component_adjustment_requested
    )


def disconnect_smart_segmentation_signals(
    manager_signals: ToolManagerSignals,
    tool: BaseTool,
) -> None:
    """Disconnect Smart segmentation requests with teardown diagnostics."""
    mappings = (
        (
            "smart_segmentation_requested",
            tool.signals.smart_segmentation_requested,
            manager_signals.smart_segmentation_requested,
        ),
        (
            "mask_component_adjustment_requested",
            tool.signals.mask_component_adjustment_requested,
            manager_signals.mask_component_adjustment_requested,
        ),
    )
    for signal_name, signal, slot in mappings:
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError) as exc:
            logger.warning(
                "Failed to disconnect Smart segmentation signal '%s': %s",
                signal_name,
                exc,
            )


__all__ = (
    "SmartMaskTool",
    "SmartSelectTool",
    "connect_smart_segmentation_signals",
    "disconnect_smart_segmentation_signals",
)
