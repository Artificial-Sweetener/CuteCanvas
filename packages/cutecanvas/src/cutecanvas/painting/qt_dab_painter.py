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
"""Rasterize ordinary brush dabs through bounded QPainter operations."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QRadialGradient,
    QTransform,
)
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
    qimage_to_numpy_writable_view_grayscale8,
)
from qpane.sdk.scene import LayerTransform

from .dab_engine import BrushDabEngine
from .model import BrushDab, BrushOperation, BrushStrokeSegment

_DABS = BrushDabEngine()
_IDENTITY_TRANSFORM = LayerTransform()


def paint_coverage_segments(
    image: QImage,
    origin: QPoint,
    segments: tuple[BrushStrokeSegment, ...],
    *,
    stride: int,
) -> None:
    """Paint ordered semantic coverage into a grayscale Qt image."""
    pixels, backing = qimage_to_numpy_writable_view_grayscale8(image)
    paint_coverage_pixels(pixels, origin, segments, stride=stride)
    del backing


def paint_coverage_pixels(
    pixels: np.ndarray,
    origin: QPoint,
    segments: tuple[BrushStrokeSegment, ...],
    *,
    stride: int,
) -> None:
    """Paint ordered semantic coverage into writable grayscale pixels."""
    ordered_dabs = tuple(
        (segment.operation, dab)
        for segment in segments
        for dab in _DABS.segment_dabs(segment)
    )
    paint_coverage_dabs_pixels(pixels, origin, ordered_dabs, stride=stride)


def paint_coverage_dabs_pixels(
    pixels: np.ndarray,
    origin: QPoint,
    ordered_dabs: tuple[tuple[BrushOperation, BrushDab], ...],
    *,
    stride: int,
) -> None:
    """Paint pre-resolved ordered coverage dabs into writable grayscale pixels."""
    if pixels.ndim != 2 or pixels.dtype != np.uint8:
        raise ValueError("coverage target must be a writable uint8 2-D array")
    if not pixels.flags.writeable:
        raise ValueError("coverage target must be writable")
    if not ordered_dabs:
        return
    stride = max(1, int(stride))
    if _can_batch_opaque_hard_coverage(ordered_dabs):
        _paint_opaque_hard_coverage_dabs(
            pixels,
            origin,
            ordered_dabs,
            stride=stride,
        )
        return
    image = numpy_to_qimage_grayscale8(pixels)
    painter = QPainter(image)
    try:
        _paint_coverage_dabs(
            painter,
            origin,
            ordered_dabs,
            stride=stride,
        )
    finally:
        painter.end()
    np.copyto(pixels, qimage_to_numpy_grayscale8(image))


def paint_color_dabs(
    image: QImage,
    origin: QPoint,
    dabs: tuple[BrushDab, ...],
    operation: BrushOperation,
    color: QColor,
) -> None:
    """Composite ordered ordinary color dabs into one image."""
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    erasing = operation is BrushOperation.ERASE
    painter.setCompositionMode(
        QPainter.CompositionMode_DestinationOut
        if erasing
        else QPainter.CompositionMode_SourceOver
    )
    painter.setPen(Qt.PenStyle.NoPen)
    try:
        for dab in dabs:
            center = QPointF(dab.center[0] - origin.x(), dab.center[1] - origin.y())
            radius = dab.diameter / 2.0
            alpha = max(0, min(255, round(255.0 * dab.opacity)))
            dab_color = QColor(255, 255, 255, alpha) if erasing else QColor(color)
            if not erasing:
                dab_color.setAlpha(round(dab_color.alpha() * alpha / 255.0))
            nonlinear_path = _nonlinear_dab_path(dab)
            if nonlinear_path is not None and dab.hardness >= 1.0:
                local_to_output = QTransform(
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    -origin.x(),
                    -origin.y(),
                )
                painter.setBrush(QBrush(dab_color))
                painter.drawPath(local_to_output.map(nonlinear_path))
                continue
            painter.save()
            painter.translate(center)
            _concatenate_tip_transform(painter, dab)
            if dab.hardness >= 1.0:
                painter.setBrush(QBrush(dab_color))
            else:
                painter.setBrush(_soft_dab_brush(dab_color, dab.hardness, radius))
            painter.drawEllipse(QPointF(), radius, radius)
            painter.restore()
    finally:
        painter.end()


def _paint_coverage_dabs(
    painter: QPainter,
    origin: QPoint,
    dabs: Iterable[tuple[BrushOperation, BrushDab]],
    *,
    stride: int,
) -> None:
    """Paint ordered coverage dabs that require general Qt composition."""
    for operation, dab in dabs:
        _paint_coverage_dab(painter, origin, operation, dab, stride=stride)


def _paint_opaque_hard_coverage_dabs(
    pixels: np.ndarray,
    origin: QPoint,
    dabs: tuple[tuple[BrushOperation, BrushDab], ...],
    *,
    stride: int,
) -> None:
    """Composite one uniform run through canonical circular pixel coverage."""
    operation = dabs[0][0]
    coverage_value = 0 if operation is BrushOperation.ERASE else 255
    for _operation, dab in dabs:
        center_x = (dab.center[0] - origin.x()) / stride
        center_y = (dab.center[1] - origin.y()) / stride
        radius = max(0.5, (dab.diameter / 2.0) / stride)
        top = max(0, math.floor(center_y - radius - 0.5) + 1)
        bottom = min(pixels.shape[0], math.ceil(center_y + radius - 0.5))
        if top >= bottom:
            continue
        dab_rows = np.arange(top, bottom, dtype=np.intp)
        y_distance = dab_rows.astype(np.float64) + 0.5 - center_y
        radius_squared = radius * radius
        valid = radius_squared - y_distance * y_distance > 0.0
        if not np.any(valid):
            continue
        dab_rows = dab_rows[valid]
        half_width = np.sqrt(radius_squared - y_distance[valid] * y_distance[valid])
        dab_left_edges = np.floor(center_x - half_width - 0.5).astype(np.intp) + 1
        dab_right_edges = np.ceil(center_x + half_width - 0.5).astype(np.intp)
        np.clip(dab_left_edges, 0, pixels.shape[1], out=dab_left_edges)
        np.clip(dab_right_edges, 0, pixels.shape[1], out=dab_right_edges)
        nonempty = dab_left_edges < dab_right_edges
        for row, left, right in zip(
            dab_rows[nonempty],
            dab_left_edges[nonempty],
            dab_right_edges[nonempty],
            strict=True,
        ):
            pixels[row, left:right] = coverage_value


def _can_batch_opaque_hard_coverage(
    dabs: tuple[tuple[BrushOperation, BrushDab], ...],
) -> bool:
    """Return whether one coverage surface preserves the complete dab run."""
    return bool(dabs) and all(
        operation is dabs[0][0] and _stampable_coverage_dab(dab)
        for operation, dab in dabs
    )


def _stampable_coverage_dab(dab: BrushDab) -> bool:
    """Return whether canonical binary circle coverage represents this dab."""
    return (
        round(255.0 * dab.opacity) >= 255
        and dab.hardness >= 1.0
        and dab.tip_mapping is None
        and dab.tip_transform == _IDENTITY_TRANSFORM
    )


def _paint_coverage_dab(
    painter: QPainter,
    origin: QPoint,
    operation: BrushOperation,
    dab: BrushDab,
    *,
    stride: int,
) -> None:
    """Composite one coverage dab whose ordering cannot be collapsed."""
    _set_coverage_operation(painter, operation)
    alpha = max(0, min(255, round(255.0 * dab.opacity)))
    dab_color = QColor(255, 255, 255, alpha)
    nonlinear_path = _nonlinear_dab_path(dab)
    if nonlinear_path is not None and dab.hardness >= 1.0:
        scale = 1.0 / stride
        local_to_output = QTransform(
            scale,
            0.0,
            0.0,
            scale,
            -origin.x() * scale,
            -origin.y() * scale,
        )
        painter.setBrush(QBrush(dab_color))
        painter.drawPath(local_to_output.map(nonlinear_path))
        return
    center = QPointF(
        (dab.center[0] - origin.x()) / stride,
        (dab.center[1] - origin.y()) / stride,
    )
    radius = max(0.5, (dab.diameter / 2.0) / stride)
    painter.save()
    painter.translate(center)
    _concatenate_tip_transform(painter, dab)
    if dab.hardness >= 1.0:
        painter.setBrush(QBrush(dab_color))
    else:
        painter.setBrush(_soft_dab_brush(dab_color, dab.hardness, radius))
    painter.drawEllipse(QPointF(), radius, radius)
    painter.restore()


def _set_coverage_operation(
    painter: QPainter,
    operation: BrushOperation,
) -> None:
    """Apply one mask coverage composition operation."""
    painter.setCompositionMode(
        QPainter.CompositionMode_DestinationOut
        if operation is BrushOperation.ERASE
        else QPainter.CompositionMode_SourceOver
    )
    painter.setPen(Qt.PenStyle.NoPen)


def _soft_dab_brush(color: QColor, hardness: float, radius: float) -> QBrush:
    """Return one radial brush matching the established soft-tip ramp."""
    gradient = QRadialGradient(QPointF(), radius)
    gradient.setColorAt(0.0, color)
    gradient.setColorAt(max(0.0, min(1.0, hardness)), color)
    edge = QColor(color)
    edge.setAlpha(0)
    gradient.setColorAt(1.0, edge)
    return QBrush(gradient)


def _concatenate_tip_transform(painter: QPainter, dab: BrushDab) -> None:
    """Apply one target-local brush-tip affine without moving its center."""
    transform = dab.tip_transform
    painter.setTransform(
        QTransform(
            transform.m11,
            transform.m12,
            transform.m21,
            transform.m22,
            0.0,
            0.0,
        ),
        True,
    )


def _nonlinear_dab_path(dab: BrushDab) -> QPainterPath | None:
    """Return one exact source-local footprint for a scene-circular tip."""
    mapping = dab.tip_mapping
    if mapping is None:
        return None
    local_center = QPointF(float(dab.center[0]), float(dab.center[1]))
    scene_center = mapping.map_point(local_center)
    radius = dab.diameter / 2.0
    scene_path = QPainterPath()
    scene_path.addEllipse(scene_center, radius, radius)
    source_path = mapping.inverse_map_path(scene_path)
    return None if source_path.isEmpty() else source_path


__all__ = [
    "paint_color_dabs",
    "paint_coverage_dabs_pixels",
    "paint_coverage_pixels",
    "paint_coverage_segments",
]
