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

"""Integration proof for immediate mask preview sampling."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize

from cutecanvas.masks.preview_products import preview_mask_coverage
from qpane.sdk.raster import qimage_to_numpy_grayscale8


def test_coverage_preview_keeps_subpixel_mask_segments_visible() -> None:
    """A covered source sample must survive a much coarser preview lattice."""
    pixels = np.zeros((32, 32), dtype=np.uint8)
    pixels[7, 13] = 255

    preview = preview_mask_coverage(pixels, QSize(4, 4))

    assert qimage_to_numpy_grayscale8(preview).max() == 255
