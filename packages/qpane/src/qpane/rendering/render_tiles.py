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
"""Shared stable-grid refinement for resolution-dependent render sources."""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QRectF, QRunnable, Signal
from PySide6.QtGui import QTransform

from ..concurrency import BaseWorker, TaskExecutorProtocol, TaskHandle, TaskRejected
from ..scene.raster import RasterBounds
from .render_tile_cache import RenderTileCache
from .render_tile_continuity import RenderTileContinuity
from .render_tile_geometry import (
    RenderTileKey,
    RenderTileRequest,
    estimated_request_bytes,
    guarded_tile_requests,
    overview_tile_requests,
    unique_requests,
)
from .render_tile_geometry import (
    visible_tile_requests as _visible_tile_requests,
)
from .render_tile_types import (
    RenderRefinement,
    RenderTileBatchSource,
    RenderTileProduct,
)

logger = logging.getLogger(__name__)


class _RefinementLane(str, Enum):
    """Separate stable continuity work from replaceable viewport detail."""

    CONTINUITY = "continuity"
    DETAIL = "detail"


class _RenderTileWorker(QObject, QRunnable, BaseWorker):
    """Evaluate one complete visible batch away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(
        self,
        source: RenderTileBatchSource,
        requests: tuple[RenderTileRequest, ...],
        lane: _RefinementLane,
    ) -> None:
        """Capture an immutable source snapshot and stable requests."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.source = source
        self.requests = requests
        self.lane = lane
        self.products: tuple[RenderTileProduct, ...] = ()
        self.error_message: str | None = None

    def run(self) -> None:
        """Build exact products while containing worker failures."""
        try:
            batches: OrderedDict[float, list[RenderTileRequest]] = OrderedDict()
            for request in self.requests:
                batches.setdefault(request.key.scale, []).append(request)
            products: list[RenderTileProduct] = []
            for requests in batches.values():
                if self.is_cancelled:
                    break
                products.extend(
                    self.source.render_tiles(
                        tuple(requests),
                        lambda: self.is_cancelled,
                    )
                )
            self.products = tuple(products)
        except BaseException as exc:  # pragma: no cover - worker boundary
            self.error_message = str(exc)
            logger.exception("Render tile refinement failed")
        succeeded = (
            self.error_message is None
            and not self.is_cancelled
            and len(self.products) == len(self.requests)
        )
        self.emit_finished(succeeded, payload=self, error=None)


@dataclass(slots=True)
class _PendingTiles:
    """Retain one latest request in a source refinement lane."""

    signature: tuple[RenderTileKey, ...]
    retained_signature: tuple[RenderTileKey, ...]
    worker: _RenderTileWorker
    handle: TaskHandle


@dataclass(frozen=True, slots=True)
class _OverviewRequestBatch:
    """Cache source-wide fallback geometry until its render identity changes."""

    revision_key: Hashable
    fallback_key: Hashable
    bounds: RasterBounds
    budget_bytes: int
    requests: tuple[RenderTileRequest, ...]


