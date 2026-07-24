#    QPane - High-performance PySide6 image viewer
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
"""DPR-stable responsive layout for independent render targets."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSizeF


@dataclass(frozen=True, slots=True)
class ViewTargetSpec:
    """Describe one independently rendered target for responsive layout."""

    target_id: object
    native_size: QSizeF

    def __post_init__(self) -> None:
        """Detach and validate positive native geometry."""
        size = QSizeF(self.native_size)
        if size.width() <= 0.0 or size.height() <= 0.0:
            raise ValueError("native_size dimensions must be positive")
        object.__setattr__(self, "native_size", size)


@dataclass(frozen=True, slots=True)
class ResponsiveGridPolicy:
    """Configure logical grid density and spacing."""

    minimum_cell_width: float = 280.0
    gap: float = 8.0
    maximum_columns: int | None = None

    def __post_init__(self) -> None:
        """Validate physical layout constraints."""
        if self.minimum_cell_width <= 0.0:
            raise ValueError("minimum_cell_width must be positive")
        if self.gap < 0.0:
            raise ValueError("gap must be non-negative")
        if self.maximum_columns is not None and self.maximum_columns <= 0:
            raise ValueError("maximum_columns must be positive or None")


@dataclass(frozen=True, slots=True)
class ViewTargetFrame:
    """Locate one target's cell and aspect-preserving content rectangle."""

    target_id: object
    cell: QRectF
    content: QRectF
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class ResponsiveGridSnapshot:
    """Return one immutable target arrangement with hit-testing helpers."""

    viewport: QRectF
    frames: tuple[ViewTargetFrame, ...]
    rows: int
    columns: int
    device_pixel_ratio: float

    def frame(self, target_id: object) -> ViewTargetFrame | None:
        """Return the frame for one target identity."""
        return next(
            (frame for frame in self.frames if frame.target_id == target_id),
            None,
        )

    def hit_test(self, point: QPointF) -> object | None:
        """Return the topmost target whose cell contains ``point``."""
        return next(
            (
                frame.target_id
                for frame in reversed(self.frames)
                if frame.cell.contains(point)
            ),
            None,
        )

    def visible_target_ids(self, clip: QRectF | None = None) -> tuple[object, ...]:
        """Return target IDs whose cells intersect the visible clip."""
        visible = self.viewport if clip is None else self.viewport.intersected(clip)
        return tuple(
            frame.target_id for frame in self.frames if frame.cell.intersects(visible)
        )

    def prefetch_order(self, clip: QRectF | None = None) -> tuple[object, ...]:
        """Order visible targets by physical distance from the visible center."""
        visible_ids = set(self.visible_target_ids(clip))
        visible = self.viewport if clip is None else self.viewport.intersected(clip)
        center = visible.center()
        return tuple(
            frame.target_id
            for frame in sorted(
                (frame for frame in self.frames if frame.target_id in visible_ids),
                key=lambda frame: (
                    _distance_squared(frame.content.center(), center),
                    frame.row,
                    frame.column,
                ),
            )
        )

    def damage_from(
        self,
        previous: ResponsiveGridSnapshot | None,
    ) -> tuple[QRectF, ...]:
        """Return old/new rectangles whose placement changed."""
        if previous is None:
            return tuple(QRectF(frame.cell) for frame in self.frames)
        previous_by_id = {frame.target_id: frame.cell for frame in previous.frames}
        current_by_id = {frame.target_id: frame.cell for frame in self.frames}
        damage: list[QRectF] = []
        target_ids = tuple(frame.target_id for frame in previous.frames) + tuple(
            frame.target_id
            for frame in self.frames
            if frame.target_id not in previous_by_id
        )
        for target_id in target_ids:
            before = previous_by_id.get(target_id)
            after = current_by_id.get(target_id)
            if before == after:
                continue
            if before is not None:
                damage.append(QRectF(before))
            if after is not None:
                damage.append(QRectF(after))
        return tuple(damage)


