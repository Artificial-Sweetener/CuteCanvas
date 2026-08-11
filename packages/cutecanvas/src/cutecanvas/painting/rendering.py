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
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
)

from .compositor import BrushCompositor
from .dab_engine import BrushDabEngine
from .model import BrushDab, BrushOperation, BrushStrokeSegment
from .qt_dab_painter import paint_color_dabs, paint_coverage_dabs_pixels

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
    projected_tips = any(
        segment.texture_strength > 0.0 or segment.tip_mapping is not None
        for segment in segments
    )
    if projected_tips:
        after = np.array(before, copy=True)
        for segment in segments:
            after = active_compositor.render_coverage_dabs(
                before=after,
                patch_bounds=dirty_rect,
                dabs=_DABS.segment_dabs(segment),
                operation=segment.operation,
            )
    else:
        ordered_dabs = tuple(
            (segment.operation, dab)
            for segment in segments
            for dab in _DABS.segment_dabs(segment)
        )
        after = np.array(before, copy=True)
        paint_coverage_dabs_pixels(
            after,
            dirty_rect.topLeft(),
            ordered_dabs,
            stride=1,
        )
    if constraint is not None:
        after = apply_coverage_constraint(before, after, constraint)
    image = numpy_to_qimage_grayscale8(after)
    stride = max(1, int(preview_stride))
    if stride == 1:
        return after, image
    if projected_tips:
        return after, numpy_to_qimage_grayscale8(after[::stride, ::stride])
    preview_before = np.array(before[::stride, ::stride], copy=True)
    preview_after = np.array(preview_before, copy=True)
    paint_coverage_dabs_pixels(
        preview_after,
        dirty_rect.topLeft(),
        ordered_dabs,
        stride=stride,
    )
    if constraint is not None:
        preview_after = apply_coverage_constraint(
            preview_before,
            preview_after,
            constraint[::stride, ::stride],
        )
    return after, numpy_to_qimage_grayscale8(preview_after)


def apply_coverage_constraint(
    before: np.ndarray,
    painted: np.ndarray,
    constraint: np.ndarray,
) -> np.ndarray:
    """Blend a painted result through 8-bit selection coverage exactly once."""
    if before.shape != painted.shape or before.shape != constraint.shape:
        raise ValueError("stroke constraint must match the rendered slice")
    if np.all(constraint == 255):
        return painted
    if not np.any(constraint):
        return np.array(before, copy=True)
    coverage = constraint.astype(np.uint16)
    inverse = 255 - coverage
    blended = (
        before.astype(np.uint16) * inverse + painted.astype(np.uint16) * coverage + 127
    ) // 255
    return blended.astype(np.uint8)


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
    if any(dab.texture_strength > 0.0 or dab.tip_mapping is not None for dab in dabs):
        active_compositor = _DEFAULT_COMPOSITOR if compositor is None else compositor
        return active_compositor.render_color_dabs(
            before=before,
            patch_bounds=patch_bounds,
            dabs=dabs,
            operation=operation,
            color=color,
        )
    image = numpy_to_qimage_argb32(np.array(before, copy=True, order="C"))
    paint_color_dabs(image, patch_bounds.topLeft(), dabs, operation, color)
    return qimage_to_numpy_argb32(image)
