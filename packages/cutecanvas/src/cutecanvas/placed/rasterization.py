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
from qpane.sdk.concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)
from qpane.sdk.rendering import LayerRasterizationWorker
from qpane.sdk.scene import LayerTransform

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..raster.assets import EditableRasterAssetStore
from ..raster.source_reference import EditableRasterReference
from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore
from .workflow import PlacedAssetCompletion

_MAX_RASTERIZATION_BYTES = 512 * 1024 * 1024


@dataclass(slots=True)
class _PendingRasterization:
    """Retain one exact source instance and submitted worker."""

    composition_id: uuid.UUID
    history_scope_id: uuid.UUID
    layer: CompositionLayerInstance
    source_size: QSize
    worker: LayerRasterizationWorker
    handle: TaskHandle


class PlacedAssetRasterizationService:
    """Coordinate raster render work and one atomic source-instance swap."""

    def __init__(
        self,
        *,
        placed_assets: PlacedAssetStore,
        raster_assets: EditableRasterAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        executor: TaskExecutorProtocol,
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[PlacedAssetCompletion], None],
    ) -> None:
        """Bind source, instance, worker, and publication owners."""
        self._placed_assets = placed_assets
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._executor = executor
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingRasterization] = {}
        self._latest_by_layer: dict[uuid.UUID, uuid.UUID] = {}
        self._closed = False

    def request(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin one explicit rasterization after validating its allocation."""
        if self._closed:
            return None
        layer = self._layers.layer(composition_id, layer_id)
        source = None if layer is None else layer.source
        if layer is None or not isinstance(source, PlacedAssetReference):
            return None
        snapshot = self._placed_assets.get(source.asset_id)
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
        self._cancel_layer(layer_id, "replaced by a newer rasterization")
        worker = LayerRasterizationWorker(request_id, snapshot.image, target_size)
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="layer_rasterization")
        except TaskRejected as exc:
            worker.deleteLater()
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    composition_id,
                    layer_id,
                    False,
                    str(exc),
                )
            )
            return request_id
        self._pending[request_id] = _PendingRasterization(
            composition_id,
            history_scope_id,
            layer,
            source_size,
            worker,
            handle,
        )
        self._latest_by_layer[layer_id] = request_id
        return request_id

    def shutdown(self) -> None:
        """Cancel pending rasterizations and suppress later publications."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "placed asset service detached")
        self._latest_by_layer.clear()

    def _finish(self, worker: LayerRasterizationWorker) -> None:
        """Install one current output as an editable source atomically."""
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
                pending, worker.request_id, False, "layer changed during rasterization"
            )
            return
        if worker.result is None or worker.error_message is not None:
            self._publish(
                pending,
                worker.request_id,
                False,
                worker.error_message or "layer rasterization was cancelled",
            )
            return
        raster = self._raster_assets.create(worker.result)
        replacement = replace(
            pending.layer,
            source=EditableRasterReference(raster.raster_id),
            transform=_retarget_transform(
                pending.layer.transform,
                pending.source_size,
                worker.result.size(),
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
                pending, worker.request_id, False, "layer is no longer current"
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
        """Cancel one submitted worker and publish exactly one outcome."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)
        self._latest_by_layer.pop(pending.layer.layer_id, None)
        self._publish(pending, request_id, False, message)

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


def _retarget_transform(
    transform: LayerTransform,
    source_size: QSize,
    target_size: QSize,
) -> LayerTransform:
    """Preserve the displayed affine quadrilateral across new local dimensions."""
    scale_x = source_size.width() / target_size.width()
    scale_y = source_size.height() / target_size.height()
    return LayerTransform(
        m11=transform.m11 * scale_x,
        m12=transform.m12 * scale_x,
        m21=transform.m21 * scale_y,
        m22=transform.m22 * scale_y,
        dx=transform.dx,
        dy=transform.dy,
    )
