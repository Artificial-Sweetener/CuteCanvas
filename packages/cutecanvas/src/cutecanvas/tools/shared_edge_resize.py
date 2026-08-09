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

"""Translate pointer input into coupled shared-edge layer resizing."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter
from qpane import PointerPhase, PointerSample, ToolInputProfile

from cutecanvas.editor.shared_edge_pivot import SharedEdgeHandle
from cutecanvas.editor.shared_edge_presentation import SharedEdgePresentation
from cutecanvas.ui.shared_edge import SharedEdgeRenderer
from cutecanvas.ui.transform_cursor import TransformCursorFactory

from .affine_ports import SharedEdgeResizePort
from .base import BaseTool


class SharedEdgeResizeTool(BaseTool):
    """Resize every layer participating in one coincident straight seam."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize inert callbacks and stateless feedback rendering."""
        super().__init__()
        self._renderer = SharedEdgeRenderer()
        self._cursors = TransformCursorFactory()
        self._reset()

    def activate(self, dependencies: SharedEdgeResizePort) -> None:
        """Capture the focused coupled-resize interaction boundary."""
        self._presentation = dependencies.presentation
        self._update_hover = dependencies.update_hover
        self._clear_hover = dependencies.clear_hover
        self._begin = dependencies.begin
        self._update = dependencies.update
        self._finish = dependencies.finish
        self._cancel = dependencies.cancel
        self.signals.repaint_overlay_requested.emit()

    def deactivate(self) -> None:
        """Cancel transient geometry when another tool takes ownership."""
        self._cancel()
        self._reset()
        self.signals.repaint_overlay_requested.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a coupled drag when the primary button presses an eligible seam."""
        if event.button() is not Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._active = self._begin(event.position())
        if self._active:
            event.accept()
            self.signals.repaint_overlay_requested.emit()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update active geometry or inactive seam hover feedback."""
        changed = (
            self._update(event.position())
            if self._active
            else self._update_hover(event.position())
        )
        if changed:
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Atomically commit every layer transform on primary release."""
        if event.button() is not Qt.MouseButton.LeftButton or not self._active:
            event.ignore()
            return
        self._active = False
        self._finish(event.position())
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()
        event.accept()

    def leaveEvent(self, _event: object) -> None:
        """Clear hover feedback when the pointer leaves the viewport."""
        if not self._active and self._clear_hover():
            self.signals.repaint_overlay_requested.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel the complete transient operation with Escape."""
        if event.key() != Qt.Key.Key_Escape:
            event.ignore()
            return
        changed = self._cancel()
        self._active = False
        if changed:
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle normalized touch and tablet samples through the same lifecycle."""
        point = QPointF(sample.position)
        if sample.phase is PointerPhase.BEGIN:
            self._active = self._begin(point)
            return self._active
        if sample.phase is PointerPhase.UPDATE:
            return self._update(point) if self._active else self._update_hover(point)
        if sample.phase is PointerPhase.END and self._active:
            self._active = False
            return self._finish(point)
        if sample.phase is PointerPhase.CANCEL and self._active:
            self._active = False
            return self._cancel()
        return False

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw every participant group and its current shared edge."""
        self._renderer.draw(painter, self._presentation())

    def getCursor(self) -> QCursor | None:
        """Return the native window-resize cursor normal to the focused seam."""
        presentation = self._presentation()
        edge = None if presentation is None else presentation.focused_edge
        if edge is None:
            return QCursor(Qt.CursorShape.ArrowCursor)
        if edge.focused_handle in {SharedEdgeHandle.START, SharedEdgeHandle.END}:
            if not edge.focused_enabled:
                return QCursor(Qt.CursorShape.ForbiddenCursor)
            axis = edge.focused_axis
            if axis is None:
                return QCursor(Qt.CursorShape.ArrowCursor)
            return self._cursors.resize(math.degrees(math.atan2(axis.y(), axis.x())))
        if not edge.focused_enabled:
            return QCursor(Qt.CursorShape.ForbiddenCursor)
        tangent = edge.end - edge.start
        normal_angle = math.atan2(tangent.x(), -tangent.y())
        bucket = round(normal_angle / (math.pi / 4.0)) % 4
        shape = (
            Qt.CursorShape.SizeHorCursor,
            Qt.CursorShape.SizeFDiagCursor,
            Qt.CursorShape.SizeVerCursor,
            Qt.CursorShape.SizeBDiagCursor,
        )[bucket]
        return QCursor(shape)

    def _reset(self) -> None:
        """Restore inert callbacks and local pointer state."""
        self._active = False
        self._presentation: Callable[[], SharedEdgePresentation | None] = lambda: None
        self._update_hover: Callable[[QPointF], bool] = lambda _point: False
        self._clear_hover: Callable[[], bool] = lambda: False
        self._begin: Callable[[QPointF], bool] = lambda _point: False
        self._update: Callable[[QPointF], bool] = lambda _point: False
        self._finish: Callable[[QPointF], bool] = lambda _point: False
        self._cancel: Callable[[], bool] = lambda: False


__all__ = ["SharedEdgeResizeTool"]
