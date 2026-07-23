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

"""Concurrency infrastructure primitives used by QPane managers and hosts."""

from .base_worker import BaseWorker
from .executor import (
    ExecutorSnapshot,
    LiveTunableExecutorProtocol,
    QThreadPoolExecutor,
    TaskExecutorProtocol,
    TaskHandle,
    TaskOutcome,
    TaskRejected,
)
from .metrics import (
    executor_diagnostics_provider,
    executor_summary_provider,
    gather_executor_snapshot,
    retry_diagnostics_provider,
    retry_summary_provider,
)
from .retry import (
    BackoffPolicy,
    QtTimerScheduler,
    RetryContext,
    RetryController,
    RetryPolicy,
    RetrySchedulingError,
    TerminationPolicy,
    makeQtRetryController,
    qt_retry_dispatcher,
)
from .retry_view import RetryEntriesView
from .thread_policy import ThreadPolicy, build_thread_policy, update_thread_policy

__all__ = [
    "BackoffPolicy",
    "BaseWorker",
    "ExecutorSnapshot",
    "LiveTunableExecutorProtocol",
    "QThreadPoolExecutor",
    "QtTimerScheduler",
    "RetryContext",
    "RetryController",
    "RetryEntriesView",
    "RetryPolicy",
    "RetrySchedulingError",
    "TaskExecutorProtocol",
    "TaskHandle",
    "TaskOutcome",
    "TaskRejected",
    "TerminationPolicy",
    "ThreadPolicy",
    "build_thread_policy",
    "executor_diagnostics_provider",
    "executor_summary_provider",
    "gather_executor_snapshot",
    "makeQtRetryController",
    "qt_retry_dispatcher",
    "retry_diagnostics_provider",
    "retry_summary_provider",
    "update_thread_policy",
]
