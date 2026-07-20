#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Bounded asynchronous visible-tile refinement for complex vector documents."""

from __future__ import annotations

import logging
import math
import uuid
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRectF, QRunnable, Signal
from PySide6.QtGui import QImage, QPainter, QTransform

from ..concurrency import BaseWorker, TaskExecutorProtocol, TaskHandle, TaskRejected
from .drawing import draw_vector_document
from .model import VectorDocument
from .text_layout import SemanticTextLayoutCache

logger = logging.getLogger(__name__)

_TILE_PIXELS = 512
_TILE_BLEED_PIXELS = 2
_MAX_VISIBLE_TILES = 64
_MIN_SCALE = 0.125
_MAX_SCALE = 32.0


@dataclass(frozen=True, slots=True)
class VectorTileKey:
    """Identify one exact vector revision, resolution, and local tile."""

    vector_id: uuid.UUID
    revision_key: Hashable
    scale: float
    column: int
    row: int


@dataclass(frozen=True, slots=True)
class VectorTileProduct:
    """Carry one refined image and its source-local draw geometry."""

    key: VectorTileKey
    source_rect: QRectF
    image: QImage
    image_source_rect: QRectF

    @property
    def retained_bytes(self) -> int:
        """Return the detached image allocation size."""
        return int(self.image.sizeInBytes())


@dataclass(frozen=True, slots=True)
class VectorTileRequest:
    """Describe one tile's core and antialiasing bleed geometry."""

    key: VectorTileKey
    source_rect: QRectF
    paint_rect: QRectF


@dataclass(frozen=True, slots=True)
class VectorRefinement:
    """Describe whether an exact tile set is ready, pending, or unavailable."""

    products: tuple[VectorTileProduct, ...] | None
    pending: bool

    @classmethod
    def ready(cls, products: tuple[VectorTileProduct, ...]) -> VectorRefinement:
        """Return an exact complete refinement result."""
        return cls(products, False)

    @classmethod
    def waiting(cls) -> VectorRefinement:
        """Return a result whose exact batch is still pending."""
        return cls(None, True)

    @classmethod
    def unavailable(cls) -> VectorRefinement:
        """Return a result that requires exact synchronous fallback."""
        return cls(None, False)


