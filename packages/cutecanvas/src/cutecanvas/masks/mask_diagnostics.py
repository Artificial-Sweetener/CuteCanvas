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

"""Runtime diagnostics helpers for mask stroke worker pipelines."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qpane.sdk.features import FeatureInstallError
from qpane.sdk.types import DiagnosticRecord

from ..core.config_features import require_mask_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from ..canvas import CuteCanvas
__all__ = (
    "MaskStrokeDiagnostics",
    "MaskStrokeDiagnosticsSnapshot",
    "MaskStrokeJobSnapshot",
    "MaskStrokeResultSnapshot",
    "mask_brush_detail_provider",
    "mask_job_detail_provider",
    "mask_summary_provider",
)


@dataclass(frozen=True, slots=True)
class MaskStrokeJobSnapshot:
    """Describe a pending stroke job captured for diagnostics."""

    mask_id: uuid.UUID
    job_token: int
    generation: int
    age_ms: float
    source: str | None = None
    stride: int | None = None
    pending_count: int | None = None


@dataclass(frozen=True, slots=True)
class MaskStrokeResultSnapshot:
    """Summarise the most recent stroke job outcome."""

    status: str
    mask_id: uuid.UUID | None
    job_token: int | None
    duration_ms: float | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class MaskStrokeDiagnosticsSnapshot:
    """Aggregate diagnostics pulled from the tracker."""

    outstanding: tuple[MaskStrokeJobSnapshot, ...]
    drop_counts: Mapping[str, int]
    generation_events: Mapping[str, int]
    last_result: MaskStrokeResultSnapshot | None = None


@dataclass(slots=True)
class _JobEntry:
    """Internal bookkeeping for outstanding jobs."""

    mask_id: uuid.UUID
    job_token: int
    generation: int
    submitted_at: float
    source: str | None = None
    stride: int | None = None
    pending_count: int | None = None

    def snapshot(self, now: float) -> MaskStrokeJobSnapshot:
        """Build a snapshot describing this job's age and metadata."""
        age_ms = max(0.0, (now - self.submitted_at) * 1000.0)
        return MaskStrokeJobSnapshot(
            mask_id=self.mask_id,
            job_token=self.job_token,
            generation=self.generation,
            age_ms=age_ms,
            source=self.source,
            stride=self.stride,
            pending_count=self.pending_count,
        )


class MaskStrokeDiagnostics:
    """Collect metrics describing mask stroke worker throughput."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        dirty_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Configure diagnostics tracking and optional dirty callbacks."""
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._pending: dict[tuple[uuid.UUID, int], _JobEntry] = {}
        self._drop_counts: dict[str, int] = {}
        self._generation_events: dict[str, int] = {}
        self._last_result: MaskStrokeResultSnapshot | None = None
        self._dirty_callback = dirty_callback

    def _mark_dirty(self) -> None:
        """Notify diagnostics about mask metrics changes."""
        callback = self._dirty_callback
        if callback is None:
            return
        try:
            callback("mask")
        except Exception:
            logger.debug("Mask diagnostics dirty callback failed", exc_info=True)

    # Configuration -----------------------------------------------------
    def configure(
        self,
        *,
        enabled: bool | None = None,
    ) -> None:
        """Adjust runtime toggles without recreating the tracker."""
        if enabled is not None:
            self.enabled = bool(enabled)

    # Recording helpers -------------------------------------------------
    def record_submitted(
        self,
        *,
        mask_id: uuid.UUID,
        job_token: int,
        generation: int,
        pending_count: int | None,
        source: str | None = None,
        stride: int | None = None,
    ) -> None:
        """Track a newly queued job if diagnostics are enabled."""
        if not self.enabled:
            return
        entry = _JobEntry(
            mask_id=mask_id,
            job_token=job_token,
            generation=generation,
            submitted_at=time.monotonic(),
            source=source,
            stride=stride,
            pending_count=pending_count,
        )
        key = (mask_id, job_token)
        with self._lock:
            self._pending[key] = entry
        self._mark_dirty()

    def record_completed(
        self,
        *,
        mask_id: uuid.UUID | None,
        job_token: int | None,
        status: str,
        detail: str | None = None,
    ) -> None:
        """Record the final outcome for a job."""
        if not self.enabled:
            with self._lock:
                self._last_result = None
            return
        duration_ms = None
        if mask_id is not None and job_token is not None:
            key = (mask_id, job_token)
            with self._lock:
                entry = self._pending.pop(key, None)
                if entry is not None:
                    duration_ms = max(
                        0.0, (time.monotonic() - entry.submitted_at) * 1000.0
                    )
        else:
            with self._lock:
                entry = None
        summary = MaskStrokeResultSnapshot(
            status=status,
            mask_id=mask_id,
            job_token=job_token,
            duration_ms=duration_ms,
            detail=detail,
        )
        with self._lock:
            self._last_result = summary
        self._mark_dirty()

    def record_drop(
        self,
        *,
        mask_id: uuid.UUID | None,
        job_token: int | None,
        reason: str,
        detail: str | None = None,
    ) -> None:
        """Increment drop counters and register the outcome."""
        if not reason:
            reason = "unknown"
        with self._lock:
            self._drop_counts[reason] = self._drop_counts.get(reason, 0) + 1
        self.record_completed(
            mask_id=mask_id,
            job_token=job_token,
            status=f"dropped:{reason}",
            detail=detail,
        )
        self._mark_dirty()

    def record_generation_event(self, event: str) -> None:
        """Track generation rebases/clamps for diagnostics."""
        if not event:
            return
        with self._lock:
            self._generation_events[event] = self._generation_events.get(event, 0) + 1
        self._mark_dirty()

    def cancel_mask_jobs(self, mask_id: uuid.UUID) -> None:
        """Drop pending jobs for `mask_id` without counting them as failures."""
        if not self.enabled:
            return
        with self._lock:
            for key in list(self._pending.keys()):
                if key[0] == mask_id:
                    self._pending.pop(key, None)
        self._mark_dirty()

    def snapshot(self) -> MaskStrokeDiagnosticsSnapshot | None:
        """Return the current state for diagnostics overlays."""
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            outstanding = tuple(entry.snapshot(now) for entry in self._pending.values())
            drop_counts = dict(self._drop_counts)
            generation_events = dict(self._generation_events)
            last_result = self._last_result
        return MaskStrokeDiagnosticsSnapshot(
            outstanding=outstanding,
            drop_counts=drop_counts,
            generation_events=generation_events,
            last_result=last_result,
        )

    def reset(self) -> None:
        """Clear collected state (used during reinstall)."""
        with self._lock:
            self._pending.clear()
            self._drop_counts.clear()
            self._generation_events.clear()
            self._last_result = None
        self._mark_dirty()


