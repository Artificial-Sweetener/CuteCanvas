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
"""Asynchronous nested-document conversion to editable raster content."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QRectF, QSize
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
from qpane.sdk.rendering import RegionSampleSource, rasterize_region

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..raster.assets import EditableRasterAssetStore
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from .model import ProjectResourceKind, ProjectResourceReference
from .rasterization import (
    LayerRasterizationCompletion,
    retarget_raster_transform,
)
from .source_capabilities import ProjectResourceSourceCapabilities
from .store import ProjectResourceStore

_MAX_OUTPUT_BYTES = 512 * 1024 * 1024


@dataclass(slots=True)
class _PendingCompositionRasterization:
    """Retain exact nested source and layer state until worker completion."""

    composition_id: uuid.UUID
    history_scope_id: uuid.UUID
    public_scene_id: uuid.UUID
    layer: CompositionLayerInstance
    source_size: QSize
    handle: ExecutionHandle[QImage, object] | None = None


class CompositionResourceRasterizationService:
    """Sample nested compositions and atomically replace their layer instance."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        capabilities: ProjectResourceSourceCapabilities,
        raster_assets: EditableRasterAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[LayerRasterizationCompletion], None],
    ) -> None:
        """Bind resource sampling, editable payload, history, and task owners."""
        self._resources = resources
        self._capabilities = capabilities
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:composition-rasterization"
        )
        self._latest_requests = latest_requests
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingCompositionRasterization] = {}
        self._closed = False

    def request(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin a bounded rasterization of one nested-document layer."""
        if self._closed:
            return None
        layer = self._layers.layer(composition_id, layer_id)
        source = None if layer is None else layer.source
        if layer is None or not isinstance(source, ProjectResourceReference):
            return None
        resource = self._resources.resolve(source)
        if resource is None or resource.kind is not ProjectResourceKind.COMPOSITION:
            return None
        sampled = self._capabilities.sampled_source(source)
        source_size = self._capabilities.source_size(source)
        if not isinstance(sampled, RegionSampleSource) or source_size is None:
            return None
        target_size = QSize(source_size if pixel_size is None else pixel_size)
        _validate_output_size(target_size)
        request_id = uuid.uuid4()
        source_rect = QRectF(
            0.0,
            0.0,
            float(source_size.width()),
            float(source_size.height()),
        )
        pending = _PendingCompositionRasterization(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            QSize(source_size),
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
        request = ExecutionRequest(
            operation="editor.composition.rasterize",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=target_size.width() * target_size.height() * 4,
            ),
            work=lambda context: rasterize_region(
                sampled,
                source_rect,
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
        """Cancel pending work and suppress later publications."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "rasterization service detached")
        self._execution_scope.close(reason="composition_rasterization_shutdown")

    def _finish(self, request_id: uuid.UUID, result: QImage) -> None:
        """Install one current sampled result as editable raster content."""
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
                "rasterization service detached",
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
                pending,
                request_id,
                False,
                "layer changed during rasterization",
            )
            return
        if result.isNull():
            self._publish(
                pending,
                request_id,
                False,
                "layer rasterization produced no image",
            )
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
            self._publish(
                pending,
                request_id,
                False,
                "layer is no longer current",
            )
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
        """Cancel one request and publish exactly one terminal result."""
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
        """Return the document-global replacement key for one nested layer."""
        return ("composition-rasterization", layer_id)

    def _publish(
        self,
        pending: _PendingCompositionRasterization,
        request_id: uuid.UUID,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one immutable generic completion."""
        self._completed(
            LayerRasterizationCompletion(
                request_id,
                pending.public_scene_id,
                pending.layer.layer_id,
                succeeded,
                message,
            )
        )


def _validate_output_size(size: QSize) -> None:
    """Reject empty or excessive raster allocations."""
    if size.isEmpty():
        raise ValueError("pixel_size must have positive dimensions")
    if size.width() * size.height() * 4 > _MAX_OUTPUT_BYTES:
        raise ValueError("rasterization exceeds the 512 MiB output limit")
