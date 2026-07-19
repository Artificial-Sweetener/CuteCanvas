#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Qt rendering for editor selection and layer-interaction feedback."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from ..scene.layer_selection import SceneLayerSelection
from ..scene.model import SceneDescriptor
from ..selection import PixelSelectionState, SelectionBoundaryBuilder


class PixelSelectionOverlayRenderer(QObject):
    """Cache and animate marching ants without rebuilding pixel boundaries."""

    def __init__(self, request_update: Callable[[], None], parent: QObject) -> None:
        """Bind repaint scheduling and initialize an idle animation timer."""
        super().__init__(parent)
        self._request_update = request_update
        self._builder = SelectionBoundaryBuilder()
        self._scene_id = None
        self._revision = -1
        self._path = QPainterPath()
        self._path_pixels = None
        self._path_bounds = None
        self._path_translation = QPointF()
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._advance)

    def set_state(self, state: PixelSelectionState | None) -> None:
        """Cache a new boundary and run animation only while it is visible."""
        scene_id = None if state is None else state.scene_id
        revision = -1 if state is None else state.revision
        if scene_id == self._scene_id and revision == self._revision:
            return
        self._scene_id = scene_id
        self._revision = revision
        coverage = None if state is None else state.coverage
        bounds = None if coverage is None else coverage.bounds
        if coverage is None or bounds is None:
            self._path = QPainterPath()
            self._path_pixels = None
            self._path_bounds = None
            self._path_translation = QPointF()
        elif coverage.pixels is self._path_pixels and self._path_bounds is not None:
            self._path_translation = QPointF(
                float(bounds.x - self._path_bounds.x),
                float(bounds.y - self._path_bounds.y),
            )
        else:
            self._path = self._builder.build(coverage)
            self._path_pixels = coverage.pixels
            self._path_bounds = bounds
            self._path_translation = QPointF()
        if self._path.isEmpty():
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()
        self._request_update()

    def draw(self, painter: QPainter, scene_to_panel: QTransform | None) -> None:
        """Draw cached black-and-white alternating dashes in panel space."""
        if scene_to_panel is None or self._path.isEmpty():
            return
        painter.save()
        painter.setTransform(scene_to_panel, combine=True)
        painter.translate(self._path_translation)
        self._draw_dashes(painter, QColor(245, 245, 245), self._phase)
        self._draw_dashes(painter, QColor(25, 25, 25), self._phase + 4)
        painter.restore()

    def _draw_dashes(self, painter: QPainter, color: QColor, offset: int) -> None:
        """Draw one cosmetic half of the marching-ant pattern."""
        pen = QPen(color, 1.0, Qt.PenStyle.CustomDashLine)
        pen.setCosmetic(True)
        pen.setDashPattern([4.0, 4.0])
        pen.setDashOffset(float(offset))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)

    def _advance(self) -> None:
        """Advance dash phase without changing cached geometry."""
        self._phase = (self._phase + 1) % 8
        self._request_update()


class LayerHoverOverlayRenderer:
    """Draw the unobtrusive outside edge of a move-tool hover target."""

    def draw(self, painter: QPainter, corners: Sequence[QPointF]) -> None:
        """Draw a cosmetic perimeter around four panel-space corners."""
        if len(corners) != 4:
            return
        painter.save()
        pen = QPen(QColor(90, 145, 205, 220), 1.0, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF(corners))
        painter.restore()


class EditorOverlayPresenter:
    """Coordinate editor feedback geometry without owning editor state."""

    def __init__(self, request_update: Callable[[], None], parent: QObject) -> None:
        """Create focused selection and hover renderers."""
        self._selection = PixelSelectionOverlayRenderer(request_update, parent)
        self._hover = LayerHoverOverlayRenderer()

    def set_selection(self, state: PixelSelectionState | None) -> None:
        """Refresh cached marching-ant geometry from authoritative state."""
        self._selection.set_state(state)

    def draw(
        self,
        painter: QPainter,
        scene_to_panel: QTransform | None,
        scene: SceneDescriptor | None,
        hovered: SceneLayerSelection | None,
    ) -> None:
        """Draw selection and move-hover feedback in panel coordinates."""
        self._selection.draw(painter, scene_to_panel)
        self._hover.draw(
            painter,
            self._hovered_layer_panel_corners(scene_to_panel, scene, hovered),
        )

    @staticmethod
    def _hovered_layer_panel_corners(
        scene_to_panel: QTransform | None,
        scene: SceneDescriptor | None,
        hovered: SceneLayerSelection | None,
    ) -> tuple[QPointF, ...]:
        """Return panel-space perimeter corners for move-tool hover feedback."""
        if hovered is None or scene is None or scene_to_panel is None:
            return ()
        layer = next(
            (
                candidate
                for candidate in scene.layers
                if candidate.scene_id == hovered.scene_id
                and candidate.layer_id == hovered.layer_id
            ),
            None,
        )
        if layer is None:
            return ()
        placement = layer.placement
        return tuple(
            scene_to_panel.map(point)
            for point in (
                QPointF(placement.x, placement.y),
                QPointF(placement.x + placement.width, placement.y),
                QPointF(
                    placement.x + placement.width,
                    placement.y + placement.height,
                ),
                QPointF(placement.x, placement.y + placement.height),
            )
        )
