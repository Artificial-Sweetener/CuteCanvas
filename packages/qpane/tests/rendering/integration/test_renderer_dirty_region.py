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

from __future__ import annotations

import types

from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QImage, QRegion, Qt, QTransform
from qpane.rendering.navigation_plan import translated_navigation_plan
from qpane.scene.render_plan import RenderStrategy
from qpane_test_support.render_compare import checker_image
from qpane_test_support.render_plan import make_render_plan

from qpane.rendering import Renderer


class _DummyRendererHost:
    def __init__(self, qpane_rect: QRect) -> None:
        base_plan = _make_render_plan(qpane_rect)
        self._qpane_rect = qpane_rect
        self._base_plan = base_plan
        self.viewport = types.SimpleNamespace(
            pan=QPointF(base_plan.current_pan),
            zoom=1.0,
        )
        self._view = types.SimpleNamespace(
            viewport=self.viewport,
            calculateRenderPlan=self.calculateRenderPlan,
        )
        self._size = qpane_rect.size()
        self.original_image = QImage(
            qpane_rect.size(), QImage.Format_ARGB32_Premultiplied
        )
        self.original_image.fill(Qt.white)

    def size(self) -> QSize:
        return self._size

    def devicePixelRatioF(self) -> float:
        return 1.0

    def update(self) -> None:
        # Tests rely on this during scroll reuse bookkeeping.
        return None

    def view(self):
        return self._view

    def calculateRenderPlan(self, *, use_pan: QPointF | None = None):
        """Return the base plan with an overridden pan value when requested."""
        pan = use_pan if use_pan is not None else self.viewport.pan
        return translated_navigation_plan(
            self._base_plan,
            QPointF(pan),
            device_pixel_ratio=1.0,
        )


def _make_render_plan(qpane_rect: QRect):
    """Return a direct one-layer render plan for dirty-region tests."""
    source_image = QImage(qpane_rect.size(), QImage.Format_ARGB32_Premultiplied)
    source_image.fill(Qt.white)
    return make_render_plan(
        qpane_rect,
        source_image=source_image,
        transform=QTransform(),
        strategy=RenderStrategy.DIRECT,
        current_pan=QPointF(5.0, 3.0),
        physical_viewport_rect=QRectF(qpane_rect),
    )


def test_mark_dirty_accepts_qrectf():
    renderer = Renderer(types.SimpleNamespace())
    fractional_rect = QRectF(0.2, 0.2, 10.6, 15.4)
    renderer.markDirty(fractional_rect)
    assert not renderer._dirty_region.isEmpty()
    bounding_rect = renderer._dirty_region.boundingRect()
    assert bounding_rect.width() > 0
    assert bounding_rect.height() > 0


def test_mark_dirty_handles_fractional_rectangles():
    renderer = Renderer(types.SimpleNamespace())
    tiny_rect = QRectF(1.25, 3.75, 0.1, 0.1)
    renderer.markDirty(tiny_rect)
    bounding_rect = renderer._dirty_region.boundingRect()
    assert not bounding_rect.isNull()
    assert bounding_rect.left() <= 1
    assert bounding_rect.top() <= 3


def test_canonical_physical_patches_never_remerge(qapp) -> None:
    """Adjacent patch cells must remain independently time-sliceable."""
    host = _DummyRendererHost(QRect(0, 0, 1200, 700))
    renderer = Renderer(host)
    renderer.allocate_buffers(QSize(1200, 700), 1.0)

    patches = renderer._canonical_patch_rects(QRegion(renderer._surface.pixmap.rect()))

    assert len(patches) > 1
    assert all(
        patch.width() <= renderer._COMPOSITING_PATCH_PHYSICAL_PX
        and patch.height() <= renderer._COMPOSITING_PATCH_PHYSICAL_PX
        for patch in patches
    )


