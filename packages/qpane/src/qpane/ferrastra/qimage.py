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

"""Translate detached QImage storage to and from canonical RGBA8 products."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QImage


@dataclass(frozen=True)
class Rgba8Image:
    """Describe one detached premultiplied encoded RGBA8 buffer."""

    pixels: bytes
    width: int
    height: int
    stride_bytes: int


def qimage_to_rgba8(image: QImage) -> Rgba8Image:
    """Copy one non-null QImage into byte-ordered premultiplied RGBA8 storage."""
    if image.isNull():
        raise ValueError("image must not be null")
    converted = image.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
    return Rgba8Image(
        pixels=bytes(converted.constBits()),
        width=converted.width(),
        height=converted.height(),
        stride_bytes=converted.bytesPerLine(),
    )


def qimage_from_rgba8(
    pixels: bytes,
    width: int,
    height: int,
    stride_bytes: int,
) -> QImage:
    """Copy canonical RGBA8 storage into QPane's detached presentation format."""
    if width <= 0 or height <= 0 or stride_bytes < width * 4:
        raise ValueError("RGBA8 image layout is invalid")
    required = (height - 1) * stride_bytes + width * 4
    if len(pixels) < required:
        raise ValueError("RGBA8 image buffer is shorter than its layout")
    borrowed = QImage(
        pixels,
        width,
        height,
        stride_bytes,
        QImage.Format_RGBA8888_Premultiplied,
    )
    if borrowed.isNull():
        raise ValueError("RGBA8 image layout could not be represented")
    return borrowed.convertToFormat(QImage.Format_ARGB32_Premultiplied).copy()


__all__ = ["Rgba8Image", "qimage_from_rgba8", "qimage_to_rgba8"]
