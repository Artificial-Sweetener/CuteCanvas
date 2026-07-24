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
"""Source-neutral layer rasterization routing and completion values."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize
from qpane.sdk.scene import LayerTransform

from ..composition.layers import CompositionLayerStore
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore

RasterizationRequest = Callable[
    [uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, QSize | None],
    uuid.UUID | None,
]


@dataclass(frozen=True, slots=True)
class LayerRasterizationCompletion:
    """Describe one terminal generic layer rasterization request."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    succeeded: bool
    message: str


class LayerResourceRasterizationRouter:
    """Route one layer request through its authoritative resource-kind owner."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        layers: CompositionLayerStore,
    ) -> None:
        """Bind resource identity and layer instance owners."""
        self._resources = resources
        self._layers = layers
        self._owners: dict[ProjectResourceKind, RasterizationRequest] = {}

    def register(
        self,
        kind: ProjectResourceKind,
        owner: RasterizationRequest,
    ) -> None:
        """Register the sole rasterization request owner for one kind."""
        existing = self._owners.get(kind)
        if existing is not None and existing is not owner:
            raise ValueError(f"rasterization owner already registered for {kind.value}")
        self._owners[kind] = owner

    def request(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        public_scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None,
    ) -> uuid.UUID | None:
        """Begin rasterization through the selected layer's payload owner."""
        layer = self._layers.layer(composition_id, layer_id)
        source = None if layer is None else layer.source
        if not isinstance(source, ProjectResourceReference):
            return None
        resource = self._resources.resolve(source)
        owner = None if resource is None else self._owners.get(resource.kind)
        return (
            None
            if owner is None
            else owner(
                composition_id,
                history_scope_id,
                public_scene_id,
                layer_id,
                pixel_size,
            )
        )


def retarget_raster_transform(
    transform: LayerTransform,
    source_size: QSize,
    target_size: QSize,
) -> LayerTransform:
    """Preserve displayed affine geometry across new raster dimensions."""
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
