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

"""Shared cache metrics dataclasses and mixins for rendering managers."""

from __future__ import annotations

import time
from collections.abc import Hashable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheManagerMetrics:
    """Runtime snapshot describing cache usage, retries, and prefetch telemetry."""

    cache_bytes: int
    cache_limit: int
    active_jobs: int
    pending_retries: int
    hits: int
    misses: int
    evictions: int
    evicted_bytes: int
    last_eviction_reason: str | None
    last_eviction_timestamp: float | None
    prefetch_requested: int = 0
    prefetch_completed: int = 0
    prefetch_failed: int = 0
    last_prefetch_ms: float | None = None


class CacheMetricsMixin:
    """Provide shared cache metrics bookkeeping for executor-backed managers."""

    def __init__(self, *_, **__) -> None:
        """Initialise cache, eviction, and prefetch counters to known defaults."""
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._evictions_total: int = 0
        self._evicted_bytes: int = 0
        self._last_eviction_reason: str | None = None
        self._last_eviction_timestamp: float | None = None
        self._next_eviction_reason: str | None = None
        self._prefetch_requested: int = 0
        self._prefetch_completed: int = 0
        self._prefetch_failed: int = 0
        self._last_prefetch_ms: float | None = None
        self._prefetch_tracking: dict[Hashable, int | None] = {}

    def _reset_cache_metrics(self) -> None:
        """Reset cache, eviction, and prefetch counters to their defaults."""
        self._cache_hits = 0
        self._cache_misses = 0
        self._evictions_total = 0
        self._evicted_bytes = 0
        self._last_eviction_reason = None
        self._last_eviction_timestamp = None
        self._next_eviction_reason = None
        self._prefetch_requested = 0
        self._prefetch_completed = 0
        self._prefetch_failed = 0
        self._last_prefetch_ms = None
        self._prefetch_drop_all()

    def _record_eviction_metadata(self, reason: str) -> None:
        """Capture bookkeeping for the most recent eviction batch."""
        self._last_eviction_reason = reason
        self._last_eviction_timestamp = time.monotonic()

    def _ensure_next_eviction_reason(self, reason: str) -> None:
        """Stage ``reason`` so the next eviction batch reports it consistently."""
        if self._next_eviction_reason is None:
            self._next_eviction_reason = reason

    def _consume_next_eviction_reason(self, default: str) -> str:
        """Return and clear any staged eviction reason, falling back to ``default``."""
        reason = self._next_eviction_reason or default
        self._next_eviction_reason = None
        return reason

    def _snapshot_cache_metrics(
        self,
        *,
        cache_bytes: int,
        cache_limit: int,
        active_jobs: int,
        pending_retries: int,
    ) -> CacheManagerMetrics:
        """Build a CacheManagerMetrics instance with the current counters."""
        return CacheManagerMetrics(
            cache_bytes=cache_bytes,
            cache_limit=cache_limit,
            active_jobs=active_jobs,
            pending_retries=pending_retries,
            hits=self._cache_hits,
            misses=self._cache_misses,
            evictions=self._evictions_total,
            evicted_bytes=self._evicted_bytes,
            last_eviction_reason=self._last_eviction_reason,
            last_eviction_timestamp=self._last_eviction_timestamp,
            prefetch_requested=self._prefetch_requested,
            prefetch_completed=self._prefetch_completed,
            prefetch_failed=self._prefetch_failed,
            last_prefetch_ms=self._last_prefetch_ms,
        )

    # Prefetch helpers -------------------------------------------------

    def _prefetch_begin(self, key: Hashable, *, record_start: bool = True) -> None:
        """Record bookkeeping for a new prefetch request."""
        self._prefetch_tracking[key] = time.perf_counter_ns() if record_start else None
        self._prefetch_requested += 1

    def _prefetch_mark_started(self, key: Hashable) -> None:
        """Record the start time once work for ``key`` finally begins."""
        if key not in self._prefetch_tracking:
            return
        if self._prefetch_tracking[key] is None:
            self._prefetch_tracking[key] = time.perf_counter_ns()

    def _prefetch_finish(self, key: Hashable, *, success: bool) -> None:
        """Record completion metadata for a tracked prefetch request."""
        start_ns = self._prefetch_tracking.pop(key, None)
        if start_ns is not None:
            self._last_prefetch_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        if success:
            self._prefetch_completed += 1
        else:
            self._prefetch_failed += 1

    def _prefetch_skip_hit(self) -> None:
        """Record a completed prefetch when work was already cached."""
        self._prefetch_completed += 1
        if self._last_prefetch_ms is None:
            self._last_prefetch_ms = 0.0

    def _prefetch_drop(self, key: Hashable) -> None:
        """Remove tracking for ``key`` without affecting counters."""
        self._prefetch_tracking.pop(key, None)

    def _prefetch_drop_all(self) -> None:
        """Clear tracking for all pending prefetch requests."""
        self._prefetch_tracking.clear()

    def _prefetch_pending(self, key: Hashable) -> bool:
        """Return True when ``key`` already has an in-flight prefetch."""
        return key in self._prefetch_tracking
