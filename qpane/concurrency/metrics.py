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

"""Expose executor and retry diagnostics consumed by QPane overlays."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from ..types import DiagnosticRecord
from .executor import ExecutorSnapshot, TaskExecutorProtocol

logger = logging.getLogger(__name__)


def gather_executor_snapshot(executor: TaskExecutorProtocol) -> ExecutorSnapshot:
    """Capture a point-in-time snapshot for diagnostics surfaces.

    Args:
        executor: Task executor that exposes ``snapshot()``.

    Returns:
        ExecutorSnapshot read directly from the executor.
    """
    return executor.snapshot()


def executor_diagnostics_provider(
    executor: TaskExecutorProtocol,
) -> Iterable[DiagnosticRecord]:
    """Yield DiagnosticRecord entries describing executor utilisation.

    Args:
        executor: Task executor inspected for metrics.

    Yields:
        DiagnosticRecord values suitable for diagnostic overlays.
    """
    snapshot = executor.snapshot()
    threads_value = f"{snapshot.active_total}/{snapshot.max_workers} active"
    if getattr(snapshot, "pool_max_threads", None) is not None:
        threads_value += f" (pool {snapshot.pool_max_threads})"
    yield DiagnosticRecord("Executor|Threads", threads_value)
    pending_total = snapshot.pending_total
    if snapshot.max_pending_total:
        queued_summary = f"{pending_total}/{snapshot.max_pending_total}"
        if snapshot.pending_utilization_total_pct is not None:
            queued_summary += f" ({snapshot.pending_utilization_total_pct:.0f}%)"
    else:
        queued_summary = str(pending_total)
    categories = sorted(set(snapshot.queued_by_category) | set(snapshot.pending_limits))
    breakdown_parts: list[str] = []
    for category in categories:
        count = snapshot.queued_by_category.get(category, 0)
        limit = snapshot.pending_limits.get(category)
        normalized_limit = limit if limit and limit > 0 else None
        if normalized_limit:
            part = f"{category}:{count}/{normalized_limit}"
            utilization = snapshot.pending_utilization_by_category_pct.get(category)
            if utilization is not None:
                part += f" ({utilization:.0f}%)"
        else:
            part = f"{category}:{count}"
        breakdown_parts.append(part)
    if breakdown_parts:
        breakdown = ", ".join(breakdown_parts)
        queued_summary = f"{queued_summary} ({breakdown})"
    yield DiagnosticRecord("Executor|Queued", queued_summary)
    if snapshot.category_limits:
        limits = ", ".join(
            f"{category}:{limit}"
            for category, limit in sorted(snapshot.category_limits.items())
        )
        yield DiagnosticRecord("Executor|Category Limits", limits)
    if snapshot.device_limits:
        devices = ", ".join(
            f"{device}:{_describe_limits(limits)}"
            for device, limits in sorted(snapshot.device_limits.items())
        )
        if devices:
            yield DiagnosticRecord("Executor|Device Limits", devices)
    if snapshot.rejection_count is not None and snapshot.rejection_count > 0:
        yield DiagnosticRecord("Executor|Rejections", str(snapshot.rejection_count))
    if snapshot.average_wait_time_ms is not None:
        yield DiagnosticRecord(
            "Executor|Avg Wait",
            f"{snapshot.average_wait_time_ms:.1f} ms",
        )


def executor_summary_provider(
    executor: TaskExecutorProtocol,
) -> Iterable[DiagnosticRecord]:
    """Emit the executor name and queue depth for the executor detail overlay."""
    snapshot = executor.snapshot()
    name = getattr(snapshot, "name", None) or "Executor"
    yield DiagnosticRecord("Executor", str(name))
    pending_total = snapshot.pending_total
    summary = str(pending_total)
    if snapshot.max_pending_total:
        summary = f"{pending_total}/{snapshot.max_pending_total}"
    yield DiagnosticRecord("Queued", summary)


def retry_diagnostics_provider(qpane) -> Iterable[DiagnosticRecord]:
    """Yield detailed retry metrics per category."""
    summaries = _retry_category_summaries(qpane)
    if not summaries:
        return ()
    active_only = [s for s in summaries if s.active or s.total]
    if not active_only:
        return ()
    yield DiagnosticRecord(
        "Retry|Detail",
        ", ".join(summary.format_detail() for summary in active_only),
    )


def retry_summary_provider(qpane) -> Iterable[DiagnosticRecord]:
    """Return compact retry counters for the retry detail tier."""
    summaries = _retry_category_summaries(qpane)
    if not summaries:
        return ()
    limited = summaries[:2]
    value = ", ".join(summary.format_summary() for summary in limited)
    yield DiagnosticRecord("Retry|Summary", value)


@dataclass(frozen=True)
class _RetrySummary:
    """Structured retry counters for a category."""

    category: str
    active: int
    total: int
    peak: int | None = None

    def format_detail(self) -> str:
        """Return a verbose `category:active/total(pk=peak)` string."""
        peak_part = f"(pk={self.peak})" if self.peak is not None else ""
        return f"{self.category}:{self.active}/{self.total}{peak_part}"

    def format_summary(self) -> str:
        """Return a compact `category:active/total` summary."""
        return f"{self.category}:{self.active}/{self.total}"


def _retry_category_summaries(qpane) -> list[_RetrySummary]:
    """Collect retry summaries for QPane-owned managers routed via the facade."""
    managers = [
        ("tiles", _stack_tile_manager(qpane)),
        ("pyramid", _catalog_pyramid_manager(qpane)),
        ("autosave", _autosave_manager(qpane)),
        ("sam", _sam_manager(qpane)),
    ]
    summaries: list[_RetrySummary] = []
    for category, manager in managers:
        summary = _collect_retry_counts(category, manager)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _collect_retry_counts(category: str, manager) -> _RetrySummary | None:
    """Return a summary for ``category`` using a manager's retry snapshot."""
    if manager is None:
        return None
    snapshot = _retry_snapshot(manager)
    if snapshot is None:
        return None
    try:
        info = getattr(snapshot, "categories", {}).get(category)
        if info is None:
            return None
        active = getattr(info, "active", 0)
        total = getattr(info, "total_scheduled", 0)
        peak = getattr(info, "peak_active", None)
        return _RetrySummary(
            category=category, active=int(active), total=int(total), peak=peak
        )
    except AttributeError:
        logger.debug(
            "Retry snapshot missing expected fields (category=%s, manager=%s)",
            category,
            type(manager).__name__,
        )
        return None
    except Exception:  # pragma: no cover - defensive guard
        logger.warning(
            "Failed to read retry snapshot for category %s (manager=%s)",
            category,
            type(manager).__name__,
            exc_info=True,
        )
        return None


