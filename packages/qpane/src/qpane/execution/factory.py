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
"""Assemble QPane's opinionated standalone execution runtime."""

from __future__ import annotations

from .affinity_backend import AffinityExecutionBackend
from .default_backend import DefaultExecutionBackend
from .default_policy import DefaultExecutionPolicy
from .runtime import ExecutionRuntime


def create_default_execution_runtime(
    policy: DefaultExecutionPolicy | None = None,
) -> ExecutionRuntime:
    """Create an owned bounded runtime for standalone viewer/editor use."""

    return ExecutionRuntime(
        DefaultExecutionBackend(policy),
        capability_backends=(AffinityExecutionBackend(),),
        shutdown_backends=True,
    )


def create_native_execution_runtime(*, max_accepted: int = 32) -> ExecutionRuntime:
    """Create an owned runtime dedicated to stable native-affinity work."""
    return ExecutionRuntime(
        AffinityExecutionBackend(max_accepted=max_accepted),
        shutdown_backends=True,
    )


__all__ = [
    "create_default_execution_runtime",
    "create_native_execution_runtime",
]
