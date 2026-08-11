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
"""Own bounded mask status state and its diagnostics presentation."""

from __future__ import annotations

from collections import deque

from qpane.sdk.types import DiagnosticRecord

from .render_coordination import MaskRenderWorkStats


class MaskStatusDiagnostics:
    """Retain current mask status facts and format diagnostic rows."""

    def __init__(self) -> None:
        """Initialize one bounded current-status snapshot."""
        self._messages: deque[tuple[str, str]] = deque(maxlen=8)

    def record(self, message: str, *, label: str) -> None:
        """Record one current status event for diagnostic presentation."""
        self._messages.append((label, message))

    def latest(self, *labels: str) -> tuple[str, str] | None:
        """Return the latest status, optionally restricted to exact labels."""
        if not self._messages:
            return None
        if labels:
            label_set = set(labels)
            for label, message in reversed(self._messages):
                if label in label_set:
                    return label, message
        return self._messages[-1]

    def records(
        self,
        stats: MaskRenderWorkStats,
        summary: str,
    ) -> tuple[DiagnosticRecord, ...]:
        """Format current service and render-work facts for the overlay."""
        records: list[DiagnosticRecord] = []
        filtered = tuple(
            (label, message)
            for label, message in self._messages
            if label not in {"Mask", "Mask Autosave"}
        )
        label_counts: dict[str, int] = {}
        latest_messages: dict[str, str] = {}
        ordered_labels: list[str] = []
        for label, message in filtered:
            if label in ordered_labels:
                ordered_labels.remove(label)
            ordered_labels.append(label)
            label_counts[label] = label_counts.get(label, 0) + 1
            latest_messages[label] = message
        prefetch_count = sum(label == "Mask Prefetch" for label, _ in filtered)
        display_labels = [label for label in ordered_labels if label != "Mask Prefetch"]
        for label in display_labels[-3:]:
            message = latest_messages[label]
            count = label_counts[label]
            if count > 1:
                message = f"{message} (+{count - 1} earlier)"
            records.append(DiagnosticRecord(label, message))
        detail_parts: list[str] = []
        if stats.scheduled or stats.completed or stats.skipped or stats.failed:
            detail_parts.append(
                f"scheduled={stats.scheduled} completed={stats.completed} "
                f"skipped={stats.skipped} failed={stats.failed}"
            )
        hidden_events = max(prefetch_count - 1, 0)
        if hidden_events:
            plural = "s" if hidden_events > 1 else ""
            detail_parts.append(f"{hidden_events} earlier event{plural} hidden")
        value = (
            summary if not detail_parts else f"{summary} | {' | '.join(detail_parts)}"
        )
        records.append(DiagnosticRecord("Mask|Prefetch", value))
        return tuple(records)


__all__ = ["MaskStatusDiagnostics"]
