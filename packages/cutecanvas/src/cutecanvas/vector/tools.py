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
"""Focused shape and path gestures for semantic vector documents."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF

from qpane import PointerPhase, PointerSample, ToolInputProfile

from ..tools.base import BaseTool
from ..tools.ports import VectorInteractionPort
from .node_tool import VECTOR_NODE_MODE, VectorNodeTool
from .text_tool import VECTOR_TEXT_MODE, VectorTextTool

VECTOR_SHAPE_MODE = "vector-shape"
VECTOR_PATH_MODE = "vector-path"


class VectorShapeTool(BaseTool):
    """Create one parametric shape from a source-local drag rectangle."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize idle source and panel gesture geometry."""
        super().__init__()
        self._reset()

    def activate(self, dependencies: VectorInteractionPort) -> None:
        """Capture the focused vector interaction port."""
        self._port = dependencies

    def deactivate(self) -> None:
        """Discard uncommitted gesture geometry."""
        self._reset()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin shape geometry on a primary press over the active target."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        panel_point = self._port.snapping.begin(
            QPointF(event.position()),
            _snap_suppressed(event.modifiers()),
        )
        source_point = self._port.panel_to_source(panel_point)
        if source_point is None:
            self._port.snapping.clear()
            event.ignore()
            return
        self._begin_panel = panel_point
        self._current_panel = panel_point
        self._begin_source = source_point
        self._current_source = source_point
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update immediate overlay geometry while dragging."""
        if self._begin_source is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            event.ignore()
            return
        self._update(QPointF(event.position()), event.modifiers())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit one shape when a valid primary drag ends."""
        if event.button() != Qt.MouseButton.LeftButton or self._begin_source is None:
            event.ignore()
            return
        self._update(QPointF(event.position()), event.modifiers())
        if self._current_source is not None:
            self._port.commit_shape(self._begin_source, self._current_source)
        self._reset()
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel only transient shape geometry with Escape."""
        if event.key() != Qt.Key.Key_Escape or self._begin_source is None:
            event.ignore()
            return
        self._reset()
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Route touch and tablet contacts through the same shape lifecycle."""
        if sample.phase is PointerPhase.BEGIN:
            panel_point = self._port.snapping.begin(
                sample.position,
                _snap_suppressed(sample.modifiers),
            )
            source_point = self._port.panel_to_source(panel_point)
            if source_point is None:
                self._port.snapping.clear()
                return False
            self._begin_panel = QPointF(panel_point)
            self._current_panel = QPointF(panel_point)
            self._begin_source = QPointF(source_point)
            self._current_source = QPointF(source_point)
            self.signals.repaint_overlay_requested.emit()
            return True
        if sample.phase is PointerPhase.UPDATE and self._begin_source is not None:
            self._update(sample.position, sample.modifiers)
            return True
        if sample.phase is PointerPhase.END and self._begin_source is not None:
            self._update(sample.position, sample.modifiers)
            if self._current_source is not None:
                self._port.commit_shape(self._begin_source, self._current_source)
            self._reset()
            self.signals.repaint_overlay_requested.emit()
            return True
        if sample.phase is PointerPhase.CANCEL and self._begin_source is not None:
            self._reset()
            self.signals.repaint_overlay_requested.emit()
            return True
        return False

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw the immediate panel-space parametric-shape preview."""
        if self._begin_panel is None or self._current_panel is None:
            return
        painter.save()
        try:
            pen = QPen(Qt.GlobalColor.white, 1.0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rectangle = QRectF(self._begin_panel, self._current_panel).normalized()
            if self._port.shape_is_ellipse():
                painter.drawEllipse(rectangle)
            else:
                painter.drawRect(rectangle)
        finally:
            painter.restore()

    def getCursor(self) -> QCursor | None:
        """Return a precise creation cursor."""
        return QCursor(Qt.CursorShape.CrossCursor)

    def _update(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Update panel and mapped source endpoints when projection succeeds."""
        snapped_panel = self._port.snapping.update(
            panel_point,
            _snap_suppressed(modifiers),
            False,
        )
        source_point = self._port.panel_to_source(snapped_panel)
        if source_point is None:
            return
        self._current_panel = QPointF(snapped_panel)
        self._current_source = QPointF(source_point)
        self.signals.repaint_overlay_requested.emit()

    def _reset(self) -> None:
        """Restore inert gesture state and dependencies."""
        if hasattr(self, "_port"):
            self._port.snapping.clear()
        self._port = VectorInteractionPort()
        self._begin_panel: QPointF | None = None
        self._current_panel: QPointF | None = None
        self._begin_source: QPointF | None = None
        self._current_source: QPointF | None = None


