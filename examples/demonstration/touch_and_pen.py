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

"""Build a small mask editor configured for touch and active-pen input."""

from __future__ import annotations

import uuid

from cutecanvas import Config, CuteCanvas
from PySide6.QtGui import QImage


def build_touch_mask_editor(image: QImage) -> CuteCanvas:
    """Create a viewer where a finger or active pen can edit a blank mask."""
    if image.isNull():
        raise ValueError("image must contain pixels")
    config = Config(
        default_brush_size=30,
        touch_navigation_enabled=True,
        touch_paint_enabled=True,
        stylus_paint_enabled=True,
        pen_pressure_enabled=True,
        pen_pressure_min_ratio=0.15,
        pen_pressure_gamma=1.0,
        palm_rejection_ms=800,
        touch_inertia_enabled=True,
    )
    viewer = CuteCanvas(config=config, features=("mask",))
    image_id = uuid.uuid4()
    viewer.setImagesByID(
        CuteCanvas.imageMapFromLists([image], ids=[image_id]),
        image_id,
    )
    mask_id = viewer.createBlankMask(image.size())
    if mask_id is None:
        raise RuntimeError("mask support is unavailable")
    viewer.setActiveMaskID(mask_id)
    viewer.setControlMode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
    return viewer
