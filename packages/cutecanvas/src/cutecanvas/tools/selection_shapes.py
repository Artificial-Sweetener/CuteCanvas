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
"""Direct-manipulation tools for geometric pixel selections."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    CoverageItem,
    VectorCoverageItem,
)
from qpane import PointerPhase, PointerSample, ToolInputProfile

from .base import BaseTool
from .coverage_operation import resolve_coverage_operation
from .coverage_preview import draw_clipped_marching_ants
from .cursor_feedback import ToolCursorStyle
from .modifier_snapshot import alt_is_active, shift_is_active
from .ports import PixelSelectionInteractionPort


class SelectionShapeTool(BaseTool):
    """Own the common gesture, modifier, and commit lifecycle for selections."""

    input_profile = ToolInputProfile(touch=True, tablet=True)
    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.PRECISE
    supports_alt_erase_indicator: ClassVar[bool] = True
    supports_snapping: ClassVar[bool] = True

    def __init__(self) -> None:
        """Initialize an idle retained-geometry gesture."""
        super().__init__()
        self._geometry = CoverageGeometryFactory()
        self._reset_dependencies()
        self._begin_panel: QPointF | None = None
        self._current_panel: QPointF | None = None
        self._scene_points: list[QPointF] = []
        self._panel_points: list[QPointF] = []
        self._gesture_combine_mode = CoverageCombineMode.REPLACE
        self._pointer_modifiers = Qt.KeyboardModifier.NoModifier

    def activate(self, dependencies: PixelSelectionInteractionPort) -> None:
        """Capture coordinate and selection collaborators."""
        self._panel_to_scene = dependencies.panel_to_scene_point
        self._can_select = dependencies.can_select
        self._commit = dependencies.commit_coverage_item
        self._is_shift_held = dependencies.is_shift_held
        self._is_alt_held = dependencies.is_alt_held
        self._default_combine_mode = dependencies.default_combine_mode
        self._get_feather_radius = dependencies.get_shape_feather_radius
        self._constrain_item = dependencies.constrain_coverage_item
        self._item_to_panel_path = dependencies.coverage_item_to_panel_path
        self._snapping = dependencies.snapping

    def deactivate(self) -> None:
        """Discard transient geometry and release collaborators."""
        self._clear_gesture()
        self._reset_dependencies()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin selection geometry on a primary-button press."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._begin(QPointF(event.position()), event.modifiers()):
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update live geometry while the primary button remains held."""
        if self._begin_panel is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            event.ignore()
            return
        self._update(QPointF(event.position()), event.modifiers())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit selection geometry on primary-button release."""
        if event.button() != Qt.MouseButton.LeftButton or self._begin_panel is None:
            event.ignore()
            return
        self._finish(QPointF(event.position()), event.modifiers())
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel transient geometry with Escape without clearing durable selection."""
        if event.key() != Qt.Key.Key_Escape or self._begin_panel is None:
            event.ignore()
            return
        self._clear_gesture()
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Route touch and tablet samples through the same gesture lifecycle."""
        if sample.phase is PointerPhase.BEGIN:
            return self._begin(sample.position, sample.modifiers)
        if sample.phase is PointerPhase.UPDATE and self._begin_panel is not None:
            self._update(sample.position, sample.modifiers)
            return True
        if sample.phase is PointerPhase.END and self._begin_panel is not None:
            self._finish(sample.position, sample.modifiers)
            return True
        if sample.phase is PointerPhase.CANCEL and self._begin_panel is not None:
            self._clear_gesture()
            self.signals.repaint_overlay_requested.emit()
            return True
        return False

    def getCursor(self) -> QCursor | None:
        """Defer precise feedback while retaining unavailable-state ownership."""
        if self._can_select():
            return None
        return QCursor(Qt.CursorShape.ForbiddenCursor)

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw transient vector geometry without rasterizing selection coverage."""
        if self._begin_panel is None or self._current_panel is None:
            return
        painter.save()
        pen = QPen(Qt.GlobalColor.white, 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._draw_geometry(painter)
        painter.restore()

    def _begin(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> bool:
        """Start a gesture when panel coordinates map into the active scene."""
        if not self._can_select():
            return False
        snapped_panel = self._snap_begin(panel_point, modifiers)
        scene_point = self._panel_to_scene(snapped_panel)
        if scene_point is None:
            self._snapping.clear()
            return False
        self._begin_panel = QPointF(snapped_panel)
        self._current_panel = QPointF(snapped_panel)
        self._scene_points = [QPointF(scene_point)]
        self._panel_points = [QPointF(snapped_panel)]
        self._pointer_modifiers = modifiers
        self._gesture_combine_mode = self._modifier_combine_mode()
        self.signals.repaint_overlay_requested.emit()
        return True

    def _update(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Append or replace current gesture geometry."""
        snapped_panel = self._snap_update(panel_point, modifiers)
        scene_point = self._panel_to_scene(snapped_panel)
        if scene_point is None:
            return
        self._pointer_modifiers = modifiers
        self._current_panel = QPointF(snapped_panel)
        self._update_panel_points(snapped_panel)
        self._update_scene_points(scene_point)
        self.signals.repaint_overlay_requested.emit()

    def _finish(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Rasterize valid geometry once and commit it to selection state."""
        self._update(panel_point, modifiers)
        item = self._coverage_item()
        if item is not None:
            self._commit(item)
        self._clear_gesture()
        self.signals.repaint_overlay_requested.emit()

    def _combine_mode(self) -> CoverageCombineMode:
        """Return algebra captured when the gesture began."""
        return self._gesture_combine_mode

    def _modifier_combine_mode(self) -> CoverageCombineMode:
        """Translate familiar pre-gesture modifiers into coverage algebra."""
        return resolve_coverage_operation(
            default=self._default_combine_mode,
            alt_held=alt_is_active(
                self._is_alt_held(),
                self._pointer_modifiers,
            ),
            shift_held=shift_is_active(
                self._is_shift_held(),
                self._pointer_modifiers,
            ),
        )

    def _clear_gesture(self) -> None:
        """Discard transient vector state."""
        self._snapping.clear()
        self._begin_panel = None
        self._current_panel = None
        self._scene_points.clear()
        self._panel_points.clear()
        self._pointer_modifiers = Qt.KeyboardModifier.NoModifier

    def _reset_dependencies(self) -> None:
        """Install inert collaborators for safe deactivation."""
        self._panel_to_scene: Callable[[QPointF], QPointF | None] = lambda _point: None
        self._can_select: Callable[[], bool] = lambda: False
        self._commit: Callable[[CoverageItem], bool] = lambda _item: False
        self._is_shift_held: Callable[[], bool] = lambda: False
        self._is_alt_held: Callable[[], bool] = lambda: False
        self._default_combine_mode = CoverageCombineMode.REPLACE
        self._get_feather_radius: Callable[[], float] = lambda: 0.0
        self._constrain_item: Callable[[CoverageItem], CoverageItem | None] = (
            lambda item: item
        )
        self._item_to_panel_path: (
            Callable[[CoverageItem], QPainterPath | None] | None
        ) = None
        self._snapping = PixelSelectionInteractionPort().snapping

    def _snap_begin(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> QPointF:
        """Resolve one geometric anchor when this tool participates in snapping."""
        if not self.supports_snapping:
            return QPointF(panel_point)
        return self._snapping.begin(panel_point, _snap_suppressed(modifiers))

    def _snap_update(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> QPointF:
        """Resolve one geometric endpoint when this tool participates in snapping."""
        if not self.supports_snapping:
            return QPointF(panel_point)
        return self._snapping.update(
            panel_point,
            _snap_suppressed(modifiers),
            shift_is_active(self._is_shift_held(), modifiers),
        )

    def _shape_rectangle(self, points: list[QPointF]) -> QRectF | None:
        """Return current constrained rectangle in the points' coordinate space."""
        return _gesture_rectangle(
            points,
            constrain=shift_is_active(
                self._is_shift_held(),
                self._pointer_modifiers,
            ),
        )

    def _update_scene_points(self, scene_point: QPointF) -> None:
        """Update subclass-specific scene geometry."""
        if len(self._scene_points) == 1:
            self._scene_points.append(QPointF(scene_point))
        else:
            self._scene_points[-1] = QPointF(scene_point)

    def _update_panel_points(self, panel_point: QPointF) -> None:
        """Update the final panel point for two-corner shapes."""
        if len(self._panel_points) == 1:
            self._panel_points.append(QPointF(panel_point))
        else:
            self._panel_points[-1] = QPointF(panel_point)

    def _coverage_item(self) -> CoverageItem | None:
        """Return current geometry constrained by its authoring aperture."""
        item = self._raw_coverage_item()
        return None if item is None else self._constrain_item(item)

    def _raw_coverage_item(self) -> CoverageItem | None:
        """Return unconstrained subclass geometry when it has positive area."""
        raise NotImplementedError

    def _draw_geometry(self, painter: QPainter) -> None:
        """Draw subclass-specific panel geometry."""
        if self._item_to_panel_path is not None:
            item = self._coverage_item()
            if item is not None:
                path = self._item_to_panel_path(item)
                if path is not None:
                    draw_clipped_marching_ants(painter, path)
            return
        self._draw_unconstrained_geometry(painter)

    def _draw_unconstrained_geometry(self, painter: QPainter) -> None:
        """Draw subclass-specific panel geometry without an aperture."""
        raise NotImplementedError


class RectangleSelectionTool(SelectionShapeTool):
    """Create rectangular pixel selections."""

    def _raw_coverage_item(self) -> CoverageItem | None:
        """Retain the current scene rectangle."""
        rectangle = self._shape_rectangle(self._scene_points)
        return (
            None
            if rectangle is None
            else VectorCoverageItem(
                uuid.uuid4(),
                self._geometry.rectangle(rectangle),
                self._combine_mode(),
                feather_radius=self._get_feather_radius(),
            )
        )

    def _draw_unconstrained_geometry(self, painter: QPainter) -> None:
        """Draw the current panel rectangle."""
        rectangle = self._shape_rectangle(self._panel_points)
        if rectangle is not None:
            painter.drawRect(rectangle)


class EllipseSelectionTool(SelectionShapeTool):
    """Create elliptical pixel selections."""

    def _raw_coverage_item(self) -> CoverageItem | None:
        """Retain the current scene ellipse."""
        rectangle = self._shape_rectangle(self._scene_points)
        return (
            None
            if rectangle is None
            else VectorCoverageItem(
                uuid.uuid4(),
                self._geometry.ellipse(rectangle),
                self._combine_mode(),
                feather_radius=self._get_feather_radius(),
            )
        )

    def _draw_unconstrained_geometry(self, painter: QPainter) -> None:
        """Draw the current panel ellipse."""
        rectangle = self._shape_rectangle(self._panel_points)
        if rectangle is not None:
            painter.drawEllipse(rectangle)


class LassoSelectionTool(SelectionShapeTool):
    """Create freeform polygonal pixel selections."""

    supports_snapping: ClassVar[bool] = False

    def _update_scene_points(self, scene_point: QPointF) -> None:
        """Append freeform scene samples while suppressing exact duplicates."""
        if not self._scene_points or scene_point != self._scene_points[-1]:
            self._scene_points.append(QPointF(scene_point))

    def _update_panel_points(self, panel_point: QPointF) -> None:
        """Append freeform panel samples while suppressing duplicates."""
        if not self._panel_points or panel_point != self._panel_points[-1]:
            self._panel_points.append(QPointF(panel_point))

    def _raw_coverage_item(self) -> CoverageItem | None:
        """Retain a lasso with at least three distinct scene points."""
        if len(self._scene_points) < 3:
            return None
        return VectorCoverageItem(
            uuid.uuid4(),
            self._geometry.lasso(self._scene_points),
            self._combine_mode(),
            feather_radius=self._get_feather_radius(),
        )

    def _draw_unconstrained_geometry(self, painter: QPainter) -> None:
        """Draw accumulated freeform panel samples."""
        painter.drawPolyline(QPolygonF(self._panel_points))


def _gesture_rectangle(
    points: list[QPointF],
    *,
    constrain: bool,
) -> QRectF | None:
    """Return a positive corner-anchored rectangle with optional constraint."""
    if len(points) < 2:
        return None
    origin = points[0]
    endpoint = QPointF(points[-1])
    delta = endpoint - origin
    if constrain:
        extent = max(abs(delta.x()), abs(delta.y()))
        endpoint = QPointF(
            origin.x() + (-extent if delta.x() < 0.0 else extent),
            origin.y() + (-extent if delta.y() < 0.0 else extent),
        )
    rectangle = QRectF(origin, endpoint).normalized()
    return None if rectangle.isEmpty() else rectangle


def _snap_suppressed(modifiers: Qt.KeyboardModifier) -> bool:
    """Return whether the standard temporary snap override is held."""
    return bool(modifiers & Qt.KeyboardModifier.ControlModifier)