class RenderTileWorkCoordinator:
    """Coordinate stable coverage plus latest-only viewport refinement."""

    def __init__(
        self,
        *,
        executor: TaskExecutorProtocol,
        cache: RenderTileCache,
        ready: Callable[[], None],
    ) -> None:
        """Bind the shared executor, cache, and GUI invalidation callback."""
        self._executor = executor
        self._cache = cache
        self._ready = ready
        self._continuity = RenderTileContinuity(ready)
        self._pending: dict[tuple[str, uuid.UUID, _RefinementLane], _PendingTiles] = {}
        self._overview_requests: dict[tuple[str, uuid.UUID], _OverviewRequestBatch] = {}
        self._rejected: set[tuple[RenderTileKey, ...]] = set()
        self._closed = False

    @property
    def pending_count(self) -> int:
        """Return pending worker jobs plus an unsettled presentation transition."""
        return len(self._pending) + int(self._continuity.pending)

    @property
    def pending_tile_count(self) -> int:
        """Return the number of uncached tiles currently being evaluated."""
        return sum(len(pending.signature) for pending in self._pending.values())

    def request(
        self,
        *,
        source: RenderTileBatchSource,
        source_to_panel: QTransform,
        panel_rect: QRectF,
        device_pixel_ratio: float,
    ) -> RenderRefinement:
        """Return, schedule, or explicitly decline one visible tile set."""
        visible_requests = _visible_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=source_to_panel,
            panel_rect=panel_rect,
            device_pixel_ratio=device_pixel_ratio,
            budget_bytes=self._cache.budget_bytes,
        )
        if visible_requests is None:
            return RenderRefinement.unavailable()
        visible_signature = tuple(request.key for request in visible_requests)
        if not visible_signature:
            return RenderRefinement.ready(())
        overview_requests = self._overview_requests_for(source)
        overview_bytes = estimated_request_bytes(overview_requests)
        visible_bytes = estimated_request_bytes(visible_requests)
        if visible_bytes + overview_bytes > self._cache.budget_bytes:
            overview_requests = ()
            overview_bytes = 0
        overview_signature = tuple(request.key for request in overview_requests)
        cached = self._cache.products(visible_signature)
        self._ensure_work(
            lane=_RefinementLane.CONTINUITY,
            source=source,
            requests=overview_requests,
            required_signature=overview_signature,
            retained_signature=overview_signature,
        )
        detail_identity = (
            source.source_kind,
            source.source_id,
            _RefinementLane.DETAIL,
        )
        pending_detail = self._pending.get(detail_identity)
        if pending_detail is not None and self._pending_covers(
            pending_detail,
            visible_signature,
        ):
            detail_retained_signature = pending_detail.retained_signature
        else:
            guarded_requests = guarded_tile_requests(
                source_kind=source.source_kind,
                source_id=source.source_id,
                revision_key=source.revision_key,
                fallback_key=source.fallback_key,
                bounds=source.bounds,
                source_to_panel=source_to_panel,
                panel_rect=panel_rect,
                budget_bytes=self._cache.budget_bytes - overview_bytes,
                visible_requests=visible_requests,
            )
            overview_keys = frozenset(overview_signature)
            detail_requests = tuple(
                request
                for request in unique_requests(guarded_requests)
                if request.key not in overview_keys
            )
            detail_signature = tuple(request.key for request in detail_requests)
            detail_retained_signature = tuple(
                dict.fromkeys((*overview_signature, *detail_signature))
            )
            self._ensure_work(
                lane=_RefinementLane.DETAIL,
                source=source,
                requests=detail_requests,
                required_signature=visible_signature,
                retained_signature=detail_retained_signature,
            )
        stable_fallback = (
            self._cache.products(overview_signature) if overview_signature else None
        )
        fallback = self._cache.covering_products(visible_requests)
        identity = (source.source_kind, source.source_id)
        prefer_fallback = self._continuity.prefer_fallback(
            identity,
            visible_signature,
            exact_available=cached is not None,
        )
        if cached is not None and (
            not prefer_fallback
            or stable_fallback is None
            or _same_products(cached, stable_fallback)
        ):
            return RenderRefinement.ready(cached)
        if cached is not None:
            return RenderRefinement.waiting(stable_fallback)
        if fallback is not None:
            return RenderRefinement.waiting(fallback)
        work_available = any(
            identity_key[:2] == identity for identity_key in self._pending
        ) or any(
            signature and signature not in self._rejected
            for signature in (overview_signature, detail_retained_signature)
        )
        if self._closed or not work_available:
            return (
                RenderRefinement.waiting(fallback)
                if fallback
                else RenderRefinement.unavailable()
            )
        return RenderRefinement.waiting(fallback)

    def _pending_covers(
        self,
        pending: _PendingTiles,
        required_signature: tuple[RenderTileKey, ...],
    ) -> bool:
        """Return whether cache plus one active job covers every required tile."""
        return all(
            self._cache.contains(key) or key in pending.signature
            for key in required_signature
        )

    def _overview_requests_for(
        self,
        source: RenderTileBatchSource,
    ) -> tuple[RenderTileRequest, ...]:
        """Return cached whole-source request geometry for one render revision."""
        identity = (source.source_kind, source.source_id)
        current = self._overview_requests.get(identity)
        budget_bytes = self._cache.budget_bytes
        if (
            current is not None
            and current.revision_key == source.revision_key
            and current.fallback_key == source.fallback_key
            and current.bounds == source.bounds
            and current.budget_bytes == budget_bytes
        ):
            return current.requests
        requests = overview_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            budget_bytes=budget_bytes,
        )
        self._overview_requests[identity] = _OverviewRequestBatch(
            source.revision_key,
            source.fallback_key,
            source.bounds,
            budget_bytes,
            requests,
        )
        return requests

    def _ensure_work(
        self,
        *,
        lane: _RefinementLane,
        source: RenderTileBatchSource,
        requests: tuple[RenderTileRequest, ...],
        required_signature: tuple[RenderTileKey, ...],
        retained_signature: tuple[RenderTileKey, ...],
    ) -> None:
        """Keep one lane warm without cross-cancelling continuity work."""
        if self._closed or not requests:
            return
        missing_requests = tuple(
            request for request in requests if not self._cache.contains(request.key)
        )
        if not missing_requests or retained_signature in self._rejected:
            return
        signature = tuple(request.key for request in missing_requests)
        identity = (source.source_kind, source.source_id, lane)
        current = self._pending.get(identity)
        if current is not None and self._pending_covers(
            current,
            required_signature,
        ):
            return
        if current is not None:
            self._cancel(identity)
        worker = _RenderTileWorker(source, missing_requests, lane)
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="render_refinement")
        except TaskRejected:
            self._rejected.add(retained_signature)
            worker.deleteLater()
            return
        self._pending[identity] = _PendingTiles(
            signature,
            retained_signature,
            worker,
            handle,
        )

    def shutdown(self) -> None:
        """Cancel every queued refinement and suppress late publication."""
        if self._closed:
            return
        self._closed = True
        self._continuity.shutdown()
        for identity in tuple(self._pending):
            self._cancel(identity)
        self._overview_requests.clear()
        self._rejected.clear()

    def _finish(self, worker: _RenderTileWorker) -> None:
        """Publish only the exact latest complete request for a source."""
        identity = (
            worker.source.source_kind,
            worker.source.source_id,
            worker.lane,
        )
        pending = self._pending.get(identity)
        if pending is None or pending.worker is not worker:
            worker.deleteLater()
            return
        self._pending.pop(identity, None)
        try:
            if (
                not self._closed
                and not worker.is_cancelled
                and worker.error_message is None
                and tuple(product.key for product in worker.products)
                == pending.signature
            ):
                self._cache.admit(
                    worker.products,
                    retain_keys=pending.retained_signature,
                )
                source_identity = (
                    worker.source.source_kind,
                    worker.source.source_id,
                )
                visible_signature = self._continuity.visible_signature(source_identity)
                if visible_signature is not None:
                    self._continuity.note_exact_available(
                        source_identity,
                        exact_available=all(
                            self._cache.contains(key) for key in visible_signature
                        ),
                    )
                self._ready()
        finally:
            worker.deleteLater()

    def _cancel(
        self,
        identity: tuple[str, uuid.UUID, _RefinementLane],
    ) -> None:
        """Cancel and forget one superseded source request."""
        pending = self._pending.pop(identity, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)


def _same_products(
    first: tuple[RenderTileProduct, ...],
    second: tuple[RenderTileProduct, ...],
) -> bool:
    """Return whether two batches identify the same cached products."""
    return tuple(product.key for product in first) == tuple(
        product.key for product in second
    )
