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

"""Cycle mode behavior for the example CuteCanvas."""

from __future__ import annotations

from cutecanvas import Config, CuteCanvas
from PySide6.QtGui import QImage


def _add_image(qpane: CuteCanvas) -> None:
    """Populate the qpane with a single image to disable the placeholder."""
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(0)
    qpane.createCompositionFromImage(image, title="Cycle tools")


def _cycle(qpane: CuteCanvas) -> None:
    mask_available = qpane.maskFeatureAvailable()
    sam_available = qpane.samFeatureAvailable()
    preferred_order: list[str] = [
        CuteCanvas.CONTROL_MODE_CURSOR,
        CuteCanvas.CONTROL_MODE_PANZOOM,
        CuteCanvas.CONTROL_MODE_MOVE,
        CuteCanvas.CONTROL_MODE_TRANSFORM,
    ]
    if mask_available:
        preferred_order.append(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
    if sam_available:
        preferred_order.append(CuteCanvas.CONTROL_MODE_SMART_SELECT)
    seen = set(preferred_order)
    for mode in qpane.availableControlModes():
        if mode in seen:
            continue
        preferred_order.append(mode)
        seen.add(mode)

    def _mode_allowed(mode: str) -> bool:
        if mode == CuteCanvas.CONTROL_MODE_PANZOOM:
            return True
        if mode == CuteCanvas.CONTROL_MODE_DRAW_BRUSH:
            return mask_available
        if mode == CuteCanvas.CONTROL_MODE_SMART_SELECT:
            return mask_available and sam_available
        return True

    ordered_modes = [mode for mode in preferred_order if _mode_allowed(mode)]
    if not ordered_modes:
        return
    current = qpane.getControlMode()
    if current not in ordered_modes:
        next_mode = ordered_modes[0]
    elif len(ordered_modes) == 1:
        return
    else:
        next_index = (ordered_modes.index(current) + 1) % len(ordered_modes)
        next_mode = ordered_modes[next_index]
    if (
        next_mode
        in {
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
            CuteCanvas.CONTROL_MODE_SMART_SELECT,
        }
        and qpane.activeMaskID() is None
    ):
        raster = qpane.activeRasterResolver().resolve()
        assert raster is not None
        mask_id = qpane.createBlankMask(raster.image.size())
        if mask_id is not None:
            qpane.setActiveMaskID(mask_id)
    qpane.setControlMode(next_mode)


def test_cycle_order_matches_toolbar(monkeypatch, qapp):
    """Cycle through enabled tools without starting unrelated SAM inference."""
    from cutecanvas.sam.manager import SamManager

    def ignore_predictor_request(
        _manager, _image, _image_id, *, source_path=None
    ) -> None:
        """Keep an interaction-order test independent of predictor execution."""

    monkeypatch.setattr(
        SamManager,
        "requestPredictor",
        ignore_predictor_request,
    )
    config = Config()
    qpane = CuteCanvas(config=config, features=("mask", "sam"))
    try:
        _add_image(qpane)
        qpane.setControlMode(CuteCanvas.CONTROL_MODE_CURSOR)
        _cycle(qpane)
        assert qpane.getControlMode() == CuteCanvas.CONTROL_MODE_PANZOOM
        _cycle(qpane)
        assert qpane.getControlMode() == CuteCanvas.CONTROL_MODE_MOVE
        _cycle(qpane)
        assert qpane.getControlMode() == CuteCanvas.CONTROL_MODE_TRANSFORM
        _cycle(qpane)
        assert qpane.getControlMode() == CuteCanvas.CONTROL_MODE_DRAW_BRUSH
        _cycle(qpane)
        if qpane.samFeatureAvailable():
            assert qpane.getControlMode() == CuteCanvas.CONTROL_MODE_SMART_SELECT
        assert qpane.getControlMode() in {
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
            CuteCanvas.CONTROL_MODE_SMART_SELECT,
        }
        for expected in (
            CuteCanvas.CONTROL_MODE_PAINT_BUCKET,
            CuteCanvas.CONTROL_MODE_SELECT_RECTANGLE,
            CuteCanvas.CONTROL_MODE_SELECT_ELLIPSE,
            CuteCanvas.CONTROL_MODE_SELECT_LASSO,
            CuteCanvas.CONTROL_MODE_MASK_RECTANGLE,
            CuteCanvas.CONTROL_MODE_MASK_ELLIPSE,
            CuteCanvas.CONTROL_MODE_MASK_LASSO,
            CuteCanvas.CONTROL_MODE_CLONE_STAMP,
            CuteCanvas.CONTROL_MODE_VECTOR_SHAPE,
            CuteCanvas.CONTROL_MODE_VECTOR_PATH,
            CuteCanvas.CONTROL_MODE_VECTOR_NODE,
            CuteCanvas.CONTROL_MODE_VECTOR_TEXT,
            CuteCanvas.CONTROL_MODE_CURSOR,
        ):
            _cycle(qpane)
            assert qpane.getControlMode() == expected
    finally:
        qpane.deleteLater()
        qapp.processEvents()
