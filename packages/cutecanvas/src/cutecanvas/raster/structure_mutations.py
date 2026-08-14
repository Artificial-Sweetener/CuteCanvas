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
"""Asynchronous bounds and history ownership for editable color rasters."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from ..composition.edit_controller import CompositionEditController
from ..resources import ProjectResourceReference
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..scene.raster_mutations import RasterBoundsCompletion, RasterLayerState
from .assets import EditableRasterAssetStore
from .sparse_grid import SparseRasterSnapshot
from .structure_products import (
    RasterReframeProduct,
    build_raster_reframe,
)


@dataclass(frozen=True, slots=True)
class ColorRasterStructureEdit:
    """Retain one complete color-raster structure transition."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    before: SparseRasterSnapshot
    after: SparseRasterSnapshot

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene owning this transition."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return detached pixel bytes retained by both states."""
        return self.before.retained_bytes + self.after.retained_bytes


@dataclass(slots=True)
class _PendingColorBoundsRequest:
    """Track one typed reframe result until it is applied or rejected."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    is_current: Callable[[], bool]
    handle: ExecutionHandle[RasterReframeProduct, object] | None = None


class EditableRasterStructureMutationOwner:
    """Own editable-raster policy, asynchronous bounds, and structure history."""

    def __init__(
        self,
        assets: EditableRasterAssetStore,
        *,
        edits: CompositionEditController,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        changed: Callable[[], None],
        completed: Callable[[RasterBoundsCompletion], None],
    ) -> None:
        """Bind source storage, chronology, work scheduling, and presentation."""
        self._assets = assets
        self._edits = edits
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:raster-structure"
        )
        self._latest_requests = latest_requests
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingColorBoundsRequest] = {}
        self._closed = False

    def supports_layer(self, layer: LayerDescriptor) -> bool:
        """Return whether ``layer`` references an editable raster."""
        return self._asset(layer) is not None

    def state(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> RasterLayerState | None:
        """Return current raster storage state."""
        asset = self._asset(layer)
        if asset is None:
            return None
        content, structure = asset.surface.revisions()
        return RasterLayerState(
            scene.scene_id,
            layer.layer_id,
            asset.surface.bounds,
            asset.surface.extent_policy,
            content,
            structure,
            self._latest_requests.current_request_id(self._request_key(layer.layer_id)),
        )

    def set_extent_policy(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Replace source-owned write policy."""
        asset = self._asset(layer)
        if asset is None or not asset.surface.set_extent_policy(policy):
            return False
        self._changed()
        return True

    def request_bounds(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        is_current: Callable[[], bool],
    ) -> uuid.UUID | None:
        """Replace prior layer work and prepare reframed pixels off-thread."""
        source = layer.source
        if self._closed or not isinstance(source, ProjectResourceReference):
            return None
        asset = self._assets.get(source.resource_id)
        if asset is None:
            return None
        request_id = uuid.uuid4()
        self._replace_pending(layer.layer_id, request_id)
        if asset.surface.bounds == bounds:
            completion = RasterBoundsCompletion(
                request_id,
                scene.scene_id,
                layer.layer_id,
                True,
                "",
            )
            self._completed(completion)
            return request_id
        pending = _PendingColorBoundsRequest(
            request_id,
            scene.scene_id,
            layer.layer_id,
            source.resource_id,
            is_current,
        )
        self._pending[request_id] = pending
        key = self._request_key(layer.layer_id)
        if not self._latest_requests.claim(
            key,
            request_id,
            lambda message: self._cancel_pending(request_id, message),
        ):
            self._pending.pop(request_id, None)
            return request_id
        request = ExecutionRequest(
            operation="editor.raster.reframe",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
            ),
            work=lambda context: build_raster_reframe(
                asset.surface,
                bounds,
                context.cancellation,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda product: self._finish_request(request_id, product),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            self._latest_requests.release(key, request_id)
            completion = RasterBoundsCompletion(
                request_id,
                scene.scene_id,
                layer.layer_id,
                False,
                str(exc),
            )
            self._completed(completion)
            return request_id
        if self._pending.get(request_id) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle_request(request_id, handle, outcome)
        )
        self._changed()
        return request_id

    def shutdown(self) -> None:
        """Cancel pending work and publish terminal cancellation."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel_pending(request_id, "raster source detached")
        self._execution_scope.close(reason="raster_structure_owner_shutdown")

    def _finish_request(
        self,
        request_id: uuid.UUID,
        product: RasterReframeProduct,
    ) -> None:
        """Apply a current detached result and record one structure command."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        key = self._request_key(pending.layer_id)
        if not self._latest_requests.is_current(key, request_id):
            self._publish_completion(
                pending,
                request_id,
                False,
                "replaced by a newer bounds request",
            )
            return
        self._latest_requests.release(key, request_id)
        if self._closed:
            self._publish_completion(
                pending,
                request_id,
                False,
                "raster source detached",
            )
            return
        if not pending.is_current():
            self._publish_completion(
                pending,
                request_id,
                False,
                "raster layer is no longer current",
            )
            return
        asset = self._assets.get(pending.raster_id)
        if asset is None:
            self._publish_completion(
                pending,
                request_id,
                False,
                "raster source no longer exists",
            )
            return
        if asset.surface.revisions() != product.source_revisions:
            self._publish_completion(
                pending,
                request_id,
                False,
                "raster source changed while bounds were being prepared",
            )
            return
        before = product.source_snapshot
        asset.surface.replace_with_sparse_snapshot(product.result)
        self._edits.record_applied(
            ColorRasterStructureEdit(
                pending.scene_id,
                pending.layer_id,
                pending.raster_id,
                before,
                product.result,
            )
        )
        self._changed()
        self._publish_completion(pending, request_id, True, "")

    def _replace_pending(self, layer_id: uuid.UUID, replacement_id: uuid.UUID) -> None:
        """Cancel an older request for the same layer."""
        previous = self._latest_requests.current_request_id(self._request_key(layer_id))
        if previous is not None and previous != replacement_id:
            self._latest_requests.cancel(
                self._request_key(layer_id),
                reason="replaced by a newer bounds request",
            )

    def _cancel_pending(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel and complete one tracked request exactly once."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if pending.handle is not None:
            pending.handle.cancel(reason=message)
        self._latest_requests.release(
            self._request_key(pending.layer_id),
            request_id,
        )
        self._publish_completion(pending, request_id, False, message)

    def _settle_request(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[RasterReframeProduct, object],
        outcome: ExecutionOutcome[RasterReframeProduct],
    ) -> None:
        """Publish one failed or cancelled execution outcome."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(request_id, None)
        self._latest_requests.release(
            self._request_key(pending.layer_id),
            request_id,
        )
        message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        self._publish_completion(
            pending,
            request_id,
            False,
            message or "raster bounds request did not complete",
        )

    @staticmethod
    def _request_key(layer_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return the document-global replacement key for one raster layer."""
        return ("raster-structure", layer_id)

    def _publish_completion(
        self,
        pending: _PendingColorBoundsRequest,
        request_id: uuid.UUID,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one normalized terminal result."""
        self._completed(
            RasterBoundsCompletion(
                request_id,
                pending.scene_id,
                pending.layer_id,
                succeeded,
                message,
            )
        )

    def _asset(self, layer: LayerDescriptor):
        """Resolve the editable asset referenced by ``layer``."""
        source = layer.source
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )


class ColorRasterStructureHistoryOwner:
    """Replay raster structure edits independently of view request state."""

    def __init__(
        self,
        assets: EditableRasterAssetStore,
        changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind durable raster payloads and document invalidation."""
        self._assets = assets
        self._changed = changed

    def undo(self, command: object) -> bool:
        """Restore the earlier complete raster structure."""
        return self._restore(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore the later complete raster structure."""
        return self._restore(command, use_after=True)

    def _restore(self, command: object, *, use_after: bool) -> bool:
        """Restore one retained state through its durable source owner."""
        if not isinstance(command, ColorRasterStructureEdit):
            return False
        asset = self._assets.get(command.raster_id)
        if asset is None:
            return False
        asset.surface.replace_with_sparse_snapshot(
            command.after if use_after else command.before
        )
        self._changed(command.raster_id)
        return True