def _short_uuid_text(value: uuid.UUID | None) -> str:
    """Return a short identifier suitable for diagnostics rows."""
    if isinstance(value, uuid.UUID):
        return value.hex[:8].upper()
    if value is None:
        return "None"
    return str(value)


def _mask_job_records(snapshot) -> tuple[DiagnosticRecord, ...]:
    """Build diagnostics rows describing stroke worker activity."""
    entries: list[DiagnosticRecord] = []
    outstanding = tuple(getattr(snapshot, "outstanding", ()))
    drop_counts_mapping = getattr(snapshot, "drop_counts", {})
    if isinstance(drop_counts_mapping, Mapping):
        drop_counts = {k: int(v) for k, v in drop_counts_mapping.items() if int(v) > 0}
    else:
        drop_counts = {}
    generation_mapping = getattr(snapshot, "generation_events", {})
    if isinstance(generation_mapping, Mapping):
        generation_events = {
            k: int(v) for k, v in generation_mapping.items() if int(v) > 0
        }
    else:
        generation_events = {}
    drop_total = sum(drop_counts.values())
    badge_parts: list[str] = []
    if outstanding:
        badge_parts.append(f"{len(outstanding)} pending")
    if drop_total:
        badge_parts.append(f"{drop_total} drops")
    if not badge_parts:
        badge_value = "Idle"
    else:
        badge_value = " / ".join(badge_parts)
    entries.append(DiagnosticRecord("Mask Jobs|Badge", badge_value))
    if outstanding:
        formatted: list[str] = []
        for job in outstanding[:3]:
            mask_label = _short_uuid_text(getattr(job, "mask_id", None))
            token = getattr(job, "job_token", None)
            age_ms = getattr(job, "age_ms", 0.0)
            source = getattr(job, "source", None)
            stride = getattr(job, "stride", None)
            pending_count = getattr(job, "pending_count", None)
            parts = [mask_label]
            if token is not None:
                parts.append(f"tok={token}")
            try:
                parts.append(f"{int(age_ms):d}ms")
            except (TypeError, ValueError):
                pass
            if source:
                parts.append(str(source))
            if isinstance(stride, int) and stride > 1:
                parts.append(f"s{stride}")
            if isinstance(pending_count, int) and pending_count > 0:
                parts.append(f"p{pending_count}")
            formatted.append(" ".join(parts))
        entries.append(
            DiagnosticRecord(
                "Mask Jobs|Outstanding",
                " | ".join(formatted),
            )
        )
    if drop_counts:
        drop_bits = [
            f"{reason}={count}" for reason, count in sorted(drop_counts.items())
        ]
        entries.append(DiagnosticRecord("Mask Jobs|Drops", " ".join(drop_bits)))
    if generation_events:
        gen_bits = [
            f"{reason}={count}" for reason, count in sorted(generation_events.items())
        ]
        entries.append(DiagnosticRecord("Mask Jobs|Generations", " ".join(gen_bits)))
    last_result = getattr(snapshot, "last_result", None)
    if last_result is not None:
        parts: list[str] = []
        status = getattr(last_result, "status", None)
        if status:
            parts.append(str(status))
        mask_id = getattr(last_result, "mask_id", None)
        if mask_id is not None:
            parts.append(_short_uuid_text(mask_id))
        job_token = getattr(last_result, "job_token", None)
        if job_token is not None:
            parts.append(f"tok={job_token}")
        duration_ms = getattr(last_result, "duration_ms", None)
        try:
            if duration_ms is not None:
                parts.append(f"{duration_ms:.1f}ms")
        except (TypeError, ValueError):
            pass
        detail = getattr(last_result, "detail", None)
        if detail:
            parts.append(str(detail))
        entries.append(
            DiagnosticRecord(
                "Mask Jobs|Last",
                " ".join(part for part in parts if part).strip(),
            )
        )
    return tuple(entries)


