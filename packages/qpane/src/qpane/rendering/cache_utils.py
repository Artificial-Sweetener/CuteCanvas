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

"""Cache-dispatch helpers shared by rendering collaborators."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QRunnable

from ..concurrency import BaseWorker, TaskExecutorProtocol, TaskHandle


class CacheEvictionCoordinator:
    """Schedule cache eviction callbacks via the executor or main thread."""

    def __init__(self, *, logger: logging.Logger, name: str) -> None:
        """Store the logger metadata used when reporting eviction callbacks."""
        self._logger = logger
        self._name = name
        self._pending: bool = False
        self._handle: TaskHandle | None = None

    @property
    def pending(self) -> bool:
        """Return True when an eviction callback is already scheduled."""
        return self._pending

    def schedule(
        self,
        *,
        executor: TaskExecutorProtocol,
        callback: Callable[[], None],
        category: str = "maintenance",
    ) -> None:
        """Queue ``callback`` when no eviction task is currently pending."""
        if self._pending:
            return

        def _runner() -> None:
            """Clear pending state and execute the eviction callback."""
            self._handle = None
            self._pending = False
            callback()

        self._pending = True
        try:
            self._handle = dispatch_to_main_thread_or_executor(
                executor,
                _runner,
                category=category,
            )
        except Exception:
            self._pending = False
            self._handle = None
            raise

    def cancel(self, executor: TaskExecutorProtocol | None) -> None:
        """Cancel any scheduled eviction callback."""
        handle = self._handle
        if handle is None:
            self._pending = False
            return
        self._handle = None
        self._pending = False
        if executor is None:
            return
        cancelled = executor.cancel(handle)
        if not cancelled:
            task_id = getattr(handle, "task_id", "unknown")
            self._logger.debug(
                "%s eviction callback could not be cancelled (task=%s)",
                self._name,
                task_id,
            )


class ExecutorOwnerMixin:
    """Shared helper that gates executor shutdown calls behind ownership flags."""

    def __init__(self, *, executor_logger: logging.Logger, owner_name: str) -> None:
        """Capture executor metadata used when coordinating shutdown behaviour."""
        self._executor_logger = executor_logger
        self._executor_owner_name = owner_name

    def _maybe_wait_for_executor(self, wait: bool) -> None:
        """Invoke executor.shutdown when this manager owns the executor."""
        if not wait:
            return
        if not getattr(self, "_owns_executor", False):
            self._executor_logger.debug(
                "%s wait requested but executor is shared; skipping shutdown",
                self._executor_owner_name,
            )
            return
        executor = getattr(self, "_executor", None)
        if executor is None:
            return
        shutdown = getattr(executor, "shutdown", None)
        if shutdown is None:
            return
        try:
            shutdown(wait=True)
        except Exception:  # pragma: no cover - defensive guard
            self._executor_logger.debug(
                "%s executor shutdown raised during wait",
                self._executor_owner_name,
                exc_info=True,
            )


def dispatch_to_main_thread_or_executor(
    executor: TaskExecutorProtocol,
    callback: Callable[[], None],
    *,
    category: str,
) -> TaskHandle:
    """Dispatch a callback via the executor's main-thread hook when available.

    Args:
        executor: Task executor that may expose dispatch_to_main_thread.
        callback: No-arg callable to run.
        category: Task category label forwarded to the executor.

    Returns:
        Handle for the scheduled task.
    """
    dispatcher = getattr(executor, "dispatch_to_main_thread", None)
    protocol_default = getattr(TaskExecutorProtocol, "dispatch_to_main_thread", None)
    dispatcher_func = getattr(dispatcher, "__func__", dispatcher)
    runnable = CallbackDispatchRunnable(callback)
    if dispatcher is None or dispatcher_func is protocol_default:
        return executor.submit(runnable, category=category)
    try:
        return dispatcher(callback, category=category)
    except AttributeError:
        return executor.submit(runnable, category=category)


class CallbackDispatchRunnable(QRunnable, BaseWorker):
    """QRunnable that runs a stored no-arg callback on the worker thread."""

    def __init__(self, callback: Callable[[], None]) -> None:
        """Record the callback so run() can execute it on the worker thread."""
        QRunnable.__init__(self)
        BaseWorker.__init__(self)
        self._callback = callback

    def run(self) -> None:
        """Run the callback unless cancelled, emitting worker completion accordingly."""
        if self.is_cancelled:
            self.emit_finished(True)
            return
        try:
            self._callback()
        except Exception as exc:  # noqa: BLE001 - worker callback boundary
            self.emit_finished(False, payload=str(exc), error=exc)
        else:
            self.emit_finished(True)
