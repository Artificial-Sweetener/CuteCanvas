#    QPane - High-performance PySide6 image viewer
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
"""Verify guard-covered render-plan projection."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect
from qpane.rendering.navigation_plan import (
    translated_navigation_plan,
)
from qpane_test_support.render_plan import make_render_plan


def test_translated_navigation_plan_preserves_products_and_projects_pan() -> None:
    """Shift item output by physical pan converted through DPR."""

    plan = make_render_plan(QRect(0, 0, 320, 180))
    item = plan.render_items[0]
    source_point = QPointF(17.0, 23.0)
    mapped_before = item.transform.map(source_point)

    translated = translated_navigation_plan(
        plan,
        plan.current_pan + QPointF(35.0, -17.5),
        device_pixel_ratio=1.75,
    )
    translated_item = translated.render_items[0]
    mapped_after = translated_item.transform.map(source_point)

    assert translated.current_pan == plan.current_pan + QPointF(35.0, -17.5)
    assert mapped_after == mapped_before + QPointF(20.0, -10.0)
    assert translated_item.source_image.cacheKey() == item.source_image.cacheKey()
