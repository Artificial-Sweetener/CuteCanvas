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
"""Own cooperative cancellation state for execution tasks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock

logger = logging.getLogger(__name__)


class CancellationToken:
    """Expose thread-safe cooperative cancellation to task work."""

    def __init__(self) -> None:
        """Create an uncancelled token."""

        self._is_cancelled = False
        self._reason: str | None = None
        self._lock = Lock()
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        with self._lock:
            return self._is_cancelled

    @property
    def reason(self) -> str | None:
        """Return the first cancellation reason when present."""

        with self._lock:
            return self._reason

    def raise_if_cancelled(self) -> None:
        """Stop cooperative work promptly after cancellation."""
        reason = self.reason
        if reason is not None:
            raise RuntimeError(reason)

    def _cancel(self, reason: str) -> bool:
        """Record the first cancellation request."""

        if not reason.strip():
            raise ValueError("cancellation reason must not be blank")
        with self._lock:
            if self._is_cancelled:
                return False
            self._is_cancelled = True
            self._reason = reason
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Cancellation subscriber failed")
        return True

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Notify a bounded collaborator and return its unsubscription."""
        with self._lock:
            if not self._is_cancelled:
                self._callbacks.add(callback)

                def unsubscribe() -> None:
                    """Remove the callback when its bounded work has completed."""
                    with self._lock:
                        self._callbacks.discard(callback)

                return unsubscribe
        callback()
        return lambda: None


__all__ = ["CancellationToken"]
