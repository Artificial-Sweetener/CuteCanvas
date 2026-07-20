#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Correctness and lifecycle tests for asynchronous vector refinement."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication

from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.vector.drawing import draw_vector_document
from qpane.vector.model import VectorDocument, VectorObject
from qpane.vector.public import VectorObjectKind, VectorShapeKind, VectorStyle
from qpane.vector.render_tiles import VectorRenderWorkCoordinator, VectorTileCache
from tests.helpers.executor_stubs import RejectingStubExecutor, StubExecutor


def test_refined_tiles_match_direct_vector_drawing(qapp: QApplication) -> None:
    """Tile bleed and source projection must reproduce direct raster pixels."""
    document = _document(12)
    executor = StubExecutor(name="vector-tiles")
    cache = VectorTileCache(8 * 1024 * 1024)
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = VectorRenderWorkCoordinator(
        executor=executor,
        cache=cache,
        ready=_ready,
    )
    transform = QTransform.fromScale(4.0, 4.0)
    try:
        assert coordinator.request(
            document=document,
            revision_key=(document.revision, 0),
            source_to_panel=transform,
            panel_rect=QRectF(0.0, 0.0, 1024.0, 768.0),
            device_pixel_ratio=1.0,
        ).pending
        assert coordinator.pending_count == 1
        executor.run_category("vector_render")
        qapp.processEvents()
        refinement = coordinator.request(
            document=document,
            revision_key=(document.revision, 0),
            source_to_panel=transform,
            panel_rect=QRectF(0.0, 0.0, 1024.0, 768.0),
            device_pixel_ratio=1.0,
        )
        assert refinement.products is not None
        products = refinement.products
        assert ready_count == 1
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


def test_latest_refinement_wins_and_cache_stays_bounded(qapp: QApplication) -> None:
    """Superseded work cannot publish and cache pressure must evict exactly."""
    executor = StubExecutor(name="vector-stale")
    cache = VectorTileCache(2 * 512 * 512 * 4)
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = VectorRenderWorkCoordinator(
        executor=executor,
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
            document=first,
            revision_key=first.revision,
            **request_args,
        ).pending
        assert coordinator.request(
            document=changed,
            revision_key=changed.revision,
            **request_args,
        ).pending
        assert len(executor.cancelled) == 1
        executor.run_category("vector_render")
        qapp.processEvents()
        refinement = coordinator.request(
            document=changed,
            revision_key=changed.revision,
            **request_args,
        )
        assert refinement.products is not None
        products = refinement.products
        assert all(product.key.revision_key == changed.revision for product in products)
        assert ready_count == 1
        assert cache.usage_bytes <= 2 * 512 * 512 * 4
    finally:
        coordinator.shutdown()


def test_rejection_and_shutdown_remain_bounded(qapp: QApplication) -> None:
    """Rejected and teardown work must not retry-loop or publish."""
    executor = RejectingStubExecutor(reject_counts={"vector_render": 1})
    cache = VectorTileCache()
    ready_count = 0

    def _ready() -> None:
        nonlocal ready_count
        ready_count += 1

    coordinator = VectorRenderWorkCoordinator(
        executor=executor,
        cache=cache,
        ready=_ready,
    )
    document = _document(4)
    args = {
        "document": document,
        "revision_key": document.revision,
        "source_to_panel": QTransform(),
        "panel_rect": QRectF(0.0, 0.0, 256.0, 192.0),
        "device_pixel_ratio": 1.0,
    }
    assert not coordinator.request(**args).pending
    assert not coordinator.request(**args).pending
    assert len(executor.rejections) == 1
    coordinator.shutdown()
    executor.drain_all()
    qapp.processEvents()
    assert ready_count == 0
    assert coordinator.pending_count == 0

    disabled = VectorRenderWorkCoordinator(
        executor=executor,
        cache=VectorTileCache(0),
        ready=_ready,
    )
    unavailable = disabled.request(**args)
    assert unavailable.products is None
    assert not unavailable.pending
    disabled.shutdown()


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


def _transparent_image(width: int, height: int) -> QImage:
    """Return one cleared premultiplied test target."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image
