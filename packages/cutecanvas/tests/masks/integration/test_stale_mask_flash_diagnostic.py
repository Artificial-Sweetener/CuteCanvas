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

"""Reproduce stale sampled mask fallback after partial erasure."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QSize
from PySide6.QtWidgets import QApplication

from cutecanvas_test_support.harness.abuse_model import (
    HarnessPoint,
    PointerKind,
    StrokeAction,
)
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from qpane.rendering.render_tile_geometry import RenderTileRequest
from qpane.rendering.render_tile_types import RenderTileProduct


@pytest.mark.interactive_performance
def test_erased_mask_revision_is_not_used_as_navigation_fallback(
    qapp: QApplication,
) -> None:
    """A cold current revision must not reuse pixels erased from an older one."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(800, 600),
        mask_count=1,
        brush_size=40,
        cache_budget_mb=64,
    )
    driver = QtStrokeDriver(harness)
    retained_point = QPoint(400, 220)
    removed_point = QPoint(400, 320)
    strokes = (
        StrokeAction(
            PointerKind.MOUSE,
            points=(
                HarnessPoint(300, 220),
                HarnessPoint(500, 220),
                HarnessPoint(500, 420),
                HarnessPoint(300, 420),
            ),
            brush_size=40,
        ),
        StrokeAction(
            PointerKind.MOUSE,
            points=(HarnessPoint(380, 320), HarnessPoint(420, 320)),
            brush_size=40,
        ),
    )
    presenter = harness.viewer.view().presenter
    tile_cache = presenter._render_tile_cache
    try:
        harness.viewer.setZoom1To1(QPoint(400, 300))
        harness.drain_events(wait_ms=20)
        removed_source_point = (
            harness.viewer.activeMaskLayerCoordinates().panel_to_source(removed_point)
        )
        assert removed_source_point is not None
        for depth, stroke, point in (
            (1, strokes[0], retained_point),
            (2, strokes[1], removed_point),
        ):
            driver.begin(stroke)
            for point_index in range(1, len(stroke.points)):
                driver.move(stroke, point_index)
            driver.end(stroke)
            assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], depth)
            assert harness.wait_for_mask_tint(point).latency_ms is not None
        assert harness.wait_for_mask_render_idle(timeout_ms=5000)
        assert harness.wait_for_render_refinement_idle(timeout_ms=5000)

        stale_products = tuple(tile_cache._entries.values())
        assert any(
            _product_alpha_at(product, removed_source_point) > 0
            for product in stale_products
        )
        tile_cache.set_budget(0)

        assert harness.viewer.undoMaskEdit()
        assert harness.wait_for_background(removed_point).latency_ms is not None

        presenter._render_refinement.suspend_for_navigation()
        tile_cache.set_budget(64 * 1024 * 1024)
        tile_cache.admit(stale_products)
        harness.viewer.view().invalidate_content_cache()
        presenter.invalidate_frame_plan()

        selected_fallbacks: list[RenderTileProduct] = []
        original_presentation_products = tile_cache.presentation_products

        def record_presentation_products(
            requests: tuple[RenderTileRequest, ...],
        ) -> tuple[RenderTileProduct, ...] | None:
            """Record fallback products chosen for the hostile cold request."""
            products = original_presentation_products(requests)
            selected_fallbacks.extend(products or ())
            return products

        tile_cache.presentation_products = record_presentation_products
        try:
            compiled = presenter._scene_compiler.compiled_scene()
            assert compiled is not None
            current_source = next(
                layer.snapshot
                for layer in compiled.hybrid_layers
                if layer.descriptor.kind.value == "mask"
            )
            pan_offset = QPoint(180, 0)
            with harness.observe_presented_frames() as frame_probe:
                plan = presenter.calculateRenderPlan(
                    use_pan=QPointF(harness.viewer.getPan()) + QPointF(pan_offset)
                )
                assert plan is not None
                presenter.renderer.paint(plan)
        finally:
            tile_cache.presentation_products = original_presentation_products

        current_revision = (
            current_source.document.revision,
            current_source.presentation_revision,
        )
        stale_selected = tuple(
            product
            for product in selected_fallbacks
            if product.key.revision_key != current_revision
            and _product_alpha_at(product, removed_source_point) > 0
        )
        assert not stale_selected, {
            "current_revision": current_revision,
            "selected_revisions": tuple(
                product.key.revision_key for product in stale_selected
            ),
            "erased_point_alpha": tuple(
                _product_alpha_at(product, removed_source_point)
                for product in stale_selected
            ),
        }
        assert frame_probe.frames
        translated_removed_point = removed_point + pan_offset
        assert all(
            harness.is_background(frame.color_at(translated_removed_point))
            for frame in frame_probe.frames
        )
    finally:
        harness.close()


def _product_alpha_at(product: RenderTileProduct, source_point: QPointF) -> int:
    """Return one sampled-product alpha at a source coordinate."""
    source_rect = product.source_rect
    if not source_rect.contains(source_point):
        return 0
    image_rect = product.image_source_rect
    x_position = round(
        image_rect.x()
        + (source_point.x() - source_rect.x())
        * image_rect.width()
        / source_rect.width()
    )
    y_position = round(
        image_rect.y()
        + (source_point.y() - source_rect.y())
        * image_rect.height()
        / source_rect.height()
    )
    return product.image.pixelColor(x_position, y_position).alpha()
