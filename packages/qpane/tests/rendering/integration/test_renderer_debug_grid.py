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

"""Tests for compositor debug grid behaviour."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.scene.render_plan import RenderStrategy
from qpane_test_support.render_plan import make_render_plan


class _PainterStub:
    """Records rectangles drawn by the renderer."""

    def __init__(self):
        self.rects = []

    def setPen(self, pen):
        """Store the pen (unused)."""
        self.pen = pen

    def setBrush(self, brush):
        """Store the brush (unused)."""
        self.brush = brush

    def save(self):
        """Accept compositor state isolation."""

    def restore(self):
        """Accept compositor state restoration."""

    def setClipRect(self, rect, operation):
        """Store the active clip (unused)."""
        self.clip = (rect, operation)

    def drawImage(self, *args):
        """Accept source and tile image draws."""

    def drawRect(self, rect):
        """Record the drawn rectangle."""
        self.rects.append(rect)


def _make_render_plan(draw_grid: bool):
    """Build a minimal render plan for exercising the grid overlay."""
    image = QImage(256, 256, QImage.Format_RGB32)
    image.fill(0)
    return make_render_plan(
        QRect(0, 0, 256, 256),
        source_image=image,
        strategy=RenderStrategy.TILE,
        debug_draw_tile_grid=draw_grid,
        tile_size=64,
        max_tile_cols=4,
        max_tile_rows=4,
        visible_tile_range=(0, 3, 0, 3),
    )


def test_debug_grid_skips_when_flag_disabled():
    """Compositor should skip drawing when the item flag is false."""
    compositor = SceneItemCompositor()
    painter = _PainterStub()
    plan = _make_render_plan(draw_grid=False)
    compositor.draw_raster_source(painter, plan, plan.base_raster_item)
    assert painter.rects == []


def test_debug_grid_draws_when_flag_enabled():
    """Compositor should draw tile outlines when the item flag is true."""
    compositor = SceneItemCompositor()
    painter = _PainterStub()
    plan = _make_render_plan(draw_grid=True)
    compositor.draw_raster_source(painter, plan, plan.base_raster_item)
    assert painter.rects, "Expected at least one debug rectangle to be drawn"
