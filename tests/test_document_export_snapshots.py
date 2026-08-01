#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Prove detached raster-backed document products for external operations."""

from __future__ import annotations

import uuid

from cutecanvas import CanvasDocument, CuteCanvas
from PySide6.QtGui import QColor, QImage


def _image(color: str = "royalblue") -> QImage:
    """Return one stable embedded image fixture."""

    image = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_image_and_mask_exports_are_detached_and_revision_addressed(qapp) -> None:
    """Later document changes cannot mutate already captured external products."""

    canvas = CuteCanvas(features=("mask",))
    try:
        composition_id = canvas.createCompositionFromImage(_image())
        mask_id = canvas.createBlankMask(_image().size())
        assert mask_id is not None
        mask = QImage(_image().size(), QImage.Format.Format_Grayscale8)
        mask.fill(255)
        assert canvas.document().masks.commit_mask_image(mask_id, mask)

        image_snapshot = canvas.captureEmbeddedImageExport(composition_id)
        mask_snapshot = canvas.captureMaskExport(
            mask_id,
            composition_id=composition_id,
        )
        assert image_snapshot is not None
        assert mask_snapshot is not None
        original_image_pixel = image_snapshot.image.pixelColor(0, 0)
        original_mask_pixel = mask_snapshot.image.pixelColor(0, 0)

        canvas.document().replace_composition_image(
            composition_id,
            _image("darkorange"),
        )
        mask.fill(0)
        assert canvas.document().masks.commit_mask_image(mask_id, mask)
        newer_image = canvas.captureEmbeddedImageExport(composition_id)
        newer_mask = canvas.captureMaskExport(
            mask_id,
            composition_id=composition_id,
        )

        assert newer_image is not None and newer_mask is not None
        assert newer_image.revision > image_snapshot.revision
        assert newer_mask.revision > mask_snapshot.revision
        assert image_snapshot.image.pixelColor(0, 0) == original_image_pixel
        assert mask_snapshot.image.pixelColor(0, 0) == original_mask_pixel
    finally:
        canvas.close()
        qapp.processEvents()


def test_image_document_accepts_host_owned_composition_identity() -> None:
    """A host can correlate one imported image without a parallel ID map."""
    document = CanvasDocument()
    composition_id = uuid.uuid4()
    try:
        created_id = document.create_composition_from_image(
            _image(),
            composition_id=composition_id,
        )
        assert created_id == composition_id
        assert document.content_reference(created_id).composition_id == composition_id
    finally:
        document.close()
