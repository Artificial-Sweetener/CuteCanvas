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

"""Rendering helpers for mask stroke previews and worker slices."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QImage, QPainter

from ..raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from .stroke_models import MaskStrokeSegmentPayload


def stroke_pen_width(brush_size: float, stride: int = 1) -> int:
    """Return the pen width for a brush diameter respecting preview stride."""
    stride_value = max(1, int(stride))
    brush_value = max(1.0, float(brush_size))
    width = round(float(brush_value) / stride_value)
    return max(1, width)


def stroke_radius(brush_size: float, stride: int = 1) -> float:
    """Return the ellipse radius for a brush diameter respecting preview stride."""
    stride_value = max(1, int(stride))
    brush_value = max(1.0, float(brush_size))
    radius = (float(brush_value) / 2.0) / stride_value
    return max(0.5, radius)


def render_stroke_segments(
    *,
    before: np.ndarray,
    dirty_rect: QRect,
    segments: tuple[MaskStrokeSegmentPayload, ...],
    preview_stride: int = 1,
    constraint: np.ndarray | None = None,
) -> tuple[np.ndarray, QImage]:
    """Return an exact mask slice plus a display-scale stroke preview."""
    working_array = np.array(before, copy=True)
    image = numpy_to_qimage_grayscale8(working_array)
    if segments:
        painter = QPainter(image)
        try:
            origin = dirty_rect.topLeft()
            for segment in segments:
                paint_stroke_segment(painter, origin, segment)
        finally:
            painter.end()
    after_slice = qimage_to_numpy_grayscale8(image)
    if constraint is not None:
        after_slice = apply_coverage_constraint(before, after_slice, constraint)
        image = numpy_to_qimage_grayscale8(after_slice)
    stride = max(1, int(preview_stride))
    if stride == 1:
        return after_slice, image.copy()
    preview_array = np.array(before[::stride, ::stride], copy=True)
    preview_image = numpy_to_qimage_grayscale8(preview_array)
    if segments:
        preview_painter = QPainter(preview_image)
        try:
            origin = dirty_rect.topLeft()
            for segment in segments:
                paint_stroke_segment(
                    preview_painter,
                    origin,
                    segment,
                    stride=stride,
                )
        finally:
            preview_painter.end()
    if constraint is not None:
        preview_constraint = constraint[::stride, ::stride]
        painted_preview = qimage_to_numpy_grayscale8(preview_image)
        preview_array = apply_coverage_constraint(
            preview_array,
            painted_preview,
            preview_constraint,
        )
        preview_image = numpy_to_qimage_grayscale8(preview_array)
    return after_slice, preview_image.copy()


def apply_coverage_constraint(
    before: np.ndarray,
    painted: np.ndarray,
    constraint: np.ndarray,
) -> np.ndarray:
    """Blend a painted result through 8-bit selection coverage exactly once."""
    if before.shape != painted.shape or before.shape != constraint.shape:
        raise ValueError("stroke constraint must match the rendered slice")
    coverage = constraint.astype(np.uint16)
    inverse = 255 - coverage
    blended = (
        before.astype(np.uint16) * inverse + painted.astype(np.uint16) * coverage + 127
    ) // 255
    return blended.astype(np.uint8)


def paint_stroke_segment(
    painter: QPainter,
    origin: QPoint,
    segment: MaskStrokeSegmentPayload,
    *,
    stride: int = 1,
) -> None:
    """Paint a deterministically resampled segment relative to ``origin``."""
    stride_value = max(1, int(stride))
    draw_color = Qt.GlobalColor.black if segment.erase else Qt.GlobalColor.white
    painter.setBrush(QBrush(draw_color))
    painter.setPen(Qt.PenStyle.NoPen)
    for center, diameter in resampled_segment_dabs(segment):
        offset = QPointF(
            (center.x() - origin.x()) / stride_value,
            (center.y() - origin.y()) / stride_value,
        )
        radius = stroke_radius(diameter, stride=stride_value)
        painter.drawEllipse(offset, radius, radius)


def resampled_segment_dabs(
    segment: MaskStrokeSegmentPayload,
) -> tuple[tuple[QPointF, float], ...]:
    """Return stable subpixel dabs that cover a variable-width segment."""
    start = QPointF(float(segment.start[0]), float(segment.start[1]))
    end = QPointF(float(segment.end[0]), float(segment.end[1]))
    delta = end - start
    distance = math.hypot(delta.x(), delta.y())
    minimum_diameter = max(
        1.0,
        min(float(segment.start_diameter), float(segment.end_diameter)),
    )
    spacing = max(0.5, minimum_diameter * 0.2)
    step_count = max(1, math.ceil(distance / spacing))
    return tuple(
        (
            start + delta * (step / step_count),
            float(segment.start_diameter)
            + (float(segment.end_diameter) - float(segment.start_diameter))
            * (step / step_count),
        )
        for step in range(step_count + 1)
    )
