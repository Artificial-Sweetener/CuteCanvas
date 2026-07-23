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

"""Transient kinetic viewport motion independent of persistent view state."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QPointF, Qt, QTimer


class ViewportMotionController(QObject):
    """Own translation inertia and its timer lifecycle."""

    _FRAME_INTERVAL_MS = 16
    _MIN_SPEED = 40.0
    _MAX_SPEED = 6000.0

    def __init__(
        self,
        *,
        get_pan: Callable[[], QPointF],
        apply_pan: Callable[[QPointF], None],
        parent: QObject,
    ) -> None:
        """Capture pan callbacks and initialize an idle precise timer."""
        super().__init__(parent)
        self._get_pan = get_pan
        self._apply_pan = apply_pan
        self._velocity = QPointF()
        self._deceleration = 4500.0
        self._last_tick_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        """Return whether inertia is currently advancing the viewport."""
        return self._timer.isActive()

    def start(self, velocity: QPointF, deceleration: float) -> bool:
        """Begin bounded kinetic translation when velocity is meaningful."""
        speed = math.hypot(velocity.x(), velocity.y())
        if not math.isfinite(speed) or speed < self._MIN_SPEED:
            self.stop()
            return False
        scale = min(1.0, self._MAX_SPEED / speed)
        self._velocity = QPointF(velocity.x() * scale, velocity.y() * scale)
        self._deceleration = max(1.0, float(deceleration))
        self._last_tick_at = time.monotonic()
        self._timer.start()
        return True

    def stop(self) -> None:
        """Stop kinetic motion and clear its transient velocity."""
        self._timer.stop()
        self._velocity = QPointF()
        self._last_tick_at = None

    def advance(self, elapsed_s: float) -> bool:
        """Advance inertia deterministically; return whether motion continues."""
        dt = min(0.05, max(0.0, float(elapsed_s)))
        speed = math.hypot(self._velocity.x(), self._velocity.y())
        if dt <= 0 or speed < self._MIN_SPEED:
            self.stop()
            return False
        previous_pan = QPointF(self._get_pan())
        next_pan = previous_pan + self._velocity * dt
        self._apply_pan(next_pan)
        if self._get_pan() == previous_pan:
            self.stop()
            return False
        next_speed = max(0.0, speed - self._deceleration * dt)
        if next_speed < self._MIN_SPEED:
            self.stop()
            return False
        factor = next_speed / speed
        self._velocity *= factor
        return True

    def _tick(self) -> None:
        """Advance motion from the precise Qt timer."""
        now = time.monotonic()
        previous = self._last_tick_at
        self._last_tick_at = now
        if previous is None:
            return
        self.advance(now - previous)