def _retry_snapshot(manager):
    """Return a retry snapshot from ``manager`` using its public accessor."""
    accessor = getattr(manager, "retrySnapshot", None) or getattr(
        manager, "retry_snapshot", None
    )
    if callable(accessor):
        try:
            return accessor()
        except Exception:  # pragma: no cover - defensive guard
            logger.warning(
                "retry_snapshot accessor failed for manager %s",
                type(manager).__name__,
                exc_info=True,
            )
            return None
    return None


def _describe_limits(limits: dict[str, int]) -> str:
    """Return a compact device limit description.

    Args:
        limits: Mapping of category names to their limit.

    Returns:
        Comma-separated summary or ``-`` when limits are empty.
    """
    if not limits:
        return "-"
    return ",".join(f"{category}:{limit}" for category, limit in sorted(limits.items()))


def _call_accessor(owner, accessor_name: str, *, label: str):
    """Invoke an optional accessor with defensive logging and fallback."""
    accessor = getattr(owner, accessor_name, None)
    if not callable(accessor):
        logger.debug("%s %s lacks %s accessor", label, owner, accessor_name)
        return None
    try:
        return accessor()
    except Exception:
        logger.debug("%s.%s() raised", label, accessor_name, exc_info=True)
    return None


def _stack_tile_manager(qpane):
    """Return the view's tile manager via the public QPane facade.

    Args:
        qpane: QPane facade expected to expose ``view()``.

    Returns:
        The current tile manager or ``None`` when unavailable.
    """
    view = _call_accessor(qpane, "view", label="QPane")
    if view is None:
        return None
    return getattr(view, "tile_manager", None)


def _catalog_pyramid_manager(qpane):
    """Return the catalog-backed pyramid manager routed through the facade.

    Args:
        qpane: QPane facade that may expose catalog accessors.

    Returns:
        Pyramid manager instance or ``None`` when missing.
    """
    catalog_facade = _call_accessor(qpane, "catalog", label="QPane")
    if catalog_facade is None:
        return None
    return _call_accessor(catalog_facade, "pyramidManager", label="Catalog facade")


def _autosave_manager(qpane):
    """Return the QPane autosave manager if the facade exposes one.

    Args:
        qpane: QPane facade with an optional ``autosaveManager`` accessor.

    Returns:
        Autosave manager instance or ``None`` when not provided.
    """
    return _call_accessor(qpane, "autosaveManager", label="QPane")


def _sam_manager(qpane):
    """Return the QPane SAM manager accessor with defensive logging.

    Args:
        qpane: QPane facade with an optional ``samManager`` accessor.

    Returns:
        SAM manager instance or ``None`` when not provided.
    """
    return _call_accessor(qpane, "samManager", label="QPane")
