#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Validated in-memory values exchanged by private composition persistence."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..composition.layers import CompositionLayerInstance
from ..composition.model import CompositionRecord
from ..placed.model import PlacedAssetSnapshot
from ..raster.sparse_grid import SparseRasterSnapshot
from ..vector.model import VectorDocument


@dataclass(frozen=True, slots=True)
class CompositionArchiveSnapshot:
    """Capture one composition and all source-owned authoring surfaces."""

    document: CompositionRecord
    layers: tuple[CompositionLayerInstance, ...]
    masks: Mapping[uuid.UUID, SparseRasterSnapshot]
    rasters: Mapping[uuid.UUID, SparseRasterSnapshot]
    placed_assets: Mapping[uuid.UUID, PlacedAssetSnapshot]
    vectors: Mapping[uuid.UUID, VectorDocument]

    def __post_init__(self) -> None:
        """Normalize immutable collection boundaries."""
        if not isinstance(self.document, CompositionRecord):
            raise TypeError("document must be a CompositionRecord")
        object.__setattr__(self, "layers", tuple(self.layers))
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
        """Return the archived document identity."""
        return self.document.composition_id
