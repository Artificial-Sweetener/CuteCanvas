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
"""Mask image loading and normalization."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap


class MaskImageLoader:
    """Load grayscale mask pixels from host-provided image files."""

    @staticmethod
    def load(path: str, target_size: QSize) -> QImage | None:
        """Load and aspect-fit one file into grayscale mask pixels."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        if pixmap.size() != target_size:
            pixmap = pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio)
        image = pixmap.toImage()
        if image.format() != QImage.Format_Grayscale8:
            image = image.convertToFormat(QImage.Format_Grayscale8)
        return image
