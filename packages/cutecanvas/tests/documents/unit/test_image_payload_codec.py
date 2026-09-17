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

"""Validate lossless image layout, padding, and malformed archive boundaries."""

import io
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage

from cutecanvas.persistence.image_payload_codec import (
    image_manifest,
    read_image,
    write_image,
)


def test_odd_width_image_retains_samples_without_scanline_padding() -> None:
    """Persist three-byte RGB rows without disclosing or restoring padding bytes."""
    image = QImage(3, 2, QImage.Format.Format_RGB888)
    image.fill(QColor(21, 45, 78))
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        write_image(archive, "pixels.npy", image)
    with zipfile.ZipFile(data) as archive:
        restored = read_image(archive, "pixels.npy", 3, 2, image_manifest(image))
    assert restored.format() == image.format()
    for y in range(2):
        for x in range(3):
            assert restored.pixelColor(x, y) == image.pixelColor(x, y)


def test_untagged_premultiplied_image_keeps_its_color_interpretation() -> None:
    """Preserve absent color-space metadata as well as existing premultiplied samples."""
    image = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 0, 128, 128))
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        write_image(archive, "pixels.npy", image)
    with zipfile.ZipFile(data) as archive:
        restored = read_image(archive, "pixels.npy", 6, 5, image_manifest(image))
    assert restored == image


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("format", "Format_Invalid"),
        ("format", "unknown"),
        ("byte_order", "unknown"),
        ("color_table", [-1]),
        ("icc_profile", "not base64"),
    ],
)
def test_invalid_image_description_is_rejected(key: str, value: object) -> None:
    """Reject malformed pixel interpretation instead of publishing a partial image."""
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.fill(QColor(255, 0, 128, 128))
    metadata = image_manifest(image)
    metadata[key] = value
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        write_image(archive, "pixels.npy", image)
    with zipfile.ZipFile(data) as archive, pytest.raises(ValueError):
        read_image(archive, "pixels.npy", 2, 2, metadata)


def test_payload_shape_must_match_declared_dimensions() -> None:
    """Reject dimension drift before attaching a decoded image to the document."""
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.fill(0)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        write_image(archive, "pixels.npy", image)
    with zipfile.ZipFile(data) as archive, pytest.raises(ValueError, match="layout"):
        read_image(archive, "pixels.npy", 3, 2, image_manifest(image))
