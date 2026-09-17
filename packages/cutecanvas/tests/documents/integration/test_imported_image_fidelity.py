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

"""Preserve imported image samples through editable document archives."""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QColorSpace, QImage
from PySide6.QtWidgets import QApplication

from cutecanvas import CuteCanvas


@pytest.mark.parametrize(
    "image_format",
    [QImage.Format.Format_RGBA8888, QImage.Format.Format_RGBA64],
)
def test_imported_image_round_trip_preserves_samples_and_color_space(
    qapp: QApplication, tmp_path: Path, image_format: QImage.Format
) -> None:
    """Save semitransparent and fully transparent authored colors without rounding."""
    image = QImage(256, 2, image_format)
    for alpha in range(256):
        image.setPixelColor(alpha, 0, QColor(255, 0, 128, alpha))
        image.setPixelColor(
            alpha, 1, QColor.fromRgba64(12345, 45678, 23456, alpha * 257)
        )
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
    source = CuteCanvas(features=())
    restored = CuteCanvas(features=())
    try:
        image_id = source.createCompositionFromImage(image)
        archive = tmp_path / "imported.ccanvas"
        source.editor.persistence.save_document(archive)
        restored.editor.persistence.load_document(archive, open_first=False)
        snapshot = restored.captureEmbeddedImageExport(image_id)
        assert snapshot is not None
        assert snapshot.image.format() == image.format()
        assert bytes(snapshot.image.constBits()) == bytes(image.constBits())
        assert snapshot.image.colorSpace() == image.colorSpace()
    finally:
        source.close()
        restored.close()
        source.deleteLater()
        restored.deleteLater()
        qapp.processEvents()
