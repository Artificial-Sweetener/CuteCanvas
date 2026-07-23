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
"""Asynchronous explicit conversion of immutable vector document revisions."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

import numpy as np
from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Signal
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
)
from qpane.sdk.raster import qimage_to_numpy_argb32
from qpane.sdk.scene import LayerPlacement, LayerTransform, RasterBounds
from qpane.sdk.vector import (
    SemanticTextLayoutCache,
    VectorDocument,
    draw_vector_document,
    painted_document_path,
)

from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
    instance_resources,
)
from ..composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from ..raster.assets import EditableRasterAssetStore
from ..raster.source_reference import EditableRasterReference
from ..selection import PixelSelectionService
from .editing import VectorEditService
from .selection import VectorObjectSelectionController
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore
from .text_paths import VectorTextPathConversion, build_text_path_conversion

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 512 * 1024 * 1024


class VectorConversionKind(str, Enum):
    """Identify explicit asynchronous vector conversion operations."""

    PIXEL_SELECTION = "pixel-selection"
    EDITABLE_RASTER = "editable-raster"
    TEXT_PATHS = "text-paths"


@dataclass(frozen=True, slots=True)
class VectorConversionCompletion:
    """Describe exactly one terminal vector conversion request."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    kind: VectorConversionKind
    succeeded: bool
    message: str


class VectorRasterizer:
    """Produce explicit raster derivatives from semantic vector documents."""

    @staticmethod
    def rasterize_local(document: VectorDocument, pixel_size: QSize) -> QImage:
        """Render a document canvas into an explicit premultiplied image."""
        _validate_size(pixel_size)
        target = _transparent_image(pixel_size)
        bounds = document.bounds
        local_to_pixels = LayerTransform.from_placement(
            bounds,
            LayerPlacement(
                0.0,
                0.0,
                float(pixel_size.width()),
                float(pixel_size.height()),
            ),
        )
        _draw(
            target,
            document,
            local_to_pixels,
            text_layouts=SemanticTextLayoutCache(0),
        )
        return target

    @staticmethod
    def rasterize_selection(
        document: VectorDocument,
        layer_transform: LayerTransform,
        object_ids: frozenset[uuid.UUID] | None,
    ) -> CoverageSnapshot | None:
        """Render selected semantic object alpha into minimal scene coverage."""
        text_layouts = SemanticTextLayoutCache(0)
        document_path = painted_document_path(document, object_ids, text_layouts)
        scene_path = layer_transform.to_qtransform().map(document_path)
        if scene_path.isEmpty():
            return None
        bounds = _integer_paint_bounds(scene_path.boundingRect())
        _validate_size(QSize(bounds.width, bounds.height))
        target = _transparent_image(QSize(bounds.width, bounds.height))
        source_to_target = layer_transform.followed_by(
            LayerTransform(dx=-float(bounds.x), dy=-float(bounds.y))
        )
        _draw(
            target,
            document,
            source_to_target,
            object_ids,
            text_layouts=text_layouts,
        )
        pixels = qimage_to_numpy_argb32(target)
        alpha = np.array(pixels[:, :, 3], copy=True, order="C")
        if not np.any(alpha):
            return None
        occupied_y, occupied_x = np.nonzero(alpha)
        left = int(occupied_x.min())
        top = int(occupied_y.min())
        right = int(occupied_x.max()) + 1
        bottom = int(occupied_y.max()) + 1
        trimmed = np.array(alpha[top:bottom, left:right], copy=True, order="C")
        return CoverageSnapshot(
            RasterBounds(
                bounds.x + left,
                bounds.y + top,
                right - left,
                bottom - top,
            ),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            trimmed,
        )


