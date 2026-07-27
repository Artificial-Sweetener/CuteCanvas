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

"""Wrapped physical rectangles for copy-free retained surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize


@dataclass(frozen=True, slots=True)
class WrappedRectSegment:
    """Pair one logical surface rectangle with its wrapped storage rectangle."""

    logical_rect: QRect
    storage_rect: QRect


def wrapped_rect_segments(
    logical_rect: QRect,
    *,
    surface_size: QSize,
    storage_origin: QPoint,
) -> tuple[WrappedRectSegment, ...]:
    """Split one logical rectangle across a toroidal physical backing store."""
    surface_rect = QRect(QPoint(), surface_size)
    if logical_rect.isEmpty():
        return ()
    if not surface_rect.contains(logical_rect):
        raise ValueError("logical_rect must lie inside the wrapped surface")
    x_segments = _wrapped_axis_segments(
        logical_rect.x(),
        logical_rect.width(),
        storage_origin.x(),
        surface_size.width(),
    )
    y_segments = _wrapped_axis_segments(
        logical_rect.y(),
        logical_rect.height(),
        storage_origin.y(),
        surface_size.height(),
    )
    return tuple(
        WrappedRectSegment(
            logical_rect=QRect(
                logical_x,
                logical_y,
                segment_width,
                segment_height,
            ),
            storage_rect=QRect(
                storage_x,
                storage_y,
                segment_width,
                segment_height,
            ),
        )
        for logical_y, storage_y, segment_height in y_segments
        for logical_x, storage_x, segment_width in x_segments
    )


def _wrapped_axis_segments(
    logical_start: int,
    length: int,
    storage_origin: int,
    extent: int,
) -> tuple[tuple[int, int, int], ...]:
    """Return logical, storage, and length triples for one wrapped axis."""
    if extent <= 0 or length <= 0:
        return ()
    storage_start = (logical_start + storage_origin) % extent
    first_length = min(length, extent - storage_start)
    segments = [(logical_start, storage_start, first_length)]
    remaining = length - first_length
    if remaining:
        segments.append((logical_start + first_length, 0, remaining))
    return tuple(segments)


__all__ = ["WrappedRectSegment", "wrapped_rect_segments"]
