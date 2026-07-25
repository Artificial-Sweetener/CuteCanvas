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
"""Define the small physical execution backend boundary."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from .model import ExecutionRequirements, ExecutionResource

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionBackendCapabilities:
    """Describe hard requirements a backend can safely honor."""

    resources: frozenset[ExecutionResource]
    stable_affinity: bool = False
    exclusive_resources: bool = False
    adoption_held_leases: bool = False

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether these capabilities satisfy one request."""

        if requirements.resource not in self.resources:
            return False
        if requirements.affinity_key is not None and not self.stable_affinity:
            return False
        if requirements.exclusive_key is not None and not self.exclusive_resources:
            return False
        return not (
            requirements.lease_release.value == "adoption_finished"
            and not self.adoption_held_leases
        )


class ExecutionJob:
    """Expose one guarded runtime-owned callable to a physical backend."""

    def __init__(
        self,
        *,
        task_id: uuid.UUID,
        operation: str,
        requirements: ExecutionRequirements,
        run: Callable[[], None],
        cancel_before_start: Callable[[str], None],
    ) -> None:
        """Store guarded lifecycle entry points for backend use."""

        self.task_id = task_id
        self.operation = operation
        self.requirements = requirements
        self._run_callback = run
        self._cancel_callback = cancel_before_start
        self._activated = False
        self._settled = False
        self._settled_callbacks: list[Callable[[], None]] = []
        self._lock = Lock()

    def run(self) -> bool:
        """Invoke work at most once and return whether this call activated it."""

        with self._lock:
            if self._activated:
                logger.error(
                    "Execution backend attempted duplicate job activation",
                    extra={
                        "task_id": str(self.task_id),
                        "operation": self.operation,
                    },
                )
                return False
            self._activated = True
        self._run_callback()
        return True

    def cancel_before_start(self, *, reason: str) -> bool:
        """Terminalize accepted work removed before activation."""

        if not reason.strip():
            raise ValueError("cancellation reason must not be blank")
        with self._lock:
            if self._activated:
                return False
            self._activated = True
        self._cancel_callback(reason)
        return True

    def add_settled_callback(self, callback: Callable[[], None]) -> None:
        """Observe runtime settlement for adoption-held resource release."""

        with self._lock:
            if self._settled:
                invoke_now = True
            else:
                invoke_now = False
                self._settled_callbacks.append(callback)
        if invoke_now:
            callback()

    def _mark_settled(self) -> None:
        """Notify backend leases after the public task terminalizes."""

        with self._lock:
            if self._settled:
                return
            self._settled = True
            callbacks = tuple(self._settled_callbacks)
            self._settled_callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception(
                    "Execution backend settlement callback failed",
                    extra={
                        "task_id": str(self.task_id),
                        "operation": self.operation,
                    },
                )


class BackendSubmission(Protocol):
    """Control one backend-accepted pending or running job."""

    def cancel(self, *, reason: str) -> bool:
        """Remove pending work and acknowledge cancellation when possible."""


class ExecutionBackend(Protocol):
    """Admit and physically execute public QPane jobs."""

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Return hard capabilities supported by this backend."""

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether the backend can honor one request."""

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Accept one job or raise structured rejection before acceptance."""


class ExecutionBackendLifecycle(Protocol):
    """Release an owned backend."""

    def shutdown(self, *, wait: bool = False) -> None:
        """Stop accepting work and account for accepted jobs."""


__all__ = [
    "BackendSubmission",
    "ExecutionBackend",
    "ExecutionBackendCapabilities",
    "ExecutionBackendLifecycle",
    "ExecutionJob",
]
