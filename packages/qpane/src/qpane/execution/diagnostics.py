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
"""Describe optional execution backend diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Lock, Thread
from typing import Generic, Protocol, TypeVar

logger = logging.getLogger(__name__)
TSnapshot = TypeVar("TSnapshot")


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """Summarize bounded backend state without exposing queue internals."""

    accepted: int
    pending: int
    running: int
    retained_bytes: int
    rejected: int
    completed: int
    cancelled_before_start: int


class DiagnosticsSubscription:
    """Remove one diagnostics observer idempotently."""

    def __init__(self, unsubscribe: Callable[[], None]) -> None:
        """Store the observer removal callback."""

        self._unsubscribe = unsubscribe
        self._closed = False

    def close(self) -> None:
        """Unsubscribe once."""

        if self._closed:
            return
        self._closed = True
        self._unsubscribe()


class ExecutionDiagnosticsProvider(Protocol):
    """Expose optional snapshots and multi-observer changes."""

    def execution_snapshot(self) -> ExecutionSnapshot:
        """Return the current immutable snapshot."""

    def subscribe_diagnostics(
        self,
        callback: Callable[[ExecutionSnapshot], None],
    ) -> DiagnosticsSubscription:
        """Observe later snapshots until the subscription closes."""


class DiagnosticsHub(Generic[TSnapshot]):
    """Coalesce diagnostics delivery away from scheduler critical sections."""

    def __init__(self, *, thread_name: str) -> None:
        """Start one bounded notification worker."""

        if not thread_name.strip():
            raise ValueError("thread_name must not be blank")
        self._observers: dict[int, Callable[[TSnapshot], None]] = {}
        self._next_observer_id = 0
        self._latest: TSnapshot | None = None
        self._closed = False
        self._condition = Condition(Lock())
        self._thread = Thread(target=self._run, name=thread_name, daemon=True)
        self._thread.start()

    def publish(self, snapshot: TSnapshot) -> None:
        """Replace the pending snapshot without blocking the caller."""

        with self._condition:
            if self._closed:
                return
            self._latest = snapshot
            self._condition.notify()

    def subscribe(
        self,
        callback: Callable[[TSnapshot], None],
    ) -> DiagnosticsSubscription:
        """Register one independent observer."""

        with self._condition:
            if self._closed:
                raise RuntimeError("diagnostics hub is closed")
            self._next_observer_id += 1
            observer_id = self._next_observer_id
            self._observers[observer_id] = callback
        return DiagnosticsSubscription(lambda: self._unsubscribe(observer_id))

    def close(self, *, wait: bool = False) -> None:
        """Stop future publication and release observers."""

        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._latest = None
            self._observers.clear()
            self._condition.notify_all()
        if wait:
            self._thread.join()

    def _run(self) -> None:
        """Deliver the newest snapshot to each current observer."""

        while True:
            with self._condition:
                while self._latest is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                snapshot = self._latest
                self._latest = None
                observers = tuple(self._observers.values())
            if snapshot is None:
                continue
            for observer in observers:
                try:
                    observer(snapshot)
                except Exception:
                    logger.exception("Execution diagnostics observer failed")

    def _unsubscribe(self, observer_id: int) -> None:
        """Remove one observer."""

        with self._condition:
            self._observers.pop(observer_id, None)


__all__ = [
    "DiagnosticsHub",
    "DiagnosticsSubscription",
    "ExecutionDiagnosticsProvider",
    "ExecutionSnapshot",
]
