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
"""Asynchronous placed-source conversion to editable raster layers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
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

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..raster.assets import EditableRasterAssetStore
from ..resources import ProjectResourceReference
from ..resources.rasterization import (
    LayerRasterizationCompletion,
    retarget_raster_transform,
)
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from .raster_product import rasterize_placed_image
from .store import PlacedAssetStore
from .workflow import PlacedAssetCompletion

_MAX_RASTERIZATION_BYTES = 512 * 1024 * 1024


@dataclass(slots=True)
class _PendingRasterization:
    """Retain one exact source instance and submitted worker."""

    composition_id: uuid.UUID
    history_scope_id: uuid.UUID
    public_scene_id: uuid.UUID
    layer: CompositionLayerInstance
    source_size: QSize
    handle: ExecutionHandle[QImage, object] | None = None


class PlacedAssetRasterizationService:
    """Coordinate raster render work and one atomic source-instance swap."""

    def __init__(
        self,
        *,
        placed_assets: PlacedAssetStore,
        raster_assets: EditableRasterAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[PlacedAssetCompletion], None],
        resource_completed: Callable[[LayerRasterizationCompletion], None],
    ) -> None:
        """Bind source, instance, worker, and publication owners."""
        self._placed_assets = placed_assets
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:placed-rasterization"
        )
        self._latest_requests = latest_requests
        self._changed = changed
        self._completed = completed
        self._resource_completed = resource_completed
        self._pending: dict[uuid.UUID, _PendingRasterization] = {}
        self._closed = False

    def request(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin one explicit rasterization after validating its allocation."""
        if self._closed:
            return None
        layer = self._layers.layer(composition_id, layer_id)
        source = None if layer is None else layer.source
        if layer is None or not isinstance(source, ProjectResourceReference):
            return None
        snapshot = self._placed_assets.get(source.resource_id)
        if snapshot is None:
            return None
        if snapshot.image is None:
            return None
        source_size = snapshot.source_size
        target_size = QSize(source_size if pixel_size is None else pixel_size)
        if target_size.isEmpty():
            raise ValueError("pixel_size must have positive dimensions")
        byte_count = target_size.width() * target_size.height() * 4
        if byte_count > _MAX_RASTERIZATION_BYTES:
            raise ValueError("rasterization exceeds the 512 MiB output limit")
        request_id = uuid.uuid4()
        pending = _PendingRasterization(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            source_size,
        )
        self._pending[request_id] = pending
        key = self._request_key(layer_id)
        if not self._latest_requests.claim(
            key,
            request_id,
            lambda message: self._cancel(request_id, message),
        ):
            self._pending.pop(request_id, None)
            return None
        source_image = snapshot.image
        request = ExecutionRequest(
            operation="editor.placed.rasterize",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=byte_count,
            ),
            work=lambda context: rasterize_placed_image(
                source_image,
                target_size,
                context.cancellation,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda image: self._finish(request_id, image),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            self._latest_requests.release(key, request_id)
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    composition_id,
                    layer_id,
                    False,
                    str(exc),
                )
            )
            self._resource_completed(
                LayerRasterizationCompletion(
                    request_id,
                    public_scene_id,
                    layer_id,
                    False,
                    str(exc),
                )
            )
            return request_id
        if self._pending.get(request_id) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle(request_id, handle, outcome)
        )
        return request_id

    def shutdown(self) -> None:
        """Cancel pending rasterizations and suppress later publications."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "placed asset service detached")
        self._execution_scope.close(reason="placed_rasterization_shutdown")

    def _finish(self, request_id: uuid.UUID, result: QImage) -> None:
        """Install one current output as an editable source atomically."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        layer_id = pending.layer.layer_id
        key = self._request_key(layer_id)
        if self._closed:
            self._latest_requests.release(key, request_id)
            self._publish(
                pending,
                request_id,
                False,
                "placed asset service detached",
            )
            return
        if not self._latest_requests.is_current(key, request_id):
            self._publish(
                pending,
                request_id,
                False,
                "replaced by a newer rasterization request",
            )
            return
        self._latest_requests.release(key, request_id)
        current = self._layers.layer(pending.composition_id, layer_id)
        if current != pending.layer:
            self._publish(
                pending, request_id, False, "layer changed during rasterization"
            )
            return
        if result.isNull():
            self._publish(pending, request_id, False, "rasterization produced no image")
            return
        raster = self._raster_assets.create(result)
        replacement = replace(
            pending.layer,
            source=ProjectResourceReference(raster.raster_id),
            transform=retarget_raster_transform(
                pending.layer.transform,
                pending.source_size,
                result.size(),
            ),
            role="raster",
        )
        if not self._layer_edits.replace_instance(
            pending.composition_id,
            replacement,
            history_scope_id=pending.history_scope_id,
        ):
            self._raster_assets.remove(raster.raster_id)
            self._publish(pending, request_id, False, "layer is no longer current")
            return
        self._changed(pending.composition_id)
        self._publish(pending, request_id, True, "")

    def _settle(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[QImage, object],
        outcome: ExecutionOutcome[QImage],
    ) -> None:
        """Publish execution failure or cancellation once."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(request_id, None)
        self._latest_requests.release(
            self._request_key(pending.layer.layer_id),
            request_id,
        )
        message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        self._publish(pending, request_id, False, message or "rasterization failed")

    def _cancel_layer(self, layer_id: uuid.UUID, message: str) -> None:
        """Cancel the current request for one layer."""
        self._latest_requests.cancel(self._request_key(layer_id), reason=message)

    def _cancel(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel one submitted worker and publish exactly one outcome."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if pending.handle is not None:
            pending.handle.cancel(reason=message)
        self._latest_requests.release(
            self._request_key(pending.layer.layer_id),
            request_id,
        )
        self._publish(pending, request_id, False, message)

    @staticmethod
    def _request_key(layer_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return the document-global replacement key for one layer."""
        return ("placed-rasterization", layer_id)

    def _publish(
        self,
        pending: _PendingRasterization,
        request_id: uuid.UUID,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one normalized rasterization completion."""
        self._completed(
            PlacedAssetCompletion(
                request_id,
                pending.composition_id,
                pending.layer.layer_id,
                succeeded,
                message,
            )
        )
        self._resource_completed(
            LayerRasterizationCompletion(
                request_id,
                pending.public_scene_id,
                pending.layer.layer_id,
                succeeded,
                message,
            )
        )
