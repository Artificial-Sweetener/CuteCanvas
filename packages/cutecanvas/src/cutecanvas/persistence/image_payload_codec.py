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

"""Preserve Qt image samples and color interpretation without raster conversion."""

from __future__ import annotations

import base64
import sys
import zipfile

import numpy as np
from PySide6.QtGui import QColorSpace, QImage


def image_manifest(image: QImage) -> dict[str, object]:
    """Describe the native sample layout and color interpretation explicitly."""
    return {
        "format": image.format().name,
        "byte_order": sys.byteorder,
        "color_table": image.colorTable(),
        "icc_profile": base64.b64encode(image.colorSpace().iccProfile().data()).decode(
            "ascii"
        ),
    }


def write_image(container: zipfile.ZipFile, path: str, image: QImage) -> None:
    """Write sample bytes only, excluding uninitialized scanline padding."""
    row_bytes = (image.width() * image.depth() + 7) // 8
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine()
    )
    with container.open(path, "w") as stream:
        np.save(stream, np.ascontiguousarray(pixels[:, :row_bytes]), allow_pickle=False)


def read_image(
    container: zipfile.ZipFile,
    path: str,
    width: int,
    height: int,
    metadata: object,
) -> QImage:
    """Validate the stored representation before allocating or publishing an image."""
    if not isinstance(metadata, dict):
        raise TypeError("placed image encoding must be an object")
    if metadata.get("byte_order") != sys.byteorder:
        raise ValueError("placed image byte order is unsupported on this host")
    format_name = metadata.get("format")
    if not isinstance(format_name, str):
        raise TypeError("placed image format must be named")
    image_format = QImage.Format.__members__.get(format_name)
    if image_format is None or image_format is QImage.Format.Format_Invalid:
        raise ValueError("placed image format is unsupported")
    depth = QImage(1, 1, image_format).depth()
    row_bytes = (width * depth + 7) // 8
    if width <= 0 or height <= 0 or row_bytes * height > 1_073_741_824:
        raise ValueError("placed image sample payload exceeds archive limits")
    table = metadata.get("color_table")
    if (
        not isinstance(table, list)
        or len(table) > 256
        or any(
            type(color) is not int or not 0 <= color <= 0xFFFFFFFF for color in table
        )
    ):
        raise ValueError("placed image color table is invalid")
    profile = metadata.get("icc_profile")
    if not isinstance(profile, str) or len(profile) > 4_194_304:
        raise ValueError("placed image color profile is invalid")
    profile_bytes = base64.b64decode(profile, validate=True)
    color_space = QColorSpace.fromIccProfile(profile_bytes)
    if profile_bytes and not color_space.isValid():
        raise ValueError("placed image color profile is unsupported")
    with container.open(path) as stream:
        pixels = np.load(stream, allow_pickle=False)
    if pixels.dtype != np.uint8 or pixels.shape != (height, row_bytes):
        raise ValueError("placed image samples do not match their declared layout")
    image = QImage(width, height, image_format)
    if image.isNull():
        raise ValueError("placed image allocation failed")
    image.fill(0)
    target = np.frombuffer(image.bits(), dtype=np.uint8).reshape(
        height, image.bytesPerLine()
    )
    target[:, :row_bytes] = pixels
    image.setColorTable(table)
    if profile_bytes:
        image.setColorSpace(color_space)
    return image
