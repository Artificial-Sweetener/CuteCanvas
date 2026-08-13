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

"""Integration proof for CuteCanvas affine raster graph adaptation."""

from __future__ import annotations

from cutecanvas.ferrastra import NativeRasterProjector
from PySide6.QtGui import QColor, QImage
from qpane.sdk.scene import LayerTransform, RasterBounds


def test_identity_projection_preserves_nonzero_coordinate_bounds_and_pixels() -> None:
    """Image storage origin remains independent from authored source coordinates."""
    image = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
    image.setPixelColor(0, 0, QColor(255, 0, 0, 255))
    image.setPixelColor(1, 0, QColor(0, 255, 0, 255))
    image.setPixelColor(0, 1, QColor(0, 0, 255, 255))
    image.setPixelColor(1, 1, QColor(255, 255, 255, 128))
    bounds = RasterBounds(10, -4, 2, 2)

    projected = NativeRasterProjector().project(
        image,
        source_bounds=bounds,
        transform=LayerTransform(),
        destination_bounds=bounds,
    )

    assert projected == image


def test_fractional_affine_projection_uses_transparent_edges_and_mixed_samples() -> (
    None
):
    """Fractional translation produces canonical premultiplied interpolation."""
    image = QImage(2, 1, QImage.Format_ARGB32_Premultiplied)
    image.setPixelColor(0, 0, QColor(255, 0, 0, 255))
    image.setPixelColor(1, 0, QColor(0, 0, 255, 255))

    projected = NativeRasterProjector().project(
        image,
        source_bounds=RasterBounds(0, 0, 2, 1),
        transform=LayerTransform(dx=0.5),
        destination_bounds=RasterBounds(0, 0, 3, 1),
    )

    assert projected.pixelColor(0, 0).alpha() in range(127, 129)
    middle = projected.pixelColor(1, 0)
    assert middle.alpha() == 255
    assert abs(middle.red() - middle.blue()) <= 1
    assert projected.pixelColor(2, 0).alpha() in range(127, 129)
