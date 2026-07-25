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

"""Generate and cache image pyramids on executor-backed workers while keeping UI work responsive."""

import logging
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
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
from ..scene.identity import SourceRenderAssetKey
from .cache_metrics import CacheManagerMetrics, CacheMetricsMixin
from .owner_callback import OwnerCallback

logger = logging.getLogger(__name__)

_PYRAMID_EVICTION_BATCH = 3
_PYRAMID_RETRY_BASE_MS = 75
_PYRAMID_RETRY_MAX_MS = 1500


class PyramidStatus(str, Enum):
    """Enumerates lifecycle states for pyramid generation."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ImagePyramid:
    """Container for the original image plus its downscaled pyramid levels.

    PyramidManager mutates status and levels on the main thread while workers populate levels in the background.
    """

    asset_key: SourceRenderAssetKey
    full_resolution_image: QImage
    levels: dict[float, QImage] = field(default_factory=dict)
    status: PyramidStatus = PyramidStatus.PENDING
    size_bytes: int = 0


def _generate_pyramid(
    asset_key: SourceRenderAssetKey,
    image: QImage,
    min_view_size_px: int,
    cancellation: CancellationToken,
) -> ImagePyramid:
    """Build one detached image-pyramid product cooperatively."""
    cancellation.raise_if_cancelled()
    source_image = QImage(image)
    if source_image.format() != QImage.Format_ARGB32_Premultiplied:
        source_image = source_image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    width, height = source_image.width(), source_image.height()
    current_scale = 1.0
    loop_width, loop_height = width, height
    levels: dict[float, QImage] = {}
    while max(loop_width, loop_height) > min_view_size_px:
        cancellation.raise_if_cancelled()
        current_scale /= 2.0
        new_width = int(width * current_scale)
        new_height = int(height * current_scale)
        if new_width <= 0 or new_height <= 0:
            break
        loop_width, loop_height = new_width, new_height
        levels[current_scale] = source_image.scaled(
            new_width,
            new_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        ).copy()
    cancellation.raise_if_cancelled()
    full_resolution_image = QImage(image)
    size_bytes = full_resolution_image.sizeInBytes() + sum(
        level.sizeInBytes() for level in levels.values()
    )
    return ImagePyramid(
        asset_key=asset_key,
        full_resolution_image=full_resolution_image,
        levels=levels,
        status=PyramidStatus.COMPLETE,
        size_bytes=size_bytes,
    )


class PyramidManager(QObject, CacheMetricsMixin):
    """Manage pyramid creation, caching, and retrieval for tiled rendering.

    Generates pyramids on the shared executor, enforces byte budgets with LRU eviction, and keeps mutations on the Qt main thread. Retry scheduling relies on the shared controller's main-thread dispatch. Callers treat returned ImagePyramids as read-only snapshots.
    """

    pyramidReady = Signal(object)
    pyramidThrottled = Signal(object, int)
    usageChanged = Signal(object)
    cacheLimitChanged = Signal(object)

    def __init__(
        self,
        config: Config,
        parent=None,
        *,
        execution_scope: ExecutionScope,
    ):
        """Initialise caches, workers, and retry controllers for pyramid generation."""
        super().__init__(parent)
        CacheMetricsMixin.__init__(self)
        self._config = config
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:pyramids"
        )
        self._managed_mode = False
        self._cache_limit_bytes: int = 0
        self._pyramids: dict[SourceRenderAssetKey, ImagePyramid] = {}
        self._cache: OrderedDict[SourceRenderAssetKey, ImagePyramid] = OrderedDict()
        self._cache_admission_guard = None
        self._rejected_cache_keys: set[SourceRenderAssetKey] = set()
        self._cache_size_bytes: int = 0
        self.cache_limit_bytes = self._resolve_cache_limit_bytes(config)
        self._active_handles: dict[
            SourceRenderAssetKey,
            ExecutionHandle[ImagePyramid, object],
        ] = {}
        self._pyramid_retry: RetryController[
            SourceRenderAssetKey,
            ImagePyramid,
            ImagePyramid,
            object,
        ] = RetryController(
            "pyramid",
            RetryPolicy(
                base_ms=_PYRAMID_RETRY_BASE_MS,
                max_ms=_PYRAMID_RETRY_MAX_MS,
            ),
            QtDelayScheduler(self),
        )
        self._eviction = OwnerCallback(self)

    def apply_config(self, config: Config) -> None:
        """Refresh derived values after a configuration update."""
        self._config = config
        self.cache_limit_bytes = self._resolve_cache_limit_bytes(config)
        if not self._managed_mode:
            self._enforce_cache_size()

    @property
    def cache_usage_bytes(self) -> int:
        """Return the current pyramid cache usage in bytes."""
        return self._cache_size_bytes

    @property
    def cache_limit_bytes(self) -> int:
        """Return the configured pyramid cache budget in bytes."""
        return self._cache_limit_bytes

    @cache_limit_bytes.setter
    def cache_limit_bytes(self, value: int) -> None:
        """Set the pyramid cache budget and emit change notifications."""
        new_value = max(0, int(value))
        previous = getattr(self, "_cache_limit_bytes", 0)
        self._cache_limit_bytes = new_value
        if new_value != previous:
            self.cacheLimitChanged.emit(new_value)
        if not self._managed_mode and self._cache_size_bytes > self._cache_limit_bytes:
            self._enforce_cache_size()

    def set_managed_mode(self, enabled: bool) -> None:
        """Enable or disable managed mode.

        In managed mode, the manager disables automatic self-eviction and relaxes
        admission checks, relying on an external coordinator to drive trims.
        """
        self._managed_mode = bool(enabled)

    def set_admission_guard(self, guard: Callable[[int], bool] | None) -> None:
        """Install an optional hard-cap guard consulted before caching pyramids."""
        self._cache_admission_guard = guard

    def mark_external_trim(self, reason: str) -> None:
        """Tag the next eviction batch with an external ``reason``."""
        self._next_eviction_reason = reason

    def pyramid_for_asset(
        self, asset_key: SourceRenderAssetKey
    ) -> "ImagePyramid | None":
        """Return the ImagePyramid for an asset key, or None if absent."""
        self._assert_main_thread()
        return self._pyramids.get(asset_key)

    def iter_cached_asset_keys(self):
        """Yield cached asset keys in LRU order (oldest first)."""
        self._assert_main_thread()
        return iter(self._cache.keys())

    def pending_asset_keys(self):
        """Return asset keys that still have generation in progress."""
        self._assert_main_thread()
        return set(self._active_handles)

    def prefetch_pyramid(
        self,
        asset_key: SourceRenderAssetKey,
        image: QImage,
        *,
        reason: str = "prefetch",
    ) -> bool:
        """Request background pyramid generation for ``asset_key`` if needed."""
        self._assert_main_thread()
        if not isinstance(asset_key, SourceRenderAssetKey):
            raise ValueError("asset_key is required")  # noqa: TRY004 - API contract
        if image.isNull():
            return False
        if self._prefetch_pending(asset_key):
            logger.debug("Pyramid prefetch already pending for %s", asset_key)
            return False
        pyramid = self._pyramids.get(asset_key)
        if pyramid is not None and pyramid.status == PyramidStatus.COMPLETE:
            self._prefetch_skip_hit()
            return False
        if asset_key in self._active_handles:
            logger.debug("Pyramid generation already active for %s", asset_key)
            return False
        self._prefetch_begin(asset_key, record_start=False)
        try:
            self.generate_pyramid_for_asset(asset_key, image)
        except Exception:
            self._prefetch_finish(asset_key, success=False)
            logger.exception(
                "Pyramid prefetch submission failed (asset_key=%s)", asset_key
            )
            raise
        logger.info("Scheduled pyramid prefetch for %s (reason=%s)", asset_key, reason)
        return True

    def cancel_prefetch(
        self,
        asset_keys: Sequence[SourceRenderAssetKey],
        *,
        reason: str = "navigation",
    ) -> list[SourceRenderAssetKey]:
        """Cancel outstanding pyramid prefetch requests."""
        if not asset_keys:
            return []
        self._assert_main_thread()
        cancelled: list[SourceRenderAssetKey] = []
        for asset_key in asset_keys:
            if not self._prefetch_pending(asset_key):
                continue
            cancelled_flag = self._cancel_active_generation(asset_key, reason=reason)
            self._cancel_pyramid_retry(asset_key)
            self._prefetch_finish(asset_key, success=False)
            cancelled.append(asset_key)
            logger.info(
                "Cancelled pyramid prefetch %s (reason=%s, executor_cancelled=%s)",
                asset_key,
                reason,
                cancelled_flag,
            )
        return cancelled

    def generate_pyramid_for_asset(
        self,
        asset_key: SourceRenderAssetKey,
        image: QImage,
    ):
        """Start a worker to generate a pyramid for ``asset_key``."""
        self._assert_main_thread()
        if not isinstance(asset_key, SourceRenderAssetKey):
            raise ValueError("asset_key is required")  # noqa: TRY004 - API contract
        existing = self._pyramids.get(asset_key)
        if existing is None:
            pyramid = ImagePyramid(
                asset_key=asset_key,
                full_resolution_image=image,
            )
            self._pyramids[asset_key] = pyramid
        else:
            pyramid = existing
            pyramid.full_resolution_image = image

        def _submit(
            pyr: ImagePyramid,
            attempt: int,
        ) -> ExecutionHandle[ImagePyramid, object]:
            """Submit ``pyr`` unless it already has active generation."""
            handle = self._active_handles.get(pyr.asset_key)
            if handle is not None:
                return handle
            source_image = QImage(pyr.full_resolution_image)
            min_view_size_px = int(self._config.min_view_size_px)
            request = ExecutionRequest[ImagePyramid, object](
                operation="render.pyramid",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.NATIVE_CPU,
                    urgency=ExecutionUrgency.FOREGROUND,
                    estimated_retained_bytes=max(
                        0,
                        int(source_image.sizeInBytes()),
                    ),
                ),
                tags=(("attempt", attempt),),
                work=lambda context: _generate_pyramid(
                    pyr.asset_key,
                    source_image,
                    min_view_size_px,
                    context.cancellation,
                ),
            )
            pyr.status = PyramidStatus.GENERATING
            try:
                handle = self._execution_scope.submit(
                    request,
                    adopt=self._on_pyramid_generated,
                )
            except ExecutionRejected:
                pyr.status = PyramidStatus.PENDING
                raise
            handle.add_done_callback(
                lambda outcome: self._on_pyramid_outcome(pyr.asset_key, outcome)
            )
            if not handle.state.is_terminal:
                self._active_handles[pyr.asset_key] = handle
                self._prefetch_mark_started(pyr.asset_key)
            logger.info("Queued pyramid generation for %s", pyr.asset_key)
            return handle

        def _coalesce(old: ImagePyramid, new: ImagePyramid) -> ImagePyramid:
            """Update ``old`` pyramid with the latest full-resolution image."""
            old.full_resolution_image = new.full_resolution_image
            return old

        def _throttle(
            asset_key: SourceRenderAssetKey,
            next_attempt: int,
            rejection: ExecutionRejected,
        ) -> None:
            """Record throttling metadata and emit the public signal."""
            logger.warning(
                "Pyramid generation for %s throttled: %s (%s)",
                asset_key,
                rejection,
                rejection.reason.value,
            )
            self.pyramidThrottled.emit(asset_key, next_attempt)

        self._queue_pyramid_retry(
            asset_key,
            pyramid,
            submit=_submit,
            throttle=_throttle,
            coalesce=_coalesce,
        )

    def _on_pyramid_generated(self, pyramid: ImagePyramid) -> None:
        """Adopt one complete detached pyramid product."""
        self._assert_main_thread()
        asset_key = pyramid.asset_key
        self._detach_worker(asset_key)
        self._pyramid_retry.complete(asset_key)
        self._prefetch_finish(asset_key, success=True)
        if asset_key not in self._pyramids:
            return
        self._pyramids[asset_key] = pyramid
        if self._allow_cache_insert(pyramid.size_bytes, asset_key):
            previous = self._cache.pop(asset_key, None)
            previous_bytes = previous.size_bytes if previous is not None else 0
            self._cache[asset_key] = pyramid
            self._set_cache_usage_bytes(
                self._cache_size_bytes - previous_bytes + pyramid.size_bytes
            )
            if not self._managed_mode:
                self._enforce_cache_size()
            logger.info("Pyramid generated for %s", asset_key)
        self.pyramidReady.emit(asset_key)

    def _on_pyramid_outcome(
        self,
        asset_key: SourceRenderAssetKey,
        outcome: ExecutionOutcome[ImagePyramid],
    ) -> None:
        """Apply cancellation or failure state after terminal execution."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        self._assert_main_thread()
        self._detach_worker(asset_key)
        self._pyramid_retry.complete(asset_key)
        self._prefetch_finish(asset_key, success=False)
        pyramid = self._pyramids.get(asset_key)
        if pyramid is not None:
            pyramid.status = (
                PyramidStatus.CANCELLED
                if outcome.state == ExecutionState.CANCELLED
                else PyramidStatus.FAILED
            )
        if outcome.state == ExecutionState.CANCELLED:
            logger.info(
                "Pyramid generation cancelled for %s (%s)",
                asset_key,
                outcome.cancellation_reason,
            )
        else:
            logger.error(
                "Pyramid generation failed for %s: %s",
                asset_key,
                outcome.error,
            )

    def get_best_fit_image_for_asset(
        self, asset_key: SourceRenderAssetKey, target_width: float
    ) -> QImage | None:
        """Return the pyramid level closest to the target width without upscaling.

        Falls back to the full-resolution image when no pyramid exists, generation failed or was cancelled, the target width is invalid, or the pyramid is incomplete or would upscale.
        """
        self._assert_main_thread()
        if asset_key is None:
            return None
        pyramid = self.pyramid_for_asset(asset_key)
        if pyramid is None:
            self._cache_misses += 1
            return None
        if pyramid.status in (PyramidStatus.CANCELLED, PyramidStatus.FAILED):
            self._cache_misses += 1
            return pyramid.full_resolution_image
        original_image = pyramid.full_resolution_image
        original_width = original_image.width()
        if original_width <= 0 or target_width is None or target_width <= 0:
            self._cache_misses += 1
            return original_image
        if (
            pyramid.status != PyramidStatus.COMPLETE
            or not pyramid.levels
            or target_width >= original_width
        ):
            self._cache_misses += 1
            return original_image
        target_scale = target_width / original_width
        # Pick the smallest scale that still meets ``target_scale``
        available_scales = [scale for scale in pyramid.levels if scale >= target_scale]
        best_scale = min(available_scales, default=None)
        if best_scale is not None:
            self._cache_hits += 1
            return pyramid.levels[best_scale]
        self._cache_misses += 1
        return original_image

    def remove_pyramid(self, asset_key: SourceRenderAssetKey) -> None:
        """Purge pyramid, cache state, and worker bookkeeping for ``asset_key``."""
        self._assert_main_thread()
        if not isinstance(asset_key, SourceRenderAssetKey):
            raise ValueError("asset_key is required")  # noqa: TRY004 - API contract
        was_cached = asset_key in self._cache
        had_worker = asset_key in self._active_handles
        cancelled = self._cancel_active_generation(asset_key, reason="asset-removal")
        self._drop_cache_entry(asset_key)
        self._cancel_pyramid_retry(asset_key)
        self._pyramids.pop(asset_key, None)
        self._prefetch_drop(asset_key)
        logger.info(
            "Removed pyramid state for %s (cached=%s, worker=%s, cancelled=%s)",
            asset_key,
            was_cached,
            had_worker,
            cancelled,
        )

    def clear(self) -> None:
        """Cancel workers, reset counters, and empty every cache entry."""
        self.shutdown(wait=False)
        self._assert_main_thread()
        pyramid_count = len(self._pyramids)
        self._pyramids.clear()
        had_entries = bool(self._cache)
        self._cache.clear()
        self._rejected_cache_keys.clear()
        self._prefetch_drop_all()
        self._reset_cache_metrics()
        self._set_cache_usage_bytes(0)
        assert self._cache_size_bytes == 0, "Cache size not zero after clear"
        if had_entries:
            self._record_eviction_metadata("clear")
        logger.info(
            "Cleared pyramid cache (pyramids=%d, cache_entries=%s)",
            pyramid_count,
            had_entries,
        )

    def snapshot_metrics(self) -> CacheManagerMetrics:
        """Return cache metrics for diagnostics and testing."""
        return self._snapshot_cache_metrics(
            cache_bytes=self._cache_size_bytes,
            cache_limit=self.cache_limit_bytes,
            active_jobs=len(self._active_handles),
            pending_retries=len(self.pending_retry_asset_keys()),
        )

    def retry_snapshot(self):
        """Expose the retry controller snapshot for diagnostics consumers."""
        return self._pyramid_retry.snapshot()

    def pending_retry_asset_keys(self) -> list[SourceRenderAssetKey]:
        """Return asset keys currently queued for retry."""
        return list(self._pyramid_retry.pending_keys())

    def _set_cache_usage_bytes(self, value: int) -> None:
        """Clamp and publish cache usage changes."""
        clamped = max(0, int(value))
        if clamped == self._cache_size_bytes:
            return
        self._cache_size_bytes = clamped
        self.usageChanged.emit(clamped)

    def _drop_cache_entry(self, asset_key: SourceRenderAssetKey) -> None:
        """Remove a pyramid from the LRU cache and update size accounting."""
        self._assert_main_thread()
        if asset_key in self._cache:
            self._set_cache_usage_bytes(
                self._cache_size_bytes - self._cache[asset_key].size_bytes
            )
            del self._cache[asset_key]
            assert self._cache_size_bytes >= 0, "Cache size went negative"

    def _allow_cache_insert(self, size_bytes: int, key: SourceRenderAssetKey) -> bool:
        """Return True when ``size_bytes`` is within pyramid guardrails."""
        size = max(0, int(size_bytes))
        budget_limit = max(0, int(self.cache_limit_bytes))

        def _warn(limit_value: int) -> None:
            """Log a cache admission rejection once per key."""
            if key in self._rejected_cache_keys:
                return
            logger.warning(
                "requested item exceeds budget; not cached | consumer=pyramids | "
                "size=%d | budget=%d",
                size,
                limit_value,
            )
            self._rejected_cache_keys.add(key)

        if not self._managed_mode and size > budget_limit:
            _warn(budget_limit)
            return False
        guard = self._cache_admission_guard
        if guard is not None and not guard(size):
            _warn(budget_limit)
            return False
        return True

    def _queue_pyramid_retry(
        self,
        asset_key: SourceRenderAssetKey,
        pyramid: "ImagePyramid",
        *,
        submit: Callable[
            ["ImagePyramid", int],
            ExecutionHandle[ImagePyramid, object],
        ],
        throttle: Callable[[SourceRenderAssetKey, int, ExecutionRejected], None],
        coalesce: (
            Callable[["ImagePyramid", "ImagePyramid"], "ImagePyramid"] | None
        ) = None,
    ) -> None:
        """Queue pyramid generation work through the retry controller."""
        self._pyramid_retry.submit_or_coalesce(
            asset_key,
            pyramid,
            submit=submit,
            rejected=throttle,
            merge=coalesce,
        )

    def _cancel_pyramid_retry(self, asset_key: SourceRenderAssetKey) -> None:
        """Cancel any pending retry for ``asset_key``."""
        self._pyramid_retry.cancel(asset_key)

    def _cancel_all_pyramid_retries(self) -> None:
        """Cancel every queued pyramid retry."""
        self._pyramid_retry.cancel_all()

    def _enforce_cache_size(self) -> None:
        """Request async eviction when the cache exceeds its budget."""
        if self._cache_size_bytes <= self.cache_limit_bytes or not self._cache:
            return
        if self._eviction.pending:
            return
        self._ensure_next_eviction_reason("limit")
        self._eviction.schedule(self._run_eviction_batch)

    def _run_eviction_batch(self) -> None:
        """Evict a bounded batch of pyramids on the main thread."""
        reason = self._consume_next_eviction_reason("limit")
        evicted = 0
        evicted_paths = []
        bytes_freed = 0
        new_usage = self._cache_size_bytes
        while (
            new_usage > self.cache_limit_bytes
            and self._cache
            and evicted < _PYRAMID_EVICTION_BATCH
        ):
            lru_key = next(iter(self._cache))
            removed_bytes = 0
            pyramid = self._cache.get(lru_key)
            if pyramid is not None:
                removed_bytes = pyramid.size_bytes
            self._drop_cache_entry(lru_key)
            if lru_key in self._pyramids:
                del self._pyramids[lru_key]
            if removed_bytes:
                bytes_freed += removed_bytes
                self._evicted_bytes += removed_bytes
                new_usage = max(0, new_usage - removed_bytes)
            evicted_paths.append(str(lru_key))
            self._evictions_total += 1
            self._record_eviction_metadata(reason)
            evicted += 1
        self._set_cache_usage_bytes(new_usage)
        if evicted_paths:
            logger.info(
                "Eviction batch: evicted=%d, paths=%s, bytes_freed=%d, "
                "total=%d, limit=%d",
                evicted,
                evicted_paths,
                bytes_freed,
                self._cache_size_bytes,
                self.cache_limit_bytes,
            )
        if (
            not self._managed_mode
            and self._cache_size_bytes > self.cache_limit_bytes
            and self._cache
        ):
            self._enforce_cache_size()

    def _cancel_eviction_task(self) -> None:
        """Cancel a pending eviction callback when one exists."""
        self._eviction.cancel()

    def shutdown(self, *, wait: bool = True) -> None:
        """Cancel workers and pending eviction callbacks."""
        self._assert_main_thread()
        self._cancel_eviction_task()
        self._cancel_all_pyramid_retries()
        for asset_key, handle in list(self._active_handles.items()):
            cancelled = handle.cancel(reason="pyramid_manager_shutdown")
            logger.info(
                "Requested cancellation for pyramid %s (cancelled=%s)",
                asset_key,
                cancelled,
            )
        self._active_handles.clear()
        self._prefetch_drop_all()
        self._execution_scope.close(reason="pyramid_manager_shutdown")
        if wait:
            logger.debug("Pyramid scope does not own the shared runtime")

    def _detach_worker(self, asset_key: SourceRenderAssetKey) -> None:
        """Remove bookkeeping for a finished or failed worker."""
        self._active_handles.pop(asset_key, None)

    def _cancel_active_generation(
        self, asset_key: SourceRenderAssetKey, *, reason: str
    ) -> bool:
        """Cancel active pyramid generation for ``asset_key`` when present."""
        handle = self._active_handles.pop(asset_key, None)
        cancelled = (
            handle.cancel(reason=f"pyramid_{reason}") if handle is not None else False
        )
        self._detach_worker(asset_key)
        return cancelled

    def _assert_main_thread(self):
        """Raise AssertionError if not running on the Qt main thread."""
        assert_qt_main_thread(self)

    @staticmethod
    def _resolve_cache_limit_bytes(config: Config) -> int:
        """Return the pyramid cache budget derived from cache settings."""
        cache_settings = getattr(config, "cache", None)
        if not isinstance(cache_settings, CacheSettings):
            cache_settings = CacheSettings()
        budgets = cache_settings.resolved_consumer_budgets_bytes()
        return int(budgets.get("pyramids", 0))
