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
"""Resolve the active document raster input from project resources."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage

from ..composition.service import CompositionService
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class ActiveRasterSnapshot:
    """Detached raster input selected from an active editor document."""

    resource_id: uuid.UUID
    image: QImage
    source_path: Path | None

    def __post_init__(self) -> None:
        """Detach pixels and reject null snapshots."""
        image = QImage(self.image)
        if image.isNull():
            raise ValueError("active raster snapshot must not be null")
        object.__setattr__(self, "image", image)


class ActiveRasterResolver:
    """Resolve selected or visible raster resources for pixel-consuming tools."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        resources: ProjectResourceStore,
        imported: PlacedAssetStore,
        rasters: EditableRasterAssetStore,
        current_composition_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind authoritative document, resource, and payload owners."""
        self._compositions = compositions
        self._resources = resources
        self._imported = imported
        self._rasters = rasters
        self._current_composition_id = current_composition_id

    def resolve(
        self,
        *,
        preferred_layer_id: uuid.UUID | None = None,
    ) -> ActiveRasterSnapshot | None:
        """Return the preferred raster layer or first visible raster in z-order."""
        document_id = self._current_composition_id()
        if document_id is None:
            return None
        layers = self._compositions.layers.layers_for_composition(document_id)
        ordered = tuple(
            layer for layer in layers if layer.layer_id == preferred_layer_id
        ) + tuple(
            layer for layer in reversed(layers) if layer.layer_id != preferred_layer_id
        )
        for layer in ordered:
            if not layer.visible or not isinstance(
                layer.source,
                ProjectResourceReference,
            ):
                continue
            snapshot = self._resolve_resource(layer.source.resource_id)
            if snapshot is not None:
                return snapshot
        return None

    def _resolve_resource(
        self,
        resource_id: uuid.UUID,
    ) -> ActiveRasterSnapshot | None:
        """Resolve one raster payload according to its authoritative kind."""
        record = self._resources.get(resource_id)
        if record is None:
            return None
        if record.kind in {
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        }:
            payload = self._imported.get(resource_id)
            if payload is None or payload.image is None:
                return None
            return ActiveRasterSnapshot(
                resource_id,
                payload.image,
                payload.source_path,
            )
        if record.kind is ProjectResourceKind.RASTER:
            payload = self._rasters.get(resource_id)
            if payload is None:
                return None
            return ActiveRasterSnapshot(
                resource_id,
                payload.surface.snapshot_qimage(),
                None,
            )
        return None
