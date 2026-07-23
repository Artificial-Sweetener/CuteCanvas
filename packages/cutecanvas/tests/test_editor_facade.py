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
"""Public typed-handle contracts for CuteCanvas's focused editor facade."""

from __future__ import annotations

import pytest
from cutecanvas import CuteCanvas
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QTransform


def test_typed_handles_route_document_layer_tool_and_history_workflows(qapp) -> None:
    """Common editing should not require callers to pass scene/layer ID pairs."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.documents.create(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Handle document",
        )
        image = QImage(80, 60, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFF336699)
        layer_id = canvas.addEditableRasterLayer(image, label="Paint")
        assert layer_id is not None

        layer = document.layer(layer_id)
        assert layer is not None
        assert layer.state.label == "Paint"
        assert layer.select()
        assert layer.set_transform(QTransform.fromTranslate(25.0, 35.0))
        assert canvas.editor.history.can_undo
        assert canvas.editor.history.undo()
        assert canvas.editor.history.can_redo

        canvas.editor.tools.activate(canvas.CONTROL_MODE_MOVE)
        assert canvas.editor.tools.active == canvas.CONTROL_MODE_MOVE
        assert canvas.editor.selection.state is not None

        other = canvas.editor.documents.create(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Other",
        )
        assert other.is_open
        with pytest.raises(RuntimeError, match="open the layer's document"):
            layer.select()
        document.open()
        assert layer.select()
    finally:
        canvas.deleteLater()


def test_persistence_facade_round_trips_complete_raster_document(
    qapp, tmp_path
) -> None:
    """The focused facade should preserve document and resource identity."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.documents.create(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Archive document",
        )
        image = QImage(96, 72, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFFCC8844)
        layer_id = canvas.addEditableRasterLayer(image, label="Archived pixels")
        assert layer_id is not None
        archive_path = tmp_path / "document.cutecanvas"

        canvas.editor.persistence.save(document, archive_path)
        document.remove()
        assert canvas.editor.documents.get(document.id) is None

        restored = canvas.editor.persistence.load(archive_path)
        assert restored.id == document.id
        assert restored.is_open
        assert [layer.state.label for layer in restored.layers] == ["Archived pixels"]
        restored_layer = restored.layer(layer_id)
        assert restored_layer is not None
        assert restored_layer.select()
    finally:
        canvas.deleteLater()
