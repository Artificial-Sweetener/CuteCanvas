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

"""Unit tests for catalog image utility conversions."""

import numpy as np
from PySide6.QtGui import QColor, QImage

from qpane.catalog.image_utils import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_grayscale8,
    qimage_to_numpy_view_grayscale8,
)


def test_numpy_to_qimage_argb32_rejects_non_uint8():
    with np.testing.assert_raises(ValueError):
        numpy_to_qimage_argb32(np.zeros((1, 1, 4), dtype=np.float32))


def test_numpy_to_qimage_argb32_accepts_uint8():
    array = np.zeros((2, 3, 4), dtype=np.uint8)
    image = numpy_to_qimage_argb32(array)
    assert isinstance(image, QImage)
    assert not image.isNull()
    assert image.format() == QImage.Format_ARGB32_Premultiplied


def test_qimage_to_numpy_grayscale8_returns_copy():
    image = QImage(2, 2, QImage.Format_RGB32)
    image.fill(0)
    array = qimage_to_numpy_grayscale8(image)
    assert array.shape == (2, 2)
    assert array.dtype == np.uint8
    array[:, :] = 255
    assert image.pixelColor(0, 0).red() == 0


def test_qimage_to_numpy_view_grayscale8_returns_view():
    image = QImage(2, 2, QImage.Format_Grayscale8)
    image.fill(0)
    array, backing = qimage_to_numpy_view_grayscale8(image)
    assert array.shape == (2, 2)
    assert array.dtype == np.uint8
    assert array.flags.writeable is False
    backing.setPixelColor(1, 1, QColor(200, 200, 200))
    assert array[1, 1] == 200
