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
"""Focused QWidget surfaces for built-in multi-target presentations."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QRegion
from PySide6.QtWidgets import QTabWidget, QWidget
from qpane.sdk.layout import (
    ResponsiveGridLayout,
    ResponsiveGridPolicy,
    TargetComparisonLayout,
    ViewTargetSpec,
)
from qpane.sdk.types import ComparisonOrientation

from ..canvas import CuteCanvas


class CanvasTargetMount(QWidget):
    """Keep one heavyweight renderer parented while layouts move its host."""

    def __init__(self, canvas: CuteCanvas, parent: QWidget) -> None:
        """Parent the retained canvas once and fill this lightweight mount."""
        super().__init__(parent)
        self._canvas = canvas
        canvas.setParent(self)
        canvas.setGeometry(self.rect())
        canvas.show()

    @property
    def canvas(self) -> CuteCanvas:
        """Return the retained canvas hosted by this mount."""
        return self._canvas

    def resizeEvent(self, event) -> None:
        """Keep the canvas aligned without reparenting its renderer state."""
        super().resizeEvent(event)
        self._canvas.setGeometry(self.rect())


class TabbedCanvasSurface(QTabWidget):
    """Present independent native-size canvases as host-style inspection tabs."""

    def __init__(
        self,
        entries: tuple[tuple[uuid.UUID, str, CanvasTargetMount], ...],
        activated: Callable[[uuid.UUID], None],
        parent: QWidget,
    ) -> None:
        """Install stable target tabs and activation routing."""
        super().__init__(parent)
        self._target_ids = tuple(entry[0] for entry in entries)
        self._activated = activated
        self.setDocumentMode(True)
        self.setMovable(False)
        for _target_id, title, canvas in entries:
            self.addTab(canvas, title)
        self.currentChanged.connect(self._current_changed)

    def activate(self, target_id: uuid.UUID | None) -> None:
        """Select a target tab without rebuilding its renderer."""
        if target_id in self._target_ids:
            self.setCurrentIndex(self._target_ids.index(target_id))

    def _current_changed(self, index: int) -> None:
        """Publish deliberate tab selection."""
        if 0 <= index < len(self._target_ids):
            self._activated(self._target_ids[index])


class ResponsiveCanvasGrid(QWidget):
    """Arrange canvas widgets through QPane's source-neutral grid geometry."""

    def __init__(
        self,
        entries: tuple[tuple[uuid.UUID, QRectF, CanvasTargetMount], ...],
        parent: QWidget,
        *,
        policy: ResponsiveGridPolicy | None = None,
    ) -> None:
        """Capture target native bounds and reusable child canvases."""
        super().__init__(parent)
        self._entries = entries
        self._layout_owner = ResponsiveGridLayout(policy)
        self._last_snapshot = None
        for _target_id, _bounds, canvas in entries:
            canvas.setParent(self)
            canvas.show()

    def activate(self, _target_id: uuid.UUID | None) -> None:
        """Accept the common presentation-surface activation contract."""

    def resizeEvent(self, event) -> None:
        """Apply stable logical frames derived from physical-pixel partitioning."""
        super().resizeEvent(event)
        targets = tuple(
            ViewTargetSpec(target_id, bounds.size())
            for target_id, bounds, _canvas in self._entries
        )
        snapshot = self._layout_owner.arrange(
            QRectF(self.rect()),
            targets,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        self._last_snapshot = snapshot
        canvases = {target_id: canvas for target_id, _bounds, canvas in self._entries}
        for frame in snapshot.frames:
            canvases[frame.target_id].setGeometry(frame.cell.toAlignedRect())

    def targetAt(self, position: QPointF) -> uuid.UUID | None:
        """Return the composition target under a local panel coordinate."""
        snapshot = self._last_snapshot
        return None if snapshot is None else snapshot.hit_test(position)


class IndependentCanvasComparison(QWidget):
    """Reveal two linked independent canvases across one draggable divider."""

    def __init__(
        self,
        primary: CanvasTargetMount,
        secondary: CanvasTargetMount,
        *,
        split_position: float,
        orientation: ComparisonOrientation,
        split_changed: Callable[[float], None],
        parent: QWidget,
    ) -> None:
        """Install reusable target views and source-neutral divider behavior."""
        super().__init__(parent)
        self._primary = primary
        self._secondary = secondary
        self._split_position = float(split_position)
        self._orientation = ComparisonOrientation(orientation)
        self._split_changed = split_changed
        self._layout_owner = TargetComparisonLayout()
        self._dragging = False
        secondary.setParent(self)
        primary.setParent(self)
        secondary.show()
        primary.show()
        self._overlay = _ComparisonDividerOverlay(self, self)
        self._overlay.show()

    def activate(self, _target_id: uuid.UUID | None) -> None:
        """Accept the common presentation-surface activation contract."""

    def set_split(self, position: float) -> None:
        """Apply a normalized split without recreating either target view."""
        normalized = min(1.0, max(0.0, float(position)))
        if normalized == self._split_position:
            return
        self._split_position = normalized
        self._arrange()

    def resizeEvent(self, event) -> None:
        """Keep both renderers full-size and clip only the reveal surface."""
        super().resizeEvent(event)
        self._arrange()

    def _arrange(self) -> None:
        """Apply one exact physical divider boundary to child widget geometry."""
        viewport = QRectF(self.rect())
        snapshot = self._layout_owner.arrange(
            viewport,
            split_position=self._split_position,
            orientation=self._orientation,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        geometry = self.rect()
        self._primary.setGeometry(geometry)
        self._secondary.setGeometry(geometry)
        self._primary.setMask(QRegion(snapshot.primary_clip.toAlignedRect()))
        overlay_rect = _divider_hit_rect(
            snapshot.divider,
            self._orientation,
            geometry,
        )
        self._overlay.setGeometry(overlay_rect)
        self._overlay.set_divider(
            QLineF(
                snapshot.divider.p1() - QPointF(overlay_rect.topLeft()),
                snapshot.divider.p2() - QPointF(overlay_rect.topLeft()),
            )
        )
        self._overlay.raise_()

    def _position_from_event(self, event: QMouseEvent) -> float:
        """Return normalized divider position for one local pointer event."""
        position = event.position() + QPointF(self._overlay.pos())
        if self._orientation is ComparisonOrientation.VERTICAL:
            return position.x() / max(1.0, float(self.width()))
        return position.y() / max(1.0, float(self.height()))

    def _begin_drag(self, event: QMouseEvent) -> bool:
        """Begin divider drag only near its visible line."""
        del event
        self._dragging = True
        return True

    def _continue_drag(self, event: QMouseEvent) -> None:
        """Update the reveal and session state during direct manipulation."""
        if not self._dragging:
            return
        self.set_split(self._position_from_event(event))
        self._split_changed(self._split_position)

    def _end_drag(self, event: QMouseEvent) -> None:
        """Commit the last divider position and finish capture."""
        if not self._dragging:
            return
        self._continue_drag(event)
        self._dragging = False


class _ComparisonDividerOverlay(QWidget):
    """Draw and interact with a divider above both child renderers."""

    def __init__(
        self,
        owner: IndependentCanvasComparison,
        parent: QWidget,
    ) -> None:
        """Bind the comparison owner while remaining transparent elsewhere."""
        super().__init__(parent)
        self._owner = owner
        self._divider = None
        self.setMouseTracking(True)
        self.setCursor(
            Qt.CursorShape.SplitHCursor
            if owner._orientation is ComparisonOrientation.VERTICAL
            else Qt.CursorShape.SplitVCursor
        )

    def set_divider(self, divider) -> None:
        """Replace line geometry and repaint the lightweight overlay."""
        self._divider = divider
        self.update()

    def paintEvent(self, event) -> None:
        """Draw one restrained divider without obscuring either target."""
        del event
        if self._divider is None:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor(220, 220, 220, 190), 1.0))
        painter.drawLine(self._divider)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Capture a primary-button press near the divider."""
        if event.button() is Qt.MouseButton.LeftButton and self._owner._begin_drag(
            event
        ):
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move an active divider drag."""
        self._owner._continue_drag(event)
        if self._owner._dragging:
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a primary-button divider drag."""
        if event.button() is Qt.MouseButton.LeftButton and self._owner._dragging:
            self._owner._end_drag(event)
            event.accept()
            return
        event.ignore()


def _divider_hit_rect(
    divider: QLineF,
    orientation: ComparisonOrientation,
    bounds: QRect,
) -> QRect:
    """Return a narrow interactive strip around one exact divider."""
    half_width = 8
    if orientation is ComparisonOrientation.VERTICAL:
        center = round(divider.x1())
        return QRect(center - half_width, 0, half_width * 2 + 1, bounds.height())
    center = round(divider.y1())
    return QRect(0, center - half_width, bounds.width(), half_width * 2 + 1)
