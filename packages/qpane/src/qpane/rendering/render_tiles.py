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

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from ..execution import (
    CancellationToken,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)
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


def _render_tiles(
    source: RenderTileBatchSource,
    requests: tuple[RenderTileRequest, ...],
    cancellation: CancellationToken,
) -> tuple[RenderTileProduct, ...]:
    """Evaluate one complete refinement batch cooperatively."""
    batches: OrderedDict[float, list[RenderTileRequest]] = OrderedDict()
    for request in requests:
        batches.setdefault(request.key.scale, []).append(request)
    products: list[RenderTileProduct] = []
    for batch in batches.values():
        cancellation.raise_if_cancelled()
        products.extend(
            source.render_tiles(
                tuple(batch),
                lambda: cancellation.is_cancelled,
            )
        )
    cancellation.raise_if_cancelled()
    result = tuple(products)
    if len(result) != len(requests):
        raise RuntimeError("render refinement returned an incomplete tile batch")
    return result


@dataclass(slots=True)
class _PendingTiles:
    """Retain one latest request in a source refinement lane."""

    signature: tuple[RenderTileKey, ...]
    retained_signature: tuple[RenderTileKey, ...]
    source: RenderTileBatchSource
    lane: _RefinementLane
    handle: ExecutionHandle[tuple[RenderTileProduct, ...], object] | None = None


