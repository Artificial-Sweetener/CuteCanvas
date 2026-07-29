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

from __future__ import annotations

import time
import uuid
from dataclasses import replace

import pytest
from cutecanvas import CuteCanvas
from cutecanvas.resources import ProjectResourceReference
from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QRegion, Qt
from PySide6.QtTest import QTest
from qpane import (
    ClipCoordinateSpace,
    LayerClip,
    LayerTransform,
    QPane,
    RasterSource,
    RenderLayer,
    RenderScene,
)
from qpane.rendering.navigation_plan import retained_raster_navigation_delta
from qpane.rendering.render import Renderer
from qpane.scene.identity import scene_image_asset_key, source_render_asset_key
from qpane.scene.model import LayerKind
from qpane.scene.render_plan import (
    RenderStrategy,
    TileRenderData,
)

from tests.helpers.render_compare import (
    assert_images_match,
    checker_image,
    rendered_overscanned_widget_frame,
)
from tests.helpers.render_plan import make_render_plan


@pytest.fixture()
def qpane_with_image(qapp):
    qpane = CuteCanvas(features=())
    qpane.resize(128, 128)
    image = QImage(128, 128, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.black)
    qpane.createCompositionFromImage(image)
    yield qpane
    qpane.deleteLater()
    qapp.processEvents()


def _make_mask_plan(qpane_rect: QRect):
    """Return a base raster plan with a mask render item appended."""
    plan = make_render_plan(qpane_rect)
    base_item = plan.base_raster_item
    assert base_item is not None
    mask_id = uuid.uuid4()
    mask_descriptor = replace(
        base_item.descriptor,
        layer_id=uuid.uuid4(),
        kind=LayerKind.MASK,
        source=ProjectResourceReference(mask_id),
    )
    mask_item = replace(
        base_item,
        descriptor=mask_descriptor,
        asset_key=scene_image_asset_key(
            scene_id=plan.scene_id,
            layer_id=mask_descriptor.layer_id,
            source_id=mask_id,
            source_kind="mask",
            revision=0,
            source_path=None,
        ),
        pyramid_asset_key=source_render_asset_key(
            source_id=mask_id,
            source_kind="mask",
            revision=0,
            source_path=None,
        ),
    )
    return replace(plan, render_items=(base_item, mask_item)), mask_item


def _render_clean_frame(qpane: CuteCanvas, pan: QPointF) -> QImage:
    """Return a full-redraw frame for ``pan`` using the live renderer."""
    view = qpane.view()
    renderer = view.renderer
    view.allocate_buffers()
    view.viewport.pan = QPointF(pan)
    renderer.markDirty()
    plan = view.calculateRenderPlan(use_pan=pan, is_blank=False)
    assert plan is not None
    renderer.paint(plan)
    buffer = renderer.get_base_buffer()
    assert buffer is not None
    return rendered_overscanned_widget_frame(
        QImage(buffer),
        renderer.get_subpixel_pan_offset(),
        renderer._viewport_physical_size,
        renderer.buffer_overscan_physical_px,
    )


def _render_scrolled_frame(
    qpane: CuteCanvas,
    *,
    start_pan: QPointF,
    target_pan: QPointF,
) -> QImage:
    """Return a frame produced by scroll-buffer repair from start to target pan."""
    view = qpane.view()
    renderer = view.renderer
    view.allocate_buffers()
    view.viewport.pan = QPointF(start_pan)
    renderer.markDirty()
    start_plan = view.calculateRenderPlan(use_pan=start_pan, is_blank=False)
    assert start_plan is not None
    renderer.paint(start_plan)
    view.viewport.pan = QPointF(target_pan)
    assert renderer.tryScrollBuffers(target_pan) is True
    buffer = renderer.get_base_buffer()
    assert buffer is not None
    return rendered_overscanned_widget_frame(
        QImage(buffer),
        renderer.get_subpixel_pan_offset(),
        renderer._viewport_physical_size,
        renderer.buffer_overscan_physical_px,
    )


def _make_qpane_with_checker_image(
    qapp,
    *,
    size: int = 256,
    dpr: float = 1.0,
    image_format: QImage.Format | None = None,
) -> CuteCanvas:
    """Return a CuteCanvas containing one high-contrast image."""
    qpane = CuteCanvas(features=())
    qpane.resize(128, 128)
    qpane.devicePixelRatioF = lambda: dpr  # type: ignore[method-assign]
    image = checker_image(QRect(0, 0, size, size).size())
    if image_format is not None:
        image = image.convertToFormat(image_format)
    qpane.createCompositionFromImage(image)
    qpane.setZoom1To1()
    qapp.processEvents()
    return qpane


