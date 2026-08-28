#    CuteCanvas - High-performance layered image editor
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

"""Observe system memory and maintain automatic cache budgets."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from qpane.sdk.cache import CacheCoordinator
from qpane.sdk.configuration import CacheSettings
from qpane.sdk.execution import (
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
from qpane.sdk.system import SystemHeadroomSample, sample_system_headroom

MB = 1024 * 1024


class HeadroomMonitor:
    """Own periodic memory sampling and automatic cache-budget adoption."""

    def __init__(
        self,
        *,
        owner: QObject,
        execution_scope: ExecutionScope,
        coordinator: Callable[[], CacheCoordinator | None],
        settings: Callable[[], CacheSettings],
    ) -> None:
        """Bind memory observations to one canvas lifetime."""
        self._coordinator = coordinator
        self._settings = settings
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:cache-headroom"
        )
        self._timer = QTimer(owner)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.sample)
        self._provider: object | None = None
        self._provider_missing = False
        self._last_snapshot: dict[str, object] = {}
        self._pending: ExecutionHandle[SystemHeadroomSample, object] | None = None

    @property
    def timer(self) -> QTimer:
        """Expose the owned timer for diagnostics and focused tests."""
        return self._timer

    @property
    def pending(self) -> ExecutionHandle[SystemHeadroomSample, object] | None:
        """Return the current sample handle."""
        return self._pending

    def set_provider(self, provider: object | None) -> None:
        """Inject a system-memory provider for deterministic hosts or tests."""
        self._provider = provider
        self._provider_missing = False

    def restart(self) -> None:
        """Match timer state to cache mode and coordinator availability."""
        coordinator = self._coordinator()
        if coordinator is None or self._settings().mode.lower() != "auto":
            self.stop()
            return
        self._provider_missing = False
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop sampling and cancel one current observation."""
        self._timer.stop()
        handle = self._pending
        self._pending = None
        if handle is not None:
            handle.cancel(reason="headroom monitor stopped")

    def sample(self) -> None:
        """Submit one nonblocking memory observation."""
        coordinator = self._coordinator()
        if coordinator is None or self._settings().mode.lower() != "auto":
            self.stop()
            return
        if self._pending is not None:
            return
        if self._provider_missing:
            self._apply_fallback()
            return
        request = ExecutionRequest(
            operation="cache.headroom.sample",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.BLOCKING_IO,
                urgency=ExecutionUrgency.MAINTENANCE,
            ),
            work=lambda context: sample_system_headroom(
                context.cancellation,
                self._provider,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=self._adopt,
            )
        except ExecutionRejected:
            return
        self._pending = handle
        handle.add_done_callback(lambda outcome: self._settle(handle, outcome))

    def close(self) -> None:
        """Close monitoring and its execution scope."""
        self.stop()
        self._execution_scope.close(reason="headroom_monitor_shutdown")

    def _adopt(self, sample: SystemHeadroomSample) -> None:
        """Apply one memory observation to the current automatic budget."""
        coordinator = self._coordinator()
        if coordinator is None or self._settings().mode.lower() != "auto":
            return
        settings = self._settings()
        available = max(0, sample.available_bytes)
        total = max(0, sample.total_bytes)
        headroom_bytes = min(
            int(total * max(0.0, float(settings.headroom_percent))),
            max(0, int(settings.headroom_cap_mb)) * MB,
        )
        usage_bytes = coordinator.total_usage_bytes
        budget_bytes = _safe_resident_budget(
            total_bytes=total,
            available_bytes=available,
            resident_bytes=usage_bytes,
            reserve_bytes=headroom_bytes,
        )
        if (
            sample.commit_limit_bytes is not None
            and sample.commit_available_bytes is not None
        ):
            commit_limit = max(0, sample.commit_limit_bytes)
            commit_reserve = min(
                int(commit_limit * max(0.0, float(settings.headroom_percent))),
                max(0, int(settings.headroom_cap_mb)) * MB,
            )
            budget_bytes = min(
                budget_bytes,
                _safe_resident_budget(
                    total_bytes=commit_limit,
                    available_bytes=max(0, sample.commit_available_bytes),
                    resident_bytes=usage_bytes,
                    reserve_bytes=commit_reserve,
                ),
            )
        snapshot = sample.diagnostic_snapshot()
        if (
            budget_bytes != coordinator.active_budget_bytes
            or snapshot != self._last_snapshot
        ):
            coordinator.set_active_budget(budget_bytes)
            coordinator.set_headroom_snapshot(snapshot)
            self._last_snapshot = snapshot

    def _settle(
        self,
        handle: ExecutionHandle[SystemHeadroomSample, object],
        outcome: ExecutionOutcome[SystemHeadroomSample],
    ) -> None:
        """Release one observation and install fallback after failure."""
        if self._pending is not handle:
            return
        self._pending = None
        if outcome.state == ExecutionState.FAILED:
            self._provider_missing = True
            self._apply_fallback()

    def _apply_fallback(self) -> None:
        """Install the conservative hard cap after provider failure."""
        coordinator = self._coordinator()
        if coordinator is None:
            return
        self._timer.stop()
        coordinator.set_hard_cap(True)
        budget_bytes = 1024 * MB
        if budget_bytes != coordinator.active_budget_bytes or self._last_snapshot:
            coordinator.set_active_budget(budget_bytes)
            coordinator.set_headroom_snapshot({})
            self._last_snapshot = {}


__all__ = ["HeadroomMonitor"]


def _safe_resident_budget(
    *,
    total_bytes: int,
    available_bytes: int,
    resident_bytes: int,
    reserve_bytes: int,
) -> int:
    """Return a cache budget that restores the requested system headroom."""
    capacity = max(0, total_bytes - reserve_bytes)
    pressure_target = max(0, available_bytes + resident_bytes - reserve_bytes)
    return min(pressure_target, capacity)