class VectorTileCache:
    """Own least-recently-used refined vector tiles under a byte ceiling."""

    def __init__(self, budget_bytes: int = 32 * 1024 * 1024) -> None:
        """Initialize an empty coordinated cache."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[VectorTileKey, VectorTileProduct] = OrderedDict()
        self._usage_changed: Callable[[int], None] | None = None

    @property
    def usage_bytes(self) -> int:
        """Return retained image bytes."""
        return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained tiles."""
        return len(self._entries)

    @property
    def budget_bytes(self) -> int:
        """Return the active strict retention ceiling."""
        return self._budget_bytes

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install shared-cache usage publication."""
        self._usage_changed = callback

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a strict cache budget and trim immediately."""
        self._budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest tiles until usage meets ``target_bytes``."""
        target = max(0, int(target_bytes))
        while self._entries and self._usage_bytes > target:
            _key, product = self._entries.popitem(last=False)
            self._usage_bytes -= product.retained_bytes
        self._report()

    def products(
        self,
        keys: tuple[VectorTileKey, ...],
    ) -> tuple[VectorTileProduct, ...] | None:
        """Return an atomic complete tile set, or ``None`` when any tile is cold."""
        if any(key not in self._entries for key in keys):
            return None
        products: list[VectorTileProduct] = []
        for key in keys:
            product = self._entries.pop(key)
            self._entries[key] = product
            products.append(product)
        return tuple(products)

    def admit(self, products: tuple[VectorTileProduct, ...]) -> None:
        """Admit one completed worker batch without exceeding the byte ceiling."""
        for product in products:
            previous = self._entries.pop(product.key, None)
            if previous is not None:
                self._usage_bytes -= previous.retained_bytes
            if product.retained_bytes <= self._budget_bytes:
                self._entries[product.key] = product
                self._usage_bytes += product.retained_bytes
        self.trim_to(self._budget_bytes)

    def _report(self) -> None:
        """Publish exact retained usage after mutations."""
        if self._usage_changed is not None:
            self._usage_changed(self._usage_bytes)


class _VectorTileWorker(QObject, QRunnable, BaseWorker):
    """Rasterize one bounded visible tile batch away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(
        self,
        document: VectorDocument,
        requests: tuple[VectorTileRequest, ...],
    ) -> None:
        """Capture immutable semantic and geometry inputs."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.document = document
        self.requests = requests
        self.products: tuple[VectorTileProduct, ...] = ()
        self.error_message: str | None = None

    def run(self) -> None:
        """Build exact tile images while containing worker failures."""
        try:
            text_layouts = SemanticTextLayoutCache(16 * 1024 * 1024)
            self.products = self._render_batch(text_layouts)
        except BaseException as exc:  # pragma: no cover - worker boundary
            self.error_message = str(exc)
            logger.exception("Vector tile refinement failed")
        succeeded = (
            self.error_message is None
            and not self.is_cancelled
            and len(self.products) == len(self.requests)
        )
        self.emit_finished(succeeded, payload=self, error=None)

    def _render_batch(
        self,
        text_layouts: SemanticTextLayoutCache,
    ) -> tuple[VectorTileProduct, ...]:
        """Rasterize one bounded visible batch and detach each antialiased core."""
        if not self.requests or self.is_cancelled:
            return ()
        scale = self.requests[0].key.scale
        paint_rect = QRectF(self.requests[0].paint_rect)
        for request in self.requests[1:]:
            paint_rect = paint_rect.united(request.paint_rect)
        width = max(1, math.ceil(paint_rect.width() * scale))
        height = max(1, math.ceil(paint_rect.height() * scale))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setTransform(
                QTransform(
                    scale,
                    0.0,
                    0.0,
                    scale,
                    -paint_rect.x() * scale,
                    -paint_rect.y() * scale,
                )
            )
            draw_vector_document(
                painter,
                self.document,
                None,
                text_layouts,
            )
        finally:
            painter.end()
        products: list[VectorTileProduct] = []
        for request in self.requests:
            if self.is_cancelled:
                return ()
            core = request.source_rect
            x = round((core.x() - paint_rect.x()) * scale)
            y = round((core.y() - paint_rect.y()) * scale)
            core_width = max(1, math.ceil(core.width() * scale))
            core_height = max(1, math.ceil(core.height() * scale))
            detached = image.copy(x, y, core_width, core_height)
            products.append(
                VectorTileProduct(
                    request.key,
                    core,
                    detached,
                    QRectF(0.0, 0.0, detached.width(), detached.height()),
                )
            )
        return tuple(products)


@dataclass(slots=True)
class _PendingTiles:
    """Retain one latest request for a vector source."""

    signature: tuple[VectorTileKey, ...]
    worker: _VectorTileWorker
    handle: TaskHandle


class VectorRenderWorkCoordinator:
    """Coordinate latest-only visible refinement and generation-safe publication."""

    def __init__(
        self,
        *,
        executor: TaskExecutorProtocol,
        cache: VectorTileCache,
        ready: Callable[[], None],
    ) -> None:
        """Bind the shared executor, tile cache, and GUI invalidation callback."""
        self._executor = executor
        self._cache = cache
        self._ready = ready
        self._pending: dict[uuid.UUID, _PendingTiles] = {}
        self._rejected: set[tuple[VectorTileKey, ...]] = set()
        self._closed = False

    @property
    def pending_count(self) -> int:
        """Return the number of independently pending vector sources."""
        return len(self._pending)

    def request(
        self,
        *,
        document: VectorDocument,
        revision_key: Hashable,
        source_to_panel: QTransform,
        panel_rect: QRectF,
        device_pixel_ratio: float,
    ) -> VectorRefinement:
        """Return, schedule, or explicitly decline one exact visible tile set."""
        requests = _visible_requests(
            document,
            revision_key,
            source_to_panel,
            panel_rect,
            device_pixel_ratio,
            self._cache.budget_bytes,
        )
        if requests is None:
            return VectorRefinement.unavailable()
        signature = tuple(request.key for request in requests)
        if not signature:
            return VectorRefinement.ready(())
        cached = self._cache.products(signature)
        if cached is not None:
            return VectorRefinement.ready(cached)
        if self._closed or signature in self._rejected:
            return VectorRefinement.unavailable()
        current = self._pending.get(document.vector_id)
        if current is not None and current.signature == signature:
            return VectorRefinement.waiting()
        if current is not None:
            self._cancel(document.vector_id)
        worker = _VectorTileWorker(document, requests)
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="vector_render")
        except TaskRejected:
            self._rejected.add(signature)
            worker.deleteLater()
            return VectorRefinement.unavailable()
        self._pending[document.vector_id] = _PendingTiles(signature, worker, handle)
        return VectorRefinement.waiting()

    def shutdown(self) -> None:
        """Cancel every queued refinement and suppress late publication."""
        if self._closed:
            return
        self._closed = True
        for vector_id in tuple(self._pending):
            self._cancel(vector_id)
        self._rejected.clear()

    def _finish(self, worker: _VectorTileWorker) -> None:
        """Publish only the exact latest complete request for a source."""
        pending = self._pending.get(worker.document.vector_id)
        if pending is None or pending.worker is not worker:
            return
        self._pending.pop(worker.document.vector_id, None)
        try:
            if (
                not self._closed
                and not worker.is_cancelled
                and worker.error_message is None
                and tuple(product.key for product in worker.products)
                == pending.signature
            ):
                self._cache.admit(worker.products)
                self._ready()
        finally:
            worker.deleteLater()

    def _cancel(self, vector_id: uuid.UUID) -> None:
        """Cancel and forget one superseded source request."""
        pending = self._pending.pop(vector_id, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)


def _visible_requests(
    document: VectorDocument,
    revision_key: Hashable,
    source_to_panel: QTransform,
    panel_rect: QRectF,
    device_pixel_ratio: float,
    budget_bytes: int,
) -> tuple[VectorTileRequest, ...] | None:
    """Build a bounded complete visible tile request in document coordinates."""
    panel_to_source, invertible = source_to_panel.inverted()
    if not invertible:
        return ()
    bounds = document.bounds
    document_rect = QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )
    visible = panel_to_source.mapRect(panel_rect).intersected(document_rect)
    if visible.isEmpty():
        return ()
    if budget_bytes <= 0:
        return None
    scale = _scale_bucket(source_to_panel, device_pixel_ratio)
    while True:
        requests = _requests_for_scale(document, revision_key, visible, scale)
        estimated_bytes = sum(
            max(1, math.ceil(request.paint_rect.width() * scale))
            * max(1, math.ceil(request.paint_rect.height() * scale))
            * 4
            for request in requests
        )
        if len(requests) <= _MAX_VISIBLE_TILES and estimated_bytes <= budget_bytes:
            return requests
        if scale <= _MIN_SCALE:
            return None
        scale = max(_MIN_SCALE, scale / 2.0)


def _scale_bucket(transform: QTransform, device_pixel_ratio: float) -> float:
    """Return a non-undersampling power-of-two physical scale bucket."""
    x_scale = math.hypot(transform.m11(), transform.m12())
    y_scale = math.hypot(transform.m21(), transform.m22())
    exact = max(x_scale, y_scale) * max(0.01, float(device_pixel_ratio))
    if exact <= _MIN_SCALE:
        return _MIN_SCALE
    bucket = 2.0 ** math.ceil(math.log2(exact))
    return min(_MAX_SCALE, max(_MIN_SCALE, bucket))


def _requests_for_scale(
    document: VectorDocument,
    revision_key: Hashable,
    visible: QRectF,
    scale: float,
) -> tuple[VectorTileRequest, ...]:
    """Return deterministic tile requests covering one visible local rectangle."""
    span = _TILE_PIXELS / scale
    bounds = document.bounds
    document_rect = QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )
    first_column = math.floor((visible.left() - bounds.x) / span)
    last_column = math.floor((visible.right() - bounds.x) / span)
    first_row = math.floor((visible.top() - bounds.y) / span)
    last_row = math.floor((visible.bottom() - bounds.y) / span)
    bleed = _TILE_BLEED_PIXELS / scale
    requests: list[VectorTileRequest] = []
    for row in range(first_row, last_row + 1):
        for column in range(first_column, last_column + 1):
            core = QRectF(
                bounds.x + column * span,
                bounds.y + row * span,
                span,
                span,
            ).intersected(document_rect)
            if core.isEmpty():
                continue
            paint = core.adjusted(-bleed, -bleed, bleed, bleed).intersected(
                document_rect
            )
            requests.append(
                VectorTileRequest(
                    VectorTileKey(
                        document.vector_id,
                        revision_key,
                        scale,
                        column,
                        row,
                    ),
                    core,
                    paint,
                )
            )
    return tuple(requests)
