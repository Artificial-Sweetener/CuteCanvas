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
"""Adapt whole-layer coverage edits to the shared preview transaction owner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.execution import ExecutionScope
from qpane.sdk.scene import SceneDescriptor

from cutecanvas.coverage import CoverageEdgeModificationRequest, CoverageSnapshot
from cutecanvas.coverage.spatial_constraint import CoverageSpatialConstraint
from cutecanvas.runtime.coverage_modification_contracts import (
    CoverageModificationPreviewResult,
)
from cutecanvas.runtime.coverage_modification_preview import (
    CoverageModificationPreviewCoordinator,
)
from cutecanvas.runtime.latest_requests import DocumentLatestRequestRegistry
from cutecanvas.scene.layer_edge_preview import LayerEdgePreviewStore
from cutecanvas.types import LayerEdgeModificationResult, LayerEdgeOperation

from .layer_edge_targets import LayerEdgeEditRegistry, ResolvedLayerEdgeTarget


@dataclass(slots=True)
class _LayerEdgePreviewTarget:
    """Expose one captured layer through the source-neutral preview contract."""

    resolved: ResolvedLayerEdgeTarget
    previews: LayerEdgePreviewStore
    preview_changed: Callable[[], None]

    @property
    def coverage(self) -> CoverageSnapshot:
        """Return the layer coverage captured when editing began."""

        return self.resolved.snapshot.coverage

    @property
    def spatial_constraint(self) -> CoverageSpatialConstraint:
        """Return the mandatory aperture captured with the layer revision."""

        return self.resolved.snapshot.spatial_constraint

    def build_request(
        self,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> CoverageEdgeModificationRequest:
        """Build a constrained detached edit from captured layer coverage."""

        snapshot = self.resolved.snapshot
        return CoverageEdgeModificationRequest(
            coverage=snapshot.coverage,
            operation=operation,
            radius=radius,
            spatial_constraint=snapshot.spatial_constraint,
        )

    def is_current(self) -> bool:
        """Return whether the captured layer revision is still authoritative."""

        return self.resolved.owner.is_current(self.resolved.snapshot)

    def present(
        self,
        session_id: uuid.UUID,
        generation: int,
        product: CoverageSnapshot | None,
    ) -> bool:
        """Publish transient coverage through the shared layer renderer."""

        snapshot = self.resolved.snapshot
        self.previews.publish(
            session_id=session_id,
            scene_id=snapshot.scene_id,
            layer_id=snapshot.layer_id,
            generation=generation,
            before=snapshot.coverage,
            after=product,
        )
        self.preview_changed()
        return True

    def commit(self, product: CoverageSnapshot | None) -> bool:
        """Commit once through the layer-family history owner."""

        return self.resolved.owner.commit(self.resolved.snapshot, product)

    def discard(self, session_id: uuid.UUID) -> None:
        """Remove transient layer presentation without changing durable content."""

        self._clear_preview(session_id)

    def release(self, session_id: uuid.UUID) -> None:
        """Remove transient presentation after durable adoption."""

        self._clear_preview(session_id)

    def diagnostic_context(self) -> str:
        """Describe the addressed layer for structured failure logs."""

        snapshot = self.resolved.snapshot
        return f"scene={snapshot.scene_id}, layer={snapshot.layer_id}"

    def _clear_preview(self, session_id: uuid.UUID) -> None:
        """Clear one owned transient and publish only observable changes."""

        if self.previews.clear(session_id):
            self.preview_changed()


class LayerEdgeModificationCoordinator:
    """Resolve layer targets while delegating preview lifecycle to one shared owner."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        targets: LayerEdgeEditRegistry,
        previews: LayerEdgePreviewStore,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        preview_changed: Callable[[], None],
        completed: Callable[[LayerEdgeModificationResult], None],
    ) -> None:
        """Bind layer resolution and result publication around the shared engine."""

        self._active_scene = active_scene
        self._targets = targets
        self._previews = previews
        self._preview_changed = preview_changed
        self._completed = completed
        self._sessions = CoverageModificationPreviewCoordinator(
            owner_id="layer-edge-modification",
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            completed=self._publish,
        )

    def begin(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> uuid.UUID | None:
        """Capture one editable layer and begin a replaceable preview session."""

        scene = self._active_scene()
        if scene is None or scene.scene_id != scene_id:
            return None
        resolved = self._targets.resolve(scene, layer_id)
        if resolved is None:
            return None
        self.cancel_all("replaced by a new layer edge session")
        return self._sessions.begin(
            _LayerEdgePreviewTarget(
                resolved,
                self._previews,
                self._preview_changed,
            )
        )

    def update(
        self,
        session_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Replace the latest preview from the captured layer base."""

        return self._sessions.update(session_id, operation, radius)

    def settle(self, session_id: uuid.UUID) -> bool:
        """Commit the current latest preview once it is ready."""

        return self._sessions.settle(session_id)

    def cancel(self, session_id: uuid.UUID) -> bool:
        """Discard one layer preview without changing durable content."""

        return self._sessions.cancel(session_id)

    def cancel_all(self, reason: str) -> None:
        """Discard all layer sessions for a context change."""

        self._sessions.cancel_all(reason)

    def request(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Submit a one-shot edit through the same preview transaction path."""

        session_id = self.begin(scene_id, layer_id)
        if session_id is None:
            return None
        request_id = self.update(session_id, operation, radius)
        if request_id is None:
            self.cancel(session_id)
            return None
        self.settle(session_id)
        return request_id

    def shutdown(self) -> None:
        """Close the shared lifecycle owned by layer editing."""

        self._sessions.shutdown("layer edge coordinator shut down")

    def _publish(self, result: CoverageModificationPreviewResult) -> None:
        """Translate one source-neutral result into the public layer result."""

        target = result.target
        if not isinstance(target, _LayerEdgePreviewTarget):
            return
        snapshot = target.resolved.snapshot
        message = _layer_message(result.message)
        self._completed(
            LayerEdgeModificationResult(
                result.request_id,
                result.session_id,
                snapshot.scene_id,
                snapshot.layer_id,
                result.operation,
                result.succeeded,
                message,
            )
        )


def _layer_message(message: str) -> str:
    """Translate shared lifecycle wording to the public layer vocabulary."""

    return {
        "coverage target changed during filtering": "layer changed during filtering",
        "coverage target rejected preview product": "layer rejected preview product",
        "coverage product escaped spatial constraint": (
            "layer product escaped canvas aperture"
        ),
        "coverage modification produced no change": (
            "layer edge modification produced no change"
        ),
    }.get(message, message)


__all__ = ["LayerEdgeModificationCoordinator"]
