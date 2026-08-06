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
"""Translate affine transform gestures into editor operations."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QLineF, QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPolygonF
from qpane import PointerPhase, PointerSample, ToolInputProfile
from qpane.sdk.scene import (
    TransformHandle,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

from ..ui.transform_box import TransformBoxRenderer
from ..ui.transform_cursor import TransformCursorFactory
from .base import BaseTool
from .ports import TransformInteractionPort

if TYPE_CHECKING:
    from ..editor.transform_interaction import TransformBoxPresentation

_HANDLE_HIT_RADIUS = 8.0
_ROTATION_BAND = 28.0
_SIDE_HANDLES = {
    TransformHandle.TOP,
    TransformHandle.RIGHT,
    TransformHandle.BOTTOM,
    TransformHandle.LEFT,
}


class TransformTool(BaseTool):
    """Translate pointer and keyboard input into one unresolved affine session."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize inert callbacks, renderer, and hover state."""
        super().__init__()
        self._renderer = TransformBoxRenderer()
        self._cursors = TransformCursorFactory()
        self._reset_state()

    def activate(self, dependencies: TransformInteractionPort) -> None:
        """Capture the focused affine interaction boundary."""
        self._presentation = dependencies.transform_presentation
        self._begin = dependencies.begin_transform
        self._update = dependencies.update_transform
        self._end = dependencies.end_transform_gesture
        self._commit = dependencies.commit_transform
        self._cancel = dependencies.cancel_transform
        self._suspend = dependencies.suspend_transform
        self.signals.repaint_overlay_requested.emit()

    def deactivate(self) -> None:
        """Hide controls while preserving any unresolved affine edit."""
        if self._active:
            self._suspend()
        self._reset_state()
        self.signals.repaint_overlay_requested.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin the handle, rotation, or interior operation under the pointer."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        operation = self._operation_at(QPointF(event.position()), event.modifiers())
        if operation is None or not self._begin(operation, QPointF(event.position())):
            event.ignore()
            return
        self._active = True
        self._operation = operation
        self._rotation_angle = self._rotation_tangent_angle(QPointF(event.position()))
        self.signals.cursor_update_requested.emit()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update active affine preview or hover feedback."""
        point = QPointF(event.position())
        if self._active:
            if event.buttons() & Qt.MouseButton.LeftButton and self._update(
                point,
                self._modifiers(event.modifiers()),
            ):
                self.signals.repaint_overlay_requested.emit()
            event.accept()
            return
        operation = self._operation_at(point, event.modifiers())
        rotation_angle = self._rotation_tangent_angle(point)
        handle = None if operation is None else operation.handle
        if (
            operation != self._hover_operation
            or handle != self._hover_handle
            or abs(rotation_angle - self._rotation_angle) >= 1.0
        ):
            self._hover_operation = operation
            self._hover_handle = handle
            self._rotation_angle = rotation_angle
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Release one gesture while retaining cumulative transform state."""
        if event.button() != Qt.MouseButton.LeftButton or not self._active:
            event.ignore()
            return
        self._active = False
        self._end(QPointF(event.position()), self._modifiers(event.modifiers()))
        self._operation = None
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Commit an unresolved transform when the box is double-clicked."""
        state = self._presentation()
        if (
            event.button() != Qt.MouseButton.LeftButton
            or state is None
            or not state.unresolved
            or not QPolygonF(state.corners).containsPoint(
                event.position(),
                Qt.FillRule.WindingFill,
            )
        ):
            event.ignore()
            return
        self._commit_and_repaint()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Resolve cumulative affine state with commit and cancellation keys."""
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self._commit_and_repaint():
                event.accept()
            else:
                event.ignore()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._cancel():
                self.signals.repaint_overlay_requested.emit()
                self.signals.cursor_update_requested.emit()
                event.accept()
            else:
                event.ignore()
            return
        event.ignore()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        """Clear hover state when the pointer leaves the canvas."""
        if self._hover_operation is not None:
            self._hover_operation = None
            self._hover_handle = None
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        event.ignore()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle normalized pen and touch affine sequences."""
        point = QPointF(sample.position)
        if sample.phase is PointerPhase.BEGIN:
            operation = self._operation_at(point, sample.modifiers)
            if operation is None or not self._begin(operation, point):
                return False
            self._active = True
            self._operation = operation
            self.signals.cursor_update_requested.emit()
            return True
        if sample.phase is PointerPhase.UPDATE:
            if not self._active:
                return False
            if self._update(point, self._modifiers(sample.modifiers)):
                self.signals.repaint_overlay_requested.emit()
            return True
        if sample.phase is PointerPhase.END:
            if not self._active:
                return False
            self._active = False
            self._end(point, self._modifiers(sample.modifiers))
            self._operation = None
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            return True
        if sample.phase is PointerPhase.CANCEL and self._active:
            self._active = False
            self._operation = None
            changed = self._suspend()
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            return changed
        return False

    def draw_overlay(self, painter: QPainter) -> None:
        """Delegate transform-box presentation to the stateless UI renderer."""
        self._renderer.draw(painter, self._presentation(), self._hover_handle)

    def getCursor(self) -> QCursor | None:
        """Return an operation-specific transform cursor."""
        operation = self._operation if self._active else self._hover_operation
        if operation is None:
            return QCursor(Qt.CursorShape.ArrowCursor)
        if operation.kind is TransformOperationKind.MOVE:
            return QCursor(Qt.CursorShape.SizeAllCursor)
        if operation.kind is TransformOperationKind.ROTATE:
            return self._cursors.rotate(self._rotation_angle)
        if operation.kind is TransformOperationKind.SKEW:
            return self._cursors.skew(self._handle_tangent_angle(operation.handle))
        return self._cursors.resize(self._handle_axis_angle(operation.handle))

    def _operation_at(
        self,
        point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> TransformOperation | None:
        """Resolve handle, body, or exterior rotation hit priority."""
        state = self._presentation()
        if state is None:
            return None
        for handle, handle_point in state.handles:
            if QLineF(point, handle_point).length() > _HANDLE_HIT_RADIUS:
                continue
            kind = (
                TransformOperationKind.SKEW
                if handle in _SIDE_HANDLES
                and modifiers & Qt.KeyboardModifier.ControlModifier
                and modifiers & Qt.KeyboardModifier.ShiftModifier
                else TransformOperationKind.SCALE
            )
            return TransformOperation(kind, handle)
        polygon = QPolygonF(state.corners)
        if polygon.containsPoint(point, Qt.FillRule.WindingFill):
            return TransformOperation(TransformOperationKind.MOVE)
        if self._distance_to_box(point, state) <= _ROTATION_BAND:
            return TransformOperation(TransformOperationKind.ROTATE)
        return None

    @staticmethod
    def _distance_to_box(point: QPointF, state: TransformBoxPresentation) -> float:
        """Return shortest panel distance from ``point`` to the box perimeter."""
        corners = state.corners
        return min(
            _distance_to_segment(point, corners[index], corners[(index + 1) % 4])
            for index in range(4)
        )

    @staticmethod
    def _modifiers(modifiers: Qt.KeyboardModifier) -> TransformModifiers:
        """Map current keys onto affine constraint flags."""
        return TransformModifiers(
            proportional=not bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            about_center=bool(modifiers & Qt.KeyboardModifier.AltModifier),
            snap_rotation=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
        )

    def _handle_axis_angle(self, handle: TransformHandle | None) -> float:
        """Return the panel-space radial angle for one resize handle."""
        state = self._presentation()
        if state is None or handle is None:
            return 0.0
        point = dict(state.handles).get(handle)
        if point is None:
            return 0.0
        delta = point - state.center
        return math.degrees(math.atan2(delta.y(), delta.x()))

    def _handle_tangent_angle(self, handle: TransformHandle | None) -> float:
        """Return the panel-space side tangent used by a skew gesture."""
        state = self._presentation()
        if state is None or handle is None:
            return 0.0
        points = dict(state.handles)
        if handle in {TransformHandle.TOP, TransformHandle.BOTTOM}:
            start = points.get(TransformHandle.TOP_LEFT)
            end = points.get(TransformHandle.TOP_RIGHT)
        else:
            start = points.get(TransformHandle.TOP_LEFT)
            end = points.get(TransformHandle.BOTTOM_LEFT)
        if start is None or end is None:
            return 0.0
        delta = end - start
        return math.degrees(math.atan2(delta.y(), delta.x()))

    def _rotation_tangent_angle(self, point: QPointF) -> float:
        """Return the tangent of the nearest authoritative frame corner."""
        state = self._presentation()
        if state is None:
            return 0.0
        corner = min(
            state.corners,
            key=lambda candidate: QLineF(point, candidate).length(),
        )
        radial = corner - state.center
        return math.degrees(math.atan2(radial.y(), radial.x())) + 90.0

    def _commit_and_repaint(self) -> bool:
        """Commit unresolved geometry and refresh tool feedback."""
        if not self._commit():
            return False
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()
        return True

    def _reset_state(self) -> None:
        """Restore inert callbacks and local gesture state."""
        self._active = False
        self._operation: TransformOperation | None = None
        self._hover_operation: TransformOperation | None = None
        self._hover_handle: TransformHandle | None = None
        self._rotation_angle = 0.0
        self._presentation: Callable[[], TransformBoxPresentation | None] = lambda: None
        self._begin: Callable[[TransformOperation, QPointF], bool] = (
            lambda _operation, _point: False
        )
        self._update: Callable[[QPointF, TransformModifiers], bool] = (
            lambda _point, _modifiers: False
        )
        self._end: Callable[[QPointF, TransformModifiers], bool] = (
            lambda _point, _modifiers: False
        )
        self._commit: Callable[[], bool] = lambda: False
        self._cancel: Callable[[], bool] = lambda: False
        self._suspend: Callable[[], bool] = lambda: False


def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return Euclidean distance from one point to a finite line segment."""
    segment = end - start
    length_squared = QPointF.dotProduct(segment, segment)
    if length_squared <= 1e-12:
        return QLineF(point, start).length()
    projection = max(
        0.0,
        min(1.0, QPointF.dotProduct(point - start, segment) / length_squared),
    )
    closest = start + segment * projection
    return math.hypot(point.x() - closest.x(), point.y() - closest.y())
