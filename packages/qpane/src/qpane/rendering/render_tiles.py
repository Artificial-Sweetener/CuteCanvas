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
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QRectF, QTimer
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

_REFINEMENT_CHUNK_TILES = 4
_PREFETCH_CHUNK_TILES = 1
_PREFETCH_SETTLE_MS = 150


@runtime_checkable
class _ImmediateTileSource(Protocol):
    """Provide products whose bounded result is safe to derive on the GUI thread."""

    def immediate_products(
        self,
        requests: tuple[RenderTileRequest, ...],
    ) -> tuple[RenderTileProduct, ...] | None:
        """Return immediate products or decline synchronous derivation."""
        ...


class _RefinementLane(str, Enum):
    """Separate stable continuity work from replaceable viewport detail."""

    CONTINUITY = "continuity"
    DETAIL = "detail"
    PREFETCH = "prefetch"


def _render_tiles(
    source: RenderTileBatchSource,
    requests: tuple[RenderTileRequest, ...],
    cancellation: CancellationToken,
    *,
    chunk_size: int = _REFINEMENT_CHUNK_TILES,
) -> tuple[RenderTileProduct, ...]:
    """Evaluate one complete refinement batch cooperatively."""
    batches: OrderedDict[float, list[RenderTileRequest]] = OrderedDict()
    for request in requests:
        batches.setdefault(request.key.scale, []).append(request)
    products: list[RenderTileProduct] = []
    for batch in batches.values():
        for offset in range(0, len(batch), chunk_size):
            cancellation.raise_if_cancelled()
            products.extend(
                source.render_tiles(
                    tuple(batch[offset : offset + chunk_size]),
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


@dataclass(frozen=True, slots=True)
class _DeferredPrefetch:
    """Retain the latest settled-view guard request for one source."""

    source: RenderTileBatchSource
    source_to_panel: QTransform
    panel_rect: QRectF
    visible_requests: tuple[RenderTileRequest, ...]
    overview_signature: tuple[RenderTileKey, ...]

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from the caller's frame."""
        object.__setattr__(self, "source_to_panel", QTransform(self.source_to_panel))
        object.__setattr__(self, "panel_rect", QRectF(self.panel_rect))


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
        self._pending: dict[tuple[str, uuid.UUID, _RefinementLane], _PendingTiles] = {}
        self._deferred: dict[tuple[str, uuid.UUID, _RefinementLane], _DeferredTiles] = (
            {}
        )
        self._overview_requests: dict[tuple[str, uuid.UUID], _OverviewRequestBatch] = {}
        self._deferred_prefetch: dict[tuple[str, uuid.UUID], _DeferredPrefetch] = {}
        self._rejected: set[tuple[RenderTileKey, ...]] = set()
        self._prefetch_timer = QTimer()
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(_PREFETCH_SETTLE_MS)
        self._prefetch_timer.timeout.connect(self._start_deferred_prefetch)
        self._navigation_suspended = False
        self._closed = False

    @property
    def pending_count(self) -> int:
        """Return work that can still change the visible presentation."""
        return sum(
            pending.lane is not _RefinementLane.PREFETCH
            for pending in self._pending.values()
        ) + len(self._deferred)

    @property
    def pending_tile_count(self) -> int:
        """Return the number of uncached tiles currently being evaluated."""
        return sum(len(pending.signature) for pending in self._pending.values()) + sum(
            len(deferred.requests) for deferred in self._deferred.values()
        )

    @property
    def prefetch_pending(self) -> bool:
        """Return whether speculative guard refinement can still publish."""
        return (
            self._prefetch_timer.isActive()
            or bool(self._deferred_prefetch)
            or any(
                pending.lane is _RefinementLane.PREFETCH
                for pending in self._pending.values()
            )
        )

    def suspend_for_navigation(self) -> None:
        """Cancel sampled refinement while viewport input owns responsiveness."""
        if self._closed:
            return
        self._navigation_suspended = True
        self._prefetch_timer.stop()
        self._deferred_prefetch.clear()
        for identity in tuple(self._pending):
            self._cancel(identity)

    def resume_after_navigation(self) -> None:
        """Allow the next settled frame to schedule current sampled refinement."""
        if self._closed or not self._navigation_suspended:
            return
        self._navigation_suspended = False

    def request(
        self,
        *,
        source: RenderTileBatchSource,
        source_to_panel: QTransform,
        panel_rect: QRectF,
        device_pixel_ratio: float,
        maximum_scale: float | None = None,
    ) -> RenderRefinement:
        """Return, schedule, or explicitly decline one visible tile set."""
        if self._cache.budget_bytes <= 0:
            return RenderRefinement.unavailable()
        overview_requests = self._overview_requests_for(source)
        overview_bytes = estimated_request_bytes(overview_requests)
        detail_budget_bytes = max(0, self._cache.budget_bytes - overview_bytes)
        visible_requests = _visible_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=source_to_panel,
            panel_rect=panel_rect,
            device_pixel_ratio=device_pixel_ratio,
            budget_bytes=detail_budget_bytes,
            maximum_scale=maximum_scale,
        )
        if visible_requests is None:
            visible_requests = overview_requests
        visible_signature = tuple(request.key for request in visible_requests)
        if not visible_signature:
            return RenderRefinement.ready(())
        overview_signature = tuple(request.key for request in overview_requests)
        cached = self._cache.products(visible_signature)
        if cached is None and isinstance(source, _ImmediateTileSource):
            immediate = source.immediate_products(visible_requests)
            if immediate is not None:
                self._cache.admit(immediate, retain_keys=visible_signature)
                return RenderRefinement.ready(immediate)
        if not self._navigation_suspended:
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
            overview_keys = frozenset(overview_signature)
            detail_requests = tuple(
                request
                for request in unique_requests(visible_requests)
                if request.key not in overview_keys
            )
            detail_signature = tuple(request.key for request in detail_requests)
            detail_retained_signature = tuple(
                dict.fromkeys((*overview_signature, *detail_signature))
            )
            if self._navigation_suspended or (
                continuity_pending and self._cache.products(overview_signature) is None
            ):
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
        if cached is not None and not self._navigation_suspended:
            self._schedule_prefetch(
                source=source,
                source_to_panel=source_to_panel,
                panel_rect=panel_rect,
                visible_requests=visible_requests,
                overview_signature=overview_signature,
            )
        identity = (source.source_kind, source.source_id)
        if cached is not None:
            return RenderRefinement.ready(cached)
        fallback = self._cache.presentation_products(visible_requests)
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

    def _schedule_prefetch(
        self,
        *,
        source: RenderTileBatchSource,
        source_to_panel: QTransform,
        panel_rect: QRectF,
        visible_requests: tuple[RenderTileRequest, ...],
        overview_signature: tuple[RenderTileKey, ...],
    ) -> None:
        """Debounce speculative work until the viewport has stopped changing."""
        identity = (source.source_kind, source.source_id)
        self._cancel((*identity, _RefinementLane.PREFETCH))
        self._deferred_prefetch[identity] = _DeferredPrefetch(
            source,
            source_to_panel,
            panel_rect,
            visible_requests,
            overview_signature,
        )
        self._prefetch_timer.start()

    def _start_deferred_prefetch(self) -> None:
        """Submit latest guard requests after one navigation settle interval."""
        pending = tuple(self._deferred_prefetch.values())
        self._deferred_prefetch.clear()
        if self._navigation_suspended:
            return
        for request in pending:
            self._ensure_prefetch(
                source=request.source,
                source_to_panel=request.source_to_panel,
                panel_rect=request.panel_rect,
                visible_requests=request.visible_requests,
                overview_signature=request.overview_signature,
            )

    def _ensure_prefetch(
        self,
        *,
        source: RenderTileBatchSource,
        source_to_panel: QTransform,
        panel_rect: QRectF,
        visible_requests: tuple[RenderTileRequest, ...],
        overview_signature: tuple[RenderTileKey, ...],
    ) -> None:
        """Warm a bounded guard only after current viewport detail is complete."""
        overview_bytes = estimated_request_bytes(
            tuple(
                request
                for request in self._overview_requests_for(source)
                if request.key in frozenset(overview_signature)
            )
        )
        guarded = guarded_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=source_to_panel,
            panel_rect=panel_rect,
            budget_bytes=max(0, self._cache.budget_bytes - overview_bytes),
            visible_requests=visible_requests,
        )
        occupied = frozenset(
            (*overview_signature, *(request.key for request in visible_requests))
        )
        prefetch_requests = tuple(
            request
            for request in unique_requests(guarded)
            if request.key not in occupied
        )
        prefetch_signature = tuple(request.key for request in prefetch_requests)
        if not prefetch_signature:
            return
        self._ensure_work(
            lane=_RefinementLane.PREFETCH,
            source=source,
            requests=prefetch_requests,
            required_signature=prefetch_signature,
            retained_signature=tuple(
                dict.fromkeys(
                    (
                        *overview_signature,
                        *(request.key for request in visible_requests),
                        *prefetch_signature,
                    )
                )
            ),
        )

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
            budget_bytes=budget_bytes // 2,
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
                resource_id=f"render-{lane.value}",
                urgency=(
                    ExecutionUrgency.BACKGROUND
                    if lane is _RefinementLane.PREFETCH
                    else ExecutionUrgency.FOREGROUND
                ),
                maximum_concurrency=1,
                estimated_retained_bytes=estimated_request_bytes(missing_requests),
            ),
            work=lambda context: _render_tiles(
                source,
                missing_requests,
                context.cancellation,
                chunk_size=(
                    _PREFETCH_CHUNK_TILES
                    if lane is _RefinementLane.PREFETCH
                    else _REFINEMENT_CHUNK_TILES
                ),
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda products: self._finish(identity, pending, products),
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
            if pending.lane is not _RefinementLane.PREFETCH:
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
        try:
            self._prefetch_timer.stop()
        except RuntimeError:
            pass
        for identity in tuple(self._pending):
            self._cancel(identity)
        self._deferred.clear()
        self._deferred_prefetch.clear()
        self._overview_requests.clear()
        self._rejected.clear()
        self._execution_scope.close(reason="render_refinement_shutdown")

    def _finish(
        self,
        identity: tuple[str, uuid.UUID, _RefinementLane],
        expected: _PendingTiles,
        products: tuple[RenderTileProduct, ...],
    ) -> None:
        """Publish only the exact latest complete request for a source."""
        pending = self._pending.get(identity)
        if pending is not expected:
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
            if pending.lane is not _RefinementLane.PREFETCH:
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
        if pending.lane is not _RefinementLane.PREFETCH:
            self._ready()

    def _start_deferred_detail(
        self,
        source_kind: str,
        source_id: uuid.UUID,
    ) -> None:
        """Submit the latest detail work after its continuity lane settles."""
        identity = (source_kind, source_id, _RefinementLane.DETAIL)
        deferred = self._deferred.get(identity)
        if deferred is None or self._closed or self._navigation_suspended:
            return
        self._deferred.pop(identity, None)
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