def _assert_edges_are_covered(image: QImage) -> None:
    """Assert that every visible edge pixel has rendered source coverage."""
    width = image.width()
    height = image.height()
    for x in range(width):
        assert image.pixelColor(x, 0).alpha() == 255
        assert image.pixelColor(x, height - 1).alpha() == 255
    for y in range(height):
        assert image.pixelColor(0, y).alpha() == 255
        assert image.pixelColor(width - 1, y).alpha() == 255


def test_try_scroll_buffers_uses_target_render_plan(qpane_with_image, monkeypatch):
    """Guard reuse should validate the render plan at the requested pan."""
    qpane = qpane_with_image
    view = qpane.view()
    renderer = view.renderer
    view.presenter.paint(
        is_blank=False,
        content_overlays={},
        scene_overlays={},
        overlays_suspended=False,
        draw_tool_overlay=None,
    )
    renderer._buffer_pan = QPointF(0.0, 0.0)
    renderer._subpixel_pan_offset = QPointF(0.0, 0.0)
    captured = {}
    original_calculate = view.calculateRenderPlan

    def fake_calculate(use_pan=None, **kwargs):
        captured["use_pan"] = use_pan
        return original_calculate(use_pan=use_pan, **kwargs)

    monkeypatch.setattr(view, "calculateRenderPlan", fake_calculate)
    new_pan = QPointF(4.0, 3.0)
    view.viewport.pan = QPointF(new_pan)
    result = renderer.tryScrollBuffers(new_pan)
    assert result is True
    assert captured["use_pan"] == new_pan
    assert renderer._buffer_pan == new_pan
    assert renderer.get_subpixel_pan_offset().isNull()


def test_try_scroll_buffers_rejects_changed_resolved_products(
    qpane_with_image,
) -> None:
    """Ring reuse must not combine pixels from different product snapshots."""
    qpane = qpane_with_image
    view = qpane.view()
    renderer = view.renderer
    view.allocate_buffers()
    initial_plan = view.calculateRenderPlan(use_pan=QPointF(), is_blank=False)
    assert initial_plan is not None
    renderer.markDirty()
    renderer.paint(initial_plan)
    target_pan = QPointF(12.0, 7.0)
    target_plan = view.calculateRenderPlan(use_pan=target_pan, is_blank=False)
    assert target_plan is not None
    base_item = target_plan.base_raster_item
    assert base_item is not None
    changed_source = QImage(base_item.source_image)
    changed_source.setPixel(0, 0, changed_source.pixel(0, 0) ^ 0x00FFFFFF)
    changed_plan = replace(
        target_plan,
        render_items=(replace(base_item, source_image=changed_source),),
    )
    before = renderer.snapshot_metrics()
    origin_before = renderer._surface.storage_origin

    assert (
        renderer.tryScrollBuffers(
            target_pan,
            repair_plan=changed_plan,
        )
        is False
    )

    after = renderer.snapshot_metrics()
    assert after.scroll_misses == before.scroll_misses + 1
    assert renderer._surface.storage_origin == origin_before
    assert renderer._buffer_pan == QPointF()


def test_base_scroll_strip_repair_uses_direct_fast_path(
    qpane_with_image,
    monkeypatch,
) -> None:
    """A direct base raster should bypass general layered strip drawing."""
    qpane = qpane_with_image
    renderer = qpane.view().renderer
    plan = qpane.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    calls = []

    def fail_generic_draw(*_args, **_kwargs):
        raise AssertionError("direct base repair must not draw the whole scene")

    monkeypatch.setattr(renderer._items, "draw_visible_items", fail_generic_draw)
    monkeypatch.setattr(
        renderer,
        "_repair_base_raster_strips_directly",
        lambda rects, repair_plan: calls.append((rects, repair_plan)),
    )

    assert renderer._repair_base_buffer_strips([qpane.rect()], plan) is True
    assert calls == [([qpane.rect()], plan)]


def test_tiled_base_scroll_strip_repair_uses_layered_path(
    qpane_with_image,
    monkeypatch,
) -> None:
    """A tiled base raster should use the normal layered compositor."""
    qpane = qpane_with_image
    renderer = qpane.view().renderer
    tile_image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    tile_image.fill(Qt.white)
    plan = make_render_plan(
        qpane.rect(),
        strategy=RenderStrategy.TILE,
        tiles_to_draw=(TileRenderData(tile_image, QPointF(0.0, 0.0)),),
        visible_tile_range=(0, 0, 0, 0),
    )
    calls = []

    def fail_direct_repair(*_args, **_kwargs):
        raise AssertionError("tiled repair must not use direct-source drawing")

    monkeypatch.setattr(
        renderer,
        "_repair_base_raster_strips_directly",
        fail_direct_repair,
    )
    monkeypatch.setattr(
        renderer,
        "_repair_layered_strips",
        lambda rects, repair_plan: calls.append((rects, repair_plan)) or True,
    )

    assert renderer._can_repair_base_strips_directly(plan) is False
    assert renderer._repair_base_buffer_strips([qpane.rect()], plan) is True
    assert calls == [([qpane.rect()], plan)]


