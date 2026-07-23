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
"""Exact sampled evaluation for immutable hybrid coverage documents."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QTransform

from ..raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from ..vector.geometry import object_path
from .model import (
    HybridCombineMode,
    HybridDocument,
    HybridRasterPrimitive,
    HybridVectorPrimitive,
)


class HybridDocumentEvaluator:
    """Sample ordered raster and vector coverage at the requested density."""

    def evaluate(
        self, document: HybridDocument, source_rect: QRectF, size: QSize
    ) -> QImage:
        """Return exact grayscale coverage for one source-local sample."""
        if size.isEmpty() or source_rect.isEmpty():
            return QImage()
        pixels = np.zeros((size.height(), size.width()), dtype=np.uint8)
        primitive_index = 0
        while primitive_index < len(document.primitives):
            primitive = document.primitives[primitive_index]
            if _is_batchable_vector(primitive):
                batch_end = primitive_index + 1
                while batch_end < len(document.primitives) and _is_batchable_vector(
                    document.primitives[batch_end]
                ):
                    batch_end += 1
                incoming = self._vector_batch_pixels(
                    document.primitives[primitive_index:batch_end],
                    source_rect,
                    size,
                )
                pixels = combine_hybrid_coverage(
                    pixels,
                    incoming,
                    HybridCombineMode.ADD,
                )
                primitive_index = batch_end
                continue
            primitive_rect = QRectF(
                primitive.bounds.x,
                primitive.bounds.y,
                primitive.bounds.width,
                primitive.bounds.height,
            )
            overlap = primitive_rect.intersected(source_rect)
            if overlap.isEmpty():
                if primitive.combine_mode in {
                    HybridCombineMode.REPLACE,
                    HybridCombineMode.INTERSECT,
                }:
                    pixels.fill(0)
                primitive_index += 1
                continue
            sample_rect, rows, columns = _sample_region(source_rect, size, overlap)
            sample_size = QSize(columns.stop - columns.start, rows.stop - rows.start)
            incoming = (
                qimage_to_numpy_grayscale8(
                    primitive.sampler.sample(sample_rect, sample_size)
                )
                if isinstance(primitive, HybridRasterPrimitive)
                else self._vector_pixels(primitive, sample_rect, sample_size)
            )
            expected_shape = (sample_size.height(), sample_size.width())
            if incoming.shape != expected_shape:
                raise ValueError("hybrid sampler must return the requested pixel size")
            if primitive.combine_mode in {
                HybridCombineMode.REPLACE,
                HybridCombineMode.INTERSECT,
            }:
                previous = np.array(pixels[rows, columns], copy=True, order="C")
                pixels.fill(0)
            else:
                previous = pixels[rows, columns]
            pixels[rows, columns] = combine_hybrid_coverage(
                previous,
                incoming,
                primitive.combine_mode,
            )
            primitive_index += 1
        return numpy_to_qimage_grayscale8(pixels)

    @staticmethod
    def _vector_batch_pixels(
        primitives: tuple[HybridRasterPrimitive | HybridVectorPrimitive, ...],
        source_rect: QRectF,
        size: QSize,
    ) -> np.ndarray:
        """Rasterize one additive hard-vector run with a single paint device."""
        image = QImage(size, QImage.Format.Format_Grayscale8)
        image.fill(0)
        scale_x = size.width() / source_rect.width()
        scale_y = size.height() / source_rect.height()
        source_transform = QTransform(
            scale_x,
            0.0,
            0.0,
            scale_y,
            -source_rect.x() * scale_x,
            -source_rect.y() * scale_y,
        )
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.white)
            for primitive in primitives:
                if not isinstance(primitive, HybridVectorPrimitive):
                    continue
                primitive_rect = QRectF(
                    primitive.bounds.x,
                    primitive.bounds.y,
                    primitive.bounds.width,
                    primitive.bounds.height,
                )
                if primitive_rect.intersected(source_rect).isEmpty():
                    continue
                painter.setTransform(
                    source_transform * primitive.transform.to_qtransform()
                )
                painter.drawPath(object_path(primitive.geometry))
        finally:
            painter.end()
        return qimage_to_numpy_grayscale8(image)

    @staticmethod
    def _vector_pixels(
        primitive: HybridVectorPrimitive,
        source_rect: QRectF,
        size: QSize,
    ) -> np.ndarray:
        """Rasterize one semantic vector contribution at output density."""
        scale_x = size.width() / source_rect.width()
        scale_y = size.height() / source_rect.height()
        padding_x = math.ceil(primitive.feather_radius * 3.0 * scale_x)
        padding_y = math.ceil(primitive.feather_radius * 3.0 * scale_y)
        image = QImage(
            size.width() + padding_x * 2,
            size.height() + padding_y * 2,
            QImage.Format_Grayscale8,
        )
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.white)
            transform = QTransform(
                scale_x,
                0.0,
                0.0,
                scale_y,
                -source_rect.x() * scale_x + padding_x,
                -source_rect.y() * scale_y + padding_y,
            )
            transform *= primitive.transform.to_qtransform()
            painter.setTransform(transform)
            painter.drawPath(object_path(primitive.geometry))
        finally:
            painter.end()
        pixels = qimage_to_numpy_grayscale8(image)
        if primitive.feather_radius > 0.0:
            pixels = _gaussian_box_blur(
                pixels,
                primitive.feather_radius * max(scale_x, scale_y),
            )
        return np.ascontiguousarray(
            pixels[
                padding_y : padding_y + size.height(),
                padding_x : padding_x + size.width(),
            ]
        )


def _sample_region(
    source_rect: QRectF,
    size: QSize,
    overlap: QRectF,
) -> tuple[QRectF, slice, slice]:
    """Return exact output-aligned sampling geometry for one bounded primitive."""
    scale_x = size.width() / source_rect.width()
    scale_y = size.height() / source_rect.height()
    left = max(0, math.floor((overlap.left() - source_rect.left()) * scale_x))
    top = max(0, math.floor((overlap.top() - source_rect.top()) * scale_y))
    right = min(
        size.width(),
        math.ceil((overlap.right() - source_rect.left()) * scale_x),
    )
    bottom = min(
        size.height(),
        math.ceil((overlap.bottom() - source_rect.top()) * scale_y),
    )
    columns = slice(left, max(left + 1, right))
    rows = slice(top, max(top + 1, bottom))
    return (
        QRectF(
            source_rect.left() + columns.start / scale_x,
            source_rect.top() + rows.start / scale_y,
            (columns.stop - columns.start) / scale_x,
            (rows.stop - rows.start) / scale_y,
        ),
        rows,
        columns,
    )


def _is_batchable_vector(
    primitive: HybridRasterPrimitive | HybridVectorPrimitive,
) -> bool:
    """Return whether one primitive belongs to an additive hard-vector run."""
    return (
        isinstance(primitive, HybridVectorPrimitive)
        and primitive.combine_mode is HybridCombineMode.ADD
        and primitive.feather_radius == 0.0
    )


def combine_hybrid_coverage(
    existing: np.ndarray,
    incoming: np.ndarray,
    mode: HybridCombineMode,
) -> np.ndarray:
    """Combine normalized coverage using exact alpha algebra."""
    destination = np.asarray(existing, dtype=np.uint8)
    source = np.asarray(incoming, dtype=np.uint8)
    if destination.shape != source.shape:
        raise ValueError("coverage arrays must have matching shapes")
    operation = HybridCombineMode(mode)
    if operation is HybridCombineMode.REPLACE:
        return np.array(source, copy=True, order="C")
    destination_wide = destination.astype(np.uint16)
    source_wide = source.astype(np.uint16)
    if operation is HybridCombineMode.ADD:
        combined = source_wide + _multiply(destination_wide, 255 - source_wide)
    elif operation is HybridCombineMode.SUBTRACT:
        combined = _multiply(destination_wide, 255 - source_wide)
    else:
        combined = _multiply(destination_wide, source_wide)
    return np.ascontiguousarray(combined.astype(np.uint8))


def _multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Multiply uint16 coverage with nearest-integer normalization."""
    return (left * right + 127) // 255


