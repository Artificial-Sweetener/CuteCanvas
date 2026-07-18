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

"""Helpers for monitoring the Qt event loop cadence."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

TimerFactory = Callable[[QObject], QTimer]


def _default_timer_factory(parent: QObject) -> QTimer:
    """Construct a `QTimer` whose lifetime is owned by `parent`."""
    return QTimer(parent)


class EventLoopProbe:
    """Detects prolonged event-loop gaps using a lightweight `QTimer`."""

    def __init__(
        self,
        *,
        parent: QObject,
        threshold_getter: Callable[[], float],
        warning_callback: Callable[[float, float], None] | None = None,
        clock: Callable[[], float] = time.perf_counter,
        timer_factory: TimerFactory | None = None,
    ) -> None:
        """Configure the probe and its collaborators.

        Args:
            parent: QObject that should own the internally created timer.
            threshold_getter: Callable returning the lag threshold in milliseconds.
            warning_callback: Optional callback invoked with ``(delta_ms, threshold_ms)`` when lag is detected.
                Set the threshold to ``0`` (or any non-positive value) to disable warnings entirely.
            clock: Monotonic clock used to measure elapsed time.
            timer_factory: Optional factory for injecting a custom ``QTimer`` implementation.
        """
        self._parent = parent
        self._threshold_getter = threshold_getter
        self._warning_callback = warning_callback
        self._clock = clock
        self._timer_factory = timer_factory or _default_timer_factory
        self._timer: QTimer | None = None
        self._last_tick: float | None = None

    def ensure_running(self) -> None:
        """Create and start the zero-interval timer if the probe is idle."""
        if self._timer is not None:
            return
        timer = self._timer_factory(self._parent)
        timer.setInterval(0)
        timer.timeout.connect(self._on_timeout)
        self._timer = timer
        self._last_tick = self._clock()
        timer.start()

    def stop(self) -> None:
        """Stop the probe and dispose of the internal timer."""
        timer = self._timer
        if timer is None:
            return
        timer.stop()
        try:
            timer.deleteLater()
        except Exception:  # pragma: no cover - defensive Qt cleanup
            logger.exception("Failed to dispose event-loop probe timer")
        self._timer = None
        self._last_tick = None

    def _emit_warning(self, delta_ms: float, threshold_ms: float) -> None:
        """Emit lag warnings only when an explicit callback is provided."""
        callback = self._warning_callback
        if callback is None:
            return
        callback(delta_ms, threshold_ms)

    def _on_timeout(self) -> None:
        """Measure elapsed time and emit warnings when the timer fires."""
        now = self._clock()
        last = self._last_tick
        if last is not None:
            delta_ms = (now - last) * 1000.0
            threshold_ms = self._safe_threshold()
            if threshold_ms and delta_ms > threshold_ms:
                self._emit_warning(delta_ms, threshold_ms)
        self._last_tick = now

    def _safe_threshold(self) -> float:
        """Return a non-negative lag threshold while swallowing getter failures."""
        try:
            threshold = float(self._threshold_getter())
        except Exception:  # pragma: no cover - settings access failure
            logger.exception("Failed to fetch event-loop lag threshold")
            return 0.0
        return max(threshold, 0.0)