class _VectorConversionWorker(QObject, QRunnable, BaseWorker):
    """Build one detached vector conversion result away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(
        self,
        request_id: uuid.UUID,
        document: VectorDocument,
        kind: VectorConversionKind,
        *,
        pixel_size: QSize | None = None,
        layer_transform: LayerTransform | None = None,
        object_ids: frozenset[uuid.UUID] | None = None,
        text_object_id: uuid.UUID | None = None,
    ) -> None:
        """Capture immutable request inputs and no mutable domain authority."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self.document = document
        self.kind = kind
        self.pixel_size = None if pixel_size is None else QSize(pixel_size)
        self.layer_transform = layer_transform
        self.object_ids = object_ids
        self.text_object_id = text_object_id
        self.raster: QImage | None = None
        self.coverage: CoverageSnapshot | None = None
        self.text_paths: VectorTextPathConversion | None = None
        self.error_message: str | None = None

    def run(self) -> None:
        """Produce one terminal result while containing worker failures."""
        try:
            if not self.is_cancelled:
                if self.kind is VectorConversionKind.EDITABLE_RASTER:
                    if self.pixel_size is None:
                        raise RuntimeError("raster conversion is missing pixel size")
                    self.raster = VectorRasterizer.rasterize_local(
                        self.document,
                        self.pixel_size,
                    )
                elif self.kind is VectorConversionKind.PIXEL_SELECTION:
                    if self.layer_transform is None:
                        raise RuntimeError("selection conversion is missing transform")
                    self.coverage = VectorRasterizer.rasterize_selection(
                        self.document,
                        self.layer_transform,
                        self.object_ids,
                    )
                else:
                    if self.text_object_id is None:
                        raise RuntimeError("text conversion is missing an object ID")
                    self.text_paths = build_text_path_conversion(
                        self.document,
                        self.text_object_id,
                    )
                    if self.text_paths is None:
                        raise RuntimeError("semantic text produced no painted paths")
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error_message = str(exc)
            logger.exception("Vector conversion failed")
        succeeded = self.error_message is None and not self.is_cancelled
        self.emit_finished(succeeded, payload=self, error=None)


@dataclass(slots=True)
class _PendingConversion:
    """Retain one exact request snapshot and its resource lease."""

    composition_id: uuid.UUID
    history_scope_id: uuid.UUID
    public_scene_id: uuid.UUID
    layer: CompositionLayerInstance
    retained_source: VectorDocumentReference
    document: VectorDocument
    kind: VectorConversionKind
    selection_mode: CoverageCombineMode
    selection_revision: int | None
    worker: _VectorConversionWorker
    handle: TaskHandle