class ResponsiveGridLayout:
    """Arrange independent targets on one stable physical-pixel grid."""

    def __init__(self, policy: ResponsiveGridPolicy | None = None) -> None:
        """Store immutable responsive layout policy."""
        self._policy = policy or ResponsiveGridPolicy()

    @property
    def policy(self) -> ResponsiveGridPolicy:
        """Return the current immutable grid policy."""
        return self._policy

    def arrange(
        self,
        viewport: QRectF,
        targets: tuple[ViewTargetSpec, ...],
        *,
        device_pixel_ratio: float = 1.0,
    ) -> ResponsiveGridSnapshot:
        """Arrange targets using physical pixels and return logical geometry."""
        if not isinstance(viewport, QRectF):
            raise TypeError("viewport must be a QRectF")
        if viewport.width() < 0.0 or viewport.height() < 0.0:
            raise ValueError("viewport dimensions must be non-negative")
        dpr = float(device_pixel_ratio)
        if not math.isfinite(dpr) or dpr <= 0.0:
            raise ValueError("device_pixel_ratio must be positive and finite")
        if len({target.target_id for target in targets}) != len(targets):
            raise ValueError("target IDs must be unique")
        if not targets:
            return ResponsiveGridSnapshot(
                QRectF(viewport),
                (),
                0,
                0,
                dpr,
            )

        physical_width = max(0, round(viewport.width() * dpr))
        physical_height = max(0, round(viewport.height() * dpr))
        requested_gap = round(self._policy.gap * dpr)
        minimum_width = max(1, round(self._policy.minimum_cell_width * dpr))
        available_columns = max(
            1,
            (physical_width + requested_gap) // max(1, minimum_width + requested_gap),
        )
        maximum = self._policy.maximum_columns or len(targets)
        columns = min(len(targets), maximum, available_columns)
        rows = math.ceil(len(targets) / columns)
        horizontal_gap = _bounded_gap(requested_gap, physical_width, columns)
        vertical_gap = _bounded_gap(requested_gap, physical_height, rows)
        cell_widths = _partition(
            physical_width - horizontal_gap * (columns - 1),
            columns,
        )
        cell_heights = _partition(
            physical_height - vertical_gap * (rows - 1),
            rows,
        )
        x_offsets = _offsets(cell_widths, horizontal_gap)
        y_offsets = _offsets(cell_heights, vertical_gap)
        frames = tuple(
            _frame(
                target,
                index,
                columns,
                viewport,
                dpr,
                x_offsets,
                y_offsets,
                cell_widths,
                cell_heights,
            )
            for index, target in enumerate(targets)
        )
        return ResponsiveGridSnapshot(
            QRectF(viewport),
            frames,
            rows,
            columns,
            dpr,
        )


def _frame(
    target: ViewTargetSpec,
    index: int,
    columns: int,
    viewport: QRectF,
    dpr: float,
    x_offsets: tuple[int, ...],
    y_offsets: tuple[int, ...],
    widths: tuple[int, ...],
    heights: tuple[int, ...],
) -> ViewTargetFrame:
    """Build one logical frame from an exact physical cell."""
    row, column = divmod(index, columns)
    cell = QRectF(
        viewport.x() + x_offsets[column] / dpr,
        viewport.y() + y_offsets[row] / dpr,
        widths[column] / dpr,
        heights[row] / dpr,
    )
    content = _contain(cell, target.native_size)
    return ViewTargetFrame(target.target_id, cell, content, row, column)


def _partition(total: int, count: int) -> tuple[int, ...]:
    """Partition integer physical pixels without cumulative rounding drift."""
    total = max(0, total)
    base, remainder = divmod(total, count)
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def _bounded_gap(requested: int, extent: int, count: int) -> int:
    """Fit gaps inside the physical extent even for degenerate viewports."""
    if count <= 1:
        return 0
    return min(requested, max(0, extent // (count - 1)))


def _offsets(sizes: tuple[int, ...], gap: int) -> tuple[int, ...]:
    """Return physical leading offsets for partitioned rows or columns."""
    values: list[int] = []
    current = 0
    for size in sizes:
        values.append(current)
        current += size + gap
    return tuple(values)


def _contain(cell: QRectF, native: QSizeF) -> QRectF:
    """Aspect-fit native geometry inside one cell."""
    if cell.isEmpty():
        return QRectF(cell.x(), cell.y(), 0.0, 0.0)
    scale = min(
        cell.width() / native.width(),
        cell.height() / native.height(),
    )
    width = native.width() * scale
    height = native.height() * scale
    return QRectF(
        cell.center().x() - width * 0.5,
        cell.center().y() - height * 0.5,
        width,
        height,
    )


def _distance_squared(first: QPointF, second: QPointF) -> float:
    """Return squared Euclidean distance without an unnecessary square root."""
    dx = first.x() - second.x()
    dy = first.y() - second.y()
    return dx * dx + dy * dy
