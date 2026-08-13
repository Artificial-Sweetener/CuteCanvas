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
"""PlacedAssetApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from pathlib import Path

from cutecanvas.composition.public_policy import (
    internal_layer_policy,
)
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.types import (
    LayerPolicy,
    PlacedAssetSnapshot,
    RasterSurfaceSnapshot,
)
from PySide6.QtCore import (
    QRectF,
)
from PySide6.QtGui import (
    QImage,
)


class PlacedAssetApiMixin:
    """Group placedassetapi facade behavior."""

    def placeEmbeddedAsset(
        self,
        image: QImage,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place a detached non-destructive embedded image in the active scene.

        Args:
            image: Non-null raster copied into composition-owned asset storage.
            placement: Optional scene destination; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection and movement.

        Returns:
            The stable layer UUID, or ``None`` when no composition is active.

        Side effects:
            Records one scene edit and publishes updated scene state.
        """
        self._validate_placed_inputs(image, placement, label, interaction)
        workflow = self._placed_asset_workflow
        if workflow is None:
            return None
        normalized = interaction or LayerPolicy(
            selectable=True,
            movable=True,
        )
        return workflow.create_embedded(
            image,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(normalized),
            label=label,
        )

    def placeLinkedAsset(
        self,
        path: Path,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
        keep_fallback: bool = True,
    ) -> uuid.UUID | None:
        """Begin non-blocking placement of an externally linked image.

        Args:
            path: Filesystem image locator decoded away from the GUI thread.
            placement: Optional scene destination; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection and movement.
            keep_fallback: Whether composition archives retain last-known pixels.

        Returns:
            A request UUID, or ``None`` when no composition is active.

        Side effects:
            Emits ``placedAssetRequestCompleted`` exactly once for accepted work.
        """
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        self._validate_placed_inputs(None, placement, label, interaction)
        if not isinstance(keep_fallback, bool):
            raise TypeError("keep_fallback must be a bool")
        workflow = self._placed_asset_workflow
        if workflow is None:
            return None
        normalized = interaction or LayerPolicy(
            selectable=True,
            movable=True,
        )
        return workflow.create_linked(
            path,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(normalized),
            label=label,
            keep_fallback=keep_fallback,
        )

    def placedAssetState(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> PlacedAssetSnapshot | None:
        """Return detached provenance and availability for one placed layer."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        if scope_id is None or workflow is None:
            return None
        snapshot = workflow.snapshot_for_layer(scope_id, layer_id)
        instance = self.compositionService().layers.layer(scope_id, layer_id)
        source = None if instance is None else instance.source
        if snapshot is None or not isinstance(source, ProjectResourceReference):
            return None
        return PlacedAssetSnapshot(
            scene_id=scene_id,
            layer_id=layer_id,
            asset_id=source.resource_id,
            mode=snapshot.mode,
            status=snapshot.status,
            source_path=snapshot.source_path,
            error=snapshot.error,
            keep_fallback=snapshot.keep_fallback,
            content_revision=snapshot.content_revision,
            generation=snapshot.generation,
        )

    def refreshPlacedAsset(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Begin a non-blocking refresh from one placed layer's linked path."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return (
            None
            if scope_id is None or workflow is None
            else workflow.refresh(scope_id, layer_id)
        )

    def relinkPlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        path: Path,
    ) -> uuid.UUID | None:
        """Begin an undoable non-blocking reload from a replacement path."""
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return (
            None
            if scope_id is None or workflow is None
            else workflow.relink(scope_id, layer_id, path)
        )

    def embedPlacedAsset(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Detach one linked placed source from its external path."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return bool(
            scope_id is not None
            and workflow is not None
            and workflow.embed(scope_id, layer_id)
        )

    def rasterSurfaceState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> RasterSurfaceSnapshot | None:
        """Return source-owned raster storage state for an active scene layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to inspect.

        Returns:
            A detached raster state snapshot, or ``None`` for non-raster layers.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        coordinator = self._raster_mutations
        if coordinator is None:
            return None
        state = coordinator.state(self._resolve_public_scene_id(scene_id), layer_id)
        if state is None:
            return None
        return RasterSurfaceSnapshot(
            scene_id=scene_id,
            layer_id=state.layer_id,
            bounds=state.bounds.to_qrect(),
            extent_policy=state.extent_policy,
            content_revision=state.content_revision,
            structure_revision=state.structure_revision,
            pending_request_id=state.pending_request_id,
        )