class VectorConversionService:
    """Coordinate vector derivatives and atomic authoritative mutations."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        raster_assets: EditableRasterAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        vector_edits: VectorEditService,
        lifetime: CompositionResourceLifetime,
        pixel_selection: PixelSelectionService,
        object_selection: VectorObjectSelectionController,
        executor: TaskExecutorProtocol,
        changed: Callable[[], None],
        completed: Callable[[VectorConversionCompletion], None],
    ) -> None:
        """Bind vector, selection, raster, history, and worker owners."""
        self._assets = assets
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._vector_edits = vector_edits
        self._lifetime = lifetime
        self._pixel_selection = pixel_selection
        self._object_selection = object_selection
        self._executor = executor
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingConversion] = {}
        self._latest: dict[tuple[uuid.UUID, VectorConversionKind], uuid.UUID] = {}
        self._closed = False

    def request_selection(
        self,
        *,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        document_to_scene: LayerTransform,
        object_ids: frozenset[uuid.UUID] | None,
        mode: CoverageCombineMode,
    ) -> uuid.UUID | None:
        """Begin conversion of vector appearance into scene pixel coverage."""
        layer = self._layers.layer(composition_id, layer_id)
        document = self._assets.get(vector_id)
        retained_source = VectorDocumentReference(vector_id)
        if (
            self._closed
            or layer is None
            or document is None
            or retained_source not in instance_resources(layer)
        ):
            return None
        if object_ids is not None and any(
            document.object(object_id) is None for object_id in object_ids
        ):
            return None
        worker = _VectorConversionWorker(
            uuid.uuid4(),
            document,
            VectorConversionKind.PIXEL_SELECTION,
            layer_transform=document_to_scene,
            object_ids=object_ids,
        )
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            worker,
            mode,
            retained_source,
        )

    def request_rasterization(
        self,
        *,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin explicit editable-raster conversion for one vector instance."""
        current = self._request_context(composition_id, layer_id)
        if current is None:
            return None
        layer, document = current
        size = (
            QSize(document.bounds.width, document.bounds.height)
            if pixel_size is None
            else QSize(pixel_size)
        )
        _validate_size(size)
        worker = _VectorConversionWorker(
            uuid.uuid4(),
            document,
            VectorConversionKind.EDITABLE_RASTER,
            pixel_size=size,
        )
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            worker,
            CoverageCombineMode.REPLACE,
            layer.source,
        )

    def request_text_paths(
        self,
        *,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Begin exact semantic-text conversion into durable vector paths."""
        layer = self._layers.layer(composition_id, layer_id)
        document = self._assets.get(vector_id)
        retained_source = VectorDocumentReference(vector_id)
        item = None if document is None else document.object(object_id)
        if (
            self._closed
            or layer is None
            or document is None
            or retained_source not in instance_resources(layer)
            or item is None
            or item.text is None
        ):
            return None
        worker = _VectorConversionWorker(
            uuid.uuid4(),
            document,
            VectorConversionKind.TEXT_PATHS,
            text_object_id=object_id,
        )
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            worker,
            CoverageCombineMode.REPLACE,
            retained_source,
        )

    def shutdown(self) -> None:
        """Cancel all work, release leases, and suppress later publication."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "vector conversion service detached")
        self._latest.clear()

    def _request_context(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[CompositionLayerInstance, VectorDocument] | None:
        """Resolve one current vector instance and immutable document revision."""
        if self._closed:
            return None
        layer = self._layers.layer(composition_id, layer_id)
        if layer is None or not isinstance(layer.source, VectorDocumentReference):
            return None
        document = self._assets.get(layer.source.vector_id)
        return None if document is None else (layer, document)

    def _submit(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer: CompositionLayerInstance,
        document: VectorDocument,
        worker: _VectorConversionWorker,
        selection_mode: CoverageCombineMode,
        retained_source: VectorDocumentReference,
    ) -> uuid.UUID:
        """Submit one bounded request while retaining its exact source."""
        key = (layer.layer_id, worker.kind)
        previous = self._latest.pop(key, None)
        if previous is not None:
            self._cancel(previous, "replaced by a newer vector conversion")
        self._lifetime.acquire(retained_source, ResourceLeaseKind.SESSION)
        BaseWorker.connect_queued(worker.finished, self._finish)
        BaseWorker.connect_queued(worker.error, self._finish)
        try:
            handle = self._executor.submit(worker, category="vector_conversion")
        except TaskRejected as exc:
            self._lifetime.release(retained_source, ResourceLeaseKind.SESSION)
            worker.deleteLater()
            self._completed(
                VectorConversionCompletion(
                    worker.request_id,
                    public_scene_id,
                    layer.layer_id,
                    worker.kind,
                    False,
                    str(exc),
                )
            )
            return worker.request_id
        self._pending[worker.request_id] = _PendingConversion(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            retained_source,
            document,
            worker.kind,
            selection_mode,
            (
                self._pixel_selection.state(history_scope_id).revision
                if worker.kind is VectorConversionKind.PIXEL_SELECTION
                else None
            ),
            worker,
            handle,
        )
        self._latest[key] = worker.request_id
        return worker.request_id

    def _finish(self, worker: _VectorConversionWorker) -> None:
        """Commit one current result to its existing authoritative owner."""
        pending = self._pending.pop(worker.request_id, None)
        if pending is None:
            return
        self._latest.pop((pending.layer.layer_id, pending.kind), None)
        try:
            if self._closed:
                return
            current = self._layers.layer(
                pending.composition_id,
                pending.layer.layer_id,
            )
            document = self._assets.get(pending.retained_source.vector_id)
            if current != pending.layer or document != pending.document:
                self._publish(pending, False, "vector layer changed during conversion")
                return
            if worker.error_message is not None or worker.is_cancelled:
                self._publish(
                    pending,
                    False,
                    worker.error_message or "vector conversion was cancelled",
                )
                return
            if pending.kind is VectorConversionKind.PIXEL_SELECTION:
                if (
                    pending.selection_revision is None
                    or self._pixel_selection.state(pending.history_scope_id).revision
                    != pending.selection_revision
                ):
                    self._publish(
                        pending,
                        False,
                        "pixel selection changed during vector conversion",
                    )
                    return
                self._finish_selection(pending, worker.coverage)
            elif pending.kind is VectorConversionKind.EDITABLE_RASTER:
                self._finish_raster(pending, worker.raster)
            else:
                self._finish_text_paths(pending, worker.text_paths)
        finally:
            self._lifetime.release(pending.retained_source, ResourceLeaseKind.SESSION)

    def _finish_selection(
        self,
        pending: _PendingConversion,
        coverage: CoverageSnapshot | None,
    ) -> None:
        """Commit derived coverage through the sole pixel-selection owner."""
        if coverage is None:
            changed = bool(
                pending.selection_mode is CoverageCombineMode.REPLACE
                and self._pixel_selection.clear(pending.history_scope_id)
            )
        else:
            changed = self._pixel_selection.commit(
                pending.history_scope_id,
                coverage,
                pending.selection_mode,
            )
        self._publish(pending, True, "" if changed else "selection was unchanged")

    def _finish_raster(
        self,
        pending: _PendingConversion,
        image: QImage | None,
    ) -> None:
        """Atomically swap a vector source for a new editable raster source."""
        if image is None or image.isNull():
            self._publish(pending, False, "vector rasterization produced no image")
            return
        raster_bounds = RasterBounds.from_size(image.size())
        raster = self._raster_assets.create(image, bounds=raster_bounds)
        document_bounds = pending.document.bounds
        pixels_to_document = LayerTransform.from_placement(
            raster_bounds,
            LayerPlacement(
                float(document_bounds.x),
                float(document_bounds.y),
                float(document_bounds.width),
                float(document_bounds.height),
            ),
        )
        replacement = replace(
            pending.layer,
            source=EditableRasterReference(raster.raster_id),
            transform=pixels_to_document.followed_by(pending.layer.transform),
            role="raster",
        )
        if not self._layer_edits.replace_instance(
            pending.composition_id,
            replacement,
            history_scope_id=pending.history_scope_id,
        ):
            self._raster_assets.remove(raster.raster_id)
            self._publish(pending, False, "vector layer is no longer current")
            return
        self._changed()
        self._publish(pending, True, "")

    def _finish_text_paths(
        self,
        pending: _PendingConversion,
        conversion: VectorTextPathConversion | None,
    ) -> None:
        """Commit derived outline geometry through vector chronology."""
        if conversion is None:
            self._publish(pending, False, "text conversion produced no paths")
            return
        if not self._vector_edits.commit_document(
            pending.history_scope_id,
            pending.layer.layer_id,
            pending.document,
            conversion.document,
        ):
            self._publish(pending, False, "vector document is no longer current")
            return
        self._object_selection.set(
            pending.history_scope_id,
            pending.layer.layer_id,
            conversion.path_ids,
        )
        self._publish(pending, True, "")

    def _cancel(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel one request, release its lease, and publish once."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.worker.cancel()
        self._executor.cancel(pending.handle)
        self._latest.pop((pending.layer.layer_id, pending.kind), None)
        self._lifetime.release(pending.retained_source, ResourceLeaseKind.SESSION)
        self._publish(pending, False, message)

    def _publish(
        self,
        pending: _PendingConversion,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one normalized terminal result."""
        self._completed(
            VectorConversionCompletion(
                pending.worker.request_id,
                pending.public_scene_id,
                pending.layer.layer_id,
                pending.kind,
                succeeded,
                message,
            )
        )


def _draw(
    target: QImage,
    document: VectorDocument,
    source_to_target: LayerTransform,
    object_ids: frozenset[uuid.UUID] | None = None,
    *,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> None:
    """Draw semantic vector content into one initialized target image."""
    painter = QPainter(target)
    if not painter.isActive():
        raise RuntimeError("vector rasterization painter could not be activated")
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setTransform(source_to_target.to_qtransform())
        draw_vector_document(painter, document, object_ids, text_layouts)
    finally:
        painter.end()


def _transparent_image(size: QSize) -> QImage:
    """Allocate one bounded transparent premultiplied raster."""
    target = QImage(size, QImage.Format_ARGB32_Premultiplied)
    if target.isNull():
        raise MemoryError("vector rasterization target could not be allocated")
    target.fill(0)
    return target


def _validate_size(size: QSize) -> None:
    """Reject empty or unbounded explicit vector raster products."""
    if size.isEmpty():
        raise ValueError("vector raster dimensions must be positive")
    if size.width() * size.height() * 4 > _MAX_OUTPUT_BYTES:
        raise ValueError("vector rasterization exceeds the 512 MiB output limit")


def _integer_paint_bounds(bounds: QRectF) -> RasterBounds:
    """Return antialias-safe half-open integer bounds around painted geometry."""
    left = math.floor(bounds.left()) - 1
    top = math.floor(bounds.top()) - 1
    right = math.ceil(bounds.right()) + 1
    bottom = math.ceil(bounds.bottom()) + 1
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))