def test_default_scene_scroll_repair_matches_full_redraw(qapp) -> None:
    """Default scene pan repair should match a clean full redraw."""
    qpane = _make_qpane_with_checker_image(qapp)
    try:
        start_pan = QPointF(0.0, 0.0)
        target_pan = QPointF(7.0, 5.0)
        expected = _render_clean_frame(qpane, target_pan)
        actual = _render_scrolled_frame(
            qpane,
            start_pan=start_pan,
            target_pan=target_pan,
        )
        assert_images_match(actual, expected)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_tiled_scroll_strip_matches_full_redraw_for_rgba_source(qapp) -> None:
    """Tiled edge repair should share full-redraw rasterization for RGBA sources."""
    qpane = _make_qpane_with_checker_image(
        qapp,
        size=1024,
        dpr=1.0,
        image_format=QImage.Format_RGBA8888,
    )
    try:
        start_pan = QPointF(-159.0, 300.0)
        target_pan = QPointF(-135.0, 300.0)
        expected = _render_clean_frame(qpane, target_pan)
        actual = _render_scrolled_frame(
            qpane,
            start_pan=start_pan,
            target_pan=target_pan,
        )
        assert_images_match(actual, expected)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0, 2.5, 3.0])
@pytest.mark.parametrize(
    "target_pan",
    [
        QPointF(0.5, 0.0),
        QPointF(-0.75, 0.0),
        QPointF(0.0, 0.5),
        QPointF(0.0, -0.75),
        QPointF(0.5, 0.5),
    ],
)
def test_fractional_scroll_delta_tracks_the_device_aligned_raster_phase(
    qapp,
    dpr: float,
    target_pan: QPointF,
) -> None:
    """Fractional pans should scroll only when their aligned raster phase changes."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024, dpr=dpr)
    try:
        view = qpane.view()
        renderer = view.renderer
        view.allocate_buffers()
        start_pan = QPointF(0.0, 0.0)
        view.viewport.pan = QPointF(start_pan)
        renderer.markDirty()
        start_plan = view.calculateRenderPlan(use_pan=start_pan, is_blank=False)
        assert start_plan is not None
        renderer.paint(start_plan)
        original_buffer = QImage(renderer.get_base_buffer())
        before = renderer.snapshot_metrics()

        view.viewport.pan = QPointF(target_pan)
        target_plan = view.calculateRenderPlan(use_pan=target_pan, is_blank=False)
        assert target_plan is not None
        physical_delta = retained_raster_navigation_delta(
            start_plan,
            target_plan,
            device_pixel_ratio=dpr,
        )
        assert physical_delta is not None
        assert renderer.tryScrollBuffers(target_pan) is True

        after = renderer.snapshot_metrics()
        current_buffer = renderer.get_base_buffer()
        assert current_buffer is not None
        if physical_delta.isNull():
            assert_images_match(QImage(current_buffer), original_buffer)
            assert renderer._buffer_pan == start_pan
            assert renderer.get_subpixel_pan_offset() == target_pan
            assert after.scroll_repairs == before.scroll_repairs
        else:
            assert renderer._buffer_pan == target_pan
            assert renderer.get_subpixel_pan_offset().isNull()
            assert after.scroll_repairs == before.scroll_repairs + 1
        assert after.scroll_misses == before.scroll_misses
        assert after.scroll_hits == before.scroll_hits + 1
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_live_pan_uses_scroll_buffer_reuse(qapp) -> None:
    """Pan-only viewport changes should use renderer-owned scroll reuse."""
    qpane = _make_qpane_with_checker_image(qapp)
    try:
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()
        qpane.setPan(QPointF(6.0, 0.0))
        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts + 1
        assert after.scroll_hits == before.scroll_hits + 1
        assert after.full_redraws == before.full_redraws
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_live_pan_falls_back_when_candidate_render_source_changes(
    qapp,
    monkeypatch,
) -> None:
    """A newly selected render source must invalidate the reused buffer interior."""
    qpane = _make_qpane_with_checker_image(qapp)
    try:
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()
        original_calculate = presenter.calculateRenderPlan

        def calculate_with_replaced_source(*, use_pan=None, is_blank=False):
            plan = original_calculate(use_pan=use_pan, is_blank=is_blank)
            if plan is None or use_pan is None:
                return plan
            base_item = plan.base_raster_item
            assert base_item is not None
            replacement_source = QImage(base_item.source_image)
            replacement_source.setPixel(
                0,
                0,
                replacement_source.pixel(0, 0) ^ 0x00FFFFFF,
            )
            replacement_item = replace(base_item, source_image=replacement_source)
            replacement_item = replace(
                replacement_item,
                descriptor=replace(
                    replacement_item.descriptor,
                    source_revision=replacement_item.descriptor.source_revision + 1,
                ),
            )
            return replace(plan, render_items=(replacement_item,))

        monkeypatch.setattr(
            presenter, "calculateRenderPlan", calculate_with_replaced_source
        )
        monkeypatch.setattr(
            renderer,
            "tryScrollBuffers",
            lambda *_args, **_kwargs: pytest.fail(
                "changed render sources must bypass scroll reuse"
            ),
        )

        qpane.setPan(QPointF(6.0, 0.0))

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts
        assert not renderer._dirty_region.isEmpty()
        assert renderer._dirty_region.boundingRect().contains(qpane.rect())
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_direct_pan_reuses_guard_without_replanning_frame_products(
    qapp,
    monkeypatch,
) -> None:
    """Keep stable render products off the direct-navigation hot path."""

    qpane = _make_qpane_with_checker_image(qapp)
    presenter = qpane.view().presenter
    try:
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()
        presenter.begin_navigation_interaction()
        monkeypatch.setattr(
            presenter,
            "calculateRenderPlan",
            lambda **_kwargs: pytest.fail(
                "guard-covered direct pan must not rebuild frame products"
            ),
        )

        qpane.setPan(QPointF(6.0, -4.0))

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts
        assert after.scroll_repairs == before.scroll_repairs
        current_plan = renderer.get_current_render_plan()
        assert current_plan is not None
        assert current_plan.current_pan == QPointF(6.0, -4.0)
        assert renderer._buffer_pan + renderer.get_subpixel_pan_offset() == QPointF(
            6.0,
            -4.0,
        )
    finally:
        presenter.finish_navigation_interaction()
        qpane.deleteLater()
        qapp.processEvents()


def test_warm_direct_pan_release_does_not_force_a_full_redraw(qapp) -> None:
    """An exact guarded pan must remain exact when navigation settles."""
    qpane = _make_qpane_with_checker_image(qapp)
    presenter = qpane.view().presenter
    try:
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()

        presenter.begin_navigation_interaction()
        qpane.setPan(QPointF(12.0, -8.0))
        presenter.finish_navigation_interaction()
        QTest.qWait(70)
        qapp.processEvents()

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts
        assert after.scroll_repairs == before.scroll_repairs
        assert after.full_redraws == before.full_redraws
        settled_buffer = renderer.get_base_buffer()
        assert settled_buffer is not None
        settled = rendered_overscanned_widget_frame(
            QImage(settled_buffer),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        renderer.markDirty()
        plan = presenter.calculateRenderPlan(is_blank=False)
        assert plan is not None
        renderer.paint(plan)
        clean_buffer = renderer.get_base_buffer()
        assert clean_buffer is not None
        clean = rendered_overscanned_widget_frame(
            QImage(clean_buffer),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        assert_images_match(settled, clean)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_direct_pan_checks_stable_products_without_repainting_overlap(
    qapp,
) -> None:
    """Active navigation should verify chronology while repairing only exposure."""
    qpane = _make_qpane_with_checker_image(qapp)
    presenter = qpane.view().presenter
    try:
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()
        presenter.begin_navigation_interaction()
        qpane.setPan(
            QPointF(
                float(renderer.buffer_overscan_physical_px + 8),
                0.0,
            )
        )

        after = renderer.snapshot_metrics()
        assert after.scroll_repairs == before.scroll_repairs + 1
    finally:
        presenter.finish_navigation_interaction()
        qpane.deleteLater()
        qapp.processEvents()


def test_direct_pan_release_atomically_replaces_a_repaired_ring_frame(qapp) -> None:
    """Settling must replace incrementally repaired pixels with one exact frame."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024)
    presenter = qpane.view().presenter
    try:
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = presenter.renderer
        before_renderer = renderer.snapshot_metrics()
        before_refinement = renderer.navigation_refinement_metrics()

        presenter.begin_navigation_interaction()
        qpane.setPan(
            QPointF(
                float(renderer.buffer_overscan_physical_px + 8),
                0.0,
            )
        )
        after_pan = renderer.snapshot_metrics()
        assert after_pan.scroll_repairs == before_renderer.scroll_repairs + 1
        assert not renderer._surface.storage_origin.isNull()

        presenter.finish_navigation_interaction()
        deadline = time.perf_counter() + 3.0
        while (
            presenter.navigation_refinement_pending and time.perf_counter() < deadline
        ):
            qapp.processEvents()
            QTest.qWait(1)

        assert not presenter.navigation_refinement_pending
        after_refinement = renderer.navigation_refinement_metrics()
        assert (
            after_refinement.completed_frames == before_refinement.completed_frames + 1
        )
        assert renderer._surface.storage_origin.isNull()
        settled = renderer.get_base_buffer()
        assert settled is not None
        renderer.markDirty()
        clean_plan = presenter.calculateRenderPlan(is_blank=False)
        assert clean_plan is not None
        renderer.paint(clean_plan)
        clean = renderer.get_base_buffer()
        assert clean is not None
        assert_images_match(settled, clean, tolerance=1)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_sampled_product_transition_stages_one_complete_guarded_frame(qapp) -> None:
    """Sampled cache transitions must never publish a partially updated guard."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024)
    presenter = qpane.view().presenter
    try:
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = presenter.renderer
        before_renderer = renderer.snapshot_metrics()
        before_refinement = renderer.navigation_refinement_metrics()

        presenter._handle_render_refinement_ready()
        assert presenter.navigation_refinement_pending

        deadline = time.perf_counter() + 3.0
        while (
            presenter.navigation_refinement_pending and time.perf_counter() < deadline
        ):
            qapp.processEvents()
            QTest.qWait(1)

        assert not presenter.navigation_refinement_pending
        after_renderer = renderer.snapshot_metrics()
        after_refinement = renderer.navigation_refinement_metrics()
        assert (
            after_refinement.completed_frames == before_refinement.completed_frames + 1
        )
        assert after_renderer.full_redraws == before_renderer.full_redraws
        assert renderer._buffer_valid_region == QRegion(renderer._surface.pixmap.rect())
    finally:
        qpane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("dpr", [1.25, 1.5, 2.0, 2.5, 3.0])
def test_live_high_dpi_pan_reuses_navigation_guard(
    qapp,
    dpr: float,
) -> None:
    """DPR-tagged buffers should reuse physical guard pixels without redrawing."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024, dpr=dpr)
    try:
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()

        qpane.setPan(QPointF(6.0, 0.0))
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts + 1
        assert after.scroll_misses == before.scroll_misses
        assert after.scroll_hits == before.scroll_hits + 1
        assert after.full_redraws == before.full_redraws
        presented_pan = renderer._buffer_pan + renderer.get_subpixel_pan_offset()
        assert presented_pan == QPointF(6.0, 0.0)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("zoom", [0.5, 0.75, 1.25, 1.5, 2.0, 3.75, 8.0])
