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

"""Cache consumer adapters that surface usage to the coordinator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from .coordinator import CacheConsumerCallbacks, CacheCoordinator, CachePriority

logger = logging.getLogger(__name__)


class EvictableCache(Protocol):
    """Byte-counted cache that can discard its oldest products."""

    @property
    def cache_usage_bytes(self) -> int:
        """Return current derived-raster cache usage."""
        ...

    def set_cache_usage_callback(self, callback: Callable[[], None] | None) -> None:
        """Install a usage-change callback."""
        ...

    def set_admission_guard(self, guard: Callable[[int], bool] | None) -> None:
        """Install a cache admission guard."""
        ...

    def drop_oldest(self, *, reason: str) -> int:
        """Evict one derived raster and return freed bytes."""
        ...


class _BudgetedCacheConsumer:
    """Shared plumbing for cache consumers with soft budgets and batch trims."""

    def __init__(
        self,
        manager: Any,
        coordinator: CacheCoordinator,
        *,
        consumer_id: str,
        priority: CachePriority,
        usage_label: str,
        limit_label: str,
        trim_target_label: str,
        batch_hook: str,
        marker_attr: str,
        missing_batch_label: str,
        warn_message: str,
        pre_trim: Callable[[], None] | None = None,
    ) -> None:
        """Register manager cache signals and budgets with the shared coordinator."""
        self._manager = manager
        self._coordinator = coordinator
        self._consumer_id = consumer_id
        self._usage_label = usage_label
        self._limit_label = limit_label
        self._trim_target_label = trim_target_label
        self._batch_hook = batch_hook
        self._marker_attr = marker_attr
        self._missing_batch_label = missing_batch_label
        self._warn_message = warn_message
        self._pre_trim = pre_trim
        callbacks = CacheConsumerCallbacks(
            get_usage=self._get_usage,
            set_budget=self._set_budget,
            trim_to=self._trim_to,
        )
        coordinator.register_consumer(
            consumer_id,
            priority=priority,
            callbacks=callbacks,
            preferred_bytes=self._manager.cache_limit_bytes,
        )
        self._manager.set_managed_mode(True)
        _install_admission_guard(self._manager, coordinator.should_admit)
        coordinator.set_consumer_preferred(
            consumer_id,
            _safe_int(
                getattr(self._manager, "cache_limit_bytes", 0),
                label=self._limit_label,
            ),
        )
        self._connect_signals()

    def _update_preferred_budget(self, new_limit: int | None = None) -> None:
        """Refresh the preferred budget after config changes apply."""
        self._coordinator.set_consumer_preferred(
            self._consumer_id,
            _safe_int(
                (
                    new_limit
                    if new_limit is not None
                    else getattr(self._manager, "cache_limit_bytes", 0)
                ),
                label=self._limit_label,
            ),
        )

    def _connect_signals(self) -> None:
        """Subscribe to manager signals to track cache usage and budgets."""
        usage_signal = getattr(self._manager, "usageChanged", None)
        limit_signal = getattr(self._manager, "cacheLimitChanged", None)
        if usage_signal is None:
            logger.error(
                "%s missing usageChanged signal; cannot track cache usage",
                type(self._manager).__name__,
            )
            raise RuntimeError("Manager missing usageChanged signal")
        if limit_signal is None:
            logger.error(
                "%s missing cacheLimitChanged signal; cannot track budgets",
                type(self._manager).__name__,
            )
            raise RuntimeError("Manager missing cacheLimitChanged signal")
        try:
            usage_signal.connect(self._notify)
        except Exception:
            logger.exception("Failed to connect usageChanged for %s", self._consumer_id)
            raise
        try:
            limit_signal.connect(self._update_preferred_budget)
        except Exception:
            logger.exception(
                "Failed to connect cacheLimitChanged for %s", self._consumer_id
            )
            raise

    def _get_usage(self) -> int:
        """Return the current cache usage in bytes."""
        usage_getter = getattr(self._manager, "cache_usage_bytes", None)
        if usage_getter is None:
            logger.error(
                "%s manager missing cache_usage_bytes; cannot report cache usage",
                type(self._manager).__name__,
            )
            raise RuntimeError("cache_usage_bytes missing for cache consumer")
        try:
            return _safe_int(
                usage_getter() if callable(usage_getter) else usage_getter,
                label=self._usage_label,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "%s manager failed to report cache usage",
                type(self._manager).__name__,
            )
            raise

    def _set_budget(self, target_bytes: int) -> None:
        """Apply ``target_bytes`` as the cache limit."""
        self._manager.cache_limit_bytes = _safe_int(
            target_bytes,
            label=self._limit_label,
        )

    def _trim_to(self, target_bytes: int) -> None:
        """Attempt to shrink usage to ``target_bytes`` and warn if it fails."""
        target = _safe_int(target_bytes, label=self._trim_target_label)
        self._manager.cache_limit_bytes = min(self._manager.cache_limit_bytes, target)
        if self._pre_trim is not None:
            try:
                self._pre_trim()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Cache pre-trim hook failed", exc_info=True)
        _run_cache_batch_trim(
            consumer_id=self._consumer_id,
            get_usage=self._get_usage,
            batch=getattr(self._manager, self._batch_hook, None),
            target=target,
            marker=getattr(self._manager, self._marker_attr, None),
            missing_hook_label=self._missing_batch_label,
            warn_message=self._warn_message,
        )

    def _notify(self) -> None:
        """Publish cache usage to the coordinator."""
        usage = self._get_usage()
        self._coordinator.update_usage(self._consumer_id, usage)


class KeyedCacheConsumer:
    """Coordinate a keyed cache through injected domain operations."""

    def __init__(
        self,
        coordinator: CacheCoordinator,
        *,
        consumer_id: str,
        priority: CachePriority,
        get_usage: Callable[[], int],
        set_admission_guard: Callable[[Callable[[int], bool] | None], None],
        keys: Callable[[], tuple[object, ...]],
        remove: Callable[[object], object],
        connect_usage_events: Callable[[Callable[[], None], Callable[[], None]], None],
    ) -> None:
        """Register injected keyed-cache operations with the coordinator.

        Args:
            coordinator: Shared cache coordinator that enforces budgets.
            consumer_id: Diagnostics identifier exposed in trim logs.
            priority: Trim priority relative to other consumers.
            get_usage: Current resident byte count.
            set_admission_guard: Install the coordinator admission predicate.
            keys: Return keys in eviction order.
            remove: Remove one key.
            connect_usage_events: Connect changed and cleared callbacks.
        """
        self._coordinator = coordinator
        self._consumer_id = consumer_id
        self._get_usage_callback = get_usage
        self._keys = keys
        self._remove = remove
        callbacks = CacheConsumerCallbacks(
            get_usage=self._get_usage,
            set_budget=self._set_budget,
            trim_to=self._trim_to,
        )
        coordinator.register_consumer(
            consumer_id,
            priority=priority,
            callbacks=callbacks,
            preferred_bytes=None,
        )
        set_admission_guard(coordinator.should_admit)
        connect_usage_events(self._notify, self._on_cache_cleared)

    def _on_cache_cleared(self) -> None:
        """Reset resident accounting when the cache clears."""
        self._coordinator.update_usage(self._consumer_id, 0)

    def _get_usage(self) -> int:
        """Return current cache usage in bytes."""
        try:
            return _safe_int(
                self._get_usage_callback(),
                label=f"{self._consumer_id}_cache_usage_bytes",
            )
        except Exception:
            logger.exception("Keyed cache usage callback failed")
            raise

    def _set_budget(self, target_bytes: int) -> None:
        """Leave budget enforcement to explicit trims."""
        return

    def _trim_to(self, target_bytes: int) -> None:
        """Evict oldest keys until usage reaches ``target_bytes``."""
        target = _safe_int(target_bytes, label=f"{self._consumer_id}_trim_target")
        usage = self._get_usage()
        if usage <= target:
            return
        for key in self._keys():
            if usage <= target:
                break
            self._remove(key)
            usage = self._get_usage()
        usage = max(usage, 0)
        if usage > target:
            logger.warning(
                "Keyed cache failed to trim below target | consumer=%s | "
                "usage=%d | target=%d",
                self._consumer_id,
                usage,
                target,
            )

    def _notify(self) -> None:
        """Push current usage to the coordinator."""
        self._coordinator.update_usage(self._consumer_id, self._get_usage())


class EvictableCacheConsumer:
    """Coordinate a byte-counted oldest-first cache."""

    def __init__(
        self,
        controller: EvictableCache,
        coordinator: CacheCoordinator,
        *,
        consumer_id: str,
        priority: CachePriority,
    ) -> None:
        """Register an evictable cache with the coordinator.

        Args:
            controller: Cache providing usage and oldest-first eviction hooks.
            coordinator: Shared cache coordinator.
            consumer_id: Diagnostics identifier exposed in trim logs.
            priority: Trim priority relative to other consumers.
        """
        self._controller = controller
        self._coordinator = coordinator
        self._consumer_id = consumer_id
        callbacks = CacheConsumerCallbacks(
            get_usage=self._get_usage,
            set_budget=self._set_budget,
            trim_to=self._trim_to,
        )
        coordinator.register_consumer(
            consumer_id,
            priority=priority,
            callbacks=callbacks,
            preferred_bytes=None,
        )
        _install_admission_guard(self._controller, coordinator.should_admit)
        controller.set_cache_usage_callback(self._notify)
        self._notify()

    def _get_usage(self) -> int:
        """Return cache usage in bytes."""
        try:
            return _safe_int(
                self._controller.cache_usage_bytes,
                label=f"{self._consumer_id}_cache_usage_bytes",
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Evictable cache failed to report usage")
            raise

    def _set_budget(self, target_bytes: int) -> None:
        """Leave budget enforcement to explicit trims."""
        return

    def _trim_to(self, target_bytes: int) -> None:
        """Best-effort reduction of overlay cache usage to ``target_bytes``."""
        target = _safe_int(target_bytes, label=f"{self._consumer_id}_trim_target")
        usage = self._get_usage()
        if usage <= target:
            return
        while usage > target:
            freed = _safe_int(
                self._controller.drop_oldest(reason="coordinator"),
                label=f"{self._consumer_id}_trim_freed",
            )
            if freed <= 0:
                break
            usage = max(0, usage - freed)
        if usage > target:
            logger.warning(
                "Evictable cache failed to trim below target | consumer=%s | usage=%d | "
                "target=%d",
                self._consumer_id,
                usage,
                target,
            )

    def _notify(self) -> None:
        """Publish overlay cache usage to the coordinator."""
        self._coordinator.update_usage(self._consumer_id, self._get_usage())


class TileCacheConsumer(_BudgetedCacheConsumer):
    """Coordinates a :class:`TileManager` with the cache coordinator."""

    def __init__(
        self,
        manager: Any,
        coordinator: CacheCoordinator,
        *,
        consumer_id: str = "tiles",
        priority: CachePriority = CachePriority.TILES,
    ) -> None:
        """Register ``manager`` with ``coordinator`` and wrap cache hooks.

        Args:
            manager: Tile manager exposing cache hooks and metrics.
            coordinator: Shared cache coordinator.
            consumer_id: Diagnostics identifier exposed in trim logs.
            priority: Trim priority relative to other consumers.
        """
        super().__init__(
            manager,
            coordinator,
            consumer_id=consumer_id,
            priority=priority,
            usage_label="tile_cache_usage_bytes",
            limit_label="tile_cache_limit_bytes",
            trim_target_label="tile_trim_target",
            batch_hook="_evict_cache_batch",
            marker_attr="mark_external_trim",
            missing_batch_label="tile _evict_cache_batch",
            warn_message=(
                "Tile cache failed to trim below target | consumer=%s | usage=%d | "
                "target=%d | attempts=%d"
            ),
        )


class PyramidCacheConsumer(_BudgetedCacheConsumer):
    """Coordinates a :class:`PyramidManager` with the cache coordinator."""

    def __init__(
        self,
        manager: Any,
        coordinator: CacheCoordinator,
        *,
        consumer_id: str = "pyramids",
        priority: CachePriority = CachePriority.PYRAMIDS,
    ) -> None:
        """Register ``manager`` with ``coordinator`` and wrap cache hooks.

        Args:
            manager: Pyramid manager exposing cache hooks and metrics.
            coordinator: Shared cache coordinator.
            consumer_id: Diagnostics identifier exposed in trim logs.
            priority: Trim priority relative to other consumers.
        """
        super().__init__(
            manager,
            coordinator,
            consumer_id=consumer_id,
            priority=priority,
            usage_label="pyramid_cache_usage_bytes",
            limit_label="pyramid_cache_limit_bytes",
            trim_target_label="pyramid_trim_target",
            batch_hook="_run_eviction_batch",
            marker_attr="mark_external_trim",
            missing_batch_label="pyramid _run_eviction_batch",
            warn_message=(
                "Pyramid cache failed to trim below target | consumer=%s | "
                "usage=%d | target=%d | attempts=%d"
            ),
        )
        self._manager.set_managed_mode(True)


def _install_admission_guard(manager: Any, guard: Callable[[int], bool] | None) -> None:
    """Attach ``guard`` to ``manager`` when it advertises setter support."""
    setter = getattr(manager, "set_admission_guard", None)
    if not callable(setter):
        return
    try:
        setter(guard)
    except Exception:
        logger.debug(
            "Admission guard install failed for %s",
            type(manager).__name__,
            exc_info=True,
        )


def _run_cache_batch_trim(
    *,
    consumer_id: str,
    get_usage: Callable[[], int],
    batch: Callable[[], object] | None,
    target: int,
    marker: Callable[[str], None] | None,
    missing_hook_label: str,
    warn_message: str,
    max_attempts: int = 8,
) -> int:
    """Run cache-eviction batches while preserving existing trim semantics.

    Args:
        consumer_id: Registered cache identifier used in logs.
        get_usage: Callable that returns the current cache usage in bytes.
        batch: Hook that evicts a batch of cache entries when callable.
        target: Desired usage floor in bytes.
        marker: Optional hook used to tag externally initiated trims.
        missing_hook_label: Label describing the required batch hook for logs.
        warn_message: Format string logged when trims cannot reach the target.
        max_attempts: Maximum number of batch calls before giving up.

    Returns:
        Final usage reported by ``get_usage`` after batch trims complete.

    Raises:
        RuntimeError: When the required batch hook is missing.
    """
    usage = get_usage()
    if usage <= target:
        return usage
    if marker is not None:
        try:
            marker("coordinator")
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Cache trim marker failed for %s", consumer_id, exc_info=True)
    if not callable(batch):
        logger.error(
            "Cannot trim cache for consumer %s; missing batch hook %s",
            consumer_id,
            missing_hook_label,
        )
        raise RuntimeError(  # noqa: TRY004 - collaborator contract failure
            f"Missing cache trim hook {missing_hook_label}"
        )
    attempts = 0
    while usage > target and attempts < max_attempts:
        batch()
        attempts += 1
        usage = get_usage()
    if usage > target:
        logger.warning(
            warn_message,
            consumer_id,
            usage,
            target,
            attempts,
        )
    return usage


_INVALID_VALUE_LOGGED: set[str] = set()


def _safe_int(value: float, *, label: str | None = None) -> int:
    """Clamp the provided value to a non-negative integer."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        key = label or "cache_value"
        if key not in _INVALID_VALUE_LOGGED:
            logger.warning(
                "Invalid cache metric; defaulting to zero | label=%s | value=%r",
                key,
                value,
            )
            _INVALID_VALUE_LOGGED.add(key)
        return 0
