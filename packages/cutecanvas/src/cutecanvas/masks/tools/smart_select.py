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

"""Smart-select tool implementation and wiring helpers for SAM masks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen, QWheelEvent
from qpane import PointerPhase, PointerSample, ToolInputProfile

from cutecanvas.tools.base import BaseTool
from cutecanvas.tools.cursor_feedback import ToolCursorStyle
from cutecanvas.tools.modifier_snapshot import alt_is_active
from cutecanvas.tools.ports import SmartSelectionInteractionPort

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ...canvas import CuteCanvas
    from ...tools.tools import ToolManagerSignals
__all__ = (
    "SmartSelectTool",
    "connect_smart_select_signals",
    "disconnect_smart_select_signals",
    "smart_select_cursor_provider",
)


DEFAULT_MIN_SELECTION_SIZE = 5
DEFAULT_MASK_COLOR = QColor(128, 128, 128)


class SmartSelectTool(BaseTool):
    """SAM-backed rectangular selection tool.

    Emits `region_selected_for_masking` and `mask_component_adjustment_requested`
    via the shared tool signal bus. The CuteCanvas supplies cursor visuals while this
    tool manages the selection overlay and wheel-driven component adjustments.
    """

    input_profile = ToolInputProfile(touch=True)
    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.PRECISE
    supports_alt_erase_indicator: ClassVar[bool] = True

    def __init__(self):
        """Initialize selection state and reset dependency callbacks."""
        super().__init__()
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset selection flags and dependency callbacks to safe defaults."""
        self.is_selecting_region = False
        self.selection_start_point: QPoint | None = None
        self.selection_end_point: QPoint | None = None
        self._is_alt_held: Callable[[], bool] = lambda: False
        self._get_dpr: Callable[[], float] = lambda: 1.0
        self._panel_to_content_point: Callable[[QPoint], QPoint | None] = (
            lambda point: None
        )
        self._image_to_panel_point: Callable[[QPoint], QPoint | None] = (
            lambda point: None
        )
        self._panel_to_active_mask_point: (
            Callable[[QPoint | QPointF], QPointF | None] | None
        ) = None
        self._active_mask_to_panel_point: (
            Callable[[QPoint | QPointF], QPointF | None] | None
        ) = None
        self._get_min_selection_size: Callable[[], int] = (
            lambda: DEFAULT_MIN_SELECTION_SIZE
        )
        self._get_active_mask_color: Callable[[], QColor | None] = lambda: None

    def activate(self, dependencies: SmartSelectionInteractionPort) -> None:
        """Capture CuteCanvas-provided helpers when the tool becomes active.

        Expected callables:
        - `is_alt_held`: toggles erase mode during selection/adjustment.
        - `get_dpr`: reports device pixel ratio for stroke thickness scaling.
        - `panel_to_content_point` / `image_to_panel_point`: coordinate transforms.
        - `get_min_selection_size`: minimum diagonal enforced for valid bboxes.
        - `get_active_mask_color`: supplies the active mask colour for overlay styling.
        All inputs are optional; defaults keep the tool passive when dependencies
        are missing.
        """
        self._is_alt_held = dependencies.is_alt_held
        self._get_dpr = dependencies.get_dpr
        self._panel_to_content_point = dependencies.panel_to_content_point
        self._image_to_panel_point = dependencies.image_to_panel_point
        self._panel_to_active_mask_point = dependencies.panel_to_active_mask_point
        self._active_mask_to_panel_point = dependencies.active_mask_to_panel_point
        self._get_min_selection_size = dependencies.get_min_selection_size
        self._get_active_mask_color = dependencies.get_active_mask_color

    def deactivate(self):
        """Clear selection state and restore default dependency callbacks."""
        self._reset_state()

    def getCursor(self):
        """Let the CuteCanvas provide the smart-select cursor with erase indicators."""
        return

    def mousePressEvent(self, event: QMouseEvent):
        """Start a rectangular selection when the user presses the left button."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._begin_selection(event.position().toPoint()):
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Update the active selection as the pointer moves."""
        if self._update_selection(event.position().toPoint()):
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Finalize the selection and emit a bounding box when valid."""
        if event.button() != Qt.MouseButton.LeftButton or not self.is_selecting_region:
            return
        self._finish_selection(
            event.position().toPoint(),
            event.modifiers(),
        )
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle direct touch selection without synthesized mouse events."""
        point = sample.position.toPoint()
        if sample.phase is PointerPhase.BEGIN:
            return self._begin_selection(point)
        if sample.phase is PointerPhase.UPDATE:
            return self._update_selection(point)
        if sample.phase is PointerPhase.END:
            if not self.is_selecting_region:
                return False
            self._finish_selection(point, sample.modifiers)
            return True
        if sample.phase is PointerPhase.CANCEL:
            was_selecting = self.is_selecting_region
            self._clear_selection()
            return was_selecting
        return False

    def wheelEvent(self, event: QWheelEvent):
        """Request mask component adjustments or absorb the gesture."""
        image_point = self._panel_to_mask_point(event.position().toPoint())
        if image_point is None:
            event.accept()
            return
        angle = event.angleDelta().y()
        grow = angle > 0
        self.signals.mask_component_adjustment_requested.emit(image_point, grow)
        event.accept()

    def get_selection_points(self) -> tuple[QPoint | None, QPoint | None]:
        """Return the active selection endpoints, if a drag is in progress."""
        if (
            self.is_selecting_region
            and self.selection_start_point is not None
            and self.selection_end_point is not None
        ):
            return self.selection_start_point, self.selection_end_point
        return None, None

    def draw_overlay(self, painter: QPainter):
        """Render the selection rectangle with dotted stroke matching the mask colour."""
        start_point, end_point = self.get_selection_points()
        if start_point is None or end_point is None:
            return
        mapper = self._active_mask_to_panel_point or self._image_to_panel_point
        p1 = mapper(start_point)
        p2 = mapper(end_point)
        if p1 is None or p2 is None:
            return
        painter.save()
        try:
            mask_color = self._get_active_mask_color() or DEFAULT_MASK_COLOR
            stroke_color = QColor(mask_color)
            pen = QPen(stroke_color)
            pen.setStyle(Qt.PenStyle.DotLine)
            pen.setWidthF(1.0 if self._get_dpr() < 1.5 else 2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(p1, p2).normalized())
        finally:
            painter.restore()

    def _begin_selection(self, panel_point: QPoint) -> bool:
        """Start a selection from one panel point."""
        image_point = self._panel_to_mask_point(panel_point)
        if image_point is None:
            return False
        self.is_selecting_region = True
        self.selection_start_point = image_point
        self.selection_end_point = image_point
        self.signals.repaint_overlay_requested.emit()
        return True

    def _update_selection(self, panel_point: QPoint) -> bool:
        """Move the endpoint of an active selection."""
        if not self.is_selecting_region:
            return False
        image_point = self._panel_to_mask_point(panel_point)
        if image_point is None:
            return False
        self.selection_end_point = image_point
        self.signals.repaint_overlay_requested.emit()
        return True

    def _finish_selection(
        self,
        panel_point: QPoint,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Emit a valid selection rectangle and clear transient state."""
        self.is_selecting_region = False
        self.selection_end_point = self._panel_to_mask_point(panel_point)
        if (
            self.selection_start_point is not None
            and self.selection_end_point is not None
        ):
            x1 = min(self.selection_start_point.x(), self.selection_end_point.x())
            y1 = min(self.selection_start_point.y(), self.selection_end_point.y())
            x2 = max(self.selection_start_point.x(), self.selection_end_point.x())
            y2 = max(self.selection_start_point.y(), self.selection_end_point.y())
            if x2 <= x1 or y2 <= y1:
                logger.debug(
                    "Ignoring smart-select release: zero-area rectangle (start=%s, end=%s)",
                    self.selection_start_point,
                    self.selection_end_point,
                )
            else:
                min_size = self._get_min_selection_size()
                if (x2 - x1) > min_size and (y2 - y1) > min_size:
                    bbox = np.array([x1, y1, x2, y2])
                    self.signals.region_selected_for_masking.emit(
                        bbox,
                        alt_is_active(self._is_alt_held(), modifiers),
                    )
        self._clear_selection()

    def _panel_to_mask_point(self, panel_point: QPoint) -> QPoint | None:
        """Map panel coordinates into the active mask's source space."""
        if self._panel_to_active_mask_point is None:
            return self._panel_to_content_point(panel_point)
        source_point = self._panel_to_active_mask_point(panel_point)
        return None if source_point is None else source_point.toPoint()

    def _clear_selection(self) -> None:
        """Clear transient selection geometry and repaint the overlay."""
        self.is_selecting_region = False
        self.selection_start_point = None
        self.selection_end_point = None
        self.signals.repaint_overlay_requested.emit()


def connect_smart_select_signals(
    manager_signals: ToolManagerSignals, tool: BaseTool
) -> None:
    """Connect SmartSelectTool signals to the ToolManager bus."""
    tool.signals.region_selected_for_masking.connect(
        manager_signals.region_selected_for_masking
    )
    tool.signals.mask_component_adjustment_requested.connect(
        manager_signals.mask_component_adjustment_requested
    )


def disconnect_smart_select_signals(
    manager_signals: ToolManagerSignals, tool: BaseTool
) -> None:
    """Disconnect SmartSelectTool signals with diagnostics."""
    mappings = (
        (
            "region_selected_for_masking",
            tool.signals.region_selected_for_masking,
            manager_signals.region_selected_for_masking,
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
                "Failed to disconnect smart-select signal '%s': %s",
                signal_name,
                exc,
            )


def smart_select_cursor_provider(qpane_instance: CuteCanvas) -> QCursor | None:
    """Provide the smart-select cursor with erase indicator support."""
    return qpane_instance.cursor_builder.create_precision_cursor(
        erase_indicator=qpane_instance.interaction.alt_key_held,
        device_pixel_ratio=qpane_instance.devicePixelRatioF(),
    )
