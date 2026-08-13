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
"""Identity and lifecycle ownership for editable color raster assets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cutecanvas.resources import ProjectResourceKind, ProjectResourceStore
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtGui import QImage
from qpane.sdk.raster import numpy_to_qimage_argb32
from qpane.sdk.scene import RasterBounds

from .color_surface import ColorRasterSnapshot, ColorRasterSurface
from .sparse_grid import SparseRasterSnapshot


@dataclass(slots=True)
class EditableRasterAsset:
    """Bind one stable source identity to authoritative color storage."""

    raster_id: uuid.UUID
    surface: ColorRasterSurface


class EditableRasterAssetStore:
    """Own editable raster asset creation, lookup, and deletion."""

    def __init__(self, resources: ProjectResourceStore | None = None) -> None:
        """Initialize assets under one project-resource identity owner."""
        self._resources = resources or ProjectResourceStore()
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
        resource = self._resources.create(
            ProjectResourceKind.RASTER,
            editable=True,
        )
        raster_id = resource.resource_id
        return self._retain_surface(
            raster_id,
            ColorRasterSurface(
                image,
                bounds=bounds,
                extent_policy=extent_policy,
                changed=lambda: self._resource_changed(raster_id),
            ),
        )

    def create_empty(
        self,
        bounds: RasterBounds,
        *,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.UNBOUNDED,
    ) -> EditableRasterAsset:
        """Create a logical transparent extent without allocating pixel tiles."""
        resource = self._resources.create(
            ProjectResourceKind.RASTER,
            editable=True,
        )
        raster_id = resource.resource_id
        surface = ColorRasterSurface.from_sparse_snapshot(
            SparseRasterSnapshot(
                bounds,
                extent_policy,
                channels=4,
                tile_size=512,
                tiles=(),
            ),
            changed=lambda: self._resource_changed(raster_id),
        )
        return self._retain_surface(raster_id, surface)

    def get(self, raster_id: uuid.UUID) -> EditableRasterAsset | None:
        """Return one editable raster asset when present."""
        return self._assets.get(raster_id)

    def ids(self) -> tuple[uuid.UUID, ...]:
        """Return stable identities for all retained editable raster assets."""
        return tuple(self._assets)

    def fork(self, raster_id: uuid.UUID) -> uuid.UUID | None:
        """Clone one editable raster into an independent project resource."""
        asset = self._assets.get(raster_id)
        if asset is None:
            return None
        clone = self.create(
            asset.surface.snapshot_qimage(),
            bounds=asset.surface.bounds,
            extent_policy=asset.surface.extent_policy,
        )
        return clone.raster_id

    def restore(
        self,
        raster_id: uuid.UUID,
        snapshot: ColorRasterSnapshot | SparseRasterSnapshot,
    ) -> None:
        """Install a validated durable raster snapshot at a stable identity."""
        self._validate_restore(raster_id, snapshot)
        if self._resources.get(raster_id) is None:
            self._resources.create(
                ProjectResourceKind.RASTER,
                editable=True,
                resource_id=raster_id,
            )
        else:
            self._resources.touch(raster_id)
        self._restore_payload(raster_id, snapshot)

    def restore_payload(
        self,
        raster_id: uuid.UUID,
        snapshot: ColorRasterSnapshot | SparseRasterSnapshot,
    ) -> None:
        """Restore pixels beneath an already restored project-resource record."""
        self._validate_restore(raster_id, snapshot)
        record = self._resources.get(raster_id)
        if record is None or record.kind is not ProjectResourceKind.RASTER:
            raise ValueError("raster payload requires a raster resource record")
        self._restore_payload(raster_id, snapshot)

    @staticmethod
    def _validate_restore(
        raster_id: uuid.UUID,
        snapshot: ColorRasterSnapshot | SparseRasterSnapshot,
    ) -> None:
        """Validate stable identity and supported snapshot values."""
        if not isinstance(raster_id, uuid.UUID):
            raise TypeError("raster_id must be a UUID")
        if not isinstance(snapshot, (ColorRasterSnapshot, SparseRasterSnapshot)):
            raise TypeError("snapshot must be a color raster state snapshot")

    def _restore_payload(
        self,
        raster_id: uuid.UUID,
        snapshot: ColorRasterSnapshot | SparseRasterSnapshot,
    ) -> None:
        """Install one already validated raster payload."""
        surface = (
            ColorRasterSurface.from_sparse_snapshot(
                snapshot,
                changed=lambda: self._resource_changed(raster_id),
            )
            if isinstance(snapshot, SparseRasterSnapshot)
            else ColorRasterSurface(
                numpy_to_qimage_argb32(snapshot.pixels),
                bounds=snapshot.bounds,
                extent_policy=snapshot.extent_policy,
                changed=lambda: self._resource_changed(raster_id),
            )
        )
        self._assets[raster_id] = EditableRasterAsset(
            raster_id,
            surface,
        )

    def remove(self, raster_id: uuid.UUID) -> bool:
        """Delete one editable raster asset."""
        if raster_id not in self._assets:
            return False
        self._resources.remove(raster_id)
        self._assets.pop(raster_id)
        return True

    def discard_payload(self, raster_id: uuid.UUID) -> bool:
        """Discard pixels while a transaction separately restores resource records."""
        return self._assets.pop(raster_id, None) is not None

    def clear(self) -> None:
        """Delete every editable raster asset."""
        for raster_id in tuple(self._assets):
            self.remove(raster_id)

    @property
    def resources(self) -> ProjectResourceStore:
        """Return the authoritative resource identity owner."""
        return self._resources

    def _resource_changed(self, raster_id: uuid.UUID) -> None:
        """Advance shared and dependent resource revisions after pixel changes."""
        if self._resources.get(raster_id) is not None:
            self._resources.touch(raster_id)

    def _retain_surface(
        self,
        raster_id: uuid.UUID,
        surface: ColorRasterSurface,
    ) -> EditableRasterAsset:
        """Retain one initialized surface beneath its resource identity."""
        asset = EditableRasterAsset(raster_id, surface)
        self._assets[raster_id] = asset
        return asset
