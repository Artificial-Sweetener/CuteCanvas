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
"""Canonical ordinary coverage rasterization contracts."""

from __future__ import annotations

import numpy as np
import pytest
from cutecanvas.painting import BrushStrokeSegment
from cutecanvas.painting.qt_dab_painter import paint_coverage_segments
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from qpane.sdk.raster import qimage_to_numpy_grayscale8


@pytest.mark.parametrize(("erase", "initial"), ((False, 0), (True, 255)))
def test_opaque_hard_dabs_follow_canonical_pixel_center_coverage(
    erase: bool,
    initial: int,
) -> None:
    """Hard circles cover pixel centers strictly inside their geometric radius."""
    segments = tuple(
        BrushStrokeSegment.fixed(point, point, 2.0, erase)
        for point in ((0.0, 0.0), (2.0, 2.0), (5.5, 2.5))
    )
    image = _coverage_image(initial)

    paint_coverage_segments(image, QPoint(), segments, stride=1)

    expected = np.full((64, 80), initial, dtype=np.uint8)
    changed = 0 if erase else 255
    expected[0, 0] = changed
    expected[1:3, 1:3] = changed
    expected[2, 5] = changed
    assert np.array_equal(qimage_to_numpy_grayscale8(image), expected)


def test_coverage_tip_reuse_preserves_operation_order() -> None:
    """A later erase must remain ordered after an earlier opaque paint run."""
    segments = (
        BrushStrokeSegment.fixed((32.0, 32.0), (32.0, 32.0), 24.0, False),
        BrushStrokeSegment.fixed((32.0, 32.0), (32.0, 32.0), 12.0, True),
    )
    image = _coverage_image(0)

    paint_coverage_segments(image, QPoint(), segments, stride=1)

    pixels = qimage_to_numpy_grayscale8(image)
    assert pixels[32, 32] == 0
    assert pixels[32, 22] == 255


def _coverage_image(fill: int) -> QImage:
    """Return one deterministic grayscale coverage target."""
    image = QImage(80, 64, QImage.Format.Format_Grayscale8)
    image.fill(fill)
    return image
