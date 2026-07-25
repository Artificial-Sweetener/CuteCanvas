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
"""Host-neutral execution lifecycle and standalone runtime."""

from .affinity_backend import AffinityExecutionBackend
from .backend import (
    BackendSubmission,
    ExecutionBackend,
    ExecutionBackendCapabilities,
    ExecutionBackendLifecycle,
    ExecutionJob,
)
from .cancellation import CancellationToken
from .default_backend import DefaultExecutionBackend
from .default_policy import DefaultExecutionPolicy
from .diagnostic_records import (
    execution_detail_records,
    execution_summary_records,
    retry_detail_records,
    retry_summary_records,
)
from .diagnostics import (
    DiagnosticsSubscription,
    ExecutionDiagnosticsProvider,
    ExecutionSnapshot,
)
from .dispatch import CompletionDispatcher, InlineDispatcher
from .factory import create_default_execution_runtime, create_native_execution_runtime
from .handle import ExecutionHandle
from .model import (
    ExecutionFailurePhase,
    ExecutionLeaseRelease,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionState,
    ExecutionTagValue,
    ExecutionTimings,
    ExecutionUrgency,
)
from .progress import ExecutionProgressReporter
from .qt_delay import QtDelayScheduler
from .qt_dispatch import QtOwnerDispatcher
from .retry import RetryController
from .retry_model import (
    DelayHandle,
    DelayScheduler,
    RetryCategorySnapshot,
    RetryContext,
    RetryPolicy,
    RetrySchedulingError,
    RetrySnapshot,
)
from .runtime import ExecutionRuntime
from .scope import ExecutionScope
from .task_context import ExecutionTaskContext

__all__ = [
    "AffinityExecutionBackend",
    "BackendSubmission",
    "CancellationToken",
    "CompletionDispatcher",
    "DefaultExecutionBackend",
    "DefaultExecutionPolicy",
    "DelayHandle",
    "DelayScheduler",
    "DiagnosticsSubscription",
    "ExecutionBackend",
    "ExecutionBackendCapabilities",
    "ExecutionBackendLifecycle",
    "ExecutionDiagnosticsProvider",
    "ExecutionFailurePhase",
    "ExecutionHandle",
    "ExecutionJob",
    "ExecutionLeaseRelease",
    "ExecutionOutcome",
    "ExecutionProgressReporter",
    "ExecutionRejected",
    "ExecutionRejectionReason",
    "ExecutionRequest",
    "ExecutionRequirements",
    "ExecutionResource",
    "ExecutionRuntime",
    "ExecutionScope",
    "ExecutionSnapshot",
    "ExecutionState",
    "ExecutionTagValue",
    "ExecutionTaskContext",
    "ExecutionTimings",
    "ExecutionUrgency",
    "InlineDispatcher",
    "QtDelayScheduler",
    "QtOwnerDispatcher",
    "RetryCategorySnapshot",
    "RetryContext",
    "RetryController",
    "RetryPolicy",
    "RetrySchedulingError",
    "RetrySnapshot",
    "create_default_execution_runtime",
    "create_native_execution_runtime",
    "execution_detail_records",
    "execution_summary_records",
    "retry_detail_records",
    "retry_summary_records",
]