def mask_summary_provider(qpane: CuteCanvas) -> tuple[DiagnosticRecord, ...]:
    """Return the always-on mask summary rows for diagnostics overlays."""
    service = getattr(qpane, "mask_service", None)
    if service is None:
        return ()
    records: list[DiagnosticRecord] = []
    current_id = qpane.currentCompositionID()
    mask_ids: list = []
    if current_id is not None:
        try:
            mask_ids = service.mask_ids_for_composition(current_id) or []
        except Exception:
            logger.debug("Mask ID enumeration failed", exc_info=True)
            mask_ids = []
    latest_mask = service.get_latest_status_message("Mask", "Mask Error")
    if latest_mask is not None:
        records.append(DiagnosticRecord("Mask", latest_mask[1]))
    active_mask_id = service.getActiveMaskId()
    active_repr = str(active_mask_id) if active_mask_id is not None else "None"
    records.append(
        DiagnosticRecord("Mask Layers", f"{len(mask_ids)} (active={active_repr})")
    )
    autosave_message = _autosave_status(qpane, service)
    if autosave_message:
        records.append(DiagnosticRecord("Mask Autosave", autosave_message))
    return tuple(records)


def mask_job_detail_provider(qpane: CuteCanvas) -> tuple[DiagnosticRecord, ...]:
    """Return mask worker job diagnostics for the detail overlay tier."""
    service = getattr(qpane, "mask_service", None)
    if service is None:
        return ()
    diagnostics_snapshot = service.strokeDiagnosticsSnapshot()
    if diagnostics_snapshot is None:
        return ()
    return _mask_job_records(diagnostics_snapshot)


def mask_brush_detail_provider(qpane: CuteCanvas) -> tuple[DiagnosticRecord, ...]:
    """Expose brush sizing and mode as detail-tier mask diagnostics."""
    interaction = getattr(qpane, "interaction", None)
    brush_size = getattr(interaction, "brush_size", getattr(qpane, "_brush_size", None))
    if brush_size is None:
        return ()
    records: list[DiagnosticRecord] = []
    records.append(DiagnosticRecord("Mask|Brush", str(int(brush_size))))
    alt_held = getattr(
        interaction, "alt_key_held", getattr(qpane, "_alt_key_held", False)
    )
    brush_mode = "Erase" if alt_held else "Paint"
    records.append(DiagnosticRecord("Mask|Brush Mode", brush_mode))
    return tuple(records)


def _autosave_status(qpane: CuteCanvas, service) -> str | None:
    """Return a short autosave status string for core mask diagnostics."""
    autosave_manager = None
    accessor = getattr(qpane, "autosaveManager", None)
    if callable(accessor):
        try:
            autosave_manager = accessor()
        except RuntimeError:
            logger.debug(
                "autosaveManager() raised while building diagnostics",
                exc_info=True,
            )
    settings = getattr(qpane, "settings", None)
    mask_config = None
    if settings is not None:
        try:
            mask_config = require_mask_config(settings)
        except FeatureInstallError:
            mask_config = None
    mask_autosave_enabled = bool(mask_config and mask_config.mask_autosave_enabled)
    autosave_enabled = bool(autosave_manager and mask_autosave_enabled)
    pending_fn = getattr(autosave_manager, "pending_mask_count", None)
    remaining_fn = getattr(autosave_manager, "seconds_until_next_save", None)
    autosave_status = service.get_latest_status_message(
        "Mask Autosave", "Mask Autosave Error"
    )
    if not autosave_enabled:
        return None
    pending = pending_fn() if callable(pending_fn) else 0
    if pending:
        remaining = remaining_fn() if callable(remaining_fn) else None
        if remaining is None:
            return f"Saving {pending} soon"
        return f"Saving {pending} in {remaining:.1f}s"
    if autosave_status is not None:
        return autosave_status[1]
    return "Enabled"
