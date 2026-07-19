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
from ..coverage import CoverageSnapshot
from ..raster.color_surface import ColorRasterSnapshot


@dataclass(frozen=True, slots=True)
class CompositionArchiveSnapshot:
    """Capture one composition and all source-owned authoring surfaces."""

    image_id: uuid.UUID
    layers: tuple[CompositionLayerInstance, ...]
    masks: Mapping[uuid.UUID, CoverageSnapshot]
    rasters: Mapping[uuid.UUID, ColorRasterSnapshot]

    def __post_init__(self) -> None:
        """Normalize immutable collection boundaries."""
        if not isinstance(self.image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        object.__setattr__(self, "layers", tuple(self.layers))
        object.__setattr__(self, "masks", MappingProxyType(dict(self.masks)))
        object.__setattr__(self, "rasters", MappingProxyType(dict(self.rasters)))
