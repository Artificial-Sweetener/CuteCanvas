#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Testing utilities for exercising TaskExecutorProtocol implementations."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import count
from typing import Any

from PySide6.QtCore import QRunnable
from qpane.concurrency import (
    BaseWorker,
    ExecutorSnapshot,
    TaskExecutorProtocol,
    TaskHandle,
    TaskOutcome,
    TaskRejected,
)


@dataclass
class _TaskRecord:
    """In-memory bookkeeping for stub executor submissions."""

    handle: TaskHandle
    runnable: QRunnable | None
    callback: Callable[[], None] | None
    state: str = "pending"
    outcome: TaskOutcome | None = None


class CallableRunnable(QRunnable):
    """QRunnable that executes a provided callable when run."""

    def __init__(self, func: Callable[[], Any]) -> None:
        super().__init__()
        self._func = func

    def run(self) -> None:  # pragma: no cover - exercised indirectly in tests
        self._func()


class StubExecutor(TaskExecutorProtocol):
    """Deterministic executor used to validate task orchestration logic."""

    def __init__(
        self,
        *,
        name: str = "stub",
        max_workers: int = 4,
        auto_finish: bool = False,
        supports_main_thread_dispatch: bool = True,
    ) -> None:
        self._name = name
        self._max_workers = max_workers
        self._auto_finish = auto_finish
        self._supports_main_thread_dispatch = supports_main_thread_dispatch
        self._counter = count(1)
        self._tasks: dict[str, _TaskRecord] = {}
        self._pending_order: deque[str] = deque()
        self._queued_by_category: dict[str, int] = {}
        self._active_by_category: dict[str, int] = {}
        self._active_by_device: dict[tuple[str, str], int] = {}
        self._active_total = 0
        self.cancelled: list[TaskHandle] = []
        self.finished: list[tuple[TaskHandle, TaskOutcome]] = []
        self.shutdown_called = False

    def submit(
        self,
        runnable: QRunnable,
        category: str,
        *,
        device: str | None = None,
    ) -> TaskHandle:
        """Record a runnable for later execution, optionally auto-running it."""
        handle = self._make_handle(category, device)
        if hasattr(runnable, "bind_executor"):
            runnable.bind_executor(self, handle)  # type: ignore[call-arg]
        record = _TaskRecord(handle=handle, runnable=runnable, callback=None)
        self._enqueue(record)
        if self._auto_finish:
            self.run_task(handle.task_id)
        return handle

    def dispatch_to_main_thread(
        self,
        callback: Callable[[], None],
        *,
        category: str = "main",
        device: str | None = None,
    ) -> TaskHandle:
        """Queue a callback that will execute when `run_task` is invoked."""
        if not self._supports_main_thread_dispatch:
            raise AttributeError("dispatch_to_main_thread is not supported")
        handle = self._make_handle(category, device)
        record = _TaskRecord(handle=handle, runnable=None, callback=callback)
        self._enqueue(record)
        if self._auto_finish:
            self.run_task(handle.task_id)
        return handle

    def cancel(self, handle: TaskHandle) -> bool:
        """Cancel a pending task or request cancellation from its runnable."""
        record = self._tasks.get(handle.task_id)
        if record is None:
            return False
        if record.state == "pending":
            self._remove_pending(record)
            self._tasks.pop(handle.task_id, None)
            self.cancelled.append(handle)
            return True
        if record.state != "active":
            return False
        runnable = record.runnable
        cancelled = False
        if runnable is not None and hasattr(runnable, "cancel"):
            try:
                runnable.cancel()  # type: ignore[call-arg]
                cancelled = True
            except Exception:  # noqa: BLE001 - arbitrary cancellation collaborator
                cancelled = False
        if cancelled:
            self.cancelled.append(handle)
        return cancelled

    def mark_finished(self, handle: TaskHandle, outcome: TaskOutcome) -> None:
        """Record completion metadata emitted by a worker."""
        record = self._tasks.get(handle.task_id)
        if record is None:
            return
        if record.state == "pending":
            self._remove_pending(record)
            self._tasks.pop(handle.task_id, None)
            return
        self._decrement_active(record)
        record.state = "finished"
        record.outcome = outcome
        self.finished.append((handle, outcome))
        self._tasks.pop(handle.task_id, None)

    def active_counts(self) -> dict[str, int]:
        """Return a copy of active counts keyed by category."""
        return dict(self._active_by_category)

    def snapshot(self) -> ExecutorSnapshot:
        """Return a diagnostic snapshot consistent with ExecutorSnapshot."""
        queued_by_category: dict[str, int] = {}
        for record in self._tasks.values():
            if record.state == "pending":
                category = record.handle.category
                queued_by_category[category] = queued_by_category.get(category, 0) + 1
        pending_total = sum(queued_by_category.values())
        return ExecutorSnapshot(
            name=self._name,
            max_workers=self._max_workers,
            active_total=self._active_total,
            active_by_category=dict(self._active_by_category),
            queued_by_category=queued_by_category,
            pending_total=pending_total,
            max_pending_total=None,
            pending_limits={},
            pending_utilization_total_pct=None,
            pending_utilization_by_category_pct={},
            category_limits={},
            device_limits={},
        )

    def shutdown(self, *, wait: bool = True) -> None:
        """Mark the executor as shut down for assertions."""
        self.shutdown_called = True

    # Helpers ---------------------------------------------------------
    def run_task(self, task_id: str) -> None:
        """Execute the runnable or callback associated with `task_id`."""
        record = self._tasks.get(task_id)
        if record is None or record.state != "pending":
            return
        self._activate(record)
        if record.runnable is not None:
            record.runnable.run()
            still_known = self._tasks.get(task_id)
            if (
                still_known is not None
                and still_known.state == "active"
                and not isinstance(record.runnable, BaseWorker)
            ):
                self.mark_finished(
                    record.handle,
                    TaskOutcome(success=True, payload=None, error=None),
                )
            return
        if record.callback is None:
            self.mark_finished(record.handle, TaskOutcome(success=True))
            return
        try:
            record.callback()
        except Exception as exc:  # noqa: BLE001 - mirrors worker callback boundary
            self.mark_finished(
                record.handle,
                TaskOutcome(success=False, payload=str(exc), error=exc),
            )
        else:
            self.mark_finished(record.handle, TaskOutcome(success=True))

    def run_category(self, category: str) -> None:
        """Execute all pending tasks for the specified category."""
        for task_id in list(self._pending_order):
            record = self._tasks.get(task_id)
            if record is None or record.handle.category != category:
                continue
            self.run_task(task_id)

    def drain_all(self) -> None:
        """Execute every pending task regardless of category."""
        for task_id in list(self._pending_order):
            self.run_task(task_id)

    def pending_tasks(self) -> Iterable[_TaskRecord]:
        """Expose pending tasks for fine-grained assertions."""
        for task_id in self._pending_order:
            record = self._tasks.get(task_id)
            if record is not None and record.state == "pending":
                yield record

    def _make_handle(self, category: str, device: str | None) -> TaskHandle:
        task_id = f"{self._name}-{next(self._counter)}"
        return TaskHandle(task_id=task_id, category=category, device=device)

    def _enqueue(self, record: _TaskRecord) -> None:
        self._tasks[record.handle.task_id] = record
        self._pending_order.append(record.handle.task_id)
        category = record.handle.category
        self._queued_by_category[category] = (
            self._queued_by_category.get(category, 0) + 1
        )

    def _remove_pending(self, record: _TaskRecord) -> None:
        try:
            self._pending_order.remove(record.handle.task_id)
        except ValueError:
            pass
        category = record.handle.category
        current = self._queued_by_category.get(category, 0)
        if current <= 1:
            self._queued_by_category.pop(category, None)
        else:
            self._queued_by_category[category] = current - 1

    def _activate(self, record: _TaskRecord) -> None:
        self._remove_pending(record)
        record.state = "active"
        category = record.handle.category
        device = record.handle.device
        self._active_total += 1
        self._active_by_category[category] = (
            self._active_by_category.get(category, 0) + 1
        )
        if device:
            key = (device, category)
            self._active_by_device[key] = self._active_by_device.get(key, 0) + 1

    def _decrement_active(self, record: _TaskRecord) -> None:
        category = record.handle.category
        device = record.handle.device
        self._active_total = max(0, self._active_total - 1)
        active = self._active_by_category.get(category, 0) - 1
        if active <= 0:
            self._active_by_category.pop(category, None)
        else:
            self._active_by_category[category] = active
        if device:
            key = (device, category)
            value = self._active_by_device.get(key, 0) - 1
            if value <= 0:
                self._active_by_device.pop(key, None)
            else:
                self._active_by_device[key] = value