class VectorPathTool(BaseTool):
    """Create node-based polyline paths through explicit clicks."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize an empty path gesture."""
        super().__init__()
        self._reset()

    def activate(self, dependencies: VectorInteractionPort) -> None:
        """Capture the focused vector interaction port."""
        self._port = dependencies

    def deactivate(self) -> None:
        """Discard an unresolved path without mutating document state."""
        self._reset()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Append one durable path node on a primary click."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        raw_panel = QPointF(event.position())
        panel_point = (
            self._port.snapping.begin(
                raw_panel,
                _snap_suppressed(event.modifiers()),
            )
            if not self._source_points
            else self._port.snapping.update(
                raw_panel,
                _snap_suppressed(event.modifiers()),
                False,
            )
        )
        source_point = self._port.panel_to_source(panel_point)
        if source_point is None:
            event.ignore()
            return
        self._panel_points.append(panel_point)
        self._source_points.append(source_point)
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update the non-durable next-segment preview."""
        if not self._source_points:
            event.ignore()
            return
        self._hover_panel = self._port.snapping.update(
            QPointF(event.position()),
            _snap_suppressed(event.modifiers()),
            False,
        )
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Commit the current path; Alt closes it before commit."""
        if event.button() != Qt.MouseButton.LeftButton or len(self._source_points) < 2:
            event.ignore()
            return
        self._commit(closed=bool(event.modifiers() & Qt.KeyboardModifier.AltModifier))
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Commit with Enter, close with Alt+Enter, or cancel with Escape."""
        if event.key() == Qt.Key.Key_Escape and self._source_points:
            self._reset()
            self.signals.repaint_overlay_requested.emit()
            event.accept()
            return
        if (
            event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and len(self._source_points) >= 2
        ):
            self._commit(
                closed=bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            )
            event.accept()
            return
        event.ignore()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Add touch/tablet nodes and preserve explicit commit semantics."""
        if sample.phase is PointerPhase.BEGIN:
            panel_point = (
                self._port.snapping.begin(
                    sample.position,
                    _snap_suppressed(sample.modifiers),
                )
                if not self._source_points
                else self._port.snapping.update(
                    sample.position,
                    _snap_suppressed(sample.modifiers),
                    False,
                )
            )
            source_point = self._port.panel_to_source(panel_point)
            if source_point is None:
                return False
            self._panel_points.append(QPointF(panel_point))
            self._source_points.append(QPointF(source_point))
            self.signals.repaint_overlay_requested.emit()
            return True
        if (
            sample.phase in {PointerPhase.UPDATE, PointerPhase.HOVER}
            and self._source_points
        ):
            self._hover_panel = self._port.snapping.update(
                sample.position,
                _snap_suppressed(sample.modifiers),
                False,
            )
            self.signals.repaint_overlay_requested.emit()
            return True
        if sample.phase is PointerPhase.CANCEL and self._source_points:
            self._reset()
            self.signals.repaint_overlay_requested.emit()
            return True
        return sample.phase is PointerPhase.END and bool(self._source_points)

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw immediate path nodes and the prospective next segment."""
        if not self._panel_points:
            return
        points = list(self._panel_points)
        if self._hover_panel is not None:
            points.append(self._hover_panel)
        painter.save()
        try:
            pen = QPen(Qt.GlobalColor.white, 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.GlobalColor.white)
            if len(points) > 1:
                painter.drawPolyline(QPolygonF(points))
            for point in self._panel_points:
                painter.drawEllipse(point, 3.0, 3.0)
        finally:
            painter.restore()

    def getCursor(self) -> QCursor | None:
        """Return a precise path-node cursor."""
        return QCursor(Qt.CursorShape.CrossCursor)

    def _commit(self, *, closed: bool) -> None:
        """Commit exact source nodes and clear transient presentation."""
        self._port.commit_path(tuple(self._source_points), closed)
        self._reset()
        self.signals.repaint_overlay_requested.emit()

    def _reset(self) -> None:
        """Restore inert gesture state and dependencies."""
        if hasattr(self, "_port"):
            self._port.snapping.clear()
        self._port = VectorInteractionPort()
        self._panel_points: list[QPointF] = []
        self._source_points: list[QPointF] = []
        self._hover_panel: QPointF | None = None


def install_vector_tools(register) -> None:
    """Register vector tools without adding domain branches to the tool manager."""
    register(VECTOR_SHAPE_MODE, VectorShapeTool)
    register(VECTOR_PATH_MODE, VectorPathTool)
    register(VECTOR_NODE_MODE, VectorNodeTool)
    register(VECTOR_TEXT_MODE, VectorTextTool)


def _snap_suppressed(modifiers: Qt.KeyboardModifier) -> bool:
    """Return whether the standard temporary snap override is held."""
    return bool(modifiers & Qt.KeyboardModifier.ControlModifier)
