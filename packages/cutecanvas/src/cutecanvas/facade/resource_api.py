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

"""Public layer-resource sharing and forking commands."""

from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QRectF, QSize
from qpane.sdk.scene import LayerPlacement, LayerTransform, RasterBounds

from ..composition.public_policy import internal_layer_policy
from ..types import LayerPolicy


class ResourceApiMixin:
    """Expose source-neutral project resource operations."""

    def duplicateLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Duplicate a layer instance while sharing its underlying resource."""
        scope_id = self._layer_scope(scene_id, layer_id)
        operations = self._layer_resource_operations
        if scope_id is None or operations is None:
            return None
        duplicate_id = operations.duplicate_layer(
            scope_id,
            layer_id,
            history_scope_id=self._resolve_public_scene_id(scene_id),
        )
        if duplicate_id is not None:
            self._refresh_active_scene_content(fit_view=False)
        return duplicate_id

    def forkLayerResource(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Redirect one layer to an independent copy of its current resource."""
        scope_id = self._layer_scope(scene_id, layer_id)
        operations = self._layer_resource_operations
        if scope_id is None or operations is None:
            return None
        resource_id = operations.fork_layer_resource(
            scope_id,
            layer_id,
            history_scope_id=self._resolve_public_scene_id(scene_id),
        )
        if resource_id is not None:
            self._refresh_active_scene_content(fit_view=False)
        return resource_id

    def rasterizeLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = None,
    ) -> uuid.UUID | None:
        """Convert one renderable resource layer into editable pixels.

        Args:
            scene_id: Public identifier of the active scene.
            layer_id: Layer instance to replace atomically.
            pixel_size: Optional output dimensions chosen by the host.

        Returns:
            A request UUID, or ``None`` when the layer cannot be rasterized.

        Raises:
            TypeError: If identifiers or pixel size use unsupported types.
            ValueError: If output dimensions are invalid or exceed the limit.

        Side effects:
            Emits ``layerRasterizationCompleted`` exactly once for accepted work.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if pixel_size is not None and not isinstance(pixel_size, QSize):
            raise TypeError("pixel_size must be a QSize or None")
        composition_id = self._layer_scope(scene_id, layer_id)
        router = self._resource_rasterization
        if composition_id is None or router is None:
            return None
        return router.request(
            composition_id,
            self._resolve_public_scene_id(scene_id),
            scene_id,
            layer_id,
            None if pixel_size is None else QSize(pixel_size),
        )

    def placeComposition(
        self,
        composition_id: uuid.UUID,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place one composition inside the active composition.

        Args:
            composition_id: Existing composition resource to reference.
            placement: Optional destination rectangle in active-canvas coordinates.
            label: Optional layer label.
            interaction: Optional host-controlled layer permissions.

        Returns:
            The new layer identity, or None when no composition is active.

        Raises:
            KeyError: If ``composition_id`` does not identify an existing composition.
            ValueError: If placement would introduce a resource cycle.
        """
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        source_composition_id = composition_id
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if interaction is not None and not isinstance(interaction, LayerPolicy):
            raise TypeError("interaction must be LayerPolicy or None")
        destination_composition_id = self.currentCompositionID()
        operations = self._layer_resource_operations
        if destination_composition_id is None or operations is None:
            return None
        record = self.compositionService().record(source_composition_id)
        local_bounds = RasterBounds(
            0,
            0,
            max(1, math.ceil(record.canvas_bounds.width())),
            max(1, math.ceil(record.canvas_bounds.height())),
        )
        destination = (
            LayerPlacement(
                0.0,
                0.0,
                float(local_bounds.width),
                float(local_bounds.height),
            )
            if placement is None
            else LayerPlacement(
                placement.x(),
                placement.y(),
                placement.width(),
                placement.height(),
            )
        )
        layer_id = operations.place_resource(
            destination_composition_id,
            source_composition_id,
            transform=LayerTransform.from_placement(local_bounds, destination),
            interaction=internal_layer_policy(
                interaction
                or LayerPolicy(
                    selectable=True,
                    movable=True,
                    pixel_editable=False,
                )
            ),
            label=label or record.title,
            history_scope_id=destination_composition_id,
        )
        if layer_id is not None:
            self._publish_scene_layer_change()
        return layer_id
