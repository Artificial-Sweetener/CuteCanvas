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

"""Tile generation and caching primitives powered by the shared task executor."""

import logging
from collections import OrderedDict
from collections import OrderedDict as OrderedDictType
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from ..core import CacheSettings, Config
from ..core.threading import assert_qt_main_thread
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
    RetryController,
    RetryPolicy,
)
from ..execution.qt_delay import QtDelayScheduler
from ..scene.identity import SceneLayerAssetKey, SceneLayerTileKey, SourceRenderAssetKey
from .cache_metrics import CacheManagerMetrics, CacheMetricsMixin
from .owner_callback import OwnerCallback

logger = logging.getLogger(__name__)

_TILE_EVICTION_BATCH = 16
_TILE_RETRY_BASE_MS = 50
_TILE_RETRY_MAX_MS = 1000


@dataclass(slots=True, frozen=True)
class Tile:
    """A container for tile data and its memory footprint."""

    key: SceneLayerTileKey
    image: QImage
    size_bytes: int = field(init=False)

    def __post_init__(self):
        """Calculate the byte footprint for this tile image."""
        # QImage.sizeInBytes() is more accurate than width * height * depth/8
        object.__setattr__(self, "size_bytes", self.image.sizeInBytes())


@dataclass(slots=True, frozen=True)
class _SourceTilePayloadKey:
    """Source-oriented identity for one pyramid tile payload."""

    pyramid_asset_key: SourceRenderAssetKey
    pyramid_scale: float
    row: int
    col: int

    @classmethod
    def from_layer_key(cls, key: SceneLayerTileKey) -> "_SourceTilePayloadKey":
        """Project a layer-aware tile key to its shared source payload identity."""
        return cls(
            pyramid_asset_key=key.pyramid_asset_key,
            pyramid_scale=key.pyramid_scale,
            row=key.row,
            col=key.col,
        )


def _generate_tile(
    key: SceneLayerTileKey,
    source_image: QImage,
    tile_size: int,
    tile_overlap: int,
    cancellation: CancellationToken,
) -> Tile:
    """Crop one detached tile product cooperatively."""
    cancellation.raise_if_cancelled()
    stride = tile_size - tile_overlap
    x = key.col * stride
    y = key.row * stride
    cropped_image = source_image.copy(x, y, tile_size, tile_size)
    cancellation.raise_if_cancelled()
    return Tile(key=key, image=cropped_image)


# Typed aliases for clarity
TileCache = OrderedDictType[_SourceTilePayloadKey, Tile]


WorkerState = dict[SceneLayerTileKey, ExecutionHandle[Tile, object]]


