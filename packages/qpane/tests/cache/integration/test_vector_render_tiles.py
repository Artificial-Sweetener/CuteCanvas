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
"""Correctness and lifecycle tests for asynchronous vector refinement."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.rendering.render_tile_cache import RenderTileCache
from qpane.rendering.render_tile_geometry import (
    RenderTileKey,
    RenderTileRequest,
    visible_tile_requests,
)
from qpane.rendering.render_tile_types import RenderRefinement, RenderTileProduct
from qpane.rendering.render_tiles import RenderTileWorkCoordinator
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.vector.drawing import draw_vector_document
from qpane.vector.model import VectorDocument, VectorObject
from qpane.vector.public import VectorObjectKind, VectorShapeKind, VectorStyle
from qpane.vector.tile_source import VectorRenderTileSource
from qpane_test_support.execution_backend import ControlledExecution
from qpane_test_support.qt_events import wait_until


def test_refined_tiles_match_direct_vector_drawing(qapp: QApplication) -> None:
    """Tile bleed and source projection must reproduce direct raster pixels."""
    document = _document(12)
    executor = ControlledExecution()
    cache = RenderTileCache(8 * 1024 * 1024)
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=_ready,
    )
    transform = QTransform.fromScale(4.0, 4.0)
    try:
        assert coordinator.request(
            source=VectorRenderTileSource(document, (document.revision, 0)),
            source_to_panel=transform,
            panel_rect=QRectF(0.0, 0.0, 1024.0, 768.0),
            device_pixel_ratio=1.0,
        ).pending
        assert coordinator.pending_count == 2
        _run_all_refinement(executor, qapp)
        refinement = coordinator.request(
            source=VectorRenderTileSource(document, (document.revision, 0)),
            source_to_panel=transform,
            panel_rect=QRectF(0.0, 0.0, 1024.0, 768.0),
            device_pixel_ratio=1.0,
        )
        assert refinement.products is not None
        products = refinement.products
        assert ready_count == 2
        tiled = _transparent_image(1024, 768)
        painter = QPainter(tiled)
        try:
            painter.setTransform(transform)
            for product in products:
                painter.drawImage(
                    product.source_rect,
                    product.image,
                    product.image_source_rect,
                )
        finally:
            painter.end()
        direct = _transparent_image(1024, 768)
        painter = QPainter(direct)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setTransform(transform)
            draw_vector_document(painter, document)
        finally:
            painter.end()
        assert (qimage_to_numpy_argb32(tiled) == qimage_to_numpy_argb32(direct)).all()
    finally:
        coordinator.shutdown()


def test_vector_detail_waits_for_idle_after_continuity(
    qapp: QApplication,
) -> None:
    """Exact detail must not contend with input as soon as continuity arrives."""
    executor = ControlledExecution()
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=RenderTileCache(8 * 1024 * 1024),
        ready=lambda: None,
    )
    document = _document(12)
    try:
        assert coordinator.request(
            source=VectorRenderTileSource(document, document.revision),
            source_to_panel=QTransform.fromScale(4.0, 4.0),
            panel_rect=QRectF(0.0, 0.0, 1024.0, 768.0),
            device_pixel_ratio=1.0,
        ).pending
        assert tuple(job.operation for job in executor.pending_jobs()) == (
            "render.refinement.continuity",
        )

        executor.run_operation("render.refinement.continuity")
        qapp.processEvents()
        assert not executor.pending_jobs()

        QTest.qWait(100)
        qapp.processEvents()
        assert tuple(job.operation for job in executor.pending_jobs()) == (
            "render.refinement.detail",
        )
    finally:
        coordinator.shutdown()


def test_latest_refinement_wins_and_cache_stays_bounded(qapp: QApplication) -> None:
    """Superseded work cannot publish and cache pressure must evict exactly."""
    executor = ControlledExecution()
    cache = RenderTileCache(2 * 512 * 512 * 4)
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=_ready,
    )
    first = _document(8)
    changed = first.replace_object(
        VectorObject(
            first.objects[0].object_id,
            VectorObjectKind.SHAPE,
            (17.0, 13.0, 70.0, 50.0),
            LayerTransform(),
            first.objects[0].style,
            VectorShapeKind.ELLIPSE,
        )
    )
    request_args = {
        "source_to_panel": QTransform.fromScale(4.0, 4.0),
        "panel_rect": QRectF(0.0, 0.0, 1024.0, 768.0),
        "device_pixel_ratio": 1.0,
    }
    try:
        assert coordinator.request(
            source=VectorRenderTileSource(first, first.revision),
            **request_args,
        ).pending
        assert coordinator.request(
            source=VectorRenderTileSource(changed, changed.revision),
            **request_args,
        ).pending
        assert len(executor.cancelled) == 1
        _run_all_refinement(executor, qapp)
        refinement = coordinator.request(
            source=VectorRenderTileSource(changed, changed.revision),
            **request_args,
        )
        assert refinement.products is not None
        products = refinement.products
        assert all(product.key.revision_key == changed.revision for product in products)
        assert ready_count == 2
        assert cache.usage_bytes <= 2 * 512 * 512 * 4
    finally:
        coordinator.shutdown()


def test_completed_superseded_refinement_cannot_retire_latest_request(
    qapp: QApplication,
) -> None:
    """Late owner adoption must not remove a newer request in the same lane."""
    executor = ControlledExecution()
    cache = RenderTileCache(8 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    original = _document(8)
    changed = original.replace_object(
        VectorObject(
            original.objects[0].object_id,
            VectorObjectKind.SHAPE,
            (17.0, 13.0, 70.0, 50.0),
            LayerTransform(),
            original.objects[0].style,
            VectorShapeKind.ELLIPSE,
        )
    )
    request_args = {
        "source_to_panel": QTransform.fromScale(4.0, 4.0),
        "panel_rect": QRectF(0.0, 0.0, 1024.0, 768.0),
        "device_pixel_ratio": 1.0,
    }
    try:
        assert coordinator.request(
            source=VectorRenderTileSource(original, original.revision),
            **request_args,
        ).pending
        executor.run_operation("render.refinement.continuity")
        assert coordinator.request(
            source=VectorRenderTileSource(changed, changed.revision),
            **request_args,
        ).pending

        qapp.processEvents()

        assert coordinator.pending_count == 2
        _run_all_refinement(executor, qapp)
        refinement = coordinator.request(
            source=VectorRenderTileSource(changed, changed.revision),
            **request_args,
        )
        assert refinement.exact and refinement.products
        assert all(
            product.key.revision_key == changed.revision
            for product in refinement.products
        )
    finally:
        coordinator.shutdown()


def test_rejection_and_shutdown_remain_bounded(qapp: QApplication) -> None:
    """Rejected and teardown work must not retry-loop or publish."""
    executor = ControlledExecution(rejection_counts={"render.refinement.continuity": 1})
    cache = RenderTileCache()
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=_ready,
    )
    document = _document(4)
    args = {
        "source": VectorRenderTileSource(document, document.revision),
        "source_to_panel": QTransform(),
        "panel_rect": QRectF(0.0, 0.0, 256.0, 192.0),
        "device_pixel_ratio": 1.0,
    }
    assert not coordinator.request(**args).pending
    _run_refinement_turn(executor, qapp)
    assert not coordinator.request(**args).pending
    assert len(executor.rejections) == 1
    coordinator.shutdown()
    executor.run_all()
    qapp.processEvents()
    assert ready_count == 1
    assert coordinator.pending_count == 0

    disabled = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=RenderTileCache(0),
        ready=_ready,
    )
    unavailable = disabled.request(**args)
    assert unavailable.products is None
    assert not unavailable.pending
    disabled.shutdown()


def test_fallback_is_atomic_and_limited_to_visual_compatibility_identity(
    qapp: QApplication,
) -> None:
    """Only revisions with identical rendered content may reuse settled tiles."""
    executor = ControlledExecution()
    cache = RenderTileCache(8 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    original = _document(6)
    request_args = {
        "source_to_panel": QTransform(),
        "panel_rect": QRectF(0.0, 0.0, 256.0, 192.0),
        "device_pixel_ratio": 1.0,
    }
    try:
        assert coordinator.request(
            source=VectorRenderTileSource(original, 0),
            **request_args,
        ).pending
        _run_all_refinement(executor, qapp)
        exact = coordinator.request(
            source=VectorRenderTileSource(original, 0),
            **request_args,
        )
        assert exact.exact and exact.products

        compatible = coordinator.request(
            source=VectorRenderTileSource(original, 1),
            **request_args,
        )
        assert compatible.pending and not compatible.exact
        assert compatible.products == exact.products

        revised = VectorDocument(
            original.vector_id,
            original.bounds,
            original.objects,
            revision=original.revision + 1,
        )
        changed_content = coordinator.request(
            source=VectorRenderTileSource(revised, 2),
            **request_args,
        )
        assert changed_content.pending and changed_content.products is None

        resized = VectorDocument(
            original.vector_id,
            RasterBounds(-20, 0, 276, 192),
            original.objects,
            revision=original.revision + 2,
        )
        changed_geometry = coordinator.request(
            source=VectorRenderTileSource(resized, 3),
            **request_args,
        )
        assert changed_geometry.pending and changed_geometry.products is None
    finally:
        coordinator.shutdown()


def test_guarded_tiles_keep_newly_visible_vector_content_exact_during_pan(
    qapp: QApplication,
) -> None:
    """A settled view must already contain the next tiles exposed by panning."""
    executor = ControlledExecution()
    cache = RenderTileCache(24 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    panel_rect = QRectF(0.0, 0.0, 1024.0, 768.0)

    def request_at(panel_x: float) -> RenderRefinement:
        """Request one high-zoom viewport translated by ``panel_x``."""
        return coordinator.request(
            source=VectorRenderTileSource(document, document.revision),
            source_to_panel=QTransform(4.0, 0.0, 0.0, 4.0, panel_x, 0.0),
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        )

    try:
        initial = request_at(0.0)
        assert initial.pending and initial.products is None
        initial_tile_count = coordinator.pending_tile_count
        assert initial_tile_count > 1
        _run_all_refinement(executor, qapp)
        assert request_at(0.0).exact
        wait_until(
            qapp,
            lambda: executor.pending_count > 0 or not coordinator.prefetch_pending,
            failure_message="settled vector guard prefetch did not become runnable",
        )
        _run_all_refinement(executor, qapp)

        first_exposed = request_at(-520.0)
        assert first_exposed.exact
        assert first_exposed.products

        second_exposed = request_at(-1040.0)
        assert second_exposed.exact
        assert second_exposed.products
        assert coordinator.pending_count == 0
        assert coordinator.pending_tile_count == 0
        assert not executor.cancelled

        wait_until(
            qapp,
            lambda: executor.pending_count > 0 or not coordinator.prefetch_pending,
            failure_message="settled vector guard prefetch did not become runnable",
        )
        _run_all_refinement(executor, qapp)
        third_exposed = request_at(-1560.0)
        assert third_exposed.exact
        assert third_exposed.products
        assert not executor.cancelled
    finally:
        coordinator.shutdown()


def test_memory_pressure_cancels_prefetch_without_visible_refinement(
    qapp: QApplication,
) -> None:
    """Foreground pressure must retire only speculative guard-tile work."""
    executor = ControlledExecution()
    cache = RenderTileCache(24 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    request = {
        "source": VectorRenderTileSource(document, document.revision),
        "source_to_panel": QTransform(4.0, 0.0, 0.0, 4.0, 0.0, 0.0),
        "panel_rect": QRectF(0.0, 0.0, 1024.0, 768.0),
        "device_pixel_ratio": 1.0,
    }
    try:
        assert coordinator.request(**request).pending
        _run_all_refinement(executor, qapp)
        assert coordinator.request(**request).exact
        assert coordinator.pending_count == 0
        assert coordinator.prefetch_pending

        released = coordinator.release_speculative("frame_resize")

        assert released > 0
        assert coordinator.pending_count == 0
        assert not coordinator.prefetch_pending
    finally:
        coordinator.shutdown()


def test_overview_fallback_covers_an_arbitrary_high_zoom_pan(
    qapp: QApplication,
) -> None:
    """A distant viewport must retain coarse complete content while refining."""
    executor = ControlledExecution()
    cache = RenderTileCache(24 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    panel_rect = QRectF(0.0, 0.0, 1024.0, 768.0)
    initial_transform = QTransform(4.0, 0.0, 0.0, 4.0, 0.0, 0.0)
    distant_transform = QTransform(4.0, 0.0, 0.0, 4.0, -5000.0, -5000.0)
    source = VectorRenderTileSource(document, document.revision)
    try:
        assert coordinator.request(
            source=source,
            source_to_panel=initial_transform,
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        ).pending
        _run_refinement_turn(executor, qapp)
        _run_refinement_turn(executor, qapp)

        distant = coordinator.request(
            source=source,
            source_to_panel=distant_transform,
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        )
        assert distant.pending and not distant.exact
        assert distant.products
        visible = visible_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=distant_transform,
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
            budget_bytes=cache.budget_bytes,
        )
        assert visible
        assert all(
            any(
                product.source_rect.contains(request.source_rect)
                for product in distant.products
            )
            for request in visible
        )
        assert max(product.key.scale for product in distant.products) < 4.0
    finally:
        coordinator.shutdown()


def test_visible_tile_requests_cap_pixel_grid_products_at_native_resolution() -> None:
    """Pixel-grid layers should enlarge native samples instead of baking blur."""
    source_id = uuid.uuid4()
    requests = visible_tile_requests(
        source_kind="pixel-grid",
        source_id=source_id,
        revision_key=1,
        fallback_key=1,
        bounds=RasterBounds(0, 0, 256, 256),
        source_to_panel=QTransform.fromScale(4.0, 4.0),
        panel_rect=QRectF(0.0, 0.0, 512.0, 512.0),
        device_pixel_ratio=1.0,
        budget_bytes=64 * 1024 * 1024,
        maximum_scale=1.0,
    )

    assert requests is not None
    assert requests
    assert {request.key.scale for request in requests} == {1.0}


def test_pan_storm_cannot_cancel_whole_source_continuity_work(
    qapp: QApplication,
) -> None:
    """Viewport churn must replace detail work without starving stable coverage."""
    executor = ControlledExecution()
    cache = RenderTileCache(24 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    source = VectorRenderTileSource(document, document.revision)
    panel_rect = QRectF(0.0, 0.0, 1024.0, 768.0)

    def request_at(panel_x: float) -> RenderRefinement:
        """Request one translated high-density viewport."""
        return coordinator.request(
            source=source,
            source_to_panel=QTransform(4.0, 0.0, 0.0, 4.0, panel_x, 0.0),
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        )

    try:
        assert request_at(0.0).pending
        for panel_x in range(-400, -6401, -400):
            assert request_at(float(panel_x)).pending
        assert coordinator.pending_count == 2
        assert len(executor.cancelled) < 16

        _run_refinement_turn(executor, qapp)
        _run_refinement_turn(executor, qapp)
        distant = request_at(-6400.0)
        assert distant.products
        assert distant.exact
        assert max(product.key.scale for product in distant.products) >= 1.0
    finally:
        coordinator.shutdown()


def test_pan_uses_exact_cached_tiles_over_fallback_for_newly_exposed_coverage(
    qapp: QApplication,
) -> None:
    """Newly exposed fallback must not degrade exact pixels already cached."""
    executor = ControlledExecution()
    cache = RenderTileCache(24 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    source = VectorRenderTileSource(document, document.revision)
    panel_rect = QRectF(0.0, 0.0, 1024.0, 768.0)

    def request_at(panel_x: float) -> RenderRefinement:
        """Request one translated high-density viewport."""
        return coordinator.request(
            source=source,
            source_to_panel=QTransform(4.0, 0.0, 0.0, 4.0, panel_x, 0.0),
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        )

    try:
        assert request_at(0.0).pending
        _run_all_refinement(executor, qapp)
        exact = request_at(0.0)
        assert exact.exact and exact.products
        assert {product.key.scale for product in exact.products} == {4.0}

        adjacent = request_at(-1200.0)
        assert not adjacent.exact and adjacent.products
        scales = {product.key.scale for product in adjacent.products}
        assert 4.0 in scales
        assert min(scales) < 1.0

        restored = request_at(0.0)
        assert restored.exact and restored.products
        assert {product.key.scale for product in restored.products} == {4.0}
    finally:
        coordinator.shutdown()


def test_small_budget_reserves_whole_source_continuity_before_detail(
    qapp: QApplication,
) -> None:
    """A constrained cache must retain compatible coverage for a distant pan."""
    executor = ControlledExecution()
    cache = RenderTileCache(3 * 1024 * 1024)
    coordinator = RenderTileWorkCoordinator(
        execution_scope=executor.scope,
        cache=cache,
        ready=lambda: None,
    )
    document = VectorDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 4096, 4096),
        _document(12).objects,
    )
    source = VectorRenderTileSource(document, document.revision)
    panel_rect = QRectF(0.0, 0.0, 1024.0, 768.0)

    def request_at(panel_x: float) -> RenderRefinement:
        """Request one translated view under a constrained continuity budget."""
        return coordinator.request(
            source=source,
            source_to_panel=QTransform(4.0, 0.0, 0.0, 4.0, panel_x, 0.0),
            panel_rect=panel_rect,
            device_pixel_ratio=1.0,
        )

    try:
        assert request_at(0.0).pending
        _run_all_refinement(executor, qapp)
        assert request_at(0.0).exact

        distant = request_at(-6400.0)
        assert distant.pending
        assert distant.products
        assert not distant.exact
        assert min(product.key.scale for product in distant.products) < 1.0
        assert cache.usage_bytes <= cache.budget_bytes
    finally:
        coordinator.shutdown()


def test_partial_fallback_products_are_clipped_to_cold_exact_cores() -> None:
    """Fallback coverage must never overlap and double-composite exact tiles."""
    cache = RenderTileCache()
    source_id = uuid.uuid4()
    overview_key = RenderTileKey(
        "vector",
        source_id,
        "geometry",
        "revision",
        0.5,
        0,
        0,
    )
    exact_key = RenderTileKey(
        "vector",
        source_id,
        "geometry",
        "revision",
        1.0,
        0,
        0,
    )
    missing_key = RenderTileKey(
        "vector",
        source_id,
        "geometry",
        "revision",
        1.0,
        1,
        0,
    )
    overview_image = _transparent_image(512, 256)
    exact_image = _transparent_image(512, 512)
    cache.admit(
        (
            RenderTileProduct(
                overview_key,
                QRectF(0.0, 0.0, 1024.0, 512.0),
                overview_image,
                QRectF(0.0, 0.0, 512.0, 256.0),
            ),
            RenderTileProduct(
                exact_key,
                QRectF(0.0, 0.0, 512.0, 512.0),
                exact_image,
                QRectF(0.0, 0.0, 512.0, 512.0),
            ),
        )
    )
    requests = (
        RenderTileRequest(
            exact_key,
            QRectF(0.0, 0.0, 512.0, 512.0),
            QRectF(0.0, 0.0, 512.0, 512.0),
        ),
        RenderTileRequest(
            missing_key,
            QRectF(512.0, 0.0, 512.0, 512.0),
            QRectF(512.0, 0.0, 512.0, 512.0),
        ),
    )

    products = cache.presentation_products(requests)

    assert products is not None and len(products) == 2
    fallback, exact = products
    assert fallback.source_rect == requests[1].source_rect
    assert fallback.image_source_rect == QRectF(256.0, 0.0, 256.0, 256.0)
    assert exact.source_rect == requests[0].source_rect
    assert not fallback.source_rect.intersects(exact.source_rect)


def _document(object_count: int) -> VectorDocument:
    """Return deterministic overlapping shapes spanning several tiles."""
    objects = tuple(
        VectorObject(
            uuid.uuid5(uuid.NAMESPACE_OID, f"vector-tile-{index}"),
            VectorObjectKind.SHAPE,
            (
                float((index * 37) % 220),
                float((index * 29) % 160),
                52.0,
                38.0,
            ),
            LayerTransform(),
            VectorStyle(
                fill=QColor(20 + index * 7, 100, 210, 140),
                stroke=QColor(250, 250, 250, 230),
                stroke_width=2.0,
            ),
            VectorShapeKind.RECTANGLE if index % 2 == 0 else VectorShapeKind.ELLIPSE,
        )
        for index in range(object_count)
    )
    return VectorDocument(
        uuid.uuid5(uuid.NAMESPACE_OID, "vector-tile-document"),
        RasterBounds(0, 0, 256, 192),
        objects,
    )


def _settle_refinement(qapp: QApplication) -> None:
    """Cross the production idle boundary before asserting exact promotion."""
    QTest.qWait(100)
    qapp.processEvents()


def _run_all_refinement(executor: ControlledExecution, qapp: QApplication) -> None:
    """Run staged continuity and detail jobs through their queued publications."""
    for _ in range(6):
        pending = tuple(
            job
            for job in executor.pending_jobs()
            if job.operation.startswith("render.refinement")
        )
        if not pending:
            return
        _run_refinement_turn(executor, qapp)
    raise AssertionError("render refinement did not settle")


def _run_refinement_turn(executor: ControlledExecution, qapp: QApplication) -> None:
    """Run one queued dispatch or worker generation and publish its result."""
    pending = tuple(
        job.operation.startswith("render.refinement") for job in executor.pending_jobs()
    )
    for _ in range(sum(pending)):
        executor.run_operation("render.refinement")
    qapp.processEvents()
    _settle_refinement(qapp)


def _transparent_image(width: int, height: int) -> QImage:
    """Return one cleared premultiplied test target."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image
