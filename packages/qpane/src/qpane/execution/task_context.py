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
"""Provide worker-facing cancellation and progress access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .cancellation import CancellationToken
from .progress import ExecutionProgressReporter

TProgress = TypeVar("TProgress")


@dataclass(frozen=True, slots=True)
class ExecutionTaskContext(Generic[TProgress]):
    """Expose only task-local collaborators to worker code."""

    cancellation: CancellationToken
    progress: ExecutionProgressReporter[TProgress] | None = None

    def report_progress(self, value: TProgress) -> bool:
        """Publish progress when an observer is installed."""

        if self.progress is None:
            return False
        return self.progress.report(value)


__all__ = ["ExecutionTaskContext"]
