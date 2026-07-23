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
"""Shared deterministic brush compositing for coverage and color targets."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QRadialGradient
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
    qimage_to_numpy_grayscale8,
)

from .compositor import BrushCompositor
from .dab_engine import BrushDabEngine
from .model import BrushDab, BrushOperation, BrushStrokeSegment

_DABS = BrushDabEngine()
_DEFAULT_COMPOSITOR = BrushCompositor()


def render_coverage_stroke(
    *,
    before: np.ndarray,
    dirty_rect: QRect,
    segments: tuple[BrushStrokeSegment, ...],
    preview_stride: int = 1,
    constraint: np.ndarray | None = None,
    compositor: BrushCompositor | None = None,
) -> tuple[np.ndarray, QImage]:
    """Return exact coverage pixels plus a display-scale stroke preview."""
    active_compositor = _DEFAULT_COMPOSITOR if compositor is None else compositor
    if any(segment.texture_strength > 0.0 for segment in segments):
        after = np.array(before, copy=True)
        for segment in segments:
            after = active_compositor.render_coverage_dabs(
                before=after,
                patch_bounds=dirty_rect,
                dabs=_DABS.segment_dabs(segment),
                operation=segment.operation,
            )
        image = numpy_to_qimage_grayscale8(after)
    else:
        image = numpy_to_qimage_grayscale8(np.array(before, copy=True))
        _paint_segments(image, dirty_rect.topLeft(), segments, stride=1)
        after = qimage_to_numpy_grayscale8(image)
    if constraint is not None:
        after = apply_coverage_constraint(before, after, constraint)
        image = numpy_to_qimage_grayscale8(after)
    stride = max(1, int(preview_stride))
    if stride == 1:
        return after, image.copy()
    if any(segment.texture_strength > 0.0 for segment in segments):
        return after, numpy_to_qimage_grayscale8(after[::stride, ::stride])
    preview_before = np.array(before[::stride, ::stride], copy=True)
    preview = numpy_to_qimage_grayscale8(preview_before)
    _paint_segments(preview, dirty_rect.topLeft(), segments, stride=stride)
    if constraint is not None:
        preview_after = apply_coverage_constraint(
            preview_before,
            qimage_to_numpy_grayscale8(preview),
            constraint[::stride, ::stride],
        )
        preview = numpy_to_qimage_grayscale8(preview_after)
    return after, preview.copy()


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


def paint_coverage_segment(
    painter: QPainter,
    origin: QPoint,
    segment: BrushStrokeSegment,
    *,
    stride: int = 1,
) -> None:
    """Paint one segment into grayscale target pixels."""
    stride_value = max(1, int(stride))
    erasing = segment.operation is BrushOperation.ERASE
    painter.setCompositionMode(
        QPainter.CompositionMode_DestinationOut
        if erasing
        else QPainter.CompositionMode_SourceOver
    )
    painter.setPen(Qt.PenStyle.NoPen)
    for dab in _DABS.segment_dabs(segment):
        alpha = max(0, min(255, round(255.0 * dab.opacity)))
        center = QPointF(
            (dab.center[0] - origin.x()) / stride_value,
            (dab.center[1] - origin.y()) / stride_value,
        )
        radius = max(0.5, (dab.diameter / 2.0) / stride_value)
        dab_color = QColor(255, 255, 255, alpha)
        if dab.hardness >= 1.0:
            painter.setBrush(QBrush(dab_color))
        else:
            gradient = QRadialGradient(center, radius)
            gradient.setColorAt(0.0, dab_color)
            gradient.setColorAt(max(0.0, min(1.0, dab.hardness)), dab_color)
            edge = QColor(dab_color)
            edge.setAlpha(0)
            gradient.setColorAt(1.0, edge)
            painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, radius, radius)


def render_color_stroke(
    *,
    before: np.ndarray,
    patch_bounds: QRect,
    segments: tuple[BrushStrokeSegment, ...],
    color: QColor,
    constraint: np.ndarray | None = None,
    compositor: BrushCompositor | None = None,
) -> np.ndarray:
    """Composite shared brush dabs into premultiplied BGRA patch pixels."""
    if before.dtype != np.uint8 or before.shape != (
        patch_bounds.height(),
        patch_bounds.width(),
        4,
    ):
        raise ValueError("color stroke patch must match uint8 BGRA bounds")
    working = np.array(before, copy=True, order="C")
    for segment in segments:
        working = render_color_dabs(
            before=working,
            patch_bounds=patch_bounds,
            dabs=_DABS.segment_dabs(segment),
            operation=segment.operation,
            color=color,
            compositor=compositor,
        )
    if constraint is None:
        return working
    if constraint.shape != before.shape[:2]:
        raise ValueError("color stroke constraint must match patch bounds")
    coverage = constraint.astype(np.uint16)[:, :, np.newaxis]
    inverse = 255 - coverage
    return (
        (
            before.astype(np.uint16) * inverse
            + working.astype(np.uint16) * coverage
            + 127
        )
        // 255
    ).astype(np.uint8)


def render_color_dabs(
    *,
    before: np.ndarray,
    patch_bounds: QRect,
    dabs: tuple[BrushDab, ...],
    operation: BrushOperation,
    color: QColor,
    compositor: BrushCompositor | None = None,
) -> np.ndarray:
    """Composite already-resolved dabs into one premultiplied BGRA patch."""
    if any(dab.texture_strength > 0.0 for dab in dabs):
        active_compositor = _DEFAULT_COMPOSITOR if compositor is None else compositor
        return active_compositor.render_color_dabs(
            before=before,
            patch_bounds=patch_bounds,
            dabs=dabs,
            operation=operation,
            color=color,
        )
    image = numpy_to_qimage_argb32(np.array(before, copy=True, order="C"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        _paint_color_dabs(
            painter,
            patch_bounds.topLeft(),
            dabs,
            operation,
            color,
        )
    finally:
        painter.end()
    return qimage_to_numpy_argb32(image)


def _paint_color_dabs(
    painter: QPainter,
    origin: QPoint,
    dabs: tuple[BrushDab, ...],
    operation: BrushOperation,
    color: QColor,
) -> None:
    """Composite resolved dabs through one color-target operation."""
    erasing = operation is BrushOperation.ERASE
    painter.setCompositionMode(
        QPainter.CompositionMode_DestinationOut
        if erasing
        else QPainter.CompositionMode_SourceOver
    )
    painter.setPen(Qt.PenStyle.NoPen)
    for dab in dabs:
        center = QPointF(dab.center[0] - origin.x(), dab.center[1] - origin.y())
        radius = dab.diameter / 2.0
        alpha = max(0, min(255, round(255.0 * dab.opacity)))
        dab_color = QColor(255, 255, 255, alpha) if erasing else QColor(color)
        if not erasing:
            dab_color.setAlpha(round(dab_color.alpha() * alpha / 255.0))
        if dab.hardness >= 1.0:
            painter.setBrush(QBrush(dab_color))
        else:
            gradient = QRadialGradient(center, radius)
            gradient.setColorAt(0.0, dab_color)
            gradient.setColorAt(max(0.0, min(1.0, dab.hardness)), dab_color)
            edge = QColor(dab_color)
            edge.setAlpha(0)
            gradient.setColorAt(1.0, edge)
            painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, radius, radius)


def _paint_segments(
    image: QImage,
    origin: QPoint,
    segments: tuple[BrushStrokeSegment, ...],
    *,
    stride: int,
) -> None:
    """Paint semantic segments into one target image."""
    if not segments:
        return
    painter = QPainter(image)
    try:
        for segment in segments:
            paint_coverage_segment(painter, origin, segment, stride=stride)
    finally:
        painter.end()
