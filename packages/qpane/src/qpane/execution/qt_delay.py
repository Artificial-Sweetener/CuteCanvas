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

"""Qt owner-loop delay scheduling for producer retry policies."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, QTimer

from .retry_model import DelayHandle, RetrySchedulingError


class _QtDelayHandle:
    """Own one single-shot timer until cancellation or delivery."""

    def __init__(self, timer: QTimer) -> None:
        """Capture the timer created on its owner's Qt thread."""
        self._timer: QTimer | None = timer

    def cancel(self) -> None:
        """Stop and dispose the timer when it remains live."""
        timer = self._timer
        self._timer = None
        if timer is None:
            return
        timer.stop()
        timer.deleteLater()

    def release(self) -> None:
        """Forget a timer that already delivered its callback."""
        self._timer = None


class QtDelayScheduler:
    """Schedule single-shot callbacks on a QObject owner's thread."""

    def __init__(self, owner: QObject) -> None:
        """Bind delayed callbacks to ``owner`` lifetime and affinity."""
        self._owner = owner

    def schedule(self, delay_ms: int, callback: Callable[[], None]) -> DelayHandle:
        """Create one single-shot timer on the current owner thread."""
        if QThread.currentThread() is not self._owner.thread():
            raise RetrySchedulingError("retry scheduling requires the owner thread")
        timer = QTimer(self._owner)
        timer.setSingleShot(True)
        handle = _QtDelayHandle(timer)

        def _deliver() -> None:
            """Dispose the timer before running producer policy."""
            handle.release()
            timer.deleteLater()
            callback()

        timer.timeout.connect(_deliver)
        timer.start(max(0, int(delay_ms)))
        return handle
