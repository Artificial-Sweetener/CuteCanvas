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
"""Capture exact embedded image revisions for external consumers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtGui import QImage

from .model import ProjectResourceReference

if TYPE_CHECKING:
    from ..composition.service import CompositionService
    from ..placed.store import PlacedAssetStore
    from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class EmbeddedImageExportSnapshot:
    """Carry one exact embedded image resource revision across an I/O boundary."""

    composition_id: uuid.UUID
    resource_id: uuid.UUID
    revision: int
    image: QImage

    def __post_init__(self) -> None:
        """Validate stable identity and detach mutable pixels."""
        if not isinstance(self.composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(self.resource_id, uuid.UUID):
            raise TypeError("resource_id must be a UUID")
        if not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a non-negative integer")
        if not isinstance(self.image, QImage) or self.image.isNull():
            raise ValueError("image must be a non-null QImage")
        object.__setattr__(self, "image", self.image.copy())


class EmbeddedImageExportService:
    """Capture one direct imported-image composition without activating a view."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        assets: PlacedAssetStore,
        resources: ProjectResourceStore,
    ) -> None:
        """Bind composition topology, image payloads, and resource revisions."""
        self._compositions = compositions
        self._assets = assets
        self._resources = resources

    def capture(
        self,
        composition_id: uuid.UUID,
    ) -> EmbeddedImageExportSnapshot | None:
        """Return detached pixels only for one coherent embedded content resource."""
        try:
            self._compositions.record(composition_id)
        except KeyError:
            return None
        content_layers = tuple(
            layer
            for layer in self._compositions.layers.layers_for_composition(
                composition_id
            )
            if layer.role == "content"
        )
        if len(content_layers) != 1:
            return None
        source = content_layers[0].source
        if not isinstance(source, ProjectResourceReference):
            return None
        for _attempt in range(3):
            resource = self._resources.get(source.resource_id)
            asset = self._assets.get(source.resource_id)
            if (
                resource is None
                or asset is None
                or asset.mode.value != "embedded"
                or asset.image is None
                or asset.image.isNull()
            ):
                return None
            revision = resource.revision
            image = QImage(asset.image)
            current = self._resources.get(source.resource_id)
            if current is not None and current.revision == revision:
                return EmbeddedImageExportSnapshot(
                    composition_id=composition_id,
                    resource_id=source.resource_id,
                    revision=revision,
                    image=image,
                )
        return None


__all__ = ["EmbeddedImageExportService", "EmbeddedImageExportSnapshot"]