@dataclass(frozen=True, slots=True)
class _DeferredTiles:
    """Retain latest detail work until stable continuity pixels are available."""

    source: RenderTileBatchSource
    requests: tuple[RenderTileRequest, ...]
    required_signature: tuple[RenderTileKey, ...]
    retained_signature: tuple[RenderTileKey, ...]


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
        execution_scope: ExecutionScope,
        cache: RenderTileCache,
        ready: Callable[[], None],
    ) -> None:
        """Bind an owner execution scope, cache, and GUI invalidation callback."""
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:render-refinement"
        )
        self._cache = cache
        self._ready = ready
        self._continuity = RenderTileContinuity(ready)
        self._pending: dict[tuple[str, uuid.UUID, _RefinementLane], _PendingTiles] = {}
        self._deferred: dict[tuple[str, uuid.UUID, _RefinementLane], _DeferredTiles] = (
            {}
        )
        self._overview_requests: dict[tuple[str, uuid.UUID], _OverviewRequestBatch] = {}
        self._rejected: set[tuple[RenderTileKey, ...]] = set()
        self._closed = False

    @property
    def pending_count(self) -> int:
        """Return pending worker jobs plus an unsettled presentation transition."""
        return len(self._pending) + len(self._deferred) + int(self._continuity.pending)

    @property
    def pending_tile_count(self) -> int:
        """Return the number of uncached tiles currently being evaluated."""
        return sum(len(pending.signature) for pending in self._pending.values()) + sum(
            len(deferred.requests) for deferred in self._deferred.values()
        )

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
        continuity_identity = (
            source.source_kind,
            source.source_id,
            _RefinementLane.CONTINUITY,
        )
        continuity_pending = continuity_identity in self._pending
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
            if continuity_pending and self._cache.products(overview_signature) is None:
                self._defer_detail(
                    source=source,
                    requests=detail_requests,
                    required_signature=visible_signature,
                    retained_signature=detail_retained_signature,
                )
            else:
                self._deferred.pop(detail_identity, None)
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
        work_available = (
            any(identity_key[:2] == identity for identity_key in self._pending)
            or any(identity_key[:2] == identity for identity_key in self._deferred)
            or any(
                signature and signature not in self._rejected
                for signature in (overview_signature, detail_retained_signature)
            )
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
        pending = _PendingTiles(
            signature=signature,
            retained_signature=retained_signature,
            source=source,
            lane=lane,
        )
        self._pending[identity] = pending
        request = ExecutionRequest[tuple[RenderTileProduct, ...], object](
            operation=f"render.refinement.{lane.value}",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=estimated_request_bytes(missing_requests),
            ),
            work=lambda context: _render_tiles(
                source,
                missing_requests,
                context.cancellation,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda products: self._finish(identity, products),
            )
        except ExecutionRejected:
            if self._pending.get(identity) is pending:
                self._pending.pop(identity, None)
            self._rejected.add(retained_signature)
            if lane is _RefinementLane.CONTINUITY:
                self._start_deferred_detail(
                    source.source_kind,
                    source.source_id,
                )
            self._ready()
            return
        if self._pending.get(identity) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle_request(identity, handle, outcome)
        )

    def _defer_detail(
        self,
        *,
        source: RenderTileBatchSource,
        requests: tuple[RenderTileRequest, ...],
        required_signature: tuple[RenderTileKey, ...],
        retained_signature: tuple[RenderTileKey, ...],
    ) -> None:
        """Keep only the latest detail request behind active continuity work."""
        identity = (
            source.source_kind,
            source.source_id,
            _RefinementLane.DETAIL,
        )
        self._cancel(identity)
        if self._closed or not requests:
            self._deferred.pop(identity, None)
            return
        self._deferred[identity] = _DeferredTiles(
            source,
            requests,
            required_signature,
            retained_signature,
        )

    def shutdown(self) -> None:
        """Cancel every queued refinement and suppress late publication."""
        if self._closed:
            return
        self._closed = True
        self._continuity.shutdown()
        for identity in tuple(self._pending):
            self._cancel(identity)
        self._deferred.clear()
        self._overview_requests.clear()
        self._rejected.clear()
        self._execution_scope.close(reason="render_refinement_shutdown")

    def _finish(
        self,
        identity: tuple[str, uuid.UUID, _RefinementLane],
        products: tuple[RenderTileProduct, ...],
    ) -> None:
        """Publish only the exact latest complete request for a source."""
        pending = self._pending.get(identity)
        if pending is None:
            return
        self._pending.pop(identity, None)
        if (
            not self._closed
            and tuple(product.key for product in products) == pending.signature
        ):
            self._cache.admit(
                products,
                retain_keys=pending.retained_signature,
            )
            source_identity = (
                pending.source.source_kind,
                pending.source.source_id,
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
        if pending.lane is _RefinementLane.CONTINUITY:
            self._start_deferred_detail(
                pending.source.source_kind,
                pending.source.source_id,
            )

    def _settle_request(
        self,
        identity: tuple[str, uuid.UUID, _RefinementLane],
        handle: ExecutionHandle[tuple[RenderTileProduct, ...], object],
        outcome: ExecutionOutcome[tuple[RenderTileProduct, ...]],
    ) -> None:
        """Release failed or cancelled refinement state without stale adoption."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(identity)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(identity, None)
        if outcome.state == ExecutionState.FAILED:
            logger.error(
                "Render tile refinement failed",
                exc_info=outcome.error,
            )
        if pending.lane is _RefinementLane.CONTINUITY:
            self._start_deferred_detail(
                pending.source.source_kind,
                pending.source.source_id,
            )
        self._ready()

    def _start_deferred_detail(
        self,
        source_kind: str,
        source_id: uuid.UUID,
    ) -> None:
        """Submit the latest detail work after its continuity lane settles."""
        identity = (source_kind, source_id, _RefinementLane.DETAIL)
        deferred = self._deferred.pop(identity, None)
        if deferred is None or self._closed:
            return
        self._ensure_work(
            lane=_RefinementLane.DETAIL,
            source=deferred.source,
            requests=deferred.requests,
            required_signature=deferred.required_signature,
            retained_signature=deferred.retained_signature,
        )

    def _cancel(
        self,
        identity: tuple[str, uuid.UUID, _RefinementLane],
    ) -> None:
        """Cancel and forget one superseded source request."""
        pending = self._pending.pop(identity, None)
        if pending is None:
            return
        if pending.handle is not None:
            pending.handle.cancel(reason="render_refinement_superseded")


def _same_products(
    first: tuple[RenderTileProduct, ...],
    second: tuple[RenderTileProduct, ...],
) -> bool:
    """Return whether two batches identify the same cached products."""
    return tuple(product.key for product in first) == tuple(
        product.key for product in second
    )
