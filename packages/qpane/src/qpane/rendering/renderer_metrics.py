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
"""Own renderer reuse counters and paint-duration observations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RendererMetrics:
    """Describe renderer buffer reuse and redraw behavior."""

    base_buffer_allocations: int
    scroll_attempts: int
    scroll_hits: int
    scroll_misses: int
    scroll_repairs: int
    full_redraws: int
    partial_redraws: int
    last_paint_ms: float


class RendererMetricsTracker:
    """Own paint timing while assembling immutable diagnostic snapshots."""

    def __init__(self) -> None:
        """Initialize empty paint-duration observations."""
        self._last_paint_ms = 0.0
        self._paint_sum_ms = 0.0
        self._paint_count = 0
        self._paint_max_ms = 0.0

    @property
    def last_paint_ms(self) -> float:
        """Return the last completed paint duration in milliseconds."""
        return self._last_paint_ms

    def record_paint(self, duration_ms: float) -> None:
        """Record one completed buffer-paint duration."""
        self._last_paint_ms = max(0.0, float(duration_ms))
        if self._last_paint_ms <= 0.0:
            return
        self._paint_sum_ms += self._last_paint_ms
        self._paint_count += 1
        self._paint_max_ms = max(self._paint_max_ms, self._last_paint_ms)

    def paint_stats(self) -> tuple[float, float, float]:
        """Return last, average, and maximum paint durations in milliseconds."""
        average = self._paint_sum_ms / self._paint_count if self._paint_count else 0.0
        return self._last_paint_ms, average, self._paint_max_ms

    def snapshot(
        self,
        *,
        base_buffer_allocations: int,
        scroll_attempts: int,
        scroll_hits: int,
        scroll_misses: int,
        scroll_repairs: int,
        full_redraws: int,
        partial_redraws: int,
    ) -> RendererMetrics:
        """Return one immutable snapshot from renderer-owned counters."""
        return RendererMetrics(
            base_buffer_allocations=base_buffer_allocations,
            scroll_attempts=scroll_attempts,
            scroll_hits=scroll_hits,
            scroll_misses=scroll_misses,
            scroll_repairs=scroll_repairs,
            full_redraws=full_redraws,
            partial_redraws=partial_redraws,
            last_paint_ms=self._last_paint_ms,
        )


__all__ = ["RendererMetrics", "RendererMetricsTracker"]
