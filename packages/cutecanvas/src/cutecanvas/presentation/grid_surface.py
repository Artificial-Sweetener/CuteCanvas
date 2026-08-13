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

"""Responsive document-target grid surface backed by QPane layout policy."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from math import ceil
from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QWidget

from qpane.sdk.layout import (
    ResponsiveGridLayout,
    ResponsiveGridPolicy,
    ResponsiveGridSnapshot,
    ViewTargetFrame,
    ViewTargetSpec,
)

from ..canvas import CuteCanvas
from .grid_interaction import GridTargetGestureController
from .grid_viewports import GridViewportController
from .target_mount import CanvasTargetMount


class ResponsiveCanvasGrid(QWidget):
    """Arrange canvas widgets through QPane's source-neutral grid geometry."""

    def __init__(
        self,
        entries: tuple[tuple[uuid.UUID, QRectF, CanvasTargetMount], ...],
        parent: QWidget,
        *,
        policy: ResponsiveGridPolicy | None = None,
        activated: Callable[[uuid.UUID], None],
    ) -> None:
        """Capture target native bounds and reusable child canvases."""
        super().__init__(parent)
        self._entries = entries
        resolved_policy = policy or ResponsiveGridPolicy()
        self._layout_owner = ResponsiveGridLayout(resolved_policy)
        self._minimum_visible_gutter = (
            ceil(resolved_policy.native_tile_minimum_gap)
            if resolved_policy.packing.name == "NATIVE_TILES"
            else 0
        )
        self._last_snapshot: ResponsiveGridSnapshot | None = None
        self._activated = activated
        self._gestures = GridTargetGestureController(
            targets={
                canvas.canvas: target_id for target_id, _bounds, canvas in entries
            },
            activate=activated,
            request_context=self._request_context,
        )
        self._viewports = GridViewportController(
            {target_id: canvas for target_id, _bounds, canvas in entries}
        )
        for _target_id, _bounds, canvas in entries:
            canvas.setParent(self)
            canvas.show()
            canvas.canvas.installEventFilter(self)

    @property
    def snapshot(self) -> ResponsiveGridSnapshot | None:
        """Return the most recently applied immutable target arrangement."""
        return self._last_snapshot

    def activate(self, _target_id: uuid.UUID | None) -> None:
        """Accept the common presentation-surface activation contract."""

    def release(self) -> None:
        """Detach this grid's gesture filters before its retained tiles move."""

        for _target_id, _bounds, canvas in self._entries:
            canvas.canvas.removeEventFilter(self)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Apply stable logical frames derived from physical-pixel partitioning."""
        super().resizeEvent(event)
        self.applyResponsiveGeometry()

    def applyResponsiveGeometry(self) -> None:
        """Apply cell geometry and fitted viewport state after a layout transition."""

        targets = tuple(
            ViewTargetSpec(target_id, bounds.size())
            for target_id, bounds, _canvas in self._entries
        )
        snapshot = self._layout_owner.arrange(
            QRectF(self.rect()),
            targets,
            device_pixel_ratio=self.devicePixelRatioF(),
            previous=self._last_snapshot,
        )
        self._last_snapshot = snapshot
        canvases = {target_id: canvas for target_id, _bounds, canvas in self._entries}
        geometries = _stable_widget_geometries(
            snapshot,
            bounds=self.rect(),
            minimum_visible_gutter=self._minimum_visible_gutter,
        )
        self._viewports.unlock_for_reflow()
        for target_id, geometry in geometries.items():
            canvases[target_id].setGeometry(geometry)
        self._viewports.fit_and_lock(snapshot)

    def targetAt(self, position: QPointF) -> uuid.UUID | None:
        """Return the composition target under a local panel coordinate."""
        snapshot = self._last_snapshot
        if snapshot is None:
            return None
        return next(
            (
                cast(uuid.UUID, frame.target_id)
                for frame in reversed(snapshot.frames)
                if frame.cell.contains(position)
            ),
            None,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Delegate target click, drag, and context arbitration to its owner."""

        return self._gestures.handle_event(watched, event) or super().eventFilter(
            watched,
            event,
        )

    @staticmethod
    def _request_context(watched: QObject, global_position: QPoint) -> None:
        """Publish the clicked target's stable content subject without activation."""

        if not isinstance(watched, CuteCanvas):
            return
        subject = watched.contentSubject()
        if subject is not None:
            watched.contentContextRequested.emit(subject, global_position)


def _stable_widget_geometries(
    snapshot: ResponsiveGridSnapshot,
    *,
    bounds: QRect,
    minimum_visible_gutter: int,
) -> dict[uuid.UUID, QRect]:
    """Build one integer grid from shared tile dimensions and fixed gutters."""

    frames = snapshot.frames
    if not frames:
        return {}
    tile_width = max(1, _nearest_logical_pixel(frames[0].cell.width()))
    tile_height = max(1, _nearest_logical_pixel(frames[0].cell.height()))
    horizontal_gap = _shared_gap(
        frames,
        columns=snapshot.columns,
        vertical=False,
        minimum_visible_gutter=minimum_visible_gutter,
    )
    vertical_gap = _shared_gap(
        frames,
        columns=snapshot.columns,
        vertical=True,
        minimum_visible_gutter=minimum_visible_gutter,
    )
    full_width = (
        snapshot.columns * tile_width + max(0, snapshot.columns - 1) * horizontal_gap
    )
    origin_x = _nearest_logical_pixel(snapshot.viewport.center().x() - full_width * 0.5)
    origin_y = _nearest_logical_pixel(min(frame.cell.top() for frame in frames))
    geometries: dict[uuid.UUID, QRect] = {}
    for frame in frames:
        row_count = min(
            snapshot.columns,
            len(frames) - frame.row * snapshot.columns,
        )
        row_width = row_count * tile_width + max(0, row_count - 1) * horizontal_gap
        row_origin_x = origin_x + (full_width - row_width) // 2
        geometry = QRect(
            row_origin_x + frame.column * (tile_width + horizontal_gap),
            origin_y + frame.row * (tile_height + vertical_gap),
            tile_width,
            tile_height,
        ).intersected(bounds)
        geometries[cast(uuid.UUID, frame.target_id)] = geometry
    return geometries


def _shared_gap(
    frames: tuple[ViewTargetFrame, ...],
    *,
    columns: int,
    vertical: bool,
    minimum_visible_gutter: int,
) -> int:
    """Return one rounded gutter from adjacent frames in a common grid axis."""

    for index, frame in enumerate(frames):
        next_index = index + columns if vertical else index + 1
        if next_index >= len(frames):
            continue
        peer = frames[next_index]
        if vertical:
            if peer.column != frame.column:
                continue
            gap = peer.cell.top() - frame.cell.bottom()
        else:
            if peer.row != frame.row:
                continue
            gap = peer.cell.left() - frame.cell.right()
        visible_gap = _visible_gutter_pixel(gap)
        if not visible_gap:
            return 0
        if minimum_visible_gutter:
            return minimum_visible_gutter
        return visible_gap
    return 0


def _nearest_logical_pixel(value: float) -> int:
    """Resolve one non-negative logical boundary using stable half-up rounding."""

    return int(value + 0.5)


def _visible_gutter_pixel(value: float) -> int:
    """Preserve a nonzero scene gutter when it becomes an integer widget gap."""

    return ceil(max(0.0, value) - 1e-9)