def test_adjacent_damage_patches_preserve_fractional_zoom_pixels(qapp) -> None:
    """Adjacent repair clips must keep the full-frame raster sampling phase."""
    qpane_rect = QRect(0, 0, 600, 400)
    host = _DummyRendererHost(qpane_rect)
    host.viewport.zoom = 2.01
    renderer = Renderer(host)
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    source_image = checker_image(QSize(320, 240))
    transform = QTransform()
    transform.translate(qpane_rect.center().x(), qpane_rect.center().y())
    transform.scale(host.viewport.zoom, host.viewport.zoom)
    transform.translate(-source_image.width() / 2.0, -source_image.height() / 2.0)
    plan = make_render_plan(
        qpane_rect,
        source_image=source_image,
        transform=transform,
        zoom=host.viewport.zoom,
        physical_viewport_rect=QRectF(qpane_rect),
    )
    renderer._redraw_base_image_buffer(QRegion(qpane_rect), plan)
    expected = renderer.get_base_buffer()
    assert expected is not None
    adjacent_patch_damage = QRegion(QRect(430, 180, 40, 40))

    renderer._redraw_base_image_buffer(adjacent_patch_damage, plan)

    assert renderer._physical_buffer_rects_for_damage(adjacent_patch_damage) == [
        QRect(0, 0, 512, 512),
        QRect(512, 0, 216, 512),
    ]
    assert renderer.get_base_buffer() == expected


def test_mark_dirty_supports_qregion_inputs():
    renderer = Renderer(types.SimpleNamespace())
    region = QRegion(QRect(1, 2, 50, 60))
    renderer.markDirty(region)
    assert renderer._dirty_region == region


def test_mark_dirty_unions_multiple_inputs():
    renderer = Renderer(types.SimpleNamespace())
    renderer.markDirty(QRect(0, 0, 8, 8))
    renderer.markDirty(QRect(16, 16, 4, 4))
    renderer.markDirty(QRectF(32.5, 32.5, 2.0, 2.0))
    bounding_rect = renderer._dirty_region.boundingRect()
    assert bounding_rect.left() == 0
    assert bounding_rect.top() == 0
    assert bounding_rect.right() >= 34
    assert bounding_rect.bottom() >= 34


def test_mark_dirty_whole_view_sentinel():
    renderer = Renderer(types.SimpleNamespace())
    renderer.markDirty()
    renderer.markDirty(QRect(0, 0, 10, 10))  # ignored once full view requested
    bounding_rect = renderer._dirty_region.boundingRect()
    assert bounding_rect.width() >= 200000
    assert bounding_rect.height() >= 200000


def test_subpixel_offset_canonicalization_removes_only_numerical_residue():
    """Pan reuse should discard arithmetic noise without snapping visible fractions."""
    renderer = Renderer(types.SimpleNamespace())

    assert renderer._canonical_subpixel_offset(QPointF(2.0e-13, -3.0e-13)) == QPointF()
    assert renderer._canonical_subpixel_offset(QPointF(0.25, -0.75)) == QPointF(
        0.25, -0.75
    )


def test_redraw_base_image_buffer_resets_buffer_pan_when_full_dirty():
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(_DummyRendererHost(qpane_rect))
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    renderer._buffer_pan = QPointF(-12.0, 7.0)
    renderer._subpixel_pan_offset = QPointF(0.6, 0.4)
    plan = _make_render_plan(qpane_rect)
    dirty_region = QRegion(qpane_rect)
    renderer._redraw_base_image_buffer(dirty_region, plan)
    assert renderer._buffer_pan == plan.current_pan
    assert renderer._subpixel_pan_offset == QPointF(0.0, 0.0)


def test_redraw_base_image_buffer_resets_buffer_pan_for_full_dirty_sentinel():
    """Full-view sentinel redraws should reset the buffer's pan identity."""
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(_DummyRendererHost(qpane_rect))
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    renderer._buffer_pan = QPointF(-64.0, 608.0)
    renderer._subpixel_pan_offset = QPointF(-0.69, 0.69)
    plan = _make_render_plan(qpane_rect)
    dirty_region = QRegion(QRect(-100000, -100000, 200000, 200000))
    renderer._redraw_base_image_buffer(dirty_region, plan)
    assert renderer._buffer_pan == plan.current_pan
    assert renderer._subpixel_pan_offset == QPointF(0.0, 0.0)


