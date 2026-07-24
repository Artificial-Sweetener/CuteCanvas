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
"""Validated in-memory values exchanged by private composition persistence."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from qpane.sdk.vector import VectorDocument

from ..composition.layers import CompositionLayerInstance
from ..composition.model import CompositionRecord
from ..coverage import CoverageAssetSnapshot
from ..placed.model import PlacedAssetSnapshot
from ..raster.sparse_grid import SparseRasterSnapshot
from ..resources import ProjectResourceRecord


@dataclass(frozen=True, slots=True)
class CompositionArchiveSnapshot:
    """Capture one root document and its complete transitive resource closure."""

    root_document_id: uuid.UUID
    documents: Mapping[uuid.UUID, CompositionRecord]
    layer_stacks: Mapping[uuid.UUID, tuple[CompositionLayerInstance, ...]]
    resources: Mapping[uuid.UUID, ProjectResourceRecord]
    masks: Mapping[uuid.UUID, CoverageAssetSnapshot]
    rasters: Mapping[uuid.UUID, SparseRasterSnapshot]
    placed_assets: Mapping[uuid.UUID, PlacedAssetSnapshot]
    vectors: Mapping[uuid.UUID, VectorDocument]

    def __post_init__(self) -> None:
        """Normalize immutable collection boundaries."""
        if not isinstance(self.root_document_id, uuid.UUID):
            raise TypeError("root_document_id must be a UUID")
        documents = dict(self.documents)
        if self.root_document_id not in documents:
            raise ValueError("archive root document must be present")
        if set(documents) != set(self.layer_stacks):
            raise ValueError("archive documents and layer stacks must match")
        if any(
            document_id != document.composition_id
            for document_id, document in documents.items()
        ):
            raise ValueError("archive document keys must match document identities")
        object.__setattr__(
            self,
            "documents",
            MappingProxyType(documents),
        )
        object.__setattr__(
            self,
            "layer_stacks",
            MappingProxyType(
                {
                    document_id: tuple(layers)
                    for document_id, layers in self.layer_stacks.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(dict(self.resources)),
        )
        object.__setattr__(self, "masks", MappingProxyType(dict(self.masks)))
        object.__setattr__(self, "rasters", MappingProxyType(dict(self.rasters)))
        object.__setattr__(
            self,
            "placed_assets",
            MappingProxyType(dict(self.placed_assets)),
        )
        object.__setattr__(self, "vectors", MappingProxyType(dict(self.vectors)))

    @property
    def composition_id(self) -> uuid.UUID:
        """Return the archived root document identity."""
        return self.root_document_id
