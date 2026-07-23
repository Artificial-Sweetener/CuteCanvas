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

"""Coordinate shared cache budgets across the QPane viewer's subsystems."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CacheConsumerCallbacks:
    """Hooks that let the coordinator inspect and enforce cache usage."""

    get_usage: Callable[[], int]
    set_budget: Callable[[int], None]
    trim_to: Callable[[int], None]


class CachePriority(IntEnum):
    """Eviction ordering where lower values trim before higher ones."""

    BACKGROUND_MODELS = 10
    BRUSH_TIPS = 15
    VECTOR_PRODUCTS = 18
    DERIVED_OVERLAYS = 20
    RASTER_PREVIEWS = 25
    TILES = 30
    PYRAMIDS = 40


@dataclass(slots=True)
class ConsumerRegistration:
    """Captured registration metadata plus optional budget hints."""

    consumer_id: str
    priority: CachePriority
    callbacks: CacheConsumerCallbacks
    weight: float = 1.0
    preferred_bytes: int | None = None
    override_bytes: int | None = None


@dataclass(slots=True)
class _ConsumerState:
    """Tracks live usage for a registered consumer and the last trim applied."""

    registration: ConsumerRegistration
    usage_bytes: int = 0
    last_trim: TrimRecord | None = None

    @property
    def consumer_id(self) -> str:
        """Expose the registered consumer identifier for logging helpers."""
        return self.registration.consumer_id


@dataclass(frozen=True, slots=True)
class TrimRecord:
    """Describe the last trim the coordinator asked a consumer to perform."""

    reason: str
    trimmed_bytes: int
    target_bytes: int
    timestamp: float


class CacheCoordinator:
    """Distributes a soft memory budget across cooperating cache consumers."""

    def __init__(
        self,
        active_budget_bytes: int,
        *,
        dirty_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the coordinator with a soft global budget.

        Args:
            active_budget_bytes: Maximum number of bytes the caches should hold
                collectively. Negative values are clamped to zero.
            dirty_callback: Optional callable notified when diagnostics should
                refresh cache domain rows.
        """
        self._active_budget_bytes = max(0, active_budget_bytes)
        self._consumers: dict[str, _ConsumerState] = {}
        self._missing_consumer_logs: set[tuple[str, str]] = set()
        self._dirty_callback = dirty_callback
        self._enforcing = False
        self._pending_enforce = False
        self._hard_cap_enabled = False
        self._last_trim_events: tuple[dict[str, object], ...] = ()
        self._headroom_snapshot: dict[str, object] | None = None

    @property
    def active_budget_bytes(self) -> int:
        """Return the configured global soft cap in bytes."""
        return self._active_budget_bytes

    @property
    def total_usage_bytes(self) -> int:
        """Return the current aggregate usage across all registered consumers."""
        return self._total_usage()

    def has_consumer(self, consumer_id: str) -> bool:
        """Return True when ``consumer_id`` is registered for coordination."""
        return consumer_id in self._consumers

    def set_hard_cap(self, enabled: bool) -> None:
        """Enable or disable hard-cap admissions."""
        self._hard_cap_enabled = bool(enabled)

    def set_active_budget(self, active_budget_bytes: int) -> None:
        """Update the global soft cap and immediately re-evaluate trims.

        Args:
            active_budget_bytes: New global soft limit. Negative inputs clamp to
                zero before being applied.
        """
        self._active_budget_bytes = max(0, active_budget_bytes)
        self._enforce_budget()

    def register_consumer(
        self,
        consumer_id: str,
        *,
        priority: CachePriority,
        callbacks: CacheConsumerCallbacks,
        weight: float = 1.0,
        preferred_bytes: int | None = None,
        override_bytes: int | None = None,
    ) -> ConsumerRegistration:
        """Register a cache owner and prime it with the resolved budget.

        Args:
            consumer_id: Unique identifier used for logging and diagnostics.
            priority: Trim order relative to other consumers.
            callbacks: Hook bundle that reports usage and performs trims.
            weight: Proportional entitlement used when trimming under contention.
            preferred_bytes: Soft target the coordinator should attempt to
                maintain unless an override is supplied.
            override_bytes: Hard ceiling that is enforced before global trims.

        Returns:
            The immutable registration record describing the consumer.

        Raises:
            ValueError: If a consumer with the same identifier already exists.

        Side effects:
            Invokes the consumer's ``set_budget`` callback and performs an
            immediate usage refresh so the shared budget reflects its state.
        """
        if consumer_id in self._consumers:
            raise ValueError(f"Consumer '{consumer_id}' already registered")
        registration = ConsumerRegistration(
            consumer_id=consumer_id,
            priority=priority,
            callbacks=callbacks,
            weight=max(0.0, float(weight)),
            preferred_bytes=preferred_bytes,
            override_bytes=(
                override_bytes if override_bytes is None else max(0, override_bytes)
            ),
        )
        self._consumers[consumer_id] = _ConsumerState(registration=registration)
        target = self._resolve_target_bytes(registration)
        if target is not None:
            registration.callbacks.set_budget(target)
        self._refresh_usage(consumer_id)
        return registration

    def update_usage(self, consumer_id: str, usage_bytes: int) -> None:
        """Record the latest usage for ``consumer_id`` and enforce budgets.

        Args:
            consumer_id: Registered cache identifier.
            usage_bytes: Current usage reported by the consumer.
        """
        state = self._consumers.get(consumer_id)
        if state is None:
            self._warn_unknown_consumer(consumer_id, "update_usage")
            return
        normalized_usage = max(0, usage_bytes)
        usage_changed = normalized_usage != state.usage_bytes
        state.usage_bytes = normalized_usage
        if self._enforcing:
            self._pending_enforce = self._pending_enforce or usage_changed
        else:
            self._enforce_budget()
        self._mark_dirty()

    def set_consumer_override(
        self, consumer_id: str, override_bytes: int | None
    ) -> None:
        """Set or clear a hard ceiling for ``consumer_id``.

        Args:
            consumer_id: Registered cache identifier.
            override_bytes: Maximum usage to enforce, or ``None`` to remove
                the override. Negative values clamp to zero.
        """
        state = self._consumers.get(consumer_id)
        if state is None:
            self._warn_unknown_consumer(consumer_id, "set_consumer_override")
            return
        registration = state.registration
        registration.override_bytes = (
            override_bytes if override_bytes is None else max(0, override_bytes)
        )
        target = self._resolve_target_bytes(registration)
        if target is not None:
            registration.callbacks.set_budget(target)
        self._enforce_budget()

    def set_consumer_weight(self, consumer_id: str, weight: float) -> None:
        """Update the weighting used when trimming ``consumer_id`` under contention."""
        state = self._consumers.get(consumer_id)
        if state is None:
            self._warn_unknown_consumer(consumer_id, "set_consumer_weight")
            return
        state.registration.weight = max(0.0, float(weight))
        self._enforce_budget()

    def set_consumer_preferred(
        self, consumer_id: str, preferred_bytes: int | None
    ) -> None:
        """Refresh the preferred (soft) budget for ``consumer_id``.

        Args:
            consumer_id: Registered cache identifier.
            preferred_bytes: Desired steady-state usage. ``None`` clears the
                hint and leaves the override, if present, as the active target.
        """
        state = self._consumers.get(consumer_id)
        if state is None:
            self._warn_unknown_consumer(consumer_id, "set_consumer_preferred")
            return
        registration = state.registration
        if preferred_bytes is None:
            registration.preferred_bytes = None
        else:
            registration.preferred_bytes = max(0, preferred_bytes)
        if registration.override_bytes is None:
            target = self._resolve_target_bytes(registration)
            if target is not None:
                registration.callbacks.set_budget(target)
        self._enforce_budget()

    def snapshot(self) -> dict[str, object]:
        """Capture a structured snapshot for diagnostics and tests.

        Returns:
            Dictionary describing the budget, usage, and per-consumer stats.
        """
        consumers: dict[str, dict[str, object]] = {}
        weights = {
            consumer_id: max(0.0, state.registration.weight)
            for consumer_id, state in self._consumers.items()
        }
        total_weight = sum(weights.values())
        if total_weight <= 0.0 and weights:
            total_weight = float(len(weights))
            weights = {consumer_id: 1.0 for consumer_id in weights}
        for consumer_id, state in self._consumers.items():
            registration = state.registration
            trim_record = (
                {
                    "reason": state.last_trim.reason,
                    "trimmed_bytes": state.last_trim.trimmed_bytes,
                    "target_bytes": state.last_trim.target_bytes,
                    "timestamp": state.last_trim.timestamp,
                }
                if state.last_trim is not None
                else None
            )
            consumers[consumer_id] = {
                "usage_bytes": state.usage_bytes,
                "preferred_bytes": registration.preferred_bytes,
                "weight": registration.weight,
                "override_bytes": registration.override_bytes,
                "entitlement_bytes": int(
                    self._entitlement_bytes(consumer_id, weights, total_weight)
                ),
                "overage_bytes": max(
                    0,
                    int(
                        state.usage_bytes
                        - self._entitlement_bytes(
                            consumer_id,
                            weights,
                            total_weight,
                        )
                    ),
                ),
                "priority": int(registration.priority),
                "last_trim": trim_record,
            }
        return {
            "budget_bytes": self._active_budget_bytes,
            "hard_cap": self._hard_cap_enabled,
            "usage_bytes": self._total_usage(),
            "admissions_blocked": self._hard_cap_enabled
            and self._total_usage() > self._active_budget_bytes,
            "headroom": self._headroom_snapshot,
            "consumers": consumers,
            "last_trim_events": self._last_trim_events,
        }

    def set_headroom_snapshot(self, snapshot: dict[str, object] | None) -> None:
        """Update the optional headroom snapshot used by diagnostics."""
        self._headroom_snapshot = snapshot or {}
        self._mark_dirty()

    def _refresh_usage(self, consumer_id: str) -> None:
        """Request a usage update from ``consumer_id`` and apply trims."""
        state = self._consumers.get(consumer_id)
        if state is None:
            return
        try:
            usage = state.registration.callbacks.get_usage()
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Cache consumer %s failed to report usage", consumer_id)
            return
        state.usage_bytes = max(0, usage)
        self._enforce_budget()

    def should_admit(self, size_bytes: int) -> bool:
        """Return True when an item of ``size_bytes`` should be admitted."""
        if not self._hard_cap_enabled:
            return True
        return (
            self._total_usage() + max(0, int(size_bytes))
        ) <= self._active_budget_bytes

    def _warn_unknown_consumer(self, consumer_id: str, operation: str) -> None:
        """Log once per consumer/operation pair when IDs are missing."""
        key = (consumer_id, operation)
        if key in self._missing_consumer_logs:
            return
        self._missing_consumer_logs.add(key)
        logger.warning(
            "Ignoring %s for unknown cache consumer '%s'", operation, consumer_id
        )

    def _resolve_target_bytes(self, registration: ConsumerRegistration) -> int | None:
        """Return the active target for ``registration`` (override beats preferred)."""
        if registration.override_bytes is not None:
            return registration.override_bytes
        return registration.preferred_bytes

    def _entitlement_bytes(
        self,
        consumer_id: str,
        weights: dict[str, float],
        total_weight: float,
    ) -> float:
        """Return the weighted entitlement in bytes for ``consumer_id``."""
        if total_weight <= 0.0 or self._active_budget_bytes <= 0:
            return 0.0
        weight = weights.get(consumer_id, 0.0)
        return (weight / total_weight) * self._active_budget_bytes

    def _enforce_budget(self) -> None:
        """Enforce overrides first, then trim by weighted entitlement to honor the budget."""
        if self._enforcing:
            self._pending_enforce = True
            return
        self._enforcing = True
        try:
            while True:
                self._pending_enforce = False
                self._last_trim_events = ()
                events: list[dict[str, object]] = []
                usage_before = self._total_usage()
                weights = {
                    consumer_id: max(0.0, state.registration.weight)
                    for consumer_id, state in self._consumers.items()
                }
                total_weight = sum(weights.values())
                if total_weight <= 0.0 and weights:
                    weights = {consumer_id: 1.0 for consumer_id in weights}
                    total_weight = float(len(weights))
                for state in self._consumers.values():
                    override = state.registration.override_bytes
                    if override is not None and state.usage_bytes > override:
                        usage_before_consumer = state.usage_bytes
                        freed = self._trim_consumer_to(
                            state, override, reason="override"
                        )
                        if freed > 0:
                            events.append(
                                {
                                    "consumer": state.consumer_id,
                                    "reason": "override",
                                    "freed_bytes": freed,
                                    "target_bytes": override,
                                    "usage_after": state.usage_bytes,
                                    "entitlement_bytes": int(
                                        self._entitlement_bytes(
                                            state.consumer_id, weights, total_weight
                                        )
                                    ),
                                    "overage_bytes": max(
                                        0,
                                        int(
                                            usage_before_consumer
                                            - self._entitlement_bytes(
                                                state.consumer_id,
                                                weights,
                                                total_weight,
                                            )
                                        ),
                                    ),
                                }
                            )
                if self._total_usage() > self._active_budget_bytes:
                    contenders: list[tuple[float, CachePriority, _ConsumerState]] = []
                    for state in self._consumers.values():
                        entitlement = self._entitlement_bytes(
                            state.consumer_id, weights, total_weight
                        )
                        overage = max(0.0, state.usage_bytes - entitlement)
                        contenders.append((overage, state.registration.priority, state))
                    for overage, _priority, state in sorted(
                        contenders, key=lambda item: (-item[0], item[1])
                    ):
                        if self._total_usage() <= self._active_budget_bytes:
                            break
                        entitlement = self._entitlement_bytes(
                            state.consumer_id, weights, total_weight
                        )
                        if overage <= 0:
                            continue
                        target = max(0, int(entitlement))
                        target = min(target, state.usage_bytes)
                        freed = self._trim_consumer_to(state, target, reason="global")
                        if freed > 0:
                            events.append(
                                {
                                    "consumer": state.consumer_id,
                                    "reason": "global",
                                    "freed_bytes": freed,
                                    "target_bytes": target,
                                    "usage_after": state.usage_bytes,
                                    "entitlement_bytes": int(entitlement),
                                    "overage_bytes": int(overage),
                                }
                            )
                if events:
                    self._last_trim_events = tuple(events)
                    usage_after = self._total_usage()
                    payload = {
                        "budget_bytes": self._active_budget_bytes,
                        "usage_before": usage_before,
                        "usage_after": usage_after,
                        "events": events,
                    }
                    logger.info(
                        "Cache trim summary | budget=%d | usage_before=%d "
                        "| usage_after=%d | events=%s",
                        self._active_budget_bytes,
                        usage_before,
                        usage_after,
                        events,
                        extra={"cache_trim": payload},
                    )
                elif self._total_usage() > self._active_budget_bytes:
                    self._last_trim_events = ()
                    logger.warning(
                        "Cache remains over budget after trims | budget=%d | usage=%d",
                        self._active_budget_bytes,
                        self._total_usage(),
                    )
                self._mark_dirty()
                if not self._pending_enforce:
                    break
        finally:
            self._enforcing = False

    def _trim_consumer_to(
        self, state: _ConsumerState, target: int, *, reason: str
    ) -> int:
        """Trim the cache ``state`` controls down to ``target`` bytes.

        Args:
            state: Consumer being trimmed.
            target: Desired post-trim usage in bytes.
            reason: Source of the trim (``override`` or ``global``) for logging.

        Returns:
            Number of bytes freed according to the consumer's callbacks.
        """
        registration = state.registration
        usage_before = state.usage_bytes
        try:
            registration.callbacks.set_budget(target)
            registration.callbacks.trim_to(target)
            new_usage = registration.callbacks.get_usage()
        except Exception:  # pragma: no cover - defensive guard
            logger.exception(
                "Cache consumer %s failed to trim to %d bytes",
                registration.consumer_id,
                target,
            )
            return 0
        new_usage = max(0, int(new_usage))
        state.usage_bytes = new_usage
        freed = max(0, usage_before - new_usage)
        if freed > 0:
            state.last_trim = TrimRecord(
                reason=reason,
                trimmed_bytes=freed,
                target_bytes=target,
                timestamp=time.monotonic(),
            )
        return freed

    def _mark_dirty(self) -> None:
        """Notify diagnostics when cache state changes."""
        callback = getattr(self, "_dirty_callback", None)
        if callback is None:
            return
        try:
            callback("cache")
        except Exception:
            logger.debug(
                "Cache diagnostics dirty callback failed",
                exc_info=True,
            )

    def _total_usage(self) -> int:
        """Return the aggregate usage across all registered consumers."""
        return sum(state.usage_bytes for state in self._consumers.values())
