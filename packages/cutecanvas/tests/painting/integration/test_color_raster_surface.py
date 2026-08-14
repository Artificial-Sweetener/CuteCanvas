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
"""Tests for editable color-raster storage geometry."""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from cutecanvas.raster.color_surface import ColorRasterSurface
from cutecanvas.types import RasterExtentPolicy
from qpane.scene.raster import RasterBounds


def test_content_bounds_follow_nontransparent_alpha_and_local_origin() -> None:
    """Transparent padding must not enlarge a layer transform box."""
    image = QImage(20, 15, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    surface = ColorRasterSurface(image, bounds=RasterBounds(-6, 8, 20, 15))
    assert surface.content_bounds() is None

    changed = surface.mutate_patch(
        RasterBounds(-2, 11, 7, 5),
        lambda pixels: _fill_opaque(pixels),
    )

    assert changed
    assert surface.content_bounds() == RasterBounds(-2, 11, 7, 5)


def test_unbounded_far_writes_do_not_allocate_the_transparent_gap() -> None:
    """Logical extent growth must retain only touched sparse color tiles."""
    image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    surface = ColorRasterSurface(
        image,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    far = RasterBounds(1_000_000, -1_000_000, 8, 8)
    assert surface.ensure_bounds(far)
    pixels = np.full((8, 8, 4), 255, dtype=np.uint8)
    assert surface.restore_patch(far, pixels)

    assert surface.bounds.width > 1_000_000
    assert surface.bounds.height > 1_000_000
    assert surface.allocated_bytes <= 512 * 512 * 4
    np.testing.assert_array_equal(surface.capture_region(far), pixels)
    assert surface.content_bounds() == far


def _fill_opaque(pixels: np.ndarray) -> bool:
    """Fill one premultiplied patch with opaque white pixels."""
    pixels[:, :, :] = 255
    return True