class TileManager(QObject, CacheMetricsMixin):
    """Generate, cache, and serve image tiles with executor-backed workers.

    Provides LRU eviction by byte budget, tracks prefetch stats, and emits throttle events when executor limits reject work.
    All public entrypoints expect to run on the Qt main thread; retry scheduling relies on the shared controller's main-thread dispatch.
    """

    tileReady = Signal(object)
    tilesThrottled = Signal(object, int)
    usageChanged = Signal(object)
    cacheLimitChanged = Signal(object)

    def __init__(
        self,
        config: Config,
        parent: QObject | None = None,
        *,
        execution_scope: ExecutionScope,
    ):
        """Initialise cache limits, worker pools, and retry bookkeeping."""
        super().__init__(parent)
        CacheMetricsMixin.__init__(self)
        self._config = config
        self.tile_size = config.tile_size
        self.tile_overlap = config.tile_overlap
        self._cache_admission_guard = None
        self._managed_mode = False
        self._rejected_cache_keys: set[SceneLayerTileKey] = set()
        self._tile_cache: TileCache = OrderedDict()
        self._payload_layer_keys: dict[
            _SourceTilePayloadKey, set[SceneLayerTileKey]
        ] = {}
        self._worker_payload_keys: dict[SceneLayerTileKey, _SourceTilePayloadKey] = {}
        self._payload_workers: dict[_SourceTilePayloadKey, SceneLayerTileKey] = {}
        self._payload_waiters: dict[_SourceTilePayloadKey, set[SceneLayerTileKey]] = {}
        self._cache_size_bytes: int = 0
        self._cache_limit_bytes: int = 0
        self.cache_limit_bytes = self._resolve_cache_limit_bytes(config)
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:tiles"
        )
        self._worker_state: WorkerState = {}
        self._tile_retry: RetryController[
            SceneLayerTileKey,
            QImage,
            Tile,
            object,
        ] = RetryController(
            "tiles",
            RetryPolicy(
                base_ms=_TILE_RETRY_BASE_MS,
                max_ms=_TILE_RETRY_MAX_MS,
            ),
            QtDelayScheduler(self),
        )
        self._eviction = OwnerCallback(self)

    @property
    def cache_usage_bytes(self) -> int:
        """Return the current tile cache usage in bytes."""
        return self._cache_size_bytes

    @property
    def cache_limit_bytes(self) -> int:
        """Return the configured tile cache budget in bytes."""
        return self._cache_limit_bytes

    @cache_limit_bytes.setter
    def cache_limit_bytes(self, value: int) -> None:
        """Set the tile cache budget and emit change notifications."""
        new_value = max(0, int(value))
        previous = getattr(self, "_cache_limit_bytes", 0)
        self._cache_limit_bytes = new_value
        if new_value != previous:
            self.cacheLimitChanged.emit(new_value)
        if not self._managed_mode and self._cache_size_bytes > self._cache_limit_bytes:
            self._schedule_cache_eviction()

    def set_managed_mode(self, enabled: bool) -> None:
        """Enable or disable managed mode.

        In managed mode, the manager disables automatic self-eviction and relaxes
        admission checks, relying on an external coordinator to drive trims.
        """
        self._managed_mode = bool(enabled)

    def set_admission_guard(self, guard: Callable[[int], bool] | None) -> None:
        """Install an optional hard-cap guard consulted before caching tiles."""
        self._cache_admission_guard = guard

    def apply_config(self, config: Config) -> None:
        """Refresh derived values after a configuration update."""
        previous_tile_size = self.tile_size
        previous_tile_overlap = self.tile_overlap
        self._config = config
        self.tile_size = config.tile_size
        self.tile_overlap = config.tile_overlap
        if (self.tile_size != previous_tile_size) or (
            self.tile_overlap != previous_tile_overlap
        ):
            self.clear_caches()
        if self._eviction.pending:
            self._cancel_eviction_task()
        self.cache_limit_bytes = self._resolve_cache_limit_bytes(config)
        if not self._managed_mode and self._cache_size_bytes > self.cache_limit_bytes:
            self._schedule_cache_eviction()

    def snapshot_metrics(self) -> CacheManagerMetrics:
        """Return cache and prefetch counters for diagnostics and tests."""
        return self._snapshot_cache_metrics(
            cache_bytes=self._cache_size_bytes,
            cache_limit=self.cache_limit_bytes,
            active_jobs=len(self._worker_state),
            pending_retries=len(self.pending_retry_tiles()),
        )

    def retry_snapshot(self):
        """Expose the retry controller snapshot for diagnostics consumers."""
        return self._tile_retry.snapshot()

    def pending_retry_tiles(self) -> list[SceneLayerTileKey]:
        """Return tile keys currently queued for retry."""
        return list(self._tile_retry.pending_keys())

    def _set_cache_usage_bytes(self, value: int) -> None:
        """Clamp and publish cache usage changes."""
        clamped = max(0, int(value))
        if clamped == self._cache_size_bytes:
            return
        self._cache_size_bytes = clamped
        self.usageChanged.emit(clamped)

    def add_tile(self, tile: Tile) -> None:
        """Insert `tile` into the cache while updating bookkeeping."""
        key = tile.key
        if not self._allow_cache_insert(tile.size_bytes, key):
            return
        payload_key = _SourceTilePayloadKey.from_layer_key(key)
        new_size = self._cache_size_bytes
        previous = self._tile_cache.pop(payload_key, None)
        if previous is not None:
            new_size = max(0, new_size - previous.size_bytes)
        self._tile_cache[payload_key] = tile
        self._tile_cache.move_to_end(payload_key)
        self._payload_layer_keys.setdefault(payload_key, set()).add(key)
        new_size += tile.size_bytes
        self._set_cache_usage_bytes(new_size)
        if (
            not self._managed_mode
            and self.cache_limit_bytes > 0
            and self._cache_size_bytes > self.cache_limit_bytes
        ):
            self._schedule_cache_eviction()

    def get_tile(
        self,
        key: SceneLayerTileKey,
        source_image: QImage,
        *,
        prefetch: bool = False,
    ) -> QImage | None:
        """Retrieves a tile image from the cache or starts a worker to generate it.

        Args:
            key: The scene/layer-aware key for the tile.
            source_image: The QImage to crop from if generation is needed.
            prefetch: Submit newly generated work on the lower-priority prefetch lane.

        Returns:
            The cached QImage if present, or None if generation is pending.

        Side effects:
            May enqueue a worker, update cache, or emit signals.
        """
        self._assert_main_thread()
        payload_key = _SourceTilePayloadKey.from_layer_key(key)
        cached_tile = self._tile_cache.get(payload_key)
        if cached_tile is not None:
            self._tile_cache.move_to_end(payload_key)
            self._payload_layer_keys.setdefault(payload_key, set()).add(key)
            self._cancel_tile_retry(key)
            self._cache_hits += 1
            return cached_tile.image
        representative = self._payload_workers.get(payload_key)
        if representative is not None or payload_key in self._payload_waiters:
            self._payload_waiters.setdefault(payload_key, set()).add(key)
            return None
        self._cache_misses += 1
        self._payload_waiters.setdefault(payload_key, set()).add(key)
        if prefetch:
            self._prefetch_begin(key)
        urgency = (
            ExecutionUrgency.OPPORTUNISTIC if prefetch else ExecutionUrgency.INTERACTIVE
        )

        def _submit(
            image: QImage,
            attempt: int,
        ) -> ExecutionHandle[Tile, object]:
            """Submit one detached tile request through the manager scope."""
            detached_image = QImage(image)
            self._mark_submitting(key, payload_key=payload_key)
            request = ExecutionRequest[Tile, object](
                operation="render.tile.prefetch" if prefetch else "render.tile.visible",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.NATIVE_CPU,
                    urgency=urgency,
                    estimated_retained_bytes=max(
                        0,
                        self.tile_size * self.tile_size * 4,
                    ),
                ),
                tags=(("attempt", attempt),),
                work=lambda context: _generate_tile(
                    key,
                    detached_image,
                    self.tile_size,
                    self.tile_overlap,
                    context.cancellation,
                ),
            )
            try:
                handle = self._execution_scope.submit(
                    request,
                    adopt=self._on_tile_generated,
                )
            except ExecutionRejected:
                self._discard_submitting(key, payload_key)
                raise
            handle.add_done_callback(
                lambda outcome: self._on_tile_outcome(key, outcome)
            )
            if not handle.state.is_terminal:
                self._worker_state[key] = handle
                self._prefetch_mark_started(key)
            logger.debug("Queued tile generation for %s", key)
            return handle

        def _throttle(
            rejected_key: SceneLayerTileKey,
            next_attempt: int,
            rejection: ExecutionRejected,
        ) -> None:
            """Emit throttle diagnostics when runtime capacity rejects a tile."""
            logger.warning(
                "Tile generation for %s throttled: %s (%s)",
                rejected_key,
                rejection,
                rejection.reason.value,
            )
            self.tilesThrottled.emit(rejected_key, next_attempt)

        self._queue_tile_retry(
            key,
            source_image,
            submit=_submit,
            throttle=_throttle,
        )
        return None

    def calculate_grid_dimensions(self, width: int, height: int) -> tuple[int, int]:
        """Return the tile grid size needed to cover `width` by `height`."""
        if width <= 0 or height <= 0:
            return 0, 0
        tile_size = max(1, int(self.tile_size))
        overlap = max(0, int(self.tile_overlap))
        step = max(1, tile_size - overlap)
        cols = max(1, (max(0, width - overlap) + step - 1) // step)
        rows = max(1, (max(0, height - overlap) + step - 1) // step)
        return cols, rows

    def _remove_tile_locked(self, key: SceneLayerTileKey) -> None:
        """Remove ``key`` from the cache while updating size tracking."""
        payload_key = _SourceTilePayloadKey.from_layer_key(key)
        tile = self._tile_cache.pop(payload_key, None)
        if tile is None:
            return
        self._payload_layer_keys.pop(payload_key, None)
        self._set_cache_usage_bytes(max(0, self._cache_size_bytes - tile.size_bytes))

    def clear_caches(self):
        """Removes all tiles from the cache and resets memory counters.

        Side effects:
            Cancels eviction, clears retry state, resets cache and worker state.
        """
        self._assert_main_thread()
        self._cancel_eviction_task()
        self._cancel_all_tile_retries()
        self._execution_scope.cancel_all(reason="tile_cache_clear")
        had_entries = bool(self._tile_cache)
        cached_tiles = len(self._tile_cache)
        active_workers = len(self._worker_state)
        self._tile_cache.clear()
        self._payload_layer_keys.clear()
        self._worker_payload_keys.clear()
        self._payload_workers.clear()
        self._payload_waiters.clear()
        self._worker_state.clear()
        self._rejected_cache_keys.clear()
        self._prefetch_drop_all()
        self._reset_cache_metrics()
        self._set_cache_usage_bytes(0)
        if had_entries:
            self._record_eviction_metadata("clear")
        logger.info(
            "Cleared tile cache (tiles=%d, workers=%d)",
            cached_tiles,
            active_workers,
        )

    def remove_tiles_for_asset(self, asset_key: SceneLayerAssetKey) -> None:
        """Remove all tiles associated with a scene layer asset.

        Args:
            asset_key: Asset identity to remove tiles for.

        Side effects:
            Cancels workers, updates cache/state, emits logs.
        """
        self._assert_main_thread()
        for payload_key, layer_keys in list(self._payload_layer_keys.items()):
            matching_keys = [key for key in layer_keys if key.asset_key == asset_key]
            layer_keys.difference_update(matching_keys)
            if layer_keys:
                continue
            tile = self._tile_cache.pop(payload_key, None)
            self._payload_layer_keys.pop(payload_key, None)
            if tile is not None:
                self._set_cache_usage_bytes(
                    max(0, self._cache_size_bytes - tile.size_bytes)
                )
        retry_keys = [
            key for key in self._pending_tile_retry_keys() if key.asset_key == asset_key
        ]
        for key in retry_keys:
            payload_key = _SourceTilePayloadKey.from_layer_key(key)
            waiters = self._payload_waiters.get(payload_key)
            if waiters is not None:
                waiters.difference_update(
                    waiter for waiter in list(waiters) if waiter.asset_key == asset_key
                )
                if waiters:
                    continue
            self._cancel_tile_retry(key)
            self._prefetch_finish(key, success=False)
        worker_ids = [key for key in self._worker_state if key.asset_key == asset_key]
        for key in worker_ids:
            payload_key = self._worker_payload_keys.get(
                key,
                _SourceTilePayloadKey.from_layer_key(key),
            )
            waiters = self._payload_waiters.get(payload_key)
            if waiters is not None:
                waiters.difference_update(
                    waiter for waiter in list(waiters) if waiter.asset_key == asset_key
                )
                if waiters:
                    continue
            entry = self._worker_state.pop(key, None)
            if not entry:
                continue
            cancelled = self._stop_worker(
                key,
                entry=entry,
                already_removed=True,
            )
            logger.info(
                "Cancelled inflight tile %s due to source eviction (cancelled=%s)",
                key,
                cancelled,
            )

    def remove_tiles_for_source_asset(
        self, pyramid_asset_key: SourceRenderAssetKey
    ) -> None:
        """Remove all tiles generated from a source/pyramid asset."""
        self._assert_main_thread()
        payloads_to_remove = [
            key
            for key in self._tile_cache
            if key.pyramid_asset_key == pyramid_asset_key
        ]
        for payload_key in payloads_to_remove:
            tile = self._tile_cache.pop(payload_key, None)
            self._payload_layer_keys.pop(payload_key, None)
            if tile is not None:
                self._set_cache_usage_bytes(
                    max(0, self._cache_size_bytes - tile.size_bytes)
                )
        retry_keys = [
            key
            for key in self._pending_tile_retry_keys()
            if key.pyramid_asset_key == pyramid_asset_key
        ]
        for key in retry_keys:
            self._cancel_tile_retry(key)
            self._prefetch_finish(key, success=False)
        worker_ids = [
            key
            for key in self._worker_state
            if key.pyramid_asset_key == pyramid_asset_key
        ]
        for key in worker_ids:
            entry = self._worker_state.pop(key, None)
            if not entry:
                continue
            cancelled = self._stop_worker(
                key,
                entry=entry,
                already_removed=True,
            )
            logger.info(
                "Cancelled inflight tile %s due to source eviction (cancelled=%s)",
                key,
                cancelled,
            )

    def cancel_invisible_workers(self, visible_identifiers: set):
        """Cancels any running workers for tiles that are no longer visible.

        Args:
            visible_identifiers: Set of SceneLayerTileKey currently visible.

        Side effects:
            Cancels workers, updates state, emits logs.
        """
        self._assert_main_thread()
        visible_identifiers = set(visible_identifiers)
        hidden_identifiers = [
            key
            for key in self._worker_state
            if not (
                self._payload_waiters.get(
                    self._worker_payload_keys.get(key),
                    {key},
                )
                & visible_identifiers
            )
        ]
        for identifier in hidden_identifiers:
            entry = self._worker_state.pop(identifier, None)
            if not entry:
                continue
            cancelled = self._stop_worker(
                identifier,
                entry=entry,
                already_removed=True,
            )
            logger.info(
                "Cancelled invisible tile worker %s (cancelled=%s)",
                identifier,
                cancelled,
            )
        for identifier in self._pending_tile_retry_keys():
            payload_key = _SourceTilePayloadKey.from_layer_key(identifier)
            if not (
                self._payload_waiters.get(payload_key, {identifier})
                & visible_identifiers
            ):
                self._cancel_tile_retry(identifier)

    def prefetch_tiles(
        self,
        keys: Sequence[SceneLayerTileKey],
        source_image: QImage,
        *,
        reason: str = "prefetch",
    ) -> list[SceneLayerTileKey]:
        """Schedule background generation for ``keys`` using ``source_image``."""
        if not keys or source_image.isNull():
            return []
        self._assert_main_thread()
        scheduled: list[SceneLayerTileKey] = []
        for key in keys:
            payload_key = _SourceTilePayloadKey.from_layer_key(key)
            if self._prefetch_pending(key):
                continue
            if payload_key in self._payload_workers:
                logger.debug(
                    "Skipping tile prefetch for %s; worker already active", key
                )
                continue
            cached_tile = self._tile_cache.get(payload_key)
            if cached_tile is not None:
                self._prefetch_skip_hit()
                continue
            self._prefetch_begin(key, record_start=False)
            try:
                self.get_tile(key, source_image, prefetch=True)
            except Exception:
                self._prefetch_finish(key, success=False)
                raise
            entry = self._worker_state.get(key)
            pending_retry = key in self._pending_tile_retry_keys()
            if entry is None and not pending_retry:
                cached_tile = self._tile_cache.get(payload_key)
                if cached_tile is not None:
                    self._prefetch_finish(key, success=True)
                else:
                    self._prefetch_finish(key, success=False)
                continue
            scheduled.append(key)
        if scheduled:
            for key in scheduled:
                logger.info("Scheduled tile prefetch %s (reason=%s)", key, reason)
        return scheduled

    def cancel_prefetch(
        self,
        keys: Sequence[SceneLayerTileKey],
        *,
        reason: str = "navigation",
    ) -> list[SceneLayerTileKey]:
        """Cancel outstanding prefetch workers for the provided identifiers."""
        if not keys:
            return []
        self._assert_main_thread()
        cancelled: list[SceneLayerTileKey] = []
        for key in keys:
            if not self._prefetch_pending(key):
                continue
            entry = self._worker_state.get(key)
            if entry:
                cancelled_flag = self._stop_worker(key, entry=entry)
                cancelled.append(key)
                logger.info(
                    "Cancelled tile prefetch %s (reason=%s, executor_cancelled=%s)",
                    key,
                    reason,
                    cancelled_flag,
                )
                continue
            if key in self._pending_tile_retry_keys():
                self._cancel_tile_retry(key)
                self._prefetch_finish(key, success=False)
                cancelled.append(key)
                logger.info(
                    "Cancelled tile prefetch %s before worker submission (reason=%s)",
                    key,
                    reason,
                )
        return cancelled

    def _allow_cache_insert(self, size_bytes: int, key: SceneLayerTileKey) -> bool:
        """Return True when ``size_bytes`` is within guardrail limits."""
        size = max(0, int(size_bytes))
        budget_limit = max(0, int(self.cache_limit_bytes))

        def _warn(limit_value: int) -> None:
            """Log cache admission rejection for oversize tile entries."""
            if key in self._rejected_cache_keys:
                return
            logger.warning(
                "requested item exceeds budget; not cached | consumer=tiles | "
                "size=%d | budget=%d",
                size,
                not self._managed_mode and limit_value,
            )
            self._rejected_cache_keys.add(key)

        if size > budget_limit:
            _warn(budget_limit)
            return False
        guard = self._cache_admission_guard
        if guard is not None and not guard(size):
            _warn(budget_limit)
            return False
        return True

    def _schedule_cache_eviction(self) -> None:
        """Queue a maintenance callback when cache usage exceeds the configured limit."""
        if self._eviction.pending:
            return
        if self._cache_size_bytes <= self.cache_limit_bytes or not self._tile_cache:
            return
        self._ensure_next_eviction_reason("limit")
        self._eviction.schedule(self._evict_cache_batch)

    def _evict_cache_batch(self) -> None:
        """Evict a bounded batch of tiles on the main thread."""
        reason = self._consume_next_eviction_reason("limit")
        evicted = 0
        new_usage = self._cache_size_bytes
        while (
            new_usage > self.cache_limit_bytes
            and self._tile_cache
            and evicted < _TILE_EVICTION_BATCH
        ):
            key, removed_tile = self._tile_cache.popitem(last=False)
            new_usage -= removed_tile.size_bytes
            logger.info("Evicted tile from cache: %s", key)
            self._evictions_total += 1
            self._evicted_bytes += removed_tile.size_bytes
            self._record_eviction_metadata(reason)
            evicted += 1
        self._set_cache_usage_bytes(new_usage)
        if (
            not self._managed_mode
            and self._cache_size_bytes > self.cache_limit_bytes
            and self._tile_cache
        ):
            self._schedule_cache_eviction()

    def _cancel_eviction_task(self) -> None:
        """Cancel any pending eviction maintenance task."""
        self._eviction.cancel()

    def _on_tile_generated(self, tile: Tile):
        """Slot for when a tile worker successfully finishes."""
        payload_key = self._worker_payload_keys.pop(
            tile.key,
            _SourceTilePayloadKey.from_layer_key(tile.key),
        )
        waiters = self._payload_waiters.pop(payload_key, {tile.key})
        self._payload_workers.pop(payload_key, None)
        self._worker_state.pop(tile.key, None)
        self._tile_retry.complete(tile.key)
        self.add_tile(tile)
        self._payload_layer_keys[payload_key] = set(waiters)
        self._prefetch_finish(tile.key, success=True)
        logger.info("Tile generated for %s", tile.key)
        for layer_key in waiters:
            self._payload_layer_keys.setdefault(payload_key, set()).add(layer_key)
            self.tileReady.emit(layer_key)

    def _on_tile_outcome(
        self,
        key: SceneLayerTileKey,
        outcome: ExecutionOutcome[Tile],
    ) -> None:
        """Clean up one tile request after cancellation or failure."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        error_message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        payload_key = self._worker_payload_keys.pop(
            key,
            _SourceTilePayloadKey.from_layer_key(key),
        )
        self._payload_workers.pop(payload_key, None)
        self._payload_waiters.pop(payload_key, None)
        self._worker_state.pop(key, None)
        self._tile_retry.complete(key)
        self._prefetch_finish(key, success=False)
        if outcome.state == ExecutionState.CANCELLED:
            logger.info("Tile generation cancelled for %s (%s)", key, error_message)
            return
        logger.error("Tile generation failed for %s: %s", key, error_message)

    def shutdown(self, *, wait: bool = True) -> None:
        """Cancel outstanding workers and optionally wait for executor cleanup."""
        self._assert_main_thread()
        self._cancel_eviction_task()
        self._cancel_all_tile_retries()
        for key, entry in list(self._worker_state.items()):
            cancelled = self._stop_worker(
                key,
                entry=entry,
                finalize_prefetch=False,
                cancel_retry=False,
            )
            logger.info(
                "Requested cancellation for tile %s (cancelled=%s)",
                key,
                cancelled,
            )
        self._worker_state.clear()
        self._prefetch_drop_all()
        self._execution_scope.close(reason="tile_manager_shutdown")
        if wait:
            logger.debug("Tile scope does not own the shared runtime")

    def _stop_worker(
        self,
        key: SceneLayerTileKey,
        *,
        entry: ExecutionHandle[Tile, object] | None = None,
        already_removed: bool = False,
        finalize_prefetch: bool = True,
        cancel_retry: bool = True,
    ) -> bool:
        """Cancel the worker represented by ``entry`` and update retry/prefetch state."""
        if entry is None:
            entry = self._worker_state.get(key)
        payload_key = self._worker_payload_keys.pop(
            key,
            _SourceTilePayloadKey.from_layer_key(key),
        )
        self._payload_workers.pop(payload_key, None)
        self._payload_waiters.pop(payload_key, None)
        if not already_removed:
            self._worker_state.pop(key, None)
        if entry is None:
            if finalize_prefetch:
                self._prefetch_finish(key, success=False)
            if cancel_retry:
                self._cancel_tile_retry(key)
            return False
        cancelled = entry.cancel(reason="tile_request_cancelled")
        if finalize_prefetch:
            self._prefetch_finish(key, success=False)
        if cancel_retry:
            self._cancel_tile_retry(key)
        return cancelled

    def _mark_submitting(
        self,
        key: SceneLayerTileKey,
        *,
        payload_key: _SourceTilePayloadKey,
    ) -> None:
        """Reserve source-oriented coalescing before backend submission."""
        self._worker_payload_keys[key] = payload_key
        self._payload_workers[payload_key] = key

    def _discard_submitting(
        self,
        key: SceneLayerTileKey,
        payload_key: _SourceTilePayloadKey,
    ) -> None:
        """Release a reservation after synchronous admission rejection."""
        self._worker_payload_keys.pop(key, None)
        self._payload_workers.pop(payload_key, None)

    def _queue_tile_retry(
        self,
        key: SceneLayerTileKey,
        source_image: QImage,
        *,
        submit: Callable[[QImage, int], ExecutionHandle[Tile, object]],
        throttle: Callable[[SceneLayerTileKey, int, ExecutionRejected], None],
    ) -> None:
        """Queue tile generation through the retry controller."""
        self._tile_retry.submit_or_coalesce(
            key,
            source_image,
            submit=submit,
            rejected=throttle,
        )

    def _cancel_tile_retry(self, key: SceneLayerTileKey) -> None:
        """Cancel a pending retry for ``key`` when present."""
        self._tile_retry.cancel(key)

    def _cancel_all_tile_retries(self) -> None:
        """Cancel every queued tile retry."""
        self._tile_retry.cancel_all()

    def _pending_tile_retry_keys(self) -> list[SceneLayerTileKey]:
        """Return identifiers pending retry without exposing controller internals."""
        return list(self._tile_retry.pending_keys())

    def _assert_main_thread(self) -> None:
        """Raise AssertionError if called off the Qt main thread."""
        assert_qt_main_thread(self)

    @staticmethod
    def _resolve_cache_limit_bytes(config: Config) -> int:
        """Return the tile cache budget derived from cache settings."""
        cache_settings = getattr(config, "cache", None)
        if not isinstance(cache_settings, CacheSettings):
            cache_settings = CacheSettings()
        budgets = cache_settings.resolved_consumer_budgets_bytes()
        return int(budgets.get("tiles", 0))
