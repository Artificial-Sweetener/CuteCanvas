#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask-source implementation of generic raster structure mutations."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRect, QRunnable, Signal

from ..concurrency import BaseWorker, TaskExecutorProtocol, TaskHandle, TaskRejected
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.raster import RasterBounds, RasterExtentPolicy
from ..scene.raster_mutations import RasterBoundsCompletion, RasterLayerState
from ..scene.sources import MaskLayerSource
from .edit_service import MaskEditService
from .mask import MaskAssetStore
from .render_cache import MaskRenderCache
from .surface import MaskSurface, MaskSurfaceSnapshot, reframe_mask_snapshot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PendingBoundsRequest:
    """Track one submitted worker and the scene identity it must still match."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    mask_id: uuid.UUID
    is_current: Callable[[], bool]
    worker: _MaskReframeWorker
    handle: TaskHandle


class MaskRasterMutationOwner:
    """Own mask extent policy and asynchronous local storage reframing."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        edits: MaskEditService,
        renders: MaskRenderCache,
        executor: TaskExecutorProtocol,
        mask_changed: Callable[[uuid.UUID, QRect], None],
        undo_changed: Callable[[uuid.UUID], None],
        scene_changed: Callable[[], None],
        completed: Callable[[RasterBoundsCompletion], None],
    ) -> None:
        """Bind authoritative mask collaborators and generic result callbacks."""
        self._assets = assets
        self._edits = edits
        self._renders = renders
        self._executor = executor
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed
        self._scene_changed = scene_changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingBoundsRequest] = {}
        self._latest_by_layer: dict[uuid.UUID, uuid.UUID] = {}
        self._closed = False

    def supports_layer(self, layer: LayerDescriptor) -> bool:
        """Return True for mask-backed raster descriptors."""
        return isinstance(layer.source, MaskLayerSource)

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
            pending_request_id=self._latest_by_layer.get(layer.layer_id),
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
        if self._closed or not isinstance(layer.source, MaskLayerSource):
            return None
        surface = self._assets.get_surface(layer.source.mask_id)
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
            self._executor.dispatch_to_main_thread(
                lambda: self._completed(completion),
                category="main",
            )
            return request_id
        worker = _MaskReframeWorker(request_id, surface, bounds)
        BaseWorker.connect_queued(worker.finished, self._finish_request)
        try:
            handle = self._executor.submit(worker, category="mask_structure")
        except TaskRejected as exc:
            worker.deleteLater()
            completion = RasterBoundsCompletion(
                request_id,
                scene.scene_id,
                layer.layer_id,
                False,
                str(exc),
            )
            self._executor.dispatch_to_main_thread(
                lambda: self._completed(completion),
                category="main",
            )
            return request_id
        self._pending[request_id] = _PendingBoundsRequest(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            mask_id=layer.source.mask_id,
            is_current=is_current,
            worker=worker,
            handle=handle,
        )
        self._latest_by_layer[layer.layer_id] = request_id
        self._scene_changed()
        return request_id

    def shutdown(self) -> None:
        """Cancel pending reframes and publish terminal cancellation results."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel_pending(request_id, "raster source detached")
        self._latest_by_layer.clear()

    def _surface_for(self, layer: LayerDescriptor) -> MaskSurface | None:
        """Resolve authoritative storage from one supported descriptor."""
        if not isinstance(layer.source, MaskLayerSource):
            return None
        return self._assets.get_surface(layer.source.mask_id)

    def _replace_pending(
        self,
        layer_id: uuid.UUID,
        replacement_id: uuid.UUID,
    ) -> None:
        """Cancel an older request for ``layer_id`` before accepting a replacement."""
        previous = self._latest_by_layer.get(layer_id)
        if previous is not None and previous != replacement_id:
            self._cancel_pending(previous, "replaced by a newer bounds request")

    def _cancel_pending(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel and complete one tracked request exactly once."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)
        if self._latest_by_layer.get(pending.layer_id) == request_id:
            self._latest_by_layer.pop(pending.layer_id, None)
        self._completed(
            RasterBoundsCompletion(
                request_id,
                pending.scene_id,
                pending.layer_id,
                False,
                message,
            )
        )

    def _finish_request(self, worker: _MaskReframeWorker) -> None:
        """Apply a current worker result on the Qt thread and record history."""
        pending = self._pending.pop(worker.request_id, None)
        if pending is None:
            return
        if self._latest_by_layer.get(pending.layer_id) == worker.request_id:
            self._latest_by_layer.pop(pending.layer_id, None)
        if self._closed or worker.error is not None or worker.result is None:
            message = "request cancelled" if worker.error is None else str(worker.error)
            self._publish_completion(pending, worker.request_id, False, message)
            return
        if not pending.is_current():
            self._publish_completion(
                pending,
                worker.request_id,
                False,
                "raster layer is no longer current",
            )
            return
        surface = self._assets.get_surface(pending.mask_id)
        if surface is None:
            self._publish_completion(
                pending, worker.request_id, False, "raster source no longer exists"
            )
            return
        if surface.revisions() != worker.source_revisions:
            self._publish_completion(
                pending,
                worker.request_id,
                False,
                "raster source changed while bounds were being prepared",
            )
            return
        before = worker.source_snapshot
        after = worker.result
        if before is None:
            self._publish_completion(
                pending, worker.request_id, False, "source snapshot unavailable"
            )
            return
        surface.replace_with_snapshot(after)
        if self._assets.record_applied_surface(pending.mask_id, before, after):
            self._undo_changed(pending.mask_id)
        layer = self._assets.get_layer(pending.mask_id)
        if layer is not None:
            self._renders.invalidate_layer(layer)
        self._edits.advance_epoch(pending.mask_id, reason="raster_bounds_changed")
        self._mask_changed(pending.mask_id, QRect())
        self._scene_changed()
        self._publish_completion(pending, worker.request_id, True, "")

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


class _MaskReframeWorker(QObject, QRunnable, BaseWorker):
    """Capture and reframe one mask surface without blocking the Qt thread."""

    finished = Signal(object)

    def __init__(
        self,
        request_id: uuid.UUID,
        surface: MaskSurface,
        bounds: RasterBounds,
    ) -> None:
        """Store immutable request values and the synchronized source handle."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self._surface = surface
        self._bounds = bounds
        self.source_revisions: tuple[int, int] | None = None
        self.source_snapshot: MaskSurfaceSnapshot | None = None
        self.result: MaskSurfaceSnapshot | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        """Copy current source state and calculate the requested frame."""
        try:
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            content_revision, structure_revision, snapshot = (
                self._surface.versioned_snapshot()
            )
            self.source_revisions = (content_revision, structure_revision)
            self.source_snapshot = snapshot
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            self.result = reframe_mask_snapshot(snapshot, self._bounds)
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error = exc
            logger.exception("Mask surface reframe failed")
        self.emit_finished(
            self.error is None and not self.is_cancelled,
            payload=self,
            error=self.error,
        )