def test_live_scaled_pan_reuses_exact_buffer_pixels(
    qapp,
    zoom: float,
) -> None:
    """Integer pan should repair scaled content identically to a clean redraw."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024)
    try:
        viewport = qpane.view().viewport
        viewport.setZoomAndPan(zoom, QPointF(0.0, 0.0))
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()

        qpane.setPan(QPointF(6.0, 0.0))
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts + 1
        assert after.scroll_hits == before.scroll_hits + 1
        reused_buffer = renderer.get_base_buffer()
        assert reused_buffer is not None
        reused = rendered_overscanned_widget_frame(
            QImage(reused_buffer),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        renderer.markDirty()
        reference_plan = presenter.calculateRenderPlan(is_blank=False)
        assert reference_plan is not None
        renderer.paint(reference_plan)
        reference = renderer.get_base_buffer()
        assert reference is not None
        reference_frame = rendered_overscanned_widget_frame(
            QImage(reference),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        assert_images_match(reused, reference_frame, tolerance=1)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_settled_zoom_builds_exact_frame_in_bounded_atomic_slices(qapp) -> None:
    """Zoom refinement must never block one full-surface renderer paint."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024)
    try:
        qpane.resize(1024, 768)
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()

        qpane.applyZoom(1.5, QPointF(qpane.rect().center()))
        QTest.qWait(70)
        deadline = time.perf_counter() + 3.0
        while (
            presenter.navigation_refinement_pending and time.perf_counter() < deadline
        ):
            qapp.processEvents()
            QTest.qWait(1)

        assert not presenter.navigation_refinement_pending
        staged = renderer.navigation_refinement_metrics()
        after = renderer.snapshot_metrics()
        assert staged.completed_frames == 1
        assert staged.maximum_step_ms < 16.0
        assert staged.maximum_publish_ms < 16.0
        assert after.full_redraws == before.full_redraws
        exact = renderer.get_base_buffer()
        assert exact is not None
        renderer.markDirty()
        plan = presenter.calculateRenderPlan(is_blank=False)
        assert plan is not None
        renderer.paint(plan)
        clean = renderer.get_base_buffer()
        assert clean is not None
        assert_images_match(exact, clean, tolerance=3)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.5, 3.0])
