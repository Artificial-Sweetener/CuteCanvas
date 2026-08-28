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

"""Protect navigation-buffer reuse from transient invalid viewport geometry."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from qpane.rendering.navigation_buffer import scroll_repair_regions
from qpane.rendering.render import Renderer


def test_navigation_reuse_declines_nonpositive_zoom_without_raising() -> None:
    """A transient detached viewport must fall through to a normal redraw."""
    renderer = Renderer.__new__(Renderer)
    renderer._navigation_refiner = SimpleNamespace(cancel=lambda: None)
    renderer._current_render_plan = SimpleNamespace(zoom=1.0)

    reused = renderer.tryTransformBuffers(SimpleNamespace(zoom=0.0))

    assert not reused


def test_linear_scroll_journals_only_repair_pixels_retained_by_inverse_scroll() -> None:
    """Newly exposed pixels need repair but cannot affect a linear rollback."""
    surface_rect = QRect(0, 0, 100, 80)

    regions = scroll_repair_regions(
        surface_rect,
        QRegion(surface_rect),
        dx=10,
        dy=0,
        bleed=2,
        linear_scroll=True,
    )

    assert regions.translated_valid == QRegion(QRect(10, 0, 90, 80))
    assert regions.repair == QRegion(QRect(0, 0, 12, 80))
    assert regions.rollback == QRegion(QRect(10, 0, 2, 80))
    assert regions.repair_rects == (QRect(0, 0, 12, 80),)


def test_wrapped_scroll_journals_every_repaired_storage_pixel() -> None:
    """Wrapped addressing requires every repair pixel under the old origin."""
    surface_rect = QRect(0, 0, 100, 80)

    regions = scroll_repair_regions(
        surface_rect,
        QRegion(surface_rect),
        dx=10,
        dy=0,
        bleed=2,
        linear_scroll=False,
    )

    assert regions.rollback == regions.repair
