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

"""Format execution and retry snapshots for diagnostic surfaces."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..types import DiagnosticRecord
from .diagnostics import ExecutionSnapshot

logger = logging.getLogger(__name__)


def execution_summary_records(
    snapshots: Sequence[ExecutionSnapshot],
) -> tuple[DiagnosticRecord, ...]:
    """Return compact aggregate runtime state."""
    aggregate = _aggregate_snapshots(snapshots)
    if aggregate is None:
        return ()
    return (
        DiagnosticRecord("Execution", f"{aggregate.running} running"),
        DiagnosticRecord("Queued", str(aggregate.pending)),
    )


def execution_detail_records(
    snapshots: Sequence[ExecutionSnapshot],
) -> tuple[DiagnosticRecord, ...]:
    """Return detailed aggregate runtime counters."""
    aggregate = _aggregate_snapshots(snapshots)
    if aggregate is None:
        return ()
    records = [
        DiagnosticRecord(
            "Execution|Tasks",
            f"{aggregate.running} running, {aggregate.pending} queued",
        ),
        DiagnosticRecord(
            "Execution|Retained",
            f"{aggregate.retained_bytes / (1024 * 1024):.1f} MiB",
        ),
        DiagnosticRecord("Execution|Completed", str(aggregate.completed)),
    ]
    if aggregate.rejected:
        records.append(DiagnosticRecord("Execution|Rejected", str(aggregate.rejected)))
    if aggregate.cancelled_before_start:
        records.append(
            DiagnosticRecord(
                "Execution|Cancelled Pending",
                str(aggregate.cancelled_before_start),
            )
        )
    return tuple(records)


def retry_summary_records(
    owners: Mapping[str, object | None],
) -> tuple[DiagnosticRecord, ...]:
    """Return compact retry counters from domain owners."""
    summaries = _retry_summaries(owners)
    if not summaries:
        return ()
    value = ", ".join(
        f"{name}:{active}/{total}" for name, active, total, _peak in summaries[:2]
    )
    return (DiagnosticRecord("Retry|Summary", value),)


def retry_detail_records(
    owners: Mapping[str, object | None],
) -> tuple[DiagnosticRecord, ...]:
    """Return retry counters for owners with activity."""
    active = [
        summary for summary in _retry_summaries(owners) if summary[1] or summary[2]
    ]
    if not active:
        return ()
    parts = []
    for name, count, total, peak in active:
        peak_text = "" if peak is None else f"(pk={peak})"
        parts.append(f"{name}:{count}/{total}{peak_text}")
    return (DiagnosticRecord("Retry|Detail", ", ".join(parts)),)


def _aggregate_snapshots(
    snapshots: Sequence[ExecutionSnapshot],
) -> ExecutionSnapshot | None:
    """Aggregate independent backend snapshots."""
    if not snapshots:
        return None
    return ExecutionSnapshot(
        accepted=sum(snapshot.accepted for snapshot in snapshots),
        pending=sum(snapshot.pending for snapshot in snapshots),
        running=sum(snapshot.running for snapshot in snapshots),
        retained_bytes=sum(snapshot.retained_bytes for snapshot in snapshots),
        rejected=sum(snapshot.rejected for snapshot in snapshots),
        completed=sum(snapshot.completed for snapshot in snapshots),
        cancelled_before_start=sum(
            snapshot.cancelled_before_start for snapshot in snapshots
        ),
    )


def _retry_summaries(
    owners: Mapping[str, object | None],
) -> list[tuple[str, int, int, int | None]]:
    """Read retry snapshots without coupling to concrete coordinators."""
    summaries: list[tuple[str, int, int, int | None]] = []
    for name, owner in owners.items():
        if owner is None:
            continue
        accessor = getattr(owner, "retrySnapshot", None) or getattr(
            owner,
            "retry_snapshot",
            None,
        )
        if not callable(accessor):
            continue
        try:
            snapshot = accessor()
            categories = getattr(snapshot, "categories", {})
            info = categories.get(name)
            if info is None and len(categories) == 1:
                info = next(iter(categories.values()))
            if info is None:
                continue
            summaries.append(
                (
                    name,
                    int(getattr(info, "active", 0)),
                    int(getattr(info, "total_scheduled", 0)),
                    getattr(info, "peak_active", None),
                )
            )
        except Exception:
            logger.warning(
                "Could not read retry diagnostics from %s",
                type(owner).__name__,
                exc_info=True,
            )
    return summaries


__all__ = [
    "execution_detail_records",
    "execution_summary_records",
    "retry_detail_records",
    "retry_summary_records",
]
