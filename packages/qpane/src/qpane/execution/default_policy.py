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
"""Configure QPane's owned bounded execution backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .model import ExecutionResource, ExecutionUrgency

_MEBIBYTE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class DefaultExecutionPolicy:
    """Configure standalone worker, admission, fairness, and resource limits."""

    max_workers: int = field(
        default_factory=lambda: min(8, max(2, os.cpu_count() or 2))
    )
    max_accepted: int = 256
    max_retained_bytes: int = 512 * _MEBIBYTE
    aging_interval_seconds: float = 0.25
    resource_limits: tuple[tuple[ExecutionResource, int], ...] = (
        (ExecutionResource.BLOCKING_IO, 4),
        (ExecutionResource.PYTHON_CPU, 2),
        (ExecutionResource.NATIVE_CPU, 4),
        (ExecutionResource.DEVICE, 1),
    )
    reserve_interactive_worker: bool = True

    def __post_init__(self) -> None:
        """Reject policies that could not form a bounded scheduler."""

        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if self.max_accepted <= 0:
            raise ValueError("max_accepted must be positive")
        if self.max_retained_bytes <= 0:
            raise ValueError("max_retained_bytes must be positive")
        if self.aging_interval_seconds <= 0:
            raise ValueError("aging_interval_seconds must be positive")
        seen: set[ExecutionResource] = set()
        for resource, limit in self.resource_limits:
            if resource in seen:
                raise ValueError(f"duplicate resource limit: {resource.value}")
            if limit <= 0:
                raise ValueError("resource limits must be positive")
            seen.add(resource)

    def resource_limit(self, resource: ExecutionResource) -> int:
        """Return concurrency allowed for one resource class."""

        for candidate, limit in self.resource_limits:
            if candidate == resource:
                return limit
        return self.max_workers

    @property
    def noninteractive_worker_limit(self) -> int:
        """Return capacity available without consuming the input-response lane."""

        if self.reserve_interactive_worker and self.max_workers > 1:
            return self.max_workers - 1
        return self.max_workers


_URGENCY_RANKS = {
    ExecutionUrgency.INTERACTIVE: 0,
    ExecutionUrgency.FOREGROUND: 10,
    ExecutionUrgency.BACKGROUND: 20,
    ExecutionUrgency.OPPORTUNISTIC: 30,
    ExecutionUrgency.MAINTENANCE: 40,
}


def urgency_rank(urgency: ExecutionUrgency) -> int:
    """Return the initial scheduler rank for semantic urgency."""

    return _URGENCY_RANKS[urgency]


__all__ = ["DefaultExecutionPolicy"]
