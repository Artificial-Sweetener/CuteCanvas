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
"""Own accepted tasks for one application object lifetime."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import TYPE_CHECKING, TypeVar

from .dispatch import CompletionDispatcher
from .handle import ExecutionHandle, as_object_handle
from .model import (
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
)

if TYPE_CHECKING:
    from .runtime import ExecutionRuntime

TResult = TypeVar("TResult")
TProgress = TypeVar("TProgress")


class ExecutionScope:
    """Track and cancel execution work for one owner."""

    def __init__(
        self,
        *,
        runtime: ExecutionRuntime,
        owner_id: str,
        dispatcher: CompletionDispatcher,
        parent: ExecutionScope | None = None,
        defer_on_saturation: bool = False,
    ) -> None:
        """Bind one owner lifetime to a runtime and dispatcher."""

        if not owner_id.strip():
            raise ValueError("owner_id must not be blank")
        self._runtime = runtime
        self._owner_id = owner_id
        self._dispatcher = dispatcher
        self._parent = parent
        self._defer_on_saturation = bool(defer_on_saturation)
        self._handles: set[ExecutionHandle[object, object]] = set()
        self._children: set[ExecutionScope] = set()
        self._closed = False
        self._lock = Lock()

    @property
    def owner_id(self) -> str:
        """Return the diagnostic owner identity."""

        return self._owner_id

    @property
    def is_closed(self) -> bool:
        """Return whether this scope rejects new work."""

        with self._lock:
            return self._closed

    @property
    def pending_count(self) -> int:
        """Return accepted tasks not yet settled."""

        with self._lock:
            return len(self._handles)

    def submit(
        self,
        request: ExecutionRequest[TResult, TProgress],
        *,
        adopt: Callable[[TResult], None] | None = None,
        progress: Callable[[TProgress], None] | None = None,
    ) -> ExecutionHandle[TResult, TProgress]:
        """Submit detached work and track it through settlement."""

        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SCOPE_CLOSED,
                    f"execution scope {self._owner_id} is closed",
                )
        handle = ExecutionHandle(
            request=request,
            dispatcher=self._dispatcher,
            adopt=adopt,
            progress=progress,
            released=self._release_handle,
        )
        object_handle = as_object_handle(handle)
        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SCOPE_CLOSED,
                    f"execution scope {self._owner_id} is closed",
                )
            self._handles.add(object_handle)
        try:
            self._runtime._submit(
                handle,
                request,
                defer_on_saturation=self._defer_on_saturation,
            )
        except BaseException:
            self._release_handle(handle)
            raise
        return handle

    def open_child(
        self,
        owner_id: str,
        *,
        dispatcher: CompletionDispatcher | None = None,
    ) -> ExecutionScope:
        """Create a child cancelled automatically with this scope."""

        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SCOPE_CLOSED,
                    f"execution scope {self._owner_id} is closed",
                )
            child = ExecutionScope(
                runtime=self._runtime,
                owner_id=owner_id,
                dispatcher=dispatcher or self._dispatcher,
                parent=self,
            )
            self._children.add(child)
        return child

    def open_finalization_scope(
        self,
        owner_id: str,
        *,
        dispatcher: CompletionDispatcher | None = None,
    ) -> ExecutionScope:
        """Create a runtime-owned scope that can outlive this owner.

        Backend saturation retains submitted finalizers until capacity returns.
        The caller closes the scope after finalization settles. Runtime
        shutdown remains the outer lifetime bound.
        """

        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SCOPE_CLOSED,
                    f"execution scope {self._owner_id} is closed",
                )
            return self._runtime._open_scope(
                owner_id=owner_id,
                dispatcher=dispatcher or self._dispatcher,
                defer_on_saturation=True,
            )

    def cancel_all(self, *, reason: str) -> None:
        """Request cancellation for every accepted task and child scope."""

        if not reason.strip():
            raise ValueError("cancellation reason must not be blank")
        with self._lock:
            handles = tuple(self._handles)
            children = tuple(self._children)
        for child in children:
            child.cancel_all(reason=reason)
        for handle in handles:
            handle.cancel(reason=reason)

    def close(self, *, reason: str) -> None:
        """Close this scope and cancel all owned work."""

        if not reason.strip():
            raise ValueError("close reason must not be blank")
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(self._handles)
            children = tuple(self._children)
            self._children.clear()
        for child in children:
            child.close(reason=reason)
        for handle in handles:
            handle.cancel(reason=reason)
        if self._parent is not None:
            self._parent._release_child(self)
        self._runtime._release_scope(self)

    def _release_handle(
        self,
        handle: ExecutionHandle[TResult, TProgress],
    ) -> None:
        """Stop retaining one terminal or rejected task."""

        object_handle = as_object_handle(handle)
        with self._lock:
            self._handles.discard(object_handle)

    def _release_child(self, child: ExecutionScope) -> None:
        """Stop retaining one closed child scope."""

        with self._lock:
            self._children.discard(child)


__all__ = ["ExecutionScope"]
