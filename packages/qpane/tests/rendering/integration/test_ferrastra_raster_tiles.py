#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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

"""Integration proof for exact Ferrastra raster render tiles."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import QPane
from qpane.ferrastra import FerrastraRasterTileSource
from qpane.rendering.exact_raster_geometry import exact_visible_tile_requests
from qpane.scene.identity import source_render_asset_key
from qpane.scene.raster_sampling import RasterExactSampling, RasterPresentationSampling
from qpane.scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderPlan,
)
from qpane_test_support.execution_backend import TestExecution


def test_exact_raster_tile_preserves_requested_grid_and_authoritative_pixels() -> None:
    """Adapt a native sampled view into detached one-to-one presentation geometry."""
    image = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(72, 118, 214, 255))
    source = _source(image)
    requests = exact_visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=QTransform(2.3, 0.0, 0.0, 1.7, 0.25, -0.5),
        panel_rect=QRectF(0.0, 0.0, 120.0, 80.0),
        device_pixel_ratio=1.0,
        budget_bytes=8 * 1024 * 1024,
        exact_sampling=RasterExactSampling.NEAREST,
    )

    assert requests is not None and requests
    products = source.render_tiles(requests, lambda: False)

    assert len(products) == len(requests)
    for request, product in zip(requests, products, strict=True):
        assert product.key == request.key
        assert product.image.size().toTuple() == (516, 516)
        assert product.image_source_rect == QRectF(2.0, 2.0, 512.0, 512.0)
        assert product.source_clip_rect == product.source_rect.intersected(
            QRectF(0.0, 0.0, 64.0, 48.0)
        )
        assert product.image.pixelColor(258, 258) == QColor(72, 118, 214, 255)


def test_native_cancellation_publishes_no_partial_tile_batch() -> None:
    """Cancellation subscribed before evaluation suppresses every tile product."""
    image = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("black"))
    source = _source(image)
    requests = exact_visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=QTransform.fromScale(2.0, 2.0),
        panel_rect=QRectF(0.0, 0.0, 100.0, 80.0),
        device_pixel_ratio=1.0,
        budget_bytes=8 * 1024 * 1024,
        exact_sampling=RasterExactSampling.NEAREST,
    )

    assert requests is not None and requests
    cancellation = _CancelOnSubscription()

    assert source.render_tiles(requests, cancellation) == ()


def test_affine_raster_tile_is_projected_directly_on_the_panel_physical_grid() -> None:
    """Rotation produces panel-space native pixels without a final smooth transform."""
    image = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(72, 118, 214, 255))
    source = _source(image)
    transform = QTransform()
    transform.translate(50.0, 30.0)
    transform.rotate(20.0)
    requests = exact_visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=transform,
        panel_rect=QRectF(0.0, 0.0, 160.0, 120.0),
        device_pixel_ratio=2.0,
        budget_bytes=16 * 1024 * 1024,
        exact_sampling=RasterExactSampling.AFFINE_BILINEAR,
    )

    assert requests is not None and requests
    products = source.render_tiles(requests, lambda: False)

    assert len(products) == len(requests)
    assert all(product.image.devicePixelRatio() == 2.0 for product in products)
    assert all(product.source_clip_rect == product.source_rect for product in products)


def test_nearest_exact_tile_preserves_high_frequency_source_pixels_at_200_percent() -> (
    None
):
    """Settled 200% output must repeat source pixels without reconstructed colors."""
    image = QImage(3, 1, QImage.Format_ARGB32_Premultiplied)
    colors = (QColor("red"), QColor("green"), QColor("blue"))
    for x, color in enumerate(colors):
        image.setPixelColor(x, 0, color)
    source = _source(image)
    requests = exact_visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=QTransform.fromScale(2.0, 2.0),
        panel_rect=QRectF(0.0, 0.0, 6.0, 2.0),
        device_pixel_ratio=1.0,
        budget_bytes=8 * 1024 * 1024,
        exact_sampling=RasterExactSampling.NEAREST,
    )

    assert requests is not None and len(requests) == 1
    product = source.render_tiles(requests, lambda: False)[0]

    assert product.key.exact_sampling is RasterExactSampling.NEAREST
    assert [product.image.pixelColor(x, 2) for x in range(2, 8)] == [
        QColor("red"),
        QColor("red"),
        QColor("green"),
        QColor("green"),
        QColor("blue"),
        QColor("blue"),
    ]
    assert all(product.image.pixelColor(x, 2).alpha() == 255 for x in range(10))


def test_affine_nearest_exact_tile_contains_only_authoritative_source_colors() -> None:
    """A settled high-zoom rotation selects pixels without affine reconstruction."""
    image = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
    colors = (QColor("red"), QColor("green"), QColor("blue"), QColor("white"))
    for index, color in enumerate(colors):
        image.setPixelColor(index % 2, index // 2, color)
    source = _source(image)
    transform = QTransform()
    transform.translate(20.0, 20.0)
    transform.rotate(20.0)
    transform.scale(3.0, 3.0)
    requests = exact_visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=transform,
        panel_rect=QRectF(0.0, 0.0, 48.0, 48.0),
        device_pixel_ratio=1.0,
        budget_bytes=8 * 1024 * 1024,
        exact_sampling=RasterExactSampling.NEAREST,
    )

    assert requests is not None and requests
    product = source.render_tiles(requests, lambda: False)[0]
    observed = {
        product.image.pixelColor(x, y).toTuple()
        for y in range(product.image.height())
        for x in range(product.image.width())
    }

    assert product.key.exact_sampling is RasterExactSampling.NEAREST
    assert observed == {color.toTuple() for color in colors}


def test_mounted_raster_uses_preview_then_atomically_adopts_exact_tiles(
    qapp: QApplication,
) -> None:
    """The ordinary viewer settles onto exact physical-grid products without setup."""
    execution = TestExecution(auto_finish=False)
    pane = QPane(execution_runtime=execution.runtime)
    pane.resize(480, 320)
    image = QImage(320, 240, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(72, 118, 214, 255))
    try:
        pane.setImage(image, fit=False)
        pane.show()
        qapp.processEvents()
        preview = pane.calculateRenderPlan()
        assert preview is not None
        assert isinstance(preview.render_items[0], RasterLayerRenderItem)

        exact = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(exact.render_items[0], SampledLayerRenderItem)
        sampled = exact.render_items[0]
        assert sampled.tiles
        assert sampled.presentation_sampling is RasterPresentationSampling.NEAREST
        assert all(
            tile.exact_sampling is RasterExactSampling.LANCZOS3
            for tile in sampled.tiles
        )
        assert all(tile.image.size().toTuple() == (516, 516) for tile in sampled.tiles)

        pane.applyZoom(pane.currentZoom() * 1.25)
        qapp.processEvents()
        moved_preview = pane.calculateRenderPlan()
        assert moved_preview is not None
        assert isinstance(moved_preview.render_items[0], RasterLayerRenderItem)

        moved_exact = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(moved_exact.render_items[0], SampledLayerRenderItem)

        pane.applyZoom(2.0)
        qapp.processEvents()
        sharp_preview = pane.calculateRenderPlan()
        assert sharp_preview is not None
        assert sharp_preview.render_items[0].presentation_sampling is (
            RasterPresentationSampling.NEAREST
        )
        sharp_exact = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(sharp_exact.render_items[0], SampledLayerRenderItem)
        assert all(
            tile.exact_sampling is RasterExactSampling.NEAREST
            for tile in sharp_exact.render_items[0].tiles
        )

        pane.applyZoom(1.99)
        qapp.processEvents()
        reconstructed_preview = pane.calculateRenderPlan()
        assert reconstructed_preview is not None
        assert reconstructed_preview.render_items[0].presentation_sampling is (
            RasterPresentationSampling.BILINEAR
        )
        reconstructed_exact = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(reconstructed_exact.render_items[0], SampledLayerRenderItem)
        assert all(
            tile.exact_sampling is RasterExactSampling.LANCZOS3
            for tile in reconstructed_exact.render_items[0].tiles
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_crossing_200_percent_retires_pending_reconstruction_work(
    qapp: QApplication,
) -> None:
    """A late below-threshold request cannot publish into a nearest frame."""
    execution = TestExecution(auto_finish=False)
    pane = QPane(execution_runtime=execution.runtime)
    pane.resize(480, 320)
    image = QImage(320, 240, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("black"))
    try:
        pane.setImage(image, fit=False)
        pane.show()
        qapp.processEvents()
        pane.calculateRenderPlan()
        pending_reconstruction = tuple(
            job
            for job in execution.pending_jobs()
            if job.operation.startswith("render.refinement")
        )
        assert pending_reconstruction

        pane.applyZoom(2.0)
        qapp.processEvents()
        sharp_preview = pane.calculateRenderPlan()

        assert sharp_preview is not None
        assert sharp_preview.render_items[0].presentation_sampling is (
            RasterPresentationSampling.NEAREST
        )
        assert any(job in execution.cancelled for job in pending_reconstruction)
        sharp_exact = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(sharp_exact.render_items[0], SampledLayerRenderItem)
        assert all(
            tile.exact_sampling is RasterExactSampling.NEAREST
            for tile in sharp_exact.render_items[0].tiles
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_mounted_source_native_threshold_is_stable_on_high_dpi(
    qapp: QApplication,
) -> None:
    """Display density cannot move the base image's 200% nearest boundary."""
    execution = TestExecution(auto_finish=False)
    pane = QPane(execution_runtime=execution.runtime)
    pane.devicePixelRatioF = lambda: 2.0  # type: ignore[method-assign]
    pane.resize(320, 240)
    image = QImage(128, 96, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("blue"))
    try:
        pane.setImage(image, fit=False)
        pane.show()
        pane.applyZoom(1.99)
        qapp.processEvents()
        reconstructed_preview = pane.calculateRenderPlan()
        assert reconstructed_preview is not None
        assert reconstructed_preview.render_items[0].presentation_sampling is (
            RasterPresentationSampling.BILINEAR
        )
        reconstructed_exact = _settle_exact_raster(pane, execution, qapp)
        assert all(
            tile.exact_sampling is RasterExactSampling.LANCZOS3
            for tile in reconstructed_exact.render_items[0].tiles
        )

        pane.applyZoom(2.0)
        qapp.processEvents()
        nearest_preview = pane.calculateRenderPlan()
        assert nearest_preview is not None
        assert nearest_preview.render_items[0].presentation_sampling is (
            RasterPresentationSampling.NEAREST
        )
        nearest_exact = _settle_exact_raster(pane, execution, qapp)
        assert all(
            tile.exact_sampling is RasterExactSampling.NEAREST
            for tile in nearest_exact.render_items[0].tiles
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_nearest_preview_and_settled_frame_are_identical_after_fractional_pan(
    qapp: QApplication,
) -> None:
    """Exact nearest adoption must not alter an already-correct nearest frame."""
    execution = TestExecution(auto_finish=False)
    pane = QPane(execution_runtime=execution.runtime)
    pane.resize(128, 96)
    image = QImage(32, 24, QImage.Format_ARGB32_Premultiplied)
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(
                x,
                y,
                QColor("white") if (x + y) % 2 else QColor("black"),
            )
    try:
        pane.setImage(image, fit=False)
        pane.show()
        pane.applyZoom(2.0)
        pane.setPan(QPointF(0.25, -0.5))
        pane.update()
        qapp.processEvents()
        preview_plan = pane.calculateRenderPlan()
        assert preview_plan is not None
        assert isinstance(preview_plan.render_items[0], RasterLayerRenderItem)
        preview = pane.grab().toImage()

        exact_plan = _settle_exact_raster(pane, execution, qapp)
        assert isinstance(exact_plan.render_items[0], SampledLayerRenderItem)
        pane.update()
        qapp.processEvents()
        exact = pane.grab().toImage()

        assert exact == preview
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


class _CancelOnSubscription:
    """Cancel deterministically when native evaluation subscribes."""

    def __init__(self) -> None:
        """Initialize an active test cancellation source."""
        self._cancelled = False

    def __call__(self) -> bool:
        """Return whether subscription has initiated cancellation."""
        return self._cancelled

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Cancel immediately and return a no-op unsubscription."""
        self._cancelled = True
        callback()
        return lambda: None


def _source(image: QImage) -> FerrastraRasterTileSource:
    """Return one deterministic immutable raster tile adapter."""
    return FerrastraRasterTileSource(
        image,
        source_render_asset_key(
            source_id=uuid.UUID(int=7),
            source_kind="test-raster",
            revision=3,
            source_path=None,
        ),
    )


def _settle_exact_raster(
    pane: QPane,
    execution: TestExecution,
    application: QApplication,
) -> SceneRenderPlan:
    """Drive continuity and exact detail through the mounted publication boundary."""
    for _ in range(8):
        plan = pane.calculateRenderPlan()
        if plan is not None and isinstance(
            plan.render_items[0],
            SampledLayerRenderItem,
        ):
            return plan
        pending = tuple(
            job
            for job in execution.pending_jobs()
            if job.operation.startswith("render.refinement")
        )
        for _job in pending:
            execution.run_operation("render.refinement")
        application.processEvents()
        if not pending:
            QTest.qWait(60)
            application.processEvents()
    raise AssertionError("exact raster refinement did not settle")
