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
from qpane.sdk.concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)
from qpane.sdk.rendering import RegionRasterizationWorker, RegionSampleSource

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..raster.assets import EditableRasterAssetStore
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
    worker: RegionRasterizationWorker
    handle: TaskHandle


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
        executor: TaskExecutorProtocol,
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[LayerRasterizationCompletion], None],
    ) -> None:
        """Bind resource sampling, editable payload, history, and task owners."""
        self._resources = resources
        self._capabilities = capabilities
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._executor = executor
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingCompositionRasterization] = {}
        self._latest_by_layer: dict[uuid.UUID, uuid.UUID] = {}
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
        self._cancel_layer(layer_id, "replaced by a newer rasterization")
        worker = RegionRasterizationWorker(
            request_id,
            sampled,
            QRectF(
                0.0,
                0.0,
                float(source_size.width()),
                float(source_size.height()),
            ),
            target_size,
        )
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="layer_rasterization")
        except TaskRejected as exc:
            worker.deleteLater()
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
        self._pending[request_id] = _PendingCompositionRasterization(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            QSize(source_size),
            worker,
            handle,
        )
        self._latest_by_layer[layer_id] = request_id
        return request_id

    def shutdown(self) -> None:
        """Cancel pending work and suppress later publications."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "rasterization service detached")
        self._latest_by_layer.clear()

    def _finish(self, worker: RegionRasterizationWorker) -> None:
        """Install one current sampled result as editable raster content."""
        pending = self._pending.pop(worker.request_id, None)
        if pending is None or self._closed:
            return
        layer_id = pending.layer.layer_id
        if self._latest_by_layer.get(layer_id) != worker.request_id:
            return
        self._latest_by_layer.pop(layer_id, None)
        current = self._layers.layer(pending.composition_id, layer_id)
        if current != pending.layer:
            self._publish(
                pending,
                worker.request_id,
                False,
                "layer changed during rasterization",
            )
            return
        result = worker.result
        if result is None or worker.error_message is not None:
            self._publish(
                pending,
                worker.request_id,
                False,
                worker.error_message or "layer rasterization was cancelled",
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
                worker.request_id,
                False,
                "layer is no longer current",
            )
            return
        self._changed(pending.composition_id)
        self._publish(pending, worker.request_id, True, "")

    def _cancel_layer(self, layer_id: uuid.UUID, message: str) -> None:
        """Cancel the current request for one layer."""
        request_id = self._latest_by_layer.pop(layer_id, None)
        if request_id is not None:
            self._cancel(request_id, message)

    def _cancel(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel one request and publish exactly one terminal result."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)
        self._latest_by_layer.pop(pending.layer.layer_id, None)
        self._publish(pending, request_id, False, message)

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
