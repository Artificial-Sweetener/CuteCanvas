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

"""Tests for cursor refresh behavior during mask activation signals."""

from __future__ import annotations

import uuid

from cutecanvas import CuteCanvas
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def test_mask_properties_refresh_avoids_direct_brush_cursor_calls(qapp) -> None:
    """Ensure mask activation signals refresh the tool cursor pipeline."""
    qpane = CuteCanvas(features=("mask",))
    try:
        image = QImage(8, 8, QImage.Format_ARGB32)
        image.fill(Qt.black)
        image_id = uuid.uuid4()
        image_map = CuteCanvas.imageMapFromLists([image], [None], [image_id])
        qpane.setImagesByID(image_map, image_id)
        qpane.setControlMode(CuteCanvas.CONTROL_MODE_PANZOOM)
        calls = {"brush": 0, "refresh": 0}

        def _track_brush_cursor(*_args, **_kwargs) -> None:
            calls["brush"] += 1

        def _track_refresh_cursor(*_args, **_kwargs) -> None:
            calls["refresh"] += 1

        qpane.updateBrushCursor = _track_brush_cursor  # type: ignore[assignment]
        qpane.refreshCursor = _track_refresh_cursor  # type: ignore[assignment]
        controller = qpane.mask_service.controller
        controller.active_mask_properties_changed.emit()
        assert calls["brush"] == 0
        assert calls["refresh"] == 1
    finally:
        qpane.deleteLater()
        qapp.processEvents()
