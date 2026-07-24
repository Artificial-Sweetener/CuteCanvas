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

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Signal
from qpane.sdk.concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from cutecanvas.types import RasterExtentPolicy

from ..composition.edit_controller import CompositionEditController
from ..resources import ProjectResourceReference
from ..scene.raster_mutations import RasterBoundsCompletion, RasterLayerState
from .assets import EditableRasterAssetStore
from .color_surface import ColorRasterSurface
from .sparse_grid import (
    SparseRasterSnapshot,
    reframe_sparse_raster_snapshot,
)

logger = logging.getLogger(__name__)


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
    """Track one worker result until it is applied or rejected."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    is_current: Callable[[], bool]
    worker: _ColorRasterReframeWorker
    handle: TaskHandle


class EditableRasterStructureMutationOwner:
    """Own editable-raster policy, asynchronous bounds, and structure history."""

    def __init__(
        self,
        assets: EditableRasterAssetStore,
        *,
        edits: CompositionEditController,
        executor: TaskExecutorProtocol,
        changed: Callable[[], None],
        completed: Callable[[RasterBoundsCompletion], None],
    ) -> None:
        """Bind source storage, chronology, work scheduling, and presentation."""
        self._assets = assets
        self._edits = edits
        self._executor = executor
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingColorBoundsRequest] = {}
        self._latest_by_layer: dict[uuid.UUID, uuid.UUID] = {}
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
            self._latest_by_layer.get(layer.layer_id),
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
            self._executor.dispatch_to_main_thread(
                lambda: self._completed(completion),
                category="main",
            )
            return request_id
        worker = _ColorRasterReframeWorker(request_id, asset.surface, bounds)
        BaseWorker.connect_queued(worker.finished, self._finish_request)
        try:
            handle = self._executor.submit(worker, category="raster_structure")
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
        self._pending[request_id] = _PendingColorBoundsRequest(
            scene.scene_id,
            layer.layer_id,
            source.resource_id,
            is_current,
            worker,
            handle,
        )
        self._latest_by_layer[layer.layer_id] = request_id
        self._changed()
        return request_id

    def shutdown(self) -> None:
        """Cancel pending work and publish terminal cancellation."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel_pending(request_id, "raster source detached")
        self._latest_by_layer.clear()

    def _finish_request(self, worker: _ColorRasterReframeWorker) -> None:
        """Apply a current worker result and record one structure command."""
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
        asset = self._assets.get(pending.raster_id)
        if asset is None:
            self._publish_completion(
                pending,
                worker.request_id,
                False,
                "raster source no longer exists",
            )
            return
        if asset.surface.revisions() != worker.source_revisions:
            self._publish_completion(
                pending,
                worker.request_id,
                False,
                "raster source changed while bounds were being prepared",
            )
            return
        before = worker.source_snapshot
        if before is None:
            self._publish_completion(
                pending,
                worker.request_id,
                False,
                "source snapshot unavailable",
            )
            return
        asset.surface.replace_with_sparse_snapshot(worker.result)
        self._edits.record_applied(
            ColorRasterStructureEdit(
                pending.scene_id,
                pending.layer_id,
                pending.raster_id,
                before,
                worker.result,
            )
        )
        self._changed()
        self._publish_completion(pending, worker.request_id, True, "")

    def _replace_pending(self, layer_id: uuid.UUID, replacement_id: uuid.UUID) -> None:
        """Cancel an older request for the same layer."""
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
        self._publish_completion(pending, request_id, False, message)

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


class _ColorRasterReframeWorker(QObject, QRunnable, BaseWorker):
    """Prepare one detached color-raster reframe off the Qt thread."""

    finished = Signal(object)

    def __init__(
        self,
        request_id: uuid.UUID,
        surface: ColorRasterSurface,
        bounds: RasterBounds,
    ) -> None:
        """Capture request identity and synchronized source handle."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self._surface = surface
        self._bounds = bounds
        self.source_revisions: tuple[int, int] | None = None
        self.source_snapshot: SparseRasterSnapshot | None = None
        self.result: SparseRasterSnapshot | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        """Copy current state and calculate the requested frame."""
        try:
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            content, structure, snapshot = self._surface.versioned_sparse_snapshot()
            self.source_revisions = (content, structure)
            self.source_snapshot = snapshot
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            self.result = reframe_sparse_raster_snapshot(snapshot, self._bounds)
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error = exc
            logger.exception("Color raster reframe failed")
        self.emit_finished(
            self.error is None and not self.is_cancelled,
            payload=self,
            error=self.error,
        )
