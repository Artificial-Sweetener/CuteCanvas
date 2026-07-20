#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Identity and lifecycle ownership for editable color raster assets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtGui import QImage

from ..scene.raster import RasterBounds, RasterExtentPolicy
from .color_surface import ColorRasterSnapshot, ColorRasterSurface
from .image_conversion import numpy_to_qimage_argb32
from .sparse_grid import SparseRasterSnapshot


@dataclass(slots=True)
class EditableRasterAsset:
    """Bind one stable source identity to authoritative color storage."""

    raster_id: uuid.UUID
    surface: ColorRasterSurface


class EditableRasterAssetStore:
    """Own editable raster asset creation, lookup, and deletion."""

    def __init__(self) -> None:
        """Initialize an empty asset collection."""
        self._assets: dict[uuid.UUID, EditableRasterAsset] = {}

    @property
    def revision(self) -> tuple[tuple[uuid.UUID, int, int], ...]:
        """Return all source revisions affecting assembled layer descriptors."""
        return tuple(
            (raster_id, *asset.surface.revisions())
            for raster_id, asset in self._assets.items()
        )

    def create(
        self,
        image: QImage,
        *,
        bounds: RasterBounds | None = None,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> EditableRasterAsset:
        """Create and retain one detached editable raster asset."""
        raster_id = uuid.uuid4()
        asset = EditableRasterAsset(
            raster_id,
            ColorRasterSurface(image, bounds=bounds, extent_policy=extent_policy),
        )
        self._assets[raster_id] = asset
        return asset

    def get(self, raster_id: uuid.UUID) -> EditableRasterAsset | None:
        """Return one editable raster asset when present."""
        return self._assets.get(raster_id)

    def ids(self) -> tuple[uuid.UUID, ...]:
        """Return stable identities for all retained editable raster assets."""
        return tuple(self._assets)

    def restore(
        self,
        raster_id: uuid.UUID,
        snapshot: ColorRasterSnapshot | SparseRasterSnapshot,
    ) -> None:
        """Install a validated durable raster snapshot at a stable identity."""
        if not isinstance(raster_id, uuid.UUID):
            raise TypeError("raster_id must be a UUID")
        if not isinstance(snapshot, (ColorRasterSnapshot, SparseRasterSnapshot)):
            raise TypeError("snapshot must be a color raster state snapshot")
        surface = (
            ColorRasterSurface.from_sparse_snapshot(snapshot)
            if isinstance(snapshot, SparseRasterSnapshot)
            else ColorRasterSurface(
                numpy_to_qimage_argb32(snapshot.pixels),
                bounds=snapshot.bounds,
                extent_policy=snapshot.extent_policy,
            )
        )
        self._assets[raster_id] = EditableRasterAsset(
            raster_id,
            surface,
        )

    def remove(self, raster_id: uuid.UUID) -> bool:
        """Delete one editable raster asset."""
        return self._assets.pop(raster_id, None) is not None

    def clear(self) -> None:
        """Delete every editable raster asset."""
        self._assets.clear()
