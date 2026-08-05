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
"""Adapt pixel selections to the shared coverage-preview transaction owner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.execution import ExecutionScope
from qpane.sdk.scene import RasterBounds, SceneDescriptor

from cutecanvas.coverage import (
    CoverageDocument,
    CoverageEdgeModificationRequest,
    CoverageSnapshot,
)
from cutecanvas.runtime.coverage_modification_preview import (
    CoverageModificationPreviewCoordinator,
    CoverageModificationPreviewResult,
)
from cutecanvas.runtime.latest_requests import DocumentLatestRequestRegistry
from cutecanvas.scene.canvas_bounds import scene_raster_bounds
from cutecanvas.types import LayerEdgeOperation, PixelSelectionModificationResult

from .service import PixelSelectionService


@dataclass(slots=True)
class _PixelSelectionPreviewTarget:
    """Expose one immutable selection base through the shared preview contract."""

    scene_id: uuid.UUID
    base_document: CoverageDocument | None
    base_coverage: CoverageSnapshot
    canvas_bounds: RasterBounds
    preview_revision: int
    active_scene: Callable[[], SceneDescriptor | None]
    selections: PixelSelectionService

    @property
    def coverage(self) -> CoverageSnapshot:
        """Return the selection coverage captured when editing began."""

        return self.base_coverage

    def build_request(
        self,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> CoverageEdgeModificationRequest:
        """Build one canvas-constrained edit from the original selection."""

        return CoverageEdgeModificationRequest(
            self.base_coverage,
            operation,
            radius,
            self.canvas_bounds,
        )

    def is_current(self) -> bool:
        """Return whether current selection state still belongs to this session."""

        scene = self.active_scene()
        return bool(
            scene is not None
            and scene.scene_id == self.scene_id
            and self.selections.state(self.scene_id).revision == self.preview_revision
        )

    def present(
        self,
        session_id: uuid.UUID,
        generation: int,
        product: CoverageSnapshot | None,
    ) -> bool:
        """Replace visible selection state without recording history."""

        del session_id, generation
        changed = self.selections.preview_coverage(
            self.scene_id,
            product,
            expected_revision=self.preview_revision,
        )
        if changed:
            self.preview_revision = self.selections.state(self.scene_id).revision
            return True
        current = self.selections.state(self.scene_id).coverage
        return _coverage_equal(current, product)

    def commit(self, product: CoverageSnapshot | None) -> bool:
        """Record the visible transition exactly once in selection history."""

        del product
        return self.selections.record_preview(self.scene_id, self.base_document)

    def discard(self, session_id: uuid.UUID) -> None:
        """Restore the original selection only while this session owns state."""

        del session_id
        if not self.is_current():
            return
        self.selections.preview_document(
            self.scene_id,
            self.base_document,
            coverage=self.base_coverage,
        )
        self.preview_revision = self.selections.state(self.scene_id).revision

    def release(self, session_id: uuid.UUID) -> None:
        """Retain settled visible selection after history adoption."""

        del session_id

    def diagnostic_context(self) -> str:
        """Describe the addressed selection for structured failure logs."""

        return f"scene={self.scene_id}"


class PixelSelectionModificationCoordinator:
    """Resolve active selections around the shared preview lifecycle owner."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        selections: PixelSelectionService,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        completed: Callable[[PixelSelectionModificationResult], None],
    ) -> None:
        """Bind selection capture and public results around the shared engine."""

        self._active_scene = active_scene
        self._selections = selections
        self._completed = completed
        self._sessions = CoverageModificationPreviewCoordinator(
            owner_id="pixel-selection-modification",
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            completed=self._publish,
        )

    def begin(self) -> uuid.UUID | None:
        """Capture the active selection as one immutable preview base."""

        scene = self._active_scene()
        if scene is None:
            return None
        canvas_bounds = scene_raster_bounds(scene)
        state = self._selections.state(scene.scene_id)
        if canvas_bounds is None or state.coverage is None:
            return None
        self.cancel_all("replaced by a newer document request", publish_pending=True)
        return self._sessions.begin(
            _PixelSelectionPreviewTarget(
                scene.scene_id,
                self._selections.document(scene.scene_id),
                state.coverage,
                canvas_bounds,
                state.revision,
                self._active_scene,
                self._selections,
            )
        )

    def update(
        self,
        session_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Replace the preview using the captured original selection."""

        return self._sessions.update(session_id, operation, radius)

    def settle(self, session_id: uuid.UUID) -> bool:
        """Commit the current latest preview once it is ready."""

        return self._sessions.settle(session_id)

    def cancel(self, session_id: uuid.UUID) -> bool:
        """Restore the captured selection without recording history."""

        return self._sessions.cancel(session_id)

    def cancel_all(self, reason: str, *, publish_pending: bool = False) -> None:
        """Cancel all sessions and optionally report unresolved requests."""

        self._sessions.cancel_all(reason, publish_pending=publish_pending)

    def request(
        self,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Submit one one-shot edit through the same preview transaction path."""

        session_id = self.begin()
        if session_id is None:
            return None
        request_id = self.update(session_id, operation, radius)
        if request_id is None:
            self.cancel(session_id)
            return None
        self.settle(session_id)
        return request_id

    def shutdown(self) -> None:
        """Close the shared lifecycle owned by selection editing."""

        self._sessions.shutdown("selection modifier shut down")

    def _publish(self, result: CoverageModificationPreviewResult) -> None:
        """Translate one source-neutral result into the public selection result."""

        target = result.target
        if not isinstance(target, _PixelSelectionPreviewTarget):
            return
        self._completed(
            PixelSelectionModificationResult(
                result.request_id,
                target.scene_id,
                result.operation,
                result.succeeded,
                _selection_message(result.message),
            )
        )


def _selection_message(message: str) -> str:
    """Translate shared lifecycle wording to public selection vocabulary."""

    return {
        "coverage target changed during filtering": (
            "pixel selection changed during filtering"
        ),
        "coverage target rejected preview product": (
            "pixel selection changed during filtering"
        ),
        "coverage modification produced no change": (
            "selection modification produced no change"
        ),
    }.get(message, message)


def _coverage_equal(
    left: CoverageSnapshot | None,
    right: CoverageSnapshot | None,
) -> bool:
    """Return whether optional snapshots describe identical selection coverage."""

    import numpy as np

    if left is None or right is None:
        return left is right
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )


__all__ = ["PixelSelectionModificationCoordinator"]