def test_live_fractional_physical_pan_reuses_navigation_guard(
    qapp,
    dpr: float,
) -> None:
    """Fractional physical pans should transform the settled composited frame."""
    qpane = _make_qpane_with_checker_image(qapp, size=1024, dpr=dpr)
    try:
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()

        qpane.setPan(QPointF(-25.5, -63.5))
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts + 1
        assert after.scroll_misses == before.scroll_misses
        assert after.scroll_hits == before.scroll_hits + 1
        assert after.full_redraws == before.full_redraws
        presented_pan = renderer._buffer_pan + renderer.get_subpixel_pan_offset()
        assert presented_pan == QPointF(-25.5, -63.5)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_live_pan_redraws_when_strip_repair_rejects(
    qapp,
    monkeypatch,
) -> None:
    """A rejected native strip repair must never leave a stale presented frame."""
    qpane = _make_qpane_with_checker_image(qapp)
    try:
        presenter = qpane.view().presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane.view().renderer
        before = renderer.snapshot_metrics()
        monkeypatch.setattr(
            renderer,
            "_repair_base_buffer_strips",
            lambda _rects, _plan: False,
        )

        qpane.setPan(QPointF(float(renderer.buffer_overscan_physical_px + 8), 0.0))
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        qapp.processEvents()

        after = renderer.snapshot_metrics()
        assert after.scroll_attempts == before.scroll_attempts + 1
        assert after.scroll_misses == before.scroll_misses + 1
        assert after.full_redraws == before.full_redraws + 1
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        renderer.markDirty()
        plan = presenter.calculateRenderPlan(is_blank=False)
        assert plan is not None
        renderer.paint(plan)
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        assert_images_match(incremental, repaired)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_public_scene_pan_reuses_exact_layered_pixels(qapp) -> None:
    """Multi-layer scenes should present guarded pan pixels exactly."""
    qpane = QPane()
    try:
        qpane.resize(96, 96)
        first = checker_image(QRect(0, 0, 128, 128).size())
        second = checker_image(QRect(0, 0, 128, 128).size())
        first_source = RasterSource.from_image(first)
        second_source = RasterSource.from_image(second)
        scene = RenderScene(
            canvas=QRectF(0.0, 0.0, 256.0, 128.0),
            layers=(
                RenderLayer(source=first_source),
                RenderLayer(
                    source=second_source,
                    transform=LayerTransform(dx=128.0),
                ),
            ),
        )
        qpane.setScene(scene)
        qpane.setZoom1To1()
        presenter = qpane._rendering.presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane._rendering.presenter.renderer
        before = renderer.snapshot_metrics()
        target_pan = QPointF(9.0, 4.0)
        qpane.setPan(target_pan)
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        after = renderer.snapshot_metrics()
        assert after.scroll_hits == before.scroll_hits + 1
        reused_buffer = renderer.get_base_buffer()
        assert reused_buffer is not None
        reused = rendered_overscanned_widget_frame(
            QImage(reused_buffer),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        renderer.markDirty()
        reference_plan = presenter.calculateRenderPlan(is_blank=False)
        assert reference_plan is not None
        renderer.paint(reference_plan)
        reference = renderer.get_base_buffer()
        assert reference is not None
        reference_frame = rendered_overscanned_widget_frame(
            QImage(reference),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        assert_images_match(reused, reference_frame)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_repeated_high_dpi_pan_repairs_match_independent_clean_frames(qapp) -> None:
    """Repeated two-axis ring repairs must never leave a settled displaced band."""

    def present_frame(renderer: Renderer) -> QImage:
        """Present one retained surface over a non-black host background."""
        frame = QImage(
            renderer._viewport_physical_size,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        frame.setDevicePixelRatio(1.75)
        frame.fill(QColor(187, 43, 91))
        painter = QPainter(frame)
        try:
            renderer.draw_base_buffer(painter)
        finally:
            painter.end()
        return frame

    def build_pane() -> QPane:
        """Return one identically configured layered high-DPI viewer."""
        pane = QPane()
        pane.resize(320, 180)
        pane.devicePixelRatioF = lambda: 1.75  # type: ignore[method-assign]
        first = checker_image(QRect(0, 0, 1024, 768).size())
        second = QImage(first)
        second.invertPixels()
        pane.setScene(
            RenderScene(
                canvas=QRectF(0.0, 0.0, 1024.0, 768.0),
                layers=(
                    RenderLayer(source=RasterSource.from_image(first)),
                    RenderLayer(
                        source=RasterSource.from_image(second),
                        transform=LayerTransform(dx=512.0),
                        opacity=0.35,
                    ),
                ),
            )
        )
        pane.applyZoom(5.0, QPointF(pane.rect().center()))
        pane._rendering.presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        return pane

    incremental = build_pane()
    reference = build_pane()
    incremental_presenter = incremental._rendering.presenter
    reference_presenter = reference._rendering.presenter
    incremental_renderer = incremental_presenter.renderer
    reference_renderer = reference_presenter.renderer
    pan_sequence = (
        QPointF(118.0, 74.0),
        QPointF(-96.0, 188.0),
        QPointF(264.0, -82.0),
        QPointF(-214.0, -176.0),
        QPointF(347.0, 239.0),
        QPointF(-331.0, 91.0),
        QPointF(43.0, -267.0),
    )
    try:
        incremental_presenter.begin_navigation_interaction()
        for target_pan in pan_sequence:
            incremental.setPan(target_pan)
            incremental_presenter.paint(
                is_blank=False,
                content_overlays={},
                scene_overlays={},
                overlays_suspended=False,
                draw_tool_overlay=None,
            )
            incremental_buffer = incremental_renderer.get_base_buffer()
            assert incremental_buffer is not None
            incremental_frame = rendered_overscanned_widget_frame(
                incremental_buffer,
                incremental_renderer.get_subpixel_pan_offset(),
                incremental_renderer._viewport_physical_size,
                incremental_renderer.buffer_overscan_physical_px,
            )

            reference_presenter.viewport.pan = QPointF(target_pan)
            reference_renderer.markDirty()
            reference_plan = reference_presenter.calculateRenderPlan(is_blank=False)
            assert reference_plan is not None
            reference_renderer.paint(reference_plan)
            reference_buffer = reference_renderer.get_base_buffer()
            assert reference_buffer is not None
            clean_frame = rendered_overscanned_widget_frame(
                reference_buffer,
                reference_renderer.get_subpixel_pan_offset(),
                reference_renderer._viewport_physical_size,
                reference_renderer.buffer_overscan_physical_px,
            )

            assert_images_match(incremental_frame, clean_frame, tolerance=1)
            assert_images_match(
                present_frame(incremental_renderer),
                present_frame(reference_renderer),
                tolerance=1,
            )
    finally:
        incremental_presenter.finish_navigation_interaction()
        incremental.deleteLater()
        reference.deleteLater()
        qapp.processEvents()


def test_clipped_public_scene_pan_reuses_exact_layered_pixels(qapp) -> None:
    """Scene clips should retain exact pixels in one linear storage phase."""
    qpane = QPane()
    try:
        qpane.resize(96, 96)
        first = checker_image(QRect(0, 0, 128, 128).size())
        second = checker_image(QRect(0, 0, 128, 128).size())
        second.invertPixels()
        scene = RenderScene(
            canvas=QRectF(0.0, 0.0, 256.0, 128.0),
            layers=(
                RenderLayer(source=RasterSource.from_image(first)),
                RenderLayer(
                    source=RasterSource.from_image(second),
                    clip=LayerClip(
                        coordinate_space=ClipCoordinateSpace.SCENE,
                        x=48.0,
                        y=0.0,
                        width=80.0,
                        height=128.0,
                    ),
                ),
            ),
        )
        qpane.setScene(scene)
        qpane.setZoom1To1()
        presenter = qpane._rendering.presenter
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        renderer = qpane._rendering.presenter.renderer
        before = renderer.snapshot_metrics()
        target_pan = QPointF(8.0, 0.0)
        qpane.setPan(target_pan)
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        after = renderer.snapshot_metrics()
        assert after.scroll_hits == before.scroll_hits + 1
        assert renderer._surface.storage_origin.isNull()
        reused_buffer = renderer.get_base_buffer()
        assert reused_buffer is not None
        reused = rendered_overscanned_widget_frame(
            QImage(reused_buffer),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        renderer.markDirty()
        reference_plan = presenter.calculateRenderPlan(is_blank=False)
        assert reference_plan is not None
        renderer.paint(reference_plan)
        reference = renderer.get_base_buffer()
        assert reference is not None
        reference_frame = rendered_overscanned_widget_frame(
            QImage(reference),
            renderer.get_subpixel_pan_offset(),
            renderer._viewport_physical_size,
            renderer.buffer_overscan_physical_px,
        )
        assert_images_match(reused, reference_frame)
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_base_only_predicate_accepts_default_raster_plan() -> None:
    """A single full-scene base raster item should qualify for fast paths."""
    plan = make_render_plan(QRect(0, 0, 64, 64))

    assert plan.base_raster_item is not None

    assert Renderer._base_only_raster_item(plan) is plan.base_raster_item


def test_base_only_predicate_rejects_mask_plan() -> None:
    """Mask render items must keep the layered renderer path."""
    mask_plan, _mask_item = _make_mask_plan(QRect(0, 0, 64, 64))

    assert Renderer._base_only_raster_item(mask_plan) is None


def test_base_only_predicate_rejects_clipped_plan() -> None:
    """Clipped reveal/comparison layers must keep visibility-aware rendering."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    base_item = plan.base_raster_item
    assert base_item is not None
    clip = LayerClip(
        coordinate_space=ClipCoordinateSpace.NORMALIZED_VIEWPORT,
        x=0.0,
        y=0.0,
        width=0.5,
        height=1.0,
    )
    clipped_item = replace(
        base_item,
        descriptor=replace(base_item.descriptor, clip=clip),
        clip=clip,
    )
    clipped_plan = replace(plan, render_items=(clipped_item,))

    assert Renderer._base_only_raster_item(clipped_plan) is None


def test_base_only_predicate_rejects_multi_image_plan() -> None:
    """Additional raster layers must keep the general scene renderer."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    base_item = plan.base_raster_item
    assert base_item is not None
    additional_item = replace(
        base_item,
        descriptor=replace(base_item.descriptor, layer_id=uuid.uuid4()),
    )
    layered_plan = replace(plan, render_items=(base_item, additional_item))

    assert Renderer._base_only_raster_item(layered_plan) is None


def test_base_dirty_redraw_uses_direct_fast_path(
    qpane_with_image,
    monkeypatch,
) -> None:
    """Base-only dirty redraw should not route through generic scene drawing."""
    qpane = qpane_with_image
    renderer = qpane.view().renderer
    plan = qpane.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    assert plan.base_raster_item is not None
    direct_calls = []

    def fail_generic_draw(*_args, **_kwargs):
        raise AssertionError("base dirty redraw should not draw the whole scene")

    monkeypatch.setattr(renderer._items, "draw_visible_items", fail_generic_draw)
    monkeypatch.setattr(
        renderer._items,
        "_draw_direct_view",
        lambda painter, item: direct_calls.append(item),
    )

    renderer.markDirty(qpane.rect())
    renderer.paint(plan)

    assert direct_calls == [plan.base_raster_item]


def test_layered_strip_repair_uses_normal_item_draw_paths(
    qpane_with_image,
    monkeypatch,
) -> None:
    """Layered repair should share item drawing with complete frames."""
    qpane = qpane_with_image
    renderer = qpane.view().renderer
    plan, mask_item = _make_mask_plan(qpane.rect())
    base_item = plan.base_raster_item
    assert base_item is not None
    margin = renderer.buffer_overscan_physical_px
    repair_rects = [QRect(margin, margin, 16, 16)]
    raster_calls = []
    monkeypatch.setattr(
        renderer._items,
        "draw_raster_item",
        lambda painter, render_plan, item, **_kwargs: raster_calls.append(
            (render_plan, item)
        ),
    )

    assert renderer._repair_layered_strips(repair_rects, plan) is True
    assert raster_calls == [(plan, base_item), (plan, mask_item)]


def test_try_scroll_buffers_accepts_near_integer_float_noise(
    qpane_with_image,
) -> None:
    """Insignificant float noise around device pixels should preserve reuse."""
    qpane = qpane_with_image
    view = qpane.view()
    renderer = view.renderer
    view.presenter.paint(
        is_blank=False,
        content_overlays={},
        scene_overlays={},
        overlays_suspended=False,
        draw_tool_overlay=None,
    )
    renderer._buffer_pan = QPointF(0.0, 0.0)
    noisy_integer_pan = QPointF(7.0000000001, 2.9999999999)
    view.viewport.pan = QPointF(noisy_integer_pan)
    result = renderer.tryScrollBuffers(noisy_integer_pan)
    assert result is True
    assert renderer._buffer_pan == noisy_integer_pan
    assert renderer.get_subpixel_pan_offset().isNull()


def test_try_scroll_buffers_rejects_large_scroll(qpane_with_image):
    qpane = qpane_with_image
    renderer = qpane.view().renderer
    renderer._buffer_pan = QPointF(0.0, 0.0)
    buffer = renderer.get_base_buffer()
    assert buffer is not None
    large_pan = QPointF(buffer.width() * 2, 0.0)
    assert renderer.has_scroll_buffer_overlap(large_pan) is False
    result = renderer.tryScrollBuffers(large_pan)
    assert result is False
    assert renderer._buffer_pan == QPointF(0.0, 0.0)


def test_try_scroll_buffers_requires_buffer(qapp):
    qpane = CuteCanvas(features=())
    try:
        renderer = qpane.view().renderer
        result = renderer.tryScrollBuffers(QPointF(1.0, 1.0))
    finally:
        qpane.deleteLater()
        qapp.processEvents()
    assert result is False
