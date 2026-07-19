#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Direct-manipulation tools for geometric pixel selections."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF

from ..coverage import CoverageCombineMode, CoverageSnapshot
from ..selection import SelectionGeometryRasterizer
from .base import BaseTool
from .dependencies import ToolDependencies
from .input.model import PointerPhase, PointerSample
from .input.profile import ToolInputProfile


class SelectionShapeTool(BaseTool):
    """Own the common gesture, modifier, and commit lifecycle for selections."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize an idle gesture and shared geometry rasterizer."""
        super().__init__()
        self._rasterizer = SelectionGeometryRasterizer()
        self._reset_dependencies()
        self._begin_panel: QPointF | None = None
        self._current_panel: QPointF | None = None
        self._scene_points: list[QPointF] = []
        self._panel_points: list[QPointF] = []

    def activate(self, dependencies: ToolDependencies) -> None:
        """Capture coordinate and selection collaborators."""
        self._panel_to_scene = dependencies.get(
            "panel_to_scene_point", lambda _point: None
        )
        self._commit = dependencies.get(
            "commit_pixel_selection", lambda _coverage, _mode: False
        )
        self._is_shift_held = dependencies.get("is_shift_held", lambda: False)
        self._is_alt_held = dependencies.get("is_alt_held", lambda: False)

    def deactivate(self) -> None:
        """Discard transient geometry and release collaborators."""
        self._clear_gesture()
        self._reset_dependencies()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin selection geometry on a primary-button press."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._begin(QPointF(event.position())):
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
        self._update(QPointF(event.position()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit selection geometry on primary-button release."""
        if event.button() != Qt.MouseButton.LeftButton or self._begin_panel is None:
            event.ignore()
            return
        self._finish(QPointF(event.position()))
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
            return self._begin(sample.position)
        if sample.phase is PointerPhase.UPDATE and self._begin_panel is not None:
            self._update(sample.position)
            return True
        if sample.phase is PointerPhase.END and self._begin_panel is not None:
            self._finish(sample.position)
            return True
        if sample.phase is PointerPhase.CANCEL and self._begin_panel is not None:
            self._clear_gesture()
            self.signals.repaint_overlay_requested.emit()
            return True
        return False

    def getCursor(self) -> QCursor | None:
        """Return the standard precise-selection crosshair."""
        return QCursor(Qt.CursorShape.CrossCursor)

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

    def _begin(self, panel_point: QPointF) -> bool:
        """Start a gesture when panel coordinates map into the active scene."""
        scene_point = self._panel_to_scene(panel_point)
        if scene_point is None:
            return False
        self._begin_panel = QPointF(panel_point)
        self._current_panel = QPointF(panel_point)
        self._scene_points = [QPointF(scene_point)]
        self._panel_points = [QPointF(panel_point)]
        self.signals.repaint_overlay_requested.emit()
        return True

    def _update(self, panel_point: QPointF) -> None:
        """Append or replace current gesture geometry."""
        scene_point = self._panel_to_scene(panel_point)
        if scene_point is None:
            return
        self._current_panel = QPointF(panel_point)
        self._update_panel_points(panel_point)
        self._update_scene_points(scene_point)
        self.signals.repaint_overlay_requested.emit()

    def _finish(self, panel_point: QPointF) -> None:
        """Rasterize valid geometry once and commit it to selection state."""
        self._update(panel_point)
        snapshot = self._coverage_snapshot()
        if snapshot is not None:
            self._commit(snapshot, self._combine_mode())
        self._clear_gesture()
        self.signals.repaint_overlay_requested.emit()

    def _combine_mode(self) -> CoverageCombineMode:
        """Translate familiar selection modifiers into coverage algebra."""
        shift = self._is_shift_held()
        alt = self._is_alt_held()
        if shift and alt:
            return CoverageCombineMode.INTERSECT
        if shift:
            return CoverageCombineMode.ADD
        if alt:
            return CoverageCombineMode.SUBTRACT
        return CoverageCombineMode.REPLACE

    def _clear_gesture(self) -> None:
        """Discard transient vector state."""
        self._begin_panel = None
        self._current_panel = None
        self._scene_points.clear()
        self._panel_points.clear()

    def _reset_dependencies(self) -> None:
        """Install inert collaborators for safe deactivation."""
        self._panel_to_scene: Callable[[QPointF], QPointF | None] = lambda _point: None
        self._commit: Callable[[CoverageSnapshot, CoverageCombineMode], bool] = (
            lambda _coverage, _mode: False
        )
        self._is_shift_held: Callable[[], bool] = lambda: False
        self._is_alt_held: Callable[[], bool] = lambda: False

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

    def _coverage_snapshot(self) -> CoverageSnapshot | None:
        """Return rasterized subclass geometry when it has positive area."""
        raise NotImplementedError

    def _draw_geometry(self, painter: QPainter) -> None:
        """Draw subclass-specific panel geometry."""
        raise NotImplementedError


class RectangleSelectionTool(SelectionShapeTool):
    """Create rectangular pixel selections."""

    def _coverage_snapshot(self) -> CoverageSnapshot | None:
        """Rasterize the current scene rectangle."""
        rectangle = _point_rectangle(self._scene_points)
        return None if rectangle is None else self._rasterizer.rectangle(rectangle)

    def _draw_geometry(self, painter: QPainter) -> None:
        """Draw the current panel rectangle."""
        painter.drawRect(QRectF(self._begin_panel, self._current_panel).normalized())


class EllipseSelectionTool(SelectionShapeTool):
    """Create elliptical pixel selections."""

    def _coverage_snapshot(self) -> CoverageSnapshot | None:
        """Rasterize the current scene ellipse."""
        rectangle = _point_rectangle(self._scene_points)
        return None if rectangle is None else self._rasterizer.ellipse(rectangle)

    def _draw_geometry(self, painter: QPainter) -> None:
        """Draw the current panel ellipse."""
        painter.drawEllipse(QRectF(self._begin_panel, self._current_panel).normalized())


class LassoSelectionTool(SelectionShapeTool):
    """Create freeform polygonal pixel selections."""

    def _update_scene_points(self, scene_point: QPointF) -> None:
        """Append freeform scene samples while suppressing exact duplicates."""
        if not self._scene_points or scene_point != self._scene_points[-1]:
            self._scene_points.append(QPointF(scene_point))

    def _update_panel_points(self, panel_point: QPointF) -> None:
        """Append freeform panel samples while suppressing duplicates."""
        if not self._panel_points or panel_point != self._panel_points[-1]:
            self._panel_points.append(QPointF(panel_point))

    def _coverage_snapshot(self) -> CoverageSnapshot | None:
        """Rasterize a lasso with at least three distinct scene points."""
        if len(self._scene_points) < 3:
            return None
        return self._rasterizer.lasso(self._scene_points)

    def _draw_geometry(self, painter: QPainter) -> None:
        """Draw accumulated freeform panel samples."""
        painter.drawPolyline(QPolygonF(self._panel_points))


def _point_rectangle(points: list[QPointF]) -> QRectF | None:
    """Return a positive-area rectangle from the first and final point."""
    if len(points) < 2:
        return None
    rectangle = QRectF(points[0], points[-1]).normalized()
    return None if rectangle.isEmpty() else rectangle
