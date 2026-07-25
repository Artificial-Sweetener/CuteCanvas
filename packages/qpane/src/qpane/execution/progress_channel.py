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
"""Coalesce task progress onto an owner dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar, cast

from .dispatch import CompletionDispatcher

logger = logging.getLogger(__name__)
TProgress = TypeVar("TProgress")
_MISSING = object()


class ProgressChannel(Generic[TProgress]):
    """Publish only the newest pending progress value."""

    def __init__(
        self,
        *,
        dispatcher: CompletionDispatcher,
        observer: Callable[[TProgress], None] | None,
        operation: str,
    ) -> None:
        """Bind optional progress observation to one task."""

        self._dispatcher = dispatcher
        self._observer = observer
        self._operation = operation
        self._latest: object = _MISSING
        self._queued = False
        self._closed = False
        self._lock = Lock()

    def report(self, progress: TProgress) -> bool:
        """Replace pending progress and queue at most one delivery."""

        with self._lock:
            if self._closed or self._observer is None:
                return False
            self._latest = progress
            if self._queued:
                return True
            self._queued = True
        self._queue_delivery()
        return True

    def close(self) -> None:
        """Suppress queued and future progress."""

        with self._lock:
            self._closed = True
            self._observer = None
            self._latest = _MISSING

    def _queue_delivery(self) -> None:
        """Ask the owner dispatcher to deliver the newest progress."""

        self._dispatcher.dispatch(
            self._deliver,
            discarded=self._discard,
            reason=f"{self._operation}:progress",
        )

    def _deliver(self) -> None:
        """Invoke the observer with the newest pending value."""

        with self._lock:
            if self._closed or self._observer is None:
                self._queued = False
                self._latest = _MISSING
                return
            value = self._latest
            self._latest = _MISSING
            observer = self._observer
        if value is not _MISSING:
            try:
                observer(cast(TProgress, value))
            except Exception:
                logger.exception(
                    "Execution progress observer failed",
                    extra={"operation": self._operation},
                )
                with self._lock:
                    self._observer = None
                    self._latest = _MISSING
        with self._lock:
            if self._closed or self._observer is None:
                self._queued = False
                return
            if self._latest is _MISSING:
                self._queued = False
                return
        self._queue_delivery()

    def _discard(self) -> None:
        """Suppress progress after owner delivery becomes impossible."""

        self.close()


__all__ = ["ProgressChannel"]
