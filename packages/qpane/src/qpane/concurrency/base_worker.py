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

"""Utilities that help QRunnable workers integrate with QPane executors."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt

try:  # pragma: no cover - dependency availability checked at runtime
    import shiboken6
except ImportError:  # pragma: no cover - defensive guard for alternate runtimes
    shiboken6 = None

from .executor import TaskExecutorProtocol, TaskHandle, TaskOutcome

logger = logging.getLogger(__name__)


class BaseWorker:
    """Provide cancellation flags plus executor and signal helpers for workers."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        """Initialise cancellation state and configure logging.

        Args:
            logger: Optional logger preconfigured by the caller. When omitted
                the worker creates a module-qualified logger so related tasks
                emit under the same namespace.
        """
        self._cancelled = False
        self._executor: TaskExecutorProtocol | None = None
        self._handle: TaskHandle | None = None
        self._logger = logger or logging.getLogger(__name__)
        self._signal_disposal_scheduled = False
        self._executor_completion_lock = threading.Lock()
        self._executor_completion_reported = False

    @property
    def logger(self) -> logging.Logger:
        """Expose the logger used to report worker diagnostics."""
        return self._logger

    @property
    def is_cancelled(self) -> bool:
        """Return True when the worker has been asked to cancel itself."""
        return self._cancelled

    def cancel(self) -> None:
        """Flip the cancellation flag so long-running work can exit early."""
        self._cancelled = True

    def bind_executor(self, executor: TaskExecutorProtocol, handle: TaskHandle) -> None:
        """Associate the worker with the executor that submitted it.

        Args:
            executor: Task executor responsible for tracking completions.
            handle: Handle returned by executor.submit for this worker.
        """
        self._executor = executor
        self._handle = handle

    def emit_finished(
        self,
        success: bool,
        payload: Any | None = None,
        error: BaseException | None = None,
        *,
        defer_executor_completion: bool = False,
    ) -> None:
        """Notify Qt listeners and the executor about a worker outcome.

        Args:
            success: True when the runnable completed successfully.
            payload: Optional payload forwarded to the finished signal.
            error: Optional exception captured for diagnostics.
            defer_executor_completion: Keep the scheduler slot occupied until
                ``complete_executor`` is called by the result owner.

        Side effects:
            Emits the finished/error Qt signal, schedules the worker-owned Qt
            signal bridge for disposal on its affinity thread, and releases
            the bound executor unless completion was explicitly deferred.
        """
        target_signal = "finished" if success else "error"
        self._emit_signal(target_signal, payload)
        self._schedule_signal_disposal()
        if not defer_executor_completion:
            self.complete_executor(success, payload=payload, error=error)

    def complete_executor(
        self,
        success: bool,
        payload: Any | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Release this worker's scheduler slot exactly once.

        Args:
            success: True when the deferred result was accepted successfully.
            payload: Optional result retained in executor diagnostics.
            error: Optional exception retained in executor diagnostics.
        """
        with self._executor_completion_lock:
            if self._executor_completion_reported:
                return
            self._executor_completion_reported = True
            executor = self._executor
            handle = self._handle
        if executor is not None and handle is not None:
            executor.mark_finished(
                handle,
                TaskOutcome(success=success, payload=payload, error=error),
            )

    @staticmethod
    def connect_queued(signal: Any, slot: Callable[..., None]) -> None:
        """Connect a Qt signal to slot using QueuedConnection semantics."""
        signal.connect(slot, Qt.ConnectionType.QueuedConnection)

    def _emit_signal(self, name: str, *args: Any) -> None:
        """Emit a Qt signal by name while dropping None payloads and tuple wrappers."""
        signal = getattr(self, name, None)
        signal_container = getattr(self, "signals", None)
        if signal is None and signal_container is not None:
            signal = getattr(signal_container, name, None)
        if signal is None:
            if signal_container is not None:
                self.logger.warning(
                    "Worker %s missing %s signal; dropping emit",
                    type(self).__name__,
                    name,
                )
            return
        if shiboken6 is not None:
            owner = getattr(signal, "instance", None)
            if callable(owner):
                try:
                    owner = owner()
                except (RuntimeError, TypeError):
                    owner = None
            if owner is None:
                owner = getattr(signal, "__self__", None)
            if owner is not None and not shiboken6.isValid(owner):
                return
        filtered_args = [arg for arg in args if arg is not None]
        if len(filtered_args) == 1 and isinstance(filtered_args[0], (tuple, list)):
            filtered_args = list(filtered_args[0])
        try:
            signal.emit(*filtered_args)
        except RuntimeError as exc:  # pragma: no cover - Qt raises on deleted QObject
            if "Signal source has been deleted" in str(exc):
                return
            self.logger.exception("Failed to emit %s with args %s", name, filtered_args)
        except Exception:  # pragma: no cover - Qt will raise if signatures mismatch
            self.logger.exception("Failed to emit %s with args %s", name, filtered_args)

    def _schedule_signal_disposal(self) -> None:
        """Dispose a terminal worker signal bridge on its owning Qt thread."""
        signal_container = getattr(self, "signals", None)
        if signal_container is None or self._signal_disposal_scheduled:
            return
        self._signal_disposal_scheduled = True
        try:
            signal_container.deleteLater()
        except RuntimeError:
            self.logger.debug(
                "Worker signal bridge was already unavailable during disposal",
                exc_info=True,
            )
