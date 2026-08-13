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

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from qpane.sdk.execution import (
    CancellationToken,
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
from qpane.sdk.scene import LayerPlacement, LayerTransform, RasterBounds
from qpane.sdk.vector import VectorDocument

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from ..composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from ..composition.resource_references import instance_resources
from ..raster.assets import EditableRasterAssetStore
from ..resources import ProjectResourceReference
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..selection import PixelSelectionService
from .conversion_products import (
    VectorConversionKind,
    VectorConversionProduct,
    build_vector_conversion,
    validate_vector_raster_size,
)
from .editing import VectorEditService
from .selection import VectorObjectSelectionController
from .store import VectorAssetStore
from .text_paths import VectorTextPathConversion


@dataclass(frozen=True, slots=True)
class VectorConversionCompletion:
    """Describe exactly one terminal vector conversion request."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    kind: VectorConversionKind
    succeeded: bool
    message: str


@dataclass(slots=True)
class _PendingConversion:
    """Retain one exact request snapshot and its resource lease."""

    request_id: uuid.UUID
    composition_id: uuid.UUID
    history_scope_id: uuid.UUID
    public_scene_id: uuid.UUID
    layer: CompositionLayerInstance
    retained_source: ProjectResourceReference
    document: VectorDocument
    kind: VectorConversionKind
    selection_mode: CoverageCombineMode
    selection_revision: int | None
    handle: ExecutionHandle[VectorConversionProduct, object] | None = None


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
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        changed: Callable[[], None],
        completed: Callable[[VectorConversionCompletion], None],
    ) -> None:
        """Bind vector, selection, raster, history, and execution owners."""
        self._assets = assets
        self._raster_assets = raster_assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._vector_edits = vector_edits
        self._lifetime = lifetime
        self._pixel_selection = pixel_selection
        self._object_selection = object_selection
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:vector-conversion"
        )
        self._latest_requests = latest_requests
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingConversion] = {}
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
        retained_source = ProjectResourceReference(vector_id)
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
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            VectorConversionKind.PIXEL_SELECTION,
            lambda cancellation: build_vector_conversion(
                document,
                VectorConversionKind.PIXEL_SELECTION,
                cancellation,
                layer_transform=document_to_scene,
                object_ids=object_ids,
            ),
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
        validate_vector_raster_size(size)
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            VectorConversionKind.EDITABLE_RASTER,
            lambda cancellation: build_vector_conversion(
                document,
                VectorConversionKind.EDITABLE_RASTER,
                cancellation,
                pixel_size=size,
            ),
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
        retained_source = ProjectResourceReference(vector_id)
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
        return self._submit(
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            document,
            VectorConversionKind.TEXT_PATHS,
            lambda cancellation: build_vector_conversion(
                document,
                VectorConversionKind.TEXT_PATHS,
                cancellation,
                text_object_id=object_id,
            ),
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
        self._execution_scope.close(reason="vector_conversion_service_shutdown")

    def _request_context(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[CompositionLayerInstance, VectorDocument] | None:
        """Resolve one current vector instance and immutable document revision."""
        if self._closed:
            return None
        layer = self._layers.layer(composition_id, layer_id)
        if layer is None or not isinstance(layer.source, ProjectResourceReference):
            return None
        document = self._assets.get(layer.source.resource_id)
        return None if document is None else (layer, document)

    def _submit(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer: CompositionLayerInstance,
        document: VectorDocument,
        kind: VectorConversionKind,
        work: Callable[[CancellationToken], VectorConversionProduct],
        selection_mode: CoverageCombineMode,
        retained_source: ProjectResourceReference,
    ) -> uuid.UUID:
        """Submit one bounded request while retaining its exact source."""
        request_id = uuid.uuid4()
        key = self._request_key(layer.layer_id, kind)
        self._lifetime.acquire(retained_source, ResourceLeaseKind.SESSION)
        pending = _PendingConversion(
            request_id,
            composition_id,
            history_scope_id,
            public_scene_id,
            layer,
            retained_source,
            document,
            kind,
            selection_mode,
            (
                self._pixel_selection.state(history_scope_id).revision
                if kind is VectorConversionKind.PIXEL_SELECTION
                else None
            ),
        )
        self._pending[request_id] = pending
        if not self._latest_requests.claim(
            key,
            request_id,
            lambda message: self._cancel(request_id, message),
        ):
            self._pending.pop(request_id, None)
            self._lifetime.release(retained_source, ResourceLeaseKind.SESSION)
            return request_id
        request = ExecutionRequest(
            operation=f"editor.vector.convert.{kind.value}",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
            ),
            work=lambda context: work(context.cancellation),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda product: self._finish(request_id, product),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            self._latest_requests.release(key, request_id)
            self._lifetime.release(retained_source, ResourceLeaseKind.SESSION)
            self._completed(
                VectorConversionCompletion(
                    request_id,
                    public_scene_id,
                    layer.layer_id,
                    kind,
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

    def _finish(
        self,
        request_id: uuid.UUID,
        product: VectorConversionProduct,
    ) -> None:
        """Commit one current result to its existing authoritative owner."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        key = self._request_key(pending.layer.layer_id, pending.kind)
        if not self._latest_requests.is_current(key, request_id):
            self._lifetime.release(
                pending.retained_source,
                ResourceLeaseKind.SESSION,
            )
            self._publish(
                pending,
                False,
                "replaced by a newer vector conversion request",
            )
            return
        self._latest_requests.release(key, request_id)
        try:
            if self._closed:
                self._publish(pending, False, "vector conversion service detached")
                return
            current = self._layers.layer(
                pending.composition_id,
                pending.layer.layer_id,
            )
            document = self._assets.get(pending.retained_source.resource_id)
            if current != pending.layer or document != pending.document:
                self._publish(pending, False, "vector layer changed during conversion")
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
                self._finish_selection(pending, product.coverage)
            elif pending.kind is VectorConversionKind.EDITABLE_RASTER:
                self._finish_raster(pending, product.raster)
            else:
                self._finish_text_paths(pending, product.text_paths)
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
            source=ProjectResourceReference(raster.raster_id),
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
        if pending.handle is not None:
            pending.handle.cancel(reason=message)
        key = self._request_key(pending.layer.layer_id, pending.kind)
        self._latest_requests.release(key, request_id)
        self._lifetime.release(pending.retained_source, ResourceLeaseKind.SESSION)
        self._publish(pending, False, message)

    def _settle(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[VectorConversionProduct, object],
        outcome: ExecutionOutcome[VectorConversionProduct],
    ) -> None:
        """Publish failed or cancelled execution after owner-safe delivery."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(request_id, None)
        key = self._request_key(pending.layer.layer_id, pending.kind)
        self._latest_requests.release(key, request_id)
        self._lifetime.release(pending.retained_source, ResourceLeaseKind.SESSION)
        message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        self._publish(
            pending,
            False,
            message or "vector conversion did not complete",
        )

    @staticmethod
    def _request_key(
        layer_id: uuid.UUID,
        kind: VectorConversionKind,
    ) -> tuple[str, tuple[uuid.UUID, VectorConversionKind]]:
        """Return the document-global replacement key for one conversion."""
        return ("vector-conversion", (layer_id, kind))

    def _publish(
        self,
        pending: _PendingConversion,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one normalized terminal result."""
        self._completed(
            VectorConversionCompletion(
                pending.request_id,
                pending.public_scene_id,
                pending.layer.layer_id,
                pending.kind,
                succeeded,
                message,
            )
        )
