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
"""Prove revision-safe asynchronous projection through the shared renderer."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy, QTest

from cutecanvas import CanvasProjectionStatus, CuteCanvas
from cutecanvas.document import CanvasDocument


def _wait_for_signal(spy: QSignalSpy, *, timeout_ms: int = 3000) -> bool:
    """Process Qt delivery until the spy records a signal or time expires."""
    remaining = timeout_ms
    while spy.count() == 0 and remaining > 0:
        QTest.qWait(1)
        remaining -= 1
    return spy.count() > 0


def _image(size: QSize | None = None) -> QImage:
    """Return one opaque image with an exact expected projection color."""
    size = QSize(96, 64) if size is None else size
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#2878c8"))
    return image


def test_projection_renders_composition_at_requested_resolution(qapp) -> None:
    """A composition projection is asynchronous, bounded, and color correct."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(_image())
    canvas = CuteCanvas(document=document, features=())
    completed = QSignalSpy(canvas.projectionCompleted)
    try:
        reference = document.content_reference(composition_id)
        handle = canvas.requestProjection(
            reference,
            source_bounds=QRectF(16.0, 8.0, 48.0, 32.0),
            pixel_size=QSize(240, 160),
        )

        assert _wait_for_signal(completed)
        result = completed.at(0)[0]
        assert result.request_id == handle.request_id
        assert result.status is CanvasProjectionStatus.COMPLETED
        assert result.image is not None
        assert result.image.size() == QSize(240, 160)
        assert result.image.pixelColor(120, 80) == QColor("#2878c8")
    finally:
        canvas.close()
        document.close()


def test_projection_rejects_an_obsolete_reference_without_work(qapp) -> None:
    """A changed composition cannot silently publish pixels for an old revision."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(_image())
    canvas = CuteCanvas(document=document, features=())
    completed = QSignalSpy(canvas.projectionCompleted)
    try:
        reference = document.content_reference(composition_id)
        layer = document.snapshot().compositions[composition_id].layers[0]
        document.resources.compositions.layers.update_presentation(
            composition_id,
            layer.layer_id,
            opacity=0.5,
        )

        canvas.requestProjection(reference)

        assert completed.count() == 1
        result = completed.at(0)[0]
        assert result.status is CanvasProjectionStatus.STALE
        assert result.image is None
    finally:
        canvas.close()
        document.close()


def test_projection_cancel_publishes_one_terminal_result(qapp) -> None:
    """Cancellation is prompt and late worker publication is suppressed."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(_image(QSize(2048, 2048)))
    canvas = CuteCanvas(document=document, features=())
    completed = QSignalSpy(canvas.projectionCompleted)
    try:
        handle = canvas.requestProjection(
            document.content_reference(composition_id),
            pixel_size=QSize(4096, 4096),
        )
        assert handle.cancel()
        qapp.processEvents()

        assert completed.count() == 1
        assert completed.at(0)[0].status is CanvasProjectionStatus.CANCELLED
    finally:
        canvas.close()
        document.close()
