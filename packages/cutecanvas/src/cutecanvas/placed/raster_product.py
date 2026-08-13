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

"""Construct exact editable raster products from immutable placed images."""

from __future__ import annotations

from cutecanvas.ferrastra import NativeRasterProjector
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from qpane.sdk.execution import CancellationToken
from qpane.sdk.scene import LayerTransform, RasterBounds


def rasterize_placed_image(
    image: QImage,
    target_size: QSize,
    cancellation: CancellationToken,
) -> QImage:
    """Return one cancellable exact native raster at the requested dimensions."""
    if image.isNull():
        raise ValueError("placed rasterization source must not be null")
    if target_size.isEmpty():
        raise ValueError("placed rasterization size must be positive")
    cancellation.raise_if_cancelled()
    source_bounds = RasterBounds(0, 0, image.width(), image.height())
    target_bounds = RasterBounds(0, 0, target_size.width(), target_size.height())
    return NativeRasterProjector().project(
        image,
        source_bounds=source_bounds,
        transform=LayerTransform(
            m11=target_size.width() / image.width(),
            m22=target_size.height() / image.height(),
        ),
        destination_bounds=target_bounds,
        cancellation=cancellation,
    )


__all__ = ["rasterize_placed_image"]
