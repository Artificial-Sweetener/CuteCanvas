#    CuteCanvas - High-performance layered image editor
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
"""Asynchronous, stale-safe paint-bucket interaction coordination."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)

from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from cutecanvas.painting import PaintingCoordinator, PaintTargetContext
from cutecanvas.selection import LayerCoverageProjector, PixelSelectionService

from .flood import FloodFillRequest
from .worker import FloodFillWorker


@dataclass(slots=True)
class _PendingFill:
    """Retain one submitted target revision until terminal publication."""

    context: PaintTargetContext
    source_revision: object
    mode: CoverageCombineMode
    worker: FloodFillWorker
    handle: TaskHandle


class PaintBucketCoordinator:
    """Own cancellation, constraints, and atomic publication for bucket fills."""

    def __init__(
        self,
        *,
        painting: PaintingCoordinator,
        selections: PixelSelectionService,
        executor: TaskExecutorProtocol,
        changed: Callable[[bool], None] | None = None,
    ) -> None:
        """Bind the shared target, selection, and task owners."""
        self._painting = painting
        self._selections = selections
        self._executor = executor
        self._changed = changed
        self._projector = LayerCoverageProjector()
        self._pending: _PendingFill | None = None
        self._tolerance = 32
        self._contiguous = True
        self._antialias = True

    @property
    def busy(self) -> bool:
        """Return whether one current fill request is unresolved."""
        return self._pending is not None

    @property
    def can_fill(self) -> bool:
        """Return whether the active target supplies a flood-fill sample."""
        return self._painting.can_flood_fill()

    @property
    def options(self) -> tuple[int, bool, bool]:
        """Return tolerance, contiguous, and antialias settings."""
        return self._tolerance, self._contiguous, self._antialias

    def configure(
        self,
        *,
        tolerance: int | None = None,
        contiguous: bool | None = None,
        antialias: bool | None = None,
    ) -> bool:
        """Update subsequent fill behavior without disturbing active work."""
        next_tolerance = self._tolerance if tolerance is None else int(tolerance)
        if not 0 <= next_tolerance <= 255:
            raise ValueError("paint-bucket tolerance must be between 0 and 255")
        next_contiguous = self._contiguous if contiguous is None else bool(contiguous)
        next_antialias = self._antialias if antialias is None else bool(antialias)
        values = (next_tolerance, next_contiguous, next_antialias)
        if values == self.options:
            return False
        self._tolerance, self._contiguous, self._antialias = values
        return True

    def request(
        self,
        point: QPointF,
        *,
        tolerance: int | None = None,
        contiguous: bool | None = None,
        antialias: bool | None = None,
        mode: CoverageCombineMode = CoverageCombineMode.ADD,
    ) -> bool:
        """Submit one target-local bucket request without blocking input."""
        resolved = self._painting.flood_fill_source()
        if resolved is None:
            return False
        context, source = resolved
        self.cancel()
        constraint = self._target_constraint(context)
        request = FloodFillRequest(
            source.pixels,
            source.bounds,
            round(point.x()),
            round(point.y()),
            self._tolerance if tolerance is None else tolerance,
            self._contiguous if contiguous is None else contiguous,
            self._antialias if antialias is None else antialias,
            constraint,
        )
        request_id = uuid.uuid4()
        worker = FloodFillWorker(request_id, request)
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="paint_bucket")
        except TaskRejected:
            worker.deleteLater()
            return False
        self._pending = _PendingFill(
            context,
            source.revision,
            CoverageCombineMode(mode),
            worker,
            handle,
        )
        return True

    def cancel(self) -> bool:
        """Cancel one pending request and reject any late result."""
        pending = self._pending
        if pending is None:
            return False
        self._pending = None
        pending.worker.cancel()
        self._executor.cancel(pending.handle)
        return True

    def shutdown(self) -> None:
        """Cancel pending work before editor teardown."""
        self.cancel()

    def _finish(self, worker: FloodFillWorker) -> None:
        """Commit one current successful result and reject stale completion."""
        pending = self._pending
        if pending is None or pending.worker is not worker:
            worker.deleteLater()
            return
        self._pending = None
        result = worker.result
        changed = bool(
            worker.error_message is None
            and result is not None
            and self._painting.commit_flood_fill(
                pending.context,
                result,
                pending.mode,
                pending.source_revision,
            )
        )
        worker.deleteLater()
        if self._changed is not None:
            self._changed(changed)

    def _target_constraint(
        self,
        context: PaintTargetContext,
    ) -> CoverageSnapshot | None:
        """Project active scene selection into the sampled target coordinates."""
        selection = self._selections.state(context.scene.scene_id).coverage
        layer = context.layer
        if selection is None or layer is None or layer.transform is None:
            return selection
        inverse = layer.transform.inverted()
        return None if inverse is None else self._projector.project(selection, inverse)
