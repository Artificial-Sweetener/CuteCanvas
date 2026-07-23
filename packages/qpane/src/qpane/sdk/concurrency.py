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
"""Supported task execution and retry contracts for renderer integrations."""

from ..concurrency import (
    BaseWorker,
    RetryContext,
    RetryEntriesView,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
    ThreadPolicy,
    makeQtRetryController,
    qt_retry_dispatcher,
)
from ..concurrency.executor import LiveTunableExecutorProtocol, QThreadPoolExecutor
from ..concurrency.metrics import retry_diagnostics_provider, retry_summary_provider
from ..concurrency.thread_policy import build_thread_policy

__all__ = (
    "BaseWorker",
    "LiveTunableExecutorProtocol",
    "QThreadPoolExecutor",
    "RetryContext",
    "RetryEntriesView",
    "TaskExecutorProtocol",
    "TaskHandle",
    "TaskRejected",
    "ThreadPolicy",
    "build_thread_policy",
    "makeQtRetryController",
    "qt_retry_dispatcher",
    "retry_diagnostics_provider",
    "retry_summary_provider",
)
