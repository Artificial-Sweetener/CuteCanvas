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

"""Demo window tests covering tool focus during document navigation."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.sam.manager import SamManager
from cutecanvas_demo import ExampleOptions, ExampleWindow


def _solid_image() -> QImage:
    """Return a tiny image for demo tool focus tests."""
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(Qt.black)
    return image


def test_demo_document_clicks_drive_tool_focus(qapp, monkeypatch) -> None:
    """Ensure document-layer selections set the expected tool modes."""

    def ignore_predictor_request(*_args, **_kwargs) -> None:
        """Keep inference outside a catalog-focus test."""

    monkeypatch.setattr(SamManager, "requestPredictor", ignore_predictor_request)
    window = ExampleWindow(ExampleOptions(sam_enabled=True))
    try:
        composition_id = window.qpane.createCompositionFromImage(
            _solid_image(),
            title="Tool focus",
            label="Image",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                reorderable=True,
            ),
        )
        mask_id = window.qpane.createBlankMask(_solid_image().size())
        assert mask_id is not None
        inactive_mask_id = window.qpane.createBlankMask(_solid_image().size())
        assert inactive_mask_id is not None
        window.qpane.setActiveMaskID(mask_id)
        qapp.processEvents()

        assert window.composition_ui.dock is not None
        browser = window.composition_ui.dock._browser
        qapp.processEvents()

        def _items():
            """Return current mask and imported-raster rows after refreshes."""
            snapshot = window.qpane.getCompositionSnapshot()
            entry = snapshot.compositions[composition_id]
            mask_layer = next(
                layer for layer in entry.layers if layer.source_id == mask_id
            )
            image_layer = next(
                layer
                for layer in entry.layers
                if layer.source_kind == "imported-raster"
            )
            return (
                browser._layer_items[(composition_id, mask_layer.layer_id)],
                browser._layer_items[(composition_id, image_layer.layer_id)],
            )

        window.tools.set_mode(CuteCanvas.CONTROL_MODE_CURSOR)
        mask_item, image_item = _items()
        browser._activate_item(mask_item, 0)
        qapp.processEvents()
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_DRAW_BRUSH

        window.tools.set_mode(CuteCanvas.CONTROL_MODE_MOVE)
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_MOVE
        entry = window.qpane.getCompositionSnapshot().compositions[composition_id]
        mask_policies = {
            layer.source_id: layer.interaction
            for layer in entry.layers
            if layer.source_kind == "coverage"
        }
        assert mask_policies[mask_id].selectable
        assert mask_policies[mask_id].movable
        assert mask_policies[mask_id].pixel_editable
        assert mask_policies[inactive_mask_id].selectable
        assert not mask_policies[inactive_mask_id].movable

        assert window.qpane.setActiveMaskID(inactive_mask_id)
        qapp.processEvents()
        entry = window.qpane.getCompositionSnapshot().compositions[composition_id]
        mask_policies = {
            layer.source_id: layer.interaction
            for layer in entry.layers
            if layer.source_kind == "coverage"
        }
        assert mask_policies[mask_id].selectable
        assert not mask_policies[mask_id].movable
        assert mask_policies[inactive_mask_id].selectable
        assert mask_policies[inactive_mask_id].movable
        assert mask_policies[inactive_mask_id].pixel_editable
        mask_item, image_item = _items()
        browser._activate_item(mask_item, 0)
        qapp.processEvents()
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_MOVE
        mask_item, image_item = _items()
        browser._activate_item(image_item, 0)
        qapp.processEvents()
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_MOVE

        window.tools.set_mode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
        mask_item, image_item = _items()
        browser._activate_item(image_item, 0)
        qapp.processEvents()
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_DRAW_BRUSH
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
