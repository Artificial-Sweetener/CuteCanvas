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

"""Create editor documents from imported raster resources."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from qpane.sdk.scene import LayerInteractionPolicy

from ..composition.model import CompositionDocumentPolicy
from ..composition.service import CompositionService
from ..placed.model import PlacedAssetMode
from ..placed.store import PlacedAssetStore
from .model import ProjectResourceReference
from .raster_instances import imported_raster_instance


@dataclass(frozen=True, slots=True)
class ImportedImageDocument:
    """Identify the document, layer, and resource created by one import."""

    document_id: uuid.UUID
    layer_id: uuid.UUID
    resource_id: uuid.UUID


class ImageDocumentWorkflow:
    """Create independent documents whose seed image is an ordinary resource."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        imported_rasters: PlacedAssetStore,
    ) -> None:
        """Bind document and imported-raster owners."""
        self._compositions = compositions
        self._imported_rasters = imported_rasters

    def create(
        self,
        image: QImage,
        *,
        title: str,
        label: str | None,
        interaction: LayerInteractionPolicy,
        policy: CompositionDocumentPolicy,
        document_id: uuid.UUID | None = None,
    ) -> ImportedImageDocument:
        """Import detached pixels and create one independent document atomically."""
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        resource_id = self._imported_rasters.create_embedded(image)
        layer = imported_raster_instance(
            resource_id,
            image.size(),
            interaction=interaction,
            label=label,
        )
        try:
            record = self._compositions.create_composition(
                QRectF(
                    0.0,
                    0.0,
                    float(image.width()),
                    float(image.height()),
                ),
                title=title,
                layers=(layer,),
                policy=policy,
                composition_id=document_id,
            )
        except Exception:
            self._imported_rasters.remove(resource_id)
            raise
        return ImportedImageDocument(
            document_id=record.composition_id,
            layer_id=layer.layer_id,
            resource_id=resource_id,
        )

    def replace(
        self,
        document_id: uuid.UUID,
        image: QImage,
    ) -> ImportedImageDocument:
        """Replace one imported image document's pixels under stable identities."""
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        self._compositions.record(document_id)
        candidates = tuple(
            layer
            for layer in self._compositions.layers.layers_for_composition(document_id)
            if layer.role == "content"
            and isinstance(layer.source, ProjectResourceReference)
            and (snapshot := self._imported_rasters.get(layer.source.resource_id))
            is not None
            and snapshot.mode is PlacedAssetMode.EMBEDDED
        )
        if len(candidates) != 1:
            raise ValueError(
                "composition must contain exactly one embedded content image"
            )
        layer = candidates[0]
        resource_id = layer.source.resource_id
        self._imported_rasters.replace_embedded(resource_id, image)
        self._compositions.set_canvas_bounds(
            document_id,
            QRectF(0.0, 0.0, float(image.width()), float(image.height())),
        )
        return ImportedImageDocument(
            document_id=document_id,
            layer_id=layer.layer_id,
            resource_id=resource_id,
        )