class RejectingStubExecutor(StubExecutor):
    """Stub executor that raises TaskRejected on the first N submissions per category."""

    def __init__(
        self,
        *,
        reject_counts: dict[str, int],
        name: str = "rejecting",
        **kwargs,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self._remaining_rejections = {k: max(0, v) for k, v in reject_counts.items()}
        self.rejections: list[tuple[str, TaskRejected]] = []

    def submit(
        self, runnable: QRunnable, category: str, *, device: str | None = None
    ) -> TaskHandle:
        remaining = self._remaining_rejections.get(category, 0)
        if remaining > 0:
            self._remaining_rejections[category] = remaining - 1
            pending_total = sum(
                1 for record in self._tasks.values() if record.state == "pending"
            )
            pending_category = self._queued_by_category.get(category, 0)
            rejection = TaskRejected(
                f"Rejected {category} submission",
                category=category,
                device=device,
                limit_type="category",
                limit_value=max(1, remaining),
                pending_total=pending_total,
                pending_category=pending_category,
            )
            self.rejections.append((category, rejection))
            raise rejection
        return super().submit(runnable, category, device=device)

    def remaining_rejections(self, category: str) -> int:
        """Return remaining planned rejections for ``category``."""
        return self._remaining_rejections.get(category, 0)


@dataclass
class _TestHandle:
    key: Any
    callback: Callable[[], None]
    cancelled: bool = False
    when_ms: int = 0

    def stop(self) -> None:
        self.cancelled = True

    def deleteLater(self) -> None:  # pragma: no cover - no-op in tests
        pass


class RetryTestScheduler:
    """Deterministic scheduler for unit tests (no Qt dependency)."""

    def __init__(self) -> None:
        self.scheduled: list[_TestHandle] = []

    def schedule(self, key, delay_ms: int, callback: Callable[[], None]):
        handle = _TestHandle(key=key, callback=callback, when_ms=int(delay_ms))
        self.scheduled.append(handle)
        return handle

    def cancel(self, handle: _TestHandle) -> None:
        handle.stop()

    def run_next(self) -> None:
        while self.scheduled:
            handle = self.scheduled.pop(0)
            if not handle.cancelled:
                handle.callback()
                return

    def run_all(self) -> None:
        for _ in range(len(self.scheduled)):
            self.run_next()


__all__ = [
    "CallableRunnable",
    "RejectingStubExecutor",
    "RetryTestScheduler",
    "StubExecutor",
]
