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
"""Placed-layer lifecycle and asynchronous provenance coordination."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
from qpane.sdk.scene import LayerInteractionPolicy, LayerPlacement

from ..composition.edit_controller import CompositionEditController
from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerStore
from ..resources import ProjectResourceReference
from ..resources.raster_instances import imported_raster_instance
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from .history import PlacedAssetEdit
from .model import PlacedAssetSnapshot
from .reload import PlacedAssetDecode, decode_placed_asset
from .store import PlacedAssetStore


@dataclass(frozen=True, slots=True)
class PlacedAssetCompletion:
    """Describe one terminal asynchronous placed-asset request."""

    request_id: uuid.UUID
    scope_id: uuid.UUID | None
    layer_id: uuid.UUID | None
    succeeded: bool
    message: str


@dataclass(frozen=True, slots=True)
class _NewLinkedRequest:
    """Retain inputs for an asynchronous linked-layer creation."""

    scope_id: uuid.UUID
    history_scope_id: uuid.UUID
    layer_id: uuid.UUID
    asset_id: uuid.UUID
    placement: LayerPlacement | None
    interaction: LayerInteractionPolicy
    label: str | None
    keep_fallback: bool


@dataclass(frozen=True, slots=True)
class _ReloadRequest:
    """Retain identity for a current linked-source reload."""

    scope_id: uuid.UUID
    history_scope_id: uuid.UUID
    layer_id: uuid.UUID
    asset_id: uuid.UUID
    generation: int
    before: PlacedAssetSnapshot
    record_history: bool


@dataclass(slots=True)
class _PendingDecode:
    """Own one submitted worker and its semantic request."""

    path: Path
    handle: ExecutionHandle[PlacedAssetDecode, object] | None = None
    new_layer: _NewLinkedRequest | None = None
    reload: _ReloadRequest | None = None


class PlacedAssetWorkflow:
    """Coordinate placed sources, composition instances, and async decode work."""

    def __init__(
        self,
        *,
        assets: PlacedAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        edits: CompositionEditController,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        current_scope_id: Callable[[], uuid.UUID | None],
        current_history_scope_id: Callable[[], uuid.UUID | None],
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[PlacedAssetCompletion], None],
    ) -> None:
        """Bind authoritative collaborators without duplicating their state."""
        self._assets = assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._edits = edits
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:placed-assets"
        )
        self._latest_requests = latest_requests
        self._current_scope_id = current_scope_id
        self._current_history_scope_id = current_history_scope_id
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingDecode] = {}
        self._closed = False

    def create_embedded(
        self,
        image: QImage,
        *,
        placement: LayerPlacement | None,
        interaction: LayerInteractionPolicy,
        label: str | None,
    ) -> uuid.UUID | None:
        """Create an undoable embedded placed layer in the active composition."""
        scope_id = self._current_scope_id()
        history_scope_id = self._current_history_scope_id()
        if (
            self._closed
            or scope_id is None
            or history_scope_id is None
            or image.isNull()
        ):
            return None
        asset_id = self._assets.create_embedded(image)
        instance = imported_raster_instance(
            asset_id,
            image.size(),
            layer_id=uuid.uuid4(),
            placement=placement,
            interaction=interaction,
            label=label,
        )
        if not self._layer_edits.add(
            scope_id,
            instance,
            history_scope_id=history_scope_id,
        ):
            self._assets.remove(asset_id)
            return None
        self._changed(scope_id)
        return instance.layer_id

    def create_linked(
        self,
        path: Path,
        *,
        placement: LayerPlacement | None,
        interaction: LayerInteractionPolicy,
        label: str | None,
        keep_fallback: bool,
    ) -> uuid.UUID | None:
        """Begin non-blocking linked-layer creation for the active composition."""
        scope_id = self._current_scope_id()
        history_scope_id = self._current_history_scope_id()
        if self._closed or scope_id is None or history_scope_id is None:
            return None
        request_id = uuid.uuid4()
        request = _NewLinkedRequest(
            scope_id=scope_id,
            history_scope_id=history_scope_id,
            layer_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            placement=placement,
            interaction=interaction,
            label=label,
            keep_fallback=keep_fallback,
        )
        self._submit(request_id, Path(path), new_layer=request)
        return request_id

    def duplicate(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        history_scope_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Duplicate any composition layer as an independent shared-source instance."""
        duplicate = self._layer_edits.duplicate(
            scope_id,
            layer_id,
            uuid.uuid4(),
            history_scope_id=history_scope_id,
        )
        if duplicate is None:
            return None
        self._changed(scope_id)
        return duplicate.layer_id

    def refresh(self, scope_id: uuid.UUID, layer_id: uuid.UUID) -> uuid.UUID | None:
        """Begin a non-historical refresh of one linked source."""
        return self._begin_reload(scope_id, layer_id, path=None, record_history=False)

    def relink(
        self, scope_id: uuid.UUID, layer_id: uuid.UUID, path: Path
    ) -> uuid.UUID | None:
        """Begin an undoable reload from a replacement linked path."""
        return self._begin_reload(
            scope_id,
            layer_id,
            path=Path(path),
            record_history=True,
        )

    def embed(self, scope_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Convert a linked source to embedded provenance as one exact edit."""
        asset_id = self._asset_id(scope_id, layer_id)
        if asset_id is None:
            return False
        before = self._assets.get(asset_id)
        after = self._assets.embed(asset_id)
        if before is None or after is None:
            return False
        self._cancel_asset(asset_id, "linked source was embedded")
        history_scope_id = self._current_history_scope_id()
        if history_scope_id is None:
            self._assets.restore(asset_id, before)
            return False
        self._edits.record_applied(
            PlacedAssetEdit(history_scope_id, asset_id, before, after)
        )
        self._changed(scope_id)
        return True

    def snapshot_for_layer(
        self, scope_id: uuid.UUID, layer_id: uuid.UUID
    ) -> PlacedAssetSnapshot | None:
        """Return placed source state for one composition instance."""
        asset_id = self._asset_id(scope_id, layer_id)
        return None if asset_id is None else self._assets.get(asset_id)

    def shutdown(self) -> None:
        """Cancel pending workers and suppress every future completion."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "placed asset service detached")
        self._execution_scope.close(reason="placed_asset_workflow_shutdown")

    def _begin_reload(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        path: Path | None,
        record_history: bool,
    ) -> uuid.UUID | None:
        """Capture one reload generation and submit its worker."""
        if self._closed:
            return None
        asset_id = self._asset_id(scope_id, layer_id)
        if asset_id is None:
            return None
        before = self._assets.get(asset_id)
        if before is None or before.source_path is None:
            return None
        request_id = uuid.uuid4()
        self._cancel_asset(asset_id, "replaced by a newer linked reload")
        resolved_path = before.source_path if path is None else path
        generation = self._assets.begin_reload(asset_id, resolved_path)
        if generation is None:
            return None
        request = _ReloadRequest(
            scope_id,
            self._current_history_scope_id() or scope_id,
            layer_id,
            asset_id,
            generation,
            before,
            record_history,
        )
        key = self._reload_key(asset_id)
        if not self._latest_requests.claim(
            key,
            request_id,
            lambda message: self._cancel(request_id, message),
        ):
            self._assets.restore(asset_id, before)
            return request_id
        if not self._submit(request_id, resolved_path, reload=request):
            self._latest_requests.release(key, request_id)
            self._assets.restore(asset_id, before)
            return request_id
        self._changed(scope_id)
        return request_id

    def _submit(
        self,
        request_id: uuid.UUID,
        path: Path,
        *,
        new_layer: _NewLinkedRequest | None = None,
        reload: _ReloadRequest | None = None,
    ) -> bool:
        """Submit one typed decode and retain its lifecycle handle."""
        pending = _PendingDecode(Path(path), None, new_layer, reload)
        self._pending[request_id] = pending
        request = ExecutionRequest(
            operation="editor.placed.decode",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.BLOCKING_IO,
                urgency=ExecutionUrgency.FOREGROUND,
            ),
            work=lambda context: decode_placed_asset(path, context.cancellation),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda result: self._finish(request_id, result),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            semantic = reload or new_layer
            assert semantic is not None
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    semantic.scope_id,
                    None if reload is None else reload.layer_id,
                    False,
                    str(exc),
                )
            )
            return False
        if self._pending.get(request_id) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle(request_id, handle, outcome)
        )
        return True

    def _finish(self, request_id: uuid.UUID, result: PlacedAssetDecode) -> None:
        """Publish a current decode through source and layer owners."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if self._closed:
            semantic = pending.reload or pending.new_layer
            assert semantic is not None
            if pending.reload is not None:
                self._latest_requests.release(
                    self._reload_key(pending.reload.asset_id),
                    request_id,
                )
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    semantic.scope_id,
                    None if pending.new_layer is not None else semantic.layer_id,
                    False,
                    "placed asset service detached",
                )
            )
            return
        if pending.new_layer is not None:
            self._finish_new(request_id, result, pending.new_layer)
        elif pending.reload is not None:
            self._finish_reload(request_id, result, pending.reload)

    def _finish_new(
        self,
        request_id: uuid.UUID,
        result: PlacedAssetDecode,
        request: _NewLinkedRequest,
    ) -> None:
        """Create an asset and instance only after a successful current decode."""
        if (
            result.image is None
            or result.fingerprint is None
            or result.error_message is not None
        ):
            self._publish_failure(request_id, result, request.scope_id, None)
            return
        self._assets.create_linked(
            result.image,
            result.path,
            result.fingerprint,
            keep_fallback=request.keep_fallback,
            asset_id=request.asset_id,
        )
        instance = imported_raster_instance(
            request.asset_id,
            result.image.size(),
            layer_id=request.layer_id,
            placement=request.placement,
            interaction=request.interaction,
            label=request.label,
        )
        if not self._layer_edits.add(
            request.scope_id,
            instance,
            history_scope_id=request.history_scope_id,
        ):
            self._assets.remove(request.asset_id)
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    request.scope_id,
                    None,
                    False,
                    "target composition no longer exists",
                )
            )
            return
        self._changed(request.scope_id)
        self._completed(
            PlacedAssetCompletion(
                request_id,
                request.scope_id,
                request.layer_id,
                True,
                "",
            )
        )

    def _finish_reload(
        self,
        request_id: uuid.UUID,
        result: PlacedAssetDecode,
        request: _ReloadRequest,
    ) -> None:
        """Reject stale work and update every instance of the shared source."""
        key = self._reload_key(request.asset_id)
        if not self._latest_requests.is_current(key, request_id):
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    request.scope_id,
                    request.layer_id,
                    False,
                    "replaced by a newer placed reload request",
                )
            )
            return
        self._latest_requests.release(key, request_id)
        source = ProjectResourceReference(request.asset_id)
        if not self._layers.composition_ids_for_source(source):
            self._assets.restore(request.asset_id, request.before)
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    request.scope_id,
                    request.layer_id,
                    False,
                    "placed source is no longer used by a scene layer",
                )
            )
            return
        if (
            result.image is None
            or result.fingerprint is None
            or result.error_message is not None
        ):
            after = self._assets.fail_reload(
                request.asset_id,
                request.generation,
                result.error_message or "linked image could not be decoded",
                missing=result.missing,
            )
            if after is not None and request.record_history:
                self._edits.record_applied(
                    PlacedAssetEdit(
                        request.history_scope_id,
                        request.asset_id,
                        request.before,
                        after,
                    )
                )
            if after is not None:
                self._changed(request.scope_id)
            self._publish_failure(
                request_id,
                result,
                request.scope_id,
                request.layer_id,
            )
            return
        after = self._assets.complete_reload(
            request.asset_id,
            request.generation,
            result.image,
            result.path,
            result.fingerprint,
        )
        if after is None:
            self._completed(
                PlacedAssetCompletion(
                    request_id,
                    request.scope_id,
                    request.layer_id,
                    False,
                    "placed source changed during reload",
                )
            )
            return
        if request.record_history:
            self._edits.record_applied(
                PlacedAssetEdit(
                    request.history_scope_id,
                    request.asset_id,
                    request.before,
                    after,
                )
            )
        self._changed(request.scope_id)
        self._completed(
            PlacedAssetCompletion(
                request_id,
                request.scope_id,
                request.layer_id,
                True,
                "",
            )
        )

    def _publish_failure(
        self,
        request_id: uuid.UUID,
        result: PlacedAssetDecode,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID | None,
    ) -> None:
        """Publish one normalized terminal decode failure."""
        self._completed(
            PlacedAssetCompletion(
                request_id,
                scope_id,
                layer_id,
                False,
                result.error_message or "linked image could not be decoded",
            )
        )

    def _settle(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[PlacedAssetDecode, object],
        outcome: ExecutionOutcome[PlacedAssetDecode],
    ) -> None:
        """Normalize execution failure and cancellation through workflow results."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        result = PlacedAssetDecode(
            pending.path,
            None,
            None,
            message or "linked image could not be decoded",
        )
        self._finish(request_id, result)

    def _cancel_asset(self, asset_id: uuid.UUID, message: str) -> None:
        """Cancel the current request for one shared asset when present."""
        self._latest_requests.cancel(self._reload_key(asset_id), reason=message)

    def _cancel(self, request_id: uuid.UUID, message: str) -> None:
        """Cancel one pending decode and publish exactly one terminal result."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if pending.handle is not None:
            pending.handle.cancel(reason=message)
        semantic = pending.reload or pending.new_layer
        assert semantic is not None
        if pending.reload is not None:
            self._latest_requests.release(
                self._reload_key(pending.reload.asset_id),
                request_id,
            )
        layer_id = None if pending.new_layer is not None else semantic.layer_id
        self._completed(
            PlacedAssetCompletion(
                request_id,
                semantic.scope_id,
                layer_id,
                False,
                message,
            )
        )

    @staticmethod
    def _reload_key(asset_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return the document-global replacement key for one linked source."""
        return ("placed-reload", asset_id)

    def _asset_id(self, scope_id: uuid.UUID, layer_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve a placed asset from one exact composition instance."""
        instance = self._layers.layer(scope_id, layer_id)
        source = None if instance is None else instance.source
        return (
            source.resource_id
            if isinstance(source, ProjectResourceReference)
            and self._assets.get(source.resource_id) is not None
            else None
        )
