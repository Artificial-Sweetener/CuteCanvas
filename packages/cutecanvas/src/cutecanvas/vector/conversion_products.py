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
"""Build detached vector conversion products without domain authority."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import Enum

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.execution import CancellationToken
from qpane.sdk.raster import qimage_to_numpy_argb32
from qpane.sdk.scene import LayerPlacement, LayerTransform, RasterBounds
from qpane.sdk.vector import (
    SemanticTextLayoutCache,
    VectorDocument,
    draw_vector_document,
    painted_document_path,
)

from .text_paths import VectorTextPathConversion, build_text_path_conversion

_MAX_OUTPUT_BYTES = 512 * 1024 * 1024


class VectorConversionKind(str, Enum):
    """Identify explicit asynchronous vector conversion operations."""

    PIXEL_SELECTION = "pixel-selection"
    EDITABLE_RASTER = "editable-raster"
    TEXT_PATHS = "text-paths"


@dataclass(frozen=True, slots=True)
class VectorConversionProduct:
    """Carry one detached result from vector conversion work."""

    kind: VectorConversionKind
    raster: QImage | None = None
    coverage: CoverageSnapshot | None = None
    text_paths: VectorTextPathConversion | None = None


class VectorRasterizer:
    """Produce explicit raster derivatives from semantic vector documents."""

    @staticmethod
    def rasterize_local(document: VectorDocument, pixel_size: QSize) -> QImage:
        """Render a document canvas into an explicit premultiplied image."""
        validate_vector_raster_size(pixel_size)
        target = _transparent_image(pixel_size)
        bounds = document.bounds
        local_to_pixels = LayerTransform.from_placement(
            bounds,
            LayerPlacement(
                0.0,
                0.0,
                float(pixel_size.width()),
                float(pixel_size.height()),
            ),
        )
        _draw(
            target,
            document,
            local_to_pixels,
            text_layouts=SemanticTextLayoutCache(0),
        )
        return target

    @staticmethod
    def rasterize_selection(
        document: VectorDocument,
        layer_transform: LayerTransform,
        object_ids: frozenset[uuid.UUID] | None,
    ) -> CoverageSnapshot | None:
        """Render selected semantic object alpha into minimal scene coverage."""
        text_layouts = SemanticTextLayoutCache(0)
        document_path = painted_document_path(document, object_ids, text_layouts)
        scene_path = layer_transform.to_qtransform().map(document_path)
        if scene_path.isEmpty():
            return None
        bounds = _integer_paint_bounds(scene_path.boundingRect())
        validate_vector_raster_size(QSize(bounds.width, bounds.height))
        target = _transparent_image(QSize(bounds.width, bounds.height))
        source_to_target = layer_transform.followed_by(
            LayerTransform(dx=-float(bounds.x), dy=-float(bounds.y))
        )
        _draw(
            target,
            document,
            source_to_target,
            object_ids,
            text_layouts=text_layouts,
        )
        pixels = qimage_to_numpy_argb32(target)
        alpha = np.array(pixels[:, :, 3], copy=True, order="C")
        if not np.any(alpha):
            return None
        occupied_y, occupied_x = np.nonzero(alpha)
        left = int(occupied_x.min())
        top = int(occupied_y.min())
        right = int(occupied_x.max()) + 1
        bottom = int(occupied_y.max()) + 1
        trimmed = np.array(alpha[top:bottom, left:right], copy=True, order="C")
        return CoverageSnapshot(
            RasterBounds(
                bounds.x + left,
                bounds.y + top,
                right - left,
                bottom - top,
            ),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            trimmed,
        )


def build_vector_conversion(
    document: VectorDocument,
    kind: VectorConversionKind,
    cancellation: CancellationToken,
    *,
    pixel_size: QSize | None = None,
    layer_transform: LayerTransform | None = None,
    object_ids: frozenset[uuid.UUID] | None = None,
    text_object_id: uuid.UUID | None = None,
) -> VectorConversionProduct:
    """Build one conversion product while honoring cooperative cancellation."""
    cancellation.raise_if_cancelled()
    if kind is VectorConversionKind.EDITABLE_RASTER:
        if pixel_size is None:
            raise RuntimeError("raster conversion is missing pixel size")
        raster = VectorRasterizer.rasterize_local(document, pixel_size)
        cancellation.raise_if_cancelled()
        return VectorConversionProduct(kind, raster=raster)
    if kind is VectorConversionKind.PIXEL_SELECTION:
        if layer_transform is None:
            raise RuntimeError("selection conversion is missing transform")
        coverage = VectorRasterizer.rasterize_selection(
            document,
            layer_transform,
            object_ids,
        )
        cancellation.raise_if_cancelled()
        return VectorConversionProduct(kind, coverage=coverage)
    if text_object_id is None:
        raise RuntimeError("text conversion is missing an object ID")
    text_paths = build_text_path_conversion(document, text_object_id)
    cancellation.raise_if_cancelled()
    if text_paths is None:
        raise RuntimeError("semantic text produced no painted paths")
    return VectorConversionProduct(kind, text_paths=text_paths)


def validate_vector_raster_size(size: QSize) -> None:
    """Reject empty or unbounded explicit vector raster products."""
    if size.isEmpty():
        raise ValueError("vector raster dimensions must be positive")
    if size.width() * size.height() * 4 > _MAX_OUTPUT_BYTES:
        raise ValueError("vector rasterization exceeds the 512 MiB output limit")


def _draw(
    target: QImage,
    document: VectorDocument,
    source_to_target: LayerTransform,
    object_ids: frozenset[uuid.UUID] | None = None,
    *,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> None:
    """Draw semantic vector content into one initialized target image."""
    painter = QPainter(target)
    if not painter.isActive():
        raise RuntimeError("vector rasterization painter could not be activated")
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setTransform(source_to_target.to_qtransform())
        draw_vector_document(painter, document, object_ids, text_layouts)
    finally:
        painter.end()


def _transparent_image(size: QSize) -> QImage:
    """Allocate one bounded transparent premultiplied raster."""
    target = QImage(size, QImage.Format_ARGB32_Premultiplied)
    if target.isNull():
        raise MemoryError("vector rasterization target could not be allocated")
    target.fill(0)
    return target


def _integer_paint_bounds(bounds: QRectF) -> RasterBounds:
    """Return antialias-safe half-open integer bounds around painted geometry."""
    left = math.floor(bounds.left()) - 1
    top = math.floor(bounds.top()) - 1
    right = math.ceil(bounds.right()) + 1
    bottom = math.ceil(bounds.bottom()) + 1
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))
