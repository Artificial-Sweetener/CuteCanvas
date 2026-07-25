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
"""Mask-source implementation of generic raster structure mutations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRect
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

from cutecanvas.coverage import CoverageSurface
from cutecanvas.types import RasterExtentPolicy

from ..raster.structure_products import (
    RasterReframeProduct,
    build_sparse_reframe,
)
from ..resources import ProjectResourceReference
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..scene.raster_mutations import RasterBoundsCompletion, RasterLayerState
from .edit_service import MaskEditService
from .mask import MaskAssetStore
from .render_cache import MaskRenderCache


@dataclass(slots=True)
class _PendingBoundsRequest:
    """Track one submitted worker and the scene identity it must still match."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    mask_id: uuid.UUID
    is_current: Callable[[], bool]
    handle: ExecutionHandle[RasterReframeProduct, object] | None = None


class MaskRasterMutationOwner:
    """Own mask extent policy and asynchronous local storage reframing."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        edits: MaskEditService,
        renders: MaskRenderCache,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        mask_changed: Callable[[uuid.UUID, QRect], None],
        undo_changed: Callable[[uuid.UUID], None],
        scene_changed: Callable[[], None],
        completed: Callable[[RasterBoundsCompletion], None],
    ) -> None:
        """Bind authoritative mask collaborators and generic result callbacks."""
        self._assets = assets
        self._edits = edits
        self._renders = renders
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:mask-structure"
        )
        self._latest_requests = latest_requests
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed
        self._scene_changed = scene_changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingBoundsRequest] = {}
        self._closed = False

    def supports_layer(self, layer: LayerDescriptor) -> bool:
        """Return True for mask-backed raster descriptors."""
        return (
            isinstance(layer.source, ProjectResourceReference)
            and self._assets.get_layer(layer.source.resource_id) is not None
        )

    def state(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> RasterLayerState | None:
        """Return current mask surface state for a resolved layer instance."""
        surface = self._surface_for(layer)
        if surface is None or surface.bounds is None:
            return None
        content_revision, structure_revision = surface.revisions()
        return RasterLayerState(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            bounds=surface.bounds,
            extent_policy=surface.extent_policy,
            content_revision=content_revision,
            structure_revision=structure_revision,
            pending_request_id=self._latest_requests.current_request_id(
                self._request_key(layer.layer_id)
            ),
        )

    def set_extent_policy(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Set mask write policy without touching pixels, bounds, or transform."""
        surface = self._surface_for(layer)
        if surface is None or not surface.set_extent_policy(policy):
            return False
        self._scene_changed()
        return True

    def request_bounds(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        is_current: Callable[[], bool],
    ) -> uuid.UUID | None:
        """Replace prior work for this layer and submit one off-thread reframe."""
        if self._closed or not isinstance(layer.source, ProjectResourceReference):
            return None
        surface = self._assets.get_surface(layer.source.resource_id)
        if surface is None:
            return None
        request_id = uuid.uuid4()
        self._replace_pending(layer.layer_id, request_id)
        if surface.bounds == bounds:
            completion = RasterBoundsCompletion(
                request_id,
                scene.scene_id,
                layer.layer_id,
                True,
                "",
            )
            self._completed(completion)
            return request_id
        pending = _PendingBoundsRequest(
            request_id=request_id,
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            mask_id=layer.source.resource_id,
            is_current=is_current,
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
        request = ExecutionRequest[RasterReframeProduct, object](
            operation="editor.mask.reframe",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
            ),
            work=lambda context: build_sparse_reframe(
                surface.versioned_state_snapshot,
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
        self._scene_changed()
        return request_id

    def shutdown(self) -> None:
        """Cancel pending reframes and publish terminal cancellation results."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel_pending(request_id, "raster source detached")
        self._execution_scope.close(reason="mask_raster_mutation_shutdown")

    def _surface_for(self, layer: LayerDescriptor) -> CoverageSurface | None:
        """Resolve authoritative storage from one supported descriptor."""
        if not isinstance(layer.source, ProjectResourceReference):
            return None
        return self._assets.get_surface(layer.source.resource_id)

    def _replace_pending(
        self,
        layer_id: uuid.UUID,
        replacement_id: uuid.UUID,
    ) -> None:
        """Cancel an older request for ``layer_id`` before accepting a replacement."""
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
        self._completed(
            RasterBoundsCompletion(
                request_id,
                pending.scene_id,
                pending.layer_id,
                False,
                message,
            )
        )

    def _finish_request(
        self,
        request_id: uuid.UUID,
        product: RasterReframeProduct,
    ) -> None:
        """Apply a current detached result on the Qt thread and record history."""
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
        surface = self._assets.get_surface(pending.mask_id)
        if surface is None:
            self._publish_completion(
                pending, request_id, False, "raster source no longer exists"
            )
            return
        if surface.revisions() != product.source_revisions:
            self._publish_completion(
                pending,
                request_id,
                False,
                "raster source changed while bounds were being prepared",
            )
            return
        before = product.source_snapshot
        after = product.result
        surface.replace_with_state_snapshot(after)
        if self._assets.record_applied_surface(pending.mask_id, before, after):
            self._undo_changed(pending.mask_id)
        layer = self._assets.get_layer(pending.mask_id)
        if layer is not None:
            self._renders.invalidate_layer(layer)
        self._edits.advance_epoch(pending.mask_id, reason="raster_bounds_changed")
        self._mask_changed(pending.mask_id, QRect())
        self._scene_changed()
        self._publish_completion(pending, request_id, True, "")

    def _settle_request(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[RasterReframeProduct, object],
        outcome: ExecutionOutcome[RasterReframeProduct],
    ) -> None:
        """Publish a failed or cancelled mask reframe exactly once."""
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
            message or "mask bounds request did not complete",
        )

    def _publish_completion(
        self,
        pending: _PendingBoundsRequest,
        request_id: uuid.UUID,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish a normalized generic completion payload."""
        self._completed(
            RasterBoundsCompletion(
                request_id,
                pending.scene_id,
                pending.layer_id,
                succeeded,
                message,
            )
        )

    @staticmethod
    def _request_key(layer_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return the document-global replacement key for one mask layer."""
        return ("mask-structure", layer_id)
