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
"""Route one accepted request to one capable physical backend."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Lock
from typing import TypeVar

from .backend import (
    ExecutionBackend,
    ExecutionJob,
)
from .diagnostics import DiagnosticsSubscription, ExecutionSnapshot
from .dispatch import CompletionDispatcher, InlineDispatcher
from .handle import ExecutionHandle
from .model import (
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
    ExecutionRequirements,
)
from .scope import ExecutionScope

TResult = TypeVar("TResult")
TProgress = TypeVar("TProgress")


class ExecutionRuntime:
    """Own task lifecycle while delegating admission to one backend."""

    def __init__(
        self,
        backend: ExecutionBackend,
        *,
        capability_backends: Sequence[ExecutionBackend] = (),
        shutdown_backends: bool = False,
    ) -> None:
        """Create a runtime over an ordered immutable backend topology."""

        self._backends = tuple(capability_backends) + (backend,)
        if not self._backends:
            raise ValueError("at least one execution backend is required")
        self._shutdown_backends = shutdown_backends
        self._scopes: set[ExecutionScope] = set()
        self._closed = False
        self._lock = Lock()

    @property
    def is_closed(self) -> bool:
        """Return whether this runtime rejects new scopes and work."""

        with self._lock:
            return self._closed

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether one configured backend honors the requirements."""

        return any(backend.supports(requirements) for backend in self._backends)

    def execution_snapshots(self) -> tuple[ExecutionSnapshot, ...]:
        """Return snapshots exposed by configured diagnostic-capable backends."""
        snapshots: list[ExecutionSnapshot] = []
        for backend in self._backends:
            snapshot = getattr(backend, "execution_snapshot", None)
            if not callable(snapshot):
                continue
            value = snapshot()
            if isinstance(value, ExecutionSnapshot):
                snapshots.append(value)
        return tuple(snapshots)

    def subscribe_diagnostics(
        self,
        callback: Callable[[tuple[ExecutionSnapshot, ...]], None],
    ) -> DiagnosticsSubscription:
        """Observe aggregate backend snapshots until the subscription closes."""

        subscriptions: list[DiagnosticsSubscription] = []

        def _publish(_snapshot: ExecutionSnapshot) -> None:
            """Publish one current aggregate after any backend changes."""
            callback(self.execution_snapshots())

        for backend in self._backends:
            subscribe = getattr(backend, "subscribe_diagnostics", None)
            if callable(subscribe):
                subscriptions.append(subscribe(_publish))

        def _close() -> None:
            """Close every backend observer registered for this aggregate."""
            for subscription in subscriptions:
                subscription.close()

        return DiagnosticsSubscription(_close)

    def open_scope(
        self,
        *,
        owner_id: str,
        dispatcher: CompletionDispatcher | None = None,
    ) -> ExecutionScope:
        """Create an owner-lifetime task scope."""

        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.RUNTIME_CLOSED,
                    "execution runtime is closed",
                )
            scope = ExecutionScope(
                runtime=self,
                owner_id=owner_id,
                dispatcher=dispatcher or InlineDispatcher(),
            )
            self._scopes.add(scope)
        return scope

    def shutdown(self, *, wait: bool = False) -> None:
        """Cancel every scope and release runtime-owned backends."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            scopes = tuple(self._scopes)
            self._scopes.clear()
        for scope in scopes:
            scope.close(reason="runtime_shutdown")
        if not self._shutdown_backends:
            return
        for backend in self._backends:
            shutdown = getattr(backend, "shutdown", None)
            if callable(shutdown):
                shutdown(wait=wait)

    def _submit(
        self,
        handle: ExecutionHandle[TResult, TProgress],
        request: ExecutionRequest[TResult, TProgress],
    ) -> None:
        """Submit one handle to exactly one capable backend."""

        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.RUNTIME_CLOSED,
                    "execution runtime is closed",
                )
        backend = self._select_backend(request.requirements)
        job = ExecutionJob(
            task_id=handle.task_id,
            operation=request.operation,
            requirements=request.requirements,
            run=handle._execute,
            cancel_before_start=handle._cancel_before_start,
        )
        handle._bind_job(job)
        try:
            submission = backend.submit(job)
        except ExecutionRejected:
            raise
        except BaseException as error:
            raise ExecutionRejected(
                ExecutionRejectionReason.BACKEND_UNAVAILABLE,
                f"execution backend could not accept {request.operation}",
                details=(("error_type", type(error).__name__),),
            ) from error
        handle._bind_submission(submission)

    def _select_backend(
        self,
        requirements: ExecutionRequirements,
    ) -> ExecutionBackend:
        """Choose one backend before admission."""

        for backend in self._backends:
            if backend.supports(requirements):
                return backend
        raise ExecutionRejected(
            ExecutionRejectionReason.UNSUPPORTED_REQUIREMENTS,
            f"no backend supports resource {requirements.resource.value}",
            details=(("resource", requirements.resource.value),),
        )

    def _release_scope(self, scope: ExecutionScope) -> None:
        """Stop retaining one closed scope."""

        with self._lock:
            self._scopes.discard(scope)


__all__ = ["ExecutionRuntime"]
