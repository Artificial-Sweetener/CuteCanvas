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

"""Characterize stable headless image-document payload replacement."""

from __future__ import annotations

from cutecanvas import CanvasDocument, CuteCanvas
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.rendering import ViewportZoomMode


def test_headless_image_replacement_preserves_view_masks_and_identity(qapp) -> None:
    """Replace pixels without activating, recreating, or stripping composition state."""

    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(96, 64), QColor("red"))
    )
    canvas = CuteCanvas(document=document, features=("mask",))
    try:
        canvas.resize(720, 480)
        canvas.openComposition(composition_id)
        canvas.show()
        qapp.processEvents()
        mask_id = canvas.createBlankMask(QSize(96, 64))
        assert mask_id is not None
        canvas.applyZoom(canvas.currentZoom() * 1.75)
        canvas.setPan(QPointF(43.0, -27.0))
        qapp.processEvents()
        zoom = canvas.currentZoom()
        pan = canvas.getPan()

        changed = document.replace_composition_image(
            composition_id,
            _image(QSize(96, 64), QColor("blue")),
        )
        qapp.processEvents()

        assert changed is True
        assert document.composition_ids() == (composition_id,)
        assert canvas.currentCompositionID() == composition_id
        assert tuple(
            mask.mask_id for mask in canvas.listMasksForComposition(composition_id)
        ) == (mask_id,)
        assert canvas.currentZoom() == zoom
        assert canvas.getPan() == pan
        assert canvas.view().viewport.get_zoom_mode() is ViewportZoomMode.CUSTOM
        assert document.embedded_image_for_composition(composition_id).pixelColor(
            0, 0
        ) == QColor("blue")
    finally:
        canvas.close()
        document.close()
        qapp.processEvents()


def test_headless_image_replacement_updates_canvas_bounds_without_activation(
    qapp,
) -> None:
    """Resize one inactive image document while another session target stays active."""

    document = CanvasDocument()
    active_id = document.create_composition_from_image(
        _image(QSize(80, 60), QColor("red"))
    )
    inactive_id = document.create_composition_from_image(
        _image(QSize(120, 90), QColor("blue"))
    )
    canvas = CuteCanvas(document=document, features=())
    try:
        canvas.openComposition(active_id)

        assert document.replace_composition_image(
            inactive_id,
            _image(QSize(320, 180), QColor("green")),
        )
        qapp.processEvents()

        assert canvas.currentCompositionID() == active_id
        snapshot = document.snapshot()
        inactive = snapshot.compositions[inactive_id]
        assert inactive.scene_bounds is not None
        assert inactive.scene_bounds.size().toSize() == QSize(320, 180)
    finally:
        canvas.close()
        document.close()
        qapp.processEvents()


def _image(size: QSize, color: QColor) -> QImage:
    """Return one opaque image-document fixture."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image
