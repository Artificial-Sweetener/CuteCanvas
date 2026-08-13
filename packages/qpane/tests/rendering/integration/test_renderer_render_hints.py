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
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QRegion,
    Qt,
    QTransform,
)
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.scene.model import LayerKind
from qpane.scene.raster_sampling import RasterPresentationSampling
from qpane.scene.render_plan import (
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneRenderPlan,
)
from qpane_test_support.render_plan import make_render_plan

from qpane.rendering import Renderer


class _StubQPane:
    def __init__(self, size: QSize):
        self._size = size
        self.viewport = types.SimpleNamespace(zoom=1.0, pan=QPointF(0.0, 0.0))
        self._view = types.SimpleNamespace(viewport=self.viewport)
        self.original_image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        self.original_image.fill(Qt.white)

    def devicePixelRatioF(self) -> float:
        return 1.0

    def size(self) -> QSize:
        return self._size

    def view(self):
        return self._view


def _make_plan(qpane_rect: QRect, *, presentation_sampling: RasterPresentationSampling):
    """Build a one-layer render plan with the requested hint setting."""
    source_image = QImage(qpane_rect.size(), QImage.Format_ARGB32_Premultiplied)
    source_image.fill(Qt.white)
    return make_render_plan(
        qpane_rect,
        source_image=source_image,
        presentation_sampling=presentation_sampling,
        current_pan=QPointF(0.0, 0.0),
    )


@pytest.mark.parametrize(
    ("presentation_sampling", "expected_calls"),
    (
        (RasterPresentationSampling.BILINEAR, 1),
        (RasterPresentationSampling.NEAREST, 0),
    ),
)
def test_redraw_base_image_buffer_toggles_render_hint(
    monkeypatch, presentation_sampling, expected_calls
):
    qpane_rect = QRect(0, 0, 48, 48)
    qpane = _StubQPane(qpane_rect.size())
    renderer = Renderer(qpane)
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    plan = _make_plan(qpane_rect, presentation_sampling=presentation_sampling)
    dirty_region = QRegion(qpane_rect)
    calls = []
    original = QPainter.setRenderHint

    def fake_set_render_hint(
        self: QPainter,
        hint: QPainter.RenderHint,
        on: bool = True,
    ) -> None:
        if hint == QPainter.RenderHint.SmoothPixmapTransform:
            calls.append(on)
        return original(self, hint, on)

    monkeypatch.setattr(QPainter, "setRenderHint", fake_set_render_hint, raising=False)
    renderer._redraw_base_image_buffer(dirty_region, plan)
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    ("presentation_sampling", "expected_calls"),
    (
        (RasterPresentationSampling.BILINEAR, 1),
        (RasterPresentationSampling.NEAREST, 0),
    ),
)
def test_repair_base_buffer_strips_toggles_render_hint(
    monkeypatch,
    presentation_sampling,
    expected_calls,
) -> None:
    """Strip repair should honor the same sampling hint as complete frames."""
    qpane_rect = QRect(0, 0, 48, 48)
    qpane = _StubQPane(qpane_rect.size())
    renderer = Renderer(qpane)
    renderer.allocate_buffers(qpane_rect.size(), 1.0)
    plan = _make_plan(qpane_rect, presentation_sampling=presentation_sampling)
    calls = []
    original = QPainter.setRenderHint

    def fake_set_render_hint(
        self: QPainter,
        hint: QPainter.RenderHint,
        on: bool = True,
    ) -> None:
        if hint == QPainter.RenderHint.SmoothPixmapTransform:
            calls.append(on)
        return original(self, hint, on)

    monkeypatch.setattr(QPainter, "setRenderHint", fake_set_render_hint, raising=False)
    renderer._repair_base_buffer_strips([QRect(0, 0, 10, 10)], plan)
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    ("presentation_sampling", "expected_calls"),
    (
        (RasterPresentationSampling.BILINEAR, 1),
        (RasterPresentationSampling.NEAREST, 0),
    ),
)
def test_sampled_layer_toggles_render_hint(
    monkeypatch,
    presentation_sampling: RasterPresentationSampling,
    expected_calls: int,
) -> None:
    """Sampled and mask layers should honor the shared raster sampling policy."""
    plan = _sampled_plan(presentation_sampling=presentation_sampling)
    target = QImage(8, 4, QImage.Format.Format_ARGB32_Premultiplied)
    target.fill(Qt.GlobalColor.transparent)
    calls: list[bool] = []
    original = QPainter.setRenderHint

    def fake_set_render_hint(
        self: QPainter,
        hint: QPainter.RenderHint,
        on: bool = True,
    ) -> None:
        if hint == QPainter.RenderHint.SmoothPixmapTransform:
            calls.append(on)
        return original(self, hint, on)

    monkeypatch.setattr(QPainter, "setRenderHint", fake_set_render_hint, raising=False)
    painter = QPainter(target)
    try:
        SceneItemCompositor().draw_visible_items(painter, plan)
    finally:
        painter.end()

    assert len(calls) == expected_calls


def test_sharp_sampled_layer_preserves_enlarged_source_pixels() -> None:
    """Close zoom should expose solid source pixels without filtered edge colors."""
    plan = _sampled_plan(presentation_sampling=RasterPresentationSampling.NEAREST)
    target = QImage(8, 4, QImage.Format.Format_ARGB32_Premultiplied)
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    try:
        SceneItemCompositor().draw_visible_items(painter, plan)
    finally:
        painter.end()

    assert all(target.pixelColor(x, 1) == QColor("red") for x in range(4))
    assert all(target.pixelColor(x, 1) == QColor("blue") for x in range(4, 8))


def _sampled_plan(
    *, presentation_sampling: RasterPresentationSampling
) -> SceneRenderPlan:
    """Return one enlarged two-pixel sampled layer."""
    source = QImage(2, 1, QImage.Format.Format_ARGB32_Premultiplied)
    source.setPixelColor(0, 0, QColor("red"))
    source.setPixelColor(1, 0, QColor("blue"))
    plan = make_render_plan(QRect(0, 0, 8, 4), source_image=source)
    raster_item = plan.render_items[0]
    sampled_item = SampledLayerRenderItem(
        descriptor=replace(raster_item.descriptor, kind=LayerKind.HYBRID),
        transform=QTransform.fromScale(4.0, 4.0),
        placement=raster_item.placement,
        clip=None,
        source_size=source.size(),
        presentation_sampling=presentation_sampling,
        tiles=(
            SampledTileRenderData(
                source,
                QRectF(0.0, 0.0, 2.0, 1.0),
                QRectF(source.rect()),
            ),
        ),
    )
    return replace(
        plan,
        scene_bounds=sampled_item.placement,
        content_bounds=sampled_item.placement,
        render_items=(sampled_item,),
    )