def test_redraw_base_image_buffer_keeps_buffer_pan_when_partial_dirty():
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(_DummyRendererHost(qpane_rect))
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    plan = _make_render_plan(qpane_rect)
    renderer.paint(plan)
    partial_region = QRegion(QRect(0, 0, qpane_rect.width(), qpane_rect.height() // 2))
    renderer._redraw_base_image_buffer(partial_region, plan)
    assert renderer._buffer_pan == plan.current_pan
    assert renderer._subpixel_pan_offset == QPointF()


def test_paint_skips_redraw_when_clean():
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(types.SimpleNamespace())
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    plan = _make_render_plan(qpane_rect)
    calls = []

    def fake_redraw(region, render_plan):
        calls.append((region, render_plan))

    renderer._redraw_base_image_buffer = fake_redraw  # type: ignore[assignment]
    renderer._dirty_region = QRegion(qpane_rect)
    renderer.paint(plan)
    assert len(calls) == 1
    renderer.paint(plan)
    assert len(calls) == 1


def test_paint_updates_current_plan_when_redraw_is_clean():
    """Clean paints should still refresh geometry used by overlays and hit tests."""
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(types.SimpleNamespace())
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    previous_plan = _make_render_plan(qpane_rect)
    current_plan = make_render_plan(
        qpane_rect,
        source_image=previous_plan.base_raster_item.source_image,
        transform=QTransform(previous_plan.base_raster_item.transform),
        strategy=previous_plan.base_raster_item.strategy,
        current_pan=QPointF(17.0, -4.0),
        physical_viewport_rect=QRectF(qpane_rect),
    )
    renderer._current_render_plan = previous_plan
    renderer._dirty_region = QRegion()
    renderer.paint(current_plan)
    assert renderer.get_current_render_plan() is current_plan


def test_paint_marks_buffer_on_first_use():
    qpane_rect = QRect(0, 0, 32, 32)
    renderer = Renderer(types.SimpleNamespace())
    plan = _make_render_plan(qpane_rect)
    calls = []

    def fake_redraw(region, render_state):
        calls.append(region)

    renderer._redraw_base_image_buffer = fake_redraw  # type: ignore[assignment]
    renderer.paint(plan)
    assert len(calls) == 1
    first_region = calls[0]
    assert isinstance(first_region, QRegion)
    assert first_region.boundingRect().contains(qpane_rect)
    assert renderer._dirty_region.isEmpty()


def test_renderer_snapshot_metrics_reports_reuse_counters():
    qpane_rect = QRect(0, 0, 64, 64)
    dummy_host = _DummyRendererHost(qpane_rect)
    renderer = Renderer(dummy_host)
    renderer.allocate_buffers(dummy_host.size(), 1.0)
    initial_plan = dummy_host.calculateRenderPlan(use_pan=dummy_host.viewport.pan)
    renderer.paint(initial_plan)
    metrics = renderer.snapshot_metrics()
    assert metrics.base_buffer_allocations == 1
    assert metrics.full_redraws == 1
    assert metrics.partial_redraws == 0
    new_pan = QPointF(dummy_host.viewport.pan.x() + 3.0, dummy_host.viewport.pan.y())
    dummy_host.viewport.pan = new_pan
    assert renderer.tryScrollBuffers(new_pan) is True
    renderer.markDirty(QRect(0, 0, 8, 8))
    renderer.paint(dummy_host.calculateRenderPlan(use_pan=new_pan))
    updated = renderer.snapshot_metrics()
    assert updated.scroll_attempts == 1
    assert updated.scroll_hits == 1
    assert updated.scroll_misses == 0
    assert updated.partial_redraws == 1
    assert updated.full_redraws == 1
    assert updated.last_paint_ms >= 0.0
