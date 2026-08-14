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
"""Deliver execution callbacks through a receiver's Qt thread."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from PySide6.QtCore import QObject, Qt, Signal, Slot
from shiboken6 import isValid

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PendingDispatch:
    """Retain one callback and its discard acknowledgement."""

    callback: Callable[[], None]
    discarded: Callable[[], None]
    reason: str


class QtOwnerDispatcher(QObject):
    """Queue callbacks to one QObject's affinity thread with discard safety."""

    _requested = Signal(int)

    def __init__(self, receiver: QObject) -> None:
        """Bind dispatch lifetime to a receiver."""

        super().__init__(receiver)
        self._receiver = receiver
        self._next_id = 0
        self._pending: dict[int, _PendingDispatch] = {}
        self._closed = False
        self._lock = Lock()
        self._requested.connect(
            self._deliver,
            Qt.ConnectionType.QueuedConnection,
        )
        receiver.destroyed.connect(self.close)

    @property
    def is_closed(self) -> bool:
        """Return whether this dispatcher can no longer deliver callbacks."""

        with self._lock:
            return self._closed

    def dispatch(
        self,
        callback: Callable[[], None],
        *,
        discarded: Callable[[], None],
        reason: str,
    ) -> None:
        """Queue one callback or discard it if the receiver is unavailable."""

        if not reason.strip():
            raise ValueError("dispatch reason must not be blank")
        rejected: _PendingDispatch | None = None
        with self._lock:
            if self._closed or not self._receiver_is_valid():
                should_discard = True
            else:
                should_discard = False
                self._next_id += 1
                dispatch_id = self._next_id
                self._pending[dispatch_id] = _PendingDispatch(
                    callback=callback,
                    discarded=discarded,
                    reason=reason,
                )
                try:
                    self._requested.emit(dispatch_id)
                except RuntimeError:
                    rejected = self._pending.pop(dispatch_id, None)
        if should_discard:
            _invoke_discard(discarded, reason=reason)
        elif rejected is not None:
            _invoke_discard(rejected.discarded, reason=rejected.reason)

    @Slot(int)
    def _deliver(self, dispatch_id: int) -> None:
        """Deliver one queued callback on the receiver thread."""

        with self._lock:
            pending = self._pending.pop(dispatch_id, None)
            closed = self._closed
        if pending is None:
            return
        if closed or not self._receiver_is_valid():
            _invoke_discard(pending.discarded, reason=pending.reason)
            return
        pending.callback()

    @Slot()
    def close(self) -> None:
        """Discard every queued callback and reject future delivery."""

        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            if self._closed:
                return
            self._closed = True
            pending = tuple(self._pending.values())
            self._pending.clear()
        for item in pending:
            _invoke_discard(item.discarded, reason=item.reason)

    def _receiver_is_valid(self) -> bool:
        """Return whether Qt can still deliver to the bound receiver."""

        try:
            return bool(isValid(self._receiver)) and bool(isValid(self))
        except RuntimeError:
            return False
        except TypeError:
            return True


def _invoke_discard(callback: Callable[[], None], *, reason: str) -> None:
    """Contain discard callback failures at the delivery boundary."""

    try:
        callback()
    except Exception:
        logger.exception("Execution dispatch discard failed", extra={"reason": reason})


__all__ = ["QtOwnerDispatcher"]