def _gaussian_box_blur(pixels: np.ndarray, radius: float) -> np.ndarray:
    """Approximate a Gaussian feather with three bounded box passes."""
    if radius <= 0.0 or pixels.size == 0:
        return pixels
    box_radius = max(1, round(radius * 0.57735))
    result = pixels.astype(np.float32)
    for _ in range(3):
        result = _box_blur_axis(result, box_radius, axis=1)
        result = _box_blur_axis(result, box_radius, axis=0)
    return np.ascontiguousarray(np.clip(np.rint(result), 0, 255).astype(np.uint8))


def _box_blur_axis(pixels: np.ndarray, radius: int, *, axis: int) -> np.ndarray:
    """Apply one zero-padded moving average along ``axis``."""
    padding = [(0, 0), (0, 0)]
    padding[axis] = (radius, radius)
    padded = np.pad(pixels, padding, mode="constant")
    prefix = np.cumsum(padded, axis=axis, dtype=np.float32)
    zero_shape = list(prefix.shape)
    zero_shape[axis] = 1
    prefix = np.concatenate((np.zeros(zero_shape, dtype=np.float32), prefix), axis=axis)
    high = [slice(None), slice(None)]
    low = [slice(None), slice(None)]
    high[axis] = slice(radius * 2 + 1, None)
    low[axis] = slice(None, -(radius * 2 + 1))
    return (prefix[tuple(high)] - prefix[tuple(low)]) / (radius * 2 + 1)
