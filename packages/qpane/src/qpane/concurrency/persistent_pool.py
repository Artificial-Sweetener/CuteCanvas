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

"""Persistent Python-thread backend for QPane's bounded task executor."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)


class PersistentWorkerPool:
    """Run QRunnable-compatible work on reusable Python worker threads."""

    def __init__(
        self,
        *,
        max_workers: int,
        thread_name_prefix: str = "qpane-worker",
    ) -> None:
        """Create a persistent worker pool.

        Args:
            max_workers: Positive number of reusable worker threads.
            thread_name_prefix: Prefix assigned to native worker thread names.
        """
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._max_workers = int(max_workers)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._futures: set[Future[None]] = set()
        self._active_count = 0
        self._available = True

    def start(self, runnable: Any, priority: int = 0) -> None:
        """Schedule ``runnable.run``; QPane has already resolved priority."""
        del priority
        with self._lock:
            if not self._available:
                raise RuntimeError("persistent worker pool is shut down")
            future = self._executor.submit(self._run, runnable)
            self._futures.add(future)
        future.add_done_callback(self._discard_future)

    def activeThreadCount(self) -> int:
        """Return the number of workers currently inside a runnable."""
        with self._lock:
            return self._active_count

    def maxThreadCount(self) -> int:
        """Return the fixed worker count for diagnostics."""
        return self._max_workers

    def waitForDone(self, msecs: int = -1) -> bool:
        """Wait until submitted work completes, optionally with a timeout."""
        timeout = None if msecs < 0 else msecs / 1000.0
        with self._condition:
            return self._condition.wait_for(lambda: not self._futures, timeout=timeout)

    def is_available(self) -> bool:
        """Return True while the pool accepts submissions."""
        with self._lock:
            return self._available

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop accepting work and release worker threads after queued work."""
        with self._lock:
            if not self._available:
                return
            self._available = False
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self, runnable: Any) -> None:
        """Execute one runnable while maintaining active diagnostics."""
        with self._lock:
            self._active_count += 1
        try:
            runnable.run()
        finally:
            with self._lock:
                self._active_count -= 1

    def _discard_future(self, future: Future[None]) -> None:
        """Remove completed future bookkeeping and wake waiters."""
        exception = future.exception()
        if exception is not None:
            logger.error(
                "Persistent worker terminated without reporting its outcome",
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        with self._condition:
            self._futures.discard(future)
            self._condition.notify_all()
