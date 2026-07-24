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
from ..placed.store import PlacedAssetStore
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
            )
        except Exception:
            self._imported_rasters.remove(resource_id)
            raise
        return ImportedImageDocument(
            document_id=record.composition_id,
            layer_id=layer.layer_id,
            resource_id=resource_id,
        )
