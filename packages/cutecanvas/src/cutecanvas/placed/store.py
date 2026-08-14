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
"""Authoritative storage and provenance transitions for placed raster assets."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from cutecanvas.resources import ProjectResourceKind, ProjectResourceStore
from qpane.sdk.raster import qimage_to_numpy_const_view_bgra32

from ..raster.content_bounds import occupied_channel_bounds
from .model import (
    FileFingerprint,
    PlacedAssetMode,
    PlacedAssetSnapshot,
    PlacedAssetStatus,
)


class PlacedAssetStore:
    """Own placed raster pixels, provenance, status, and source revisions."""

    def __init__(self, resources: ProjectResourceStore | None = None) -> None:
        """Initialize payloads under one project-resource identity owner."""
        self._resources = resources or ProjectResourceStore()
        self._assets: dict[uuid.UUID, PlacedAssetSnapshot] = {}
        self._content_bounds: dict[uuid.UUID, QRectF | None] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        """Return aggregate placed-asset state revision."""
        return self._revision

    def create_embedded(
        self,
        image: QImage,
        *,
        asset_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Create one embedded source from detached valid pixels."""
        if image.isNull():
            raise ValueError("placed asset image must not be null")
        resolved_id = asset_id or uuid.uuid4()
        if resolved_id in self._assets:
            raise ValueError("placed asset ID already exists")
        self._resources.create(
            ProjectResourceKind.IMPORTED_RASTER,
            editable=False,
            resource_id=resolved_id,
        )
        self._assets[resolved_id] = PlacedAssetSnapshot(
            image=QImage(image),
            source_size=image.size(),
            mode=PlacedAssetMode.EMBEDDED,
            source_path=None,
            status=PlacedAssetStatus.READY,
            error=None,
            keep_fallback=True,
            fingerprint=None,
            content_revision=0,
            generation=0,
        )
        self._content_bounds[resolved_id] = _image_content_bounds(image)
        self._revision += 1
        return resolved_id

    def replace_embedded(self, asset_id: uuid.UUID, image: QImage) -> bool:
        """Replace embedded pixels while preserving resource identity and provenance."""
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("placed asset image must not be null")
        current = self._assets.get(asset_id)
        if current is None:
            raise KeyError(f"unknown placed asset: {asset_id}")
        if current.mode is not PlacedAssetMode.EMBEDDED:
            raise ValueError("placed asset must be embedded")
        self._assets[asset_id] = PlacedAssetSnapshot(
            image=QImage(image),
            source_size=image.size(),
            mode=PlacedAssetMode.EMBEDDED,
            source_path=None,
            status=PlacedAssetStatus.READY,
            error=None,
            keep_fallback=True,
            fingerprint=None,
            content_revision=current.content_revision + 1,
            generation=current.generation,
        )
        self._content_bounds[asset_id] = _image_content_bounds(image)
        self._resources.touch(asset_id)
        self._revision += 1
        return True

    def create_linked(
        self,
        image: QImage,
        path: Path,
        fingerprint: FileFingerprint,
        *,
        keep_fallback: bool,
        asset_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Create one linked source after successful off-thread decoding."""
        if image.isNull():
            raise ValueError("linked placed asset image must not be null")
        resolved_id = asset_id or uuid.uuid4()
        if resolved_id in self._assets:
            raise ValueError("placed asset ID already exists")
        self._resources.create(
            ProjectResourceKind.LINKED_RASTER,
            editable=False,
            resource_id=resolved_id,
        )
        self._assets[resolved_id] = PlacedAssetSnapshot(
            image=QImage(image),
            source_size=image.size(),
            mode=PlacedAssetMode.LINKED,
            source_path=Path(path),
            status=PlacedAssetStatus.READY,
            error=None,
            keep_fallback=bool(keep_fallback),
            fingerprint=fingerprint,
            content_revision=0,
            generation=0,
        )
        self._content_bounds[resolved_id] = _image_content_bounds(image)
        self._revision += 1
        return resolved_id

    def get(self, asset_id: uuid.UUID) -> PlacedAssetSnapshot | None:
        """Return a detached immutable snapshot when present."""
        snapshot = self._assets.get(asset_id)
        return None if snapshot is None else snapshot

    def content_bounds(self, asset_id: uuid.UUID) -> QRectF | None:
        """Return cached alpha-tight bounds for one retained image."""
        bounds = self._content_bounds.get(asset_id)
        return None if bounds is None else QRectF(bounds)

    def fork(self, asset_id: uuid.UUID) -> uuid.UUID | None:
        """Clone provenance and pixels into an independent project resource."""
        snapshot = self._assets.get(asset_id)
        if snapshot is None:
            return None
        fork_id = uuid.uuid4()
        self._resources.create(
            self._resource_kind(snapshot.mode),
            editable=False,
            resource_id=fork_id,
        )
        self._assets[fork_id] = snapshot
        bounds = self._content_bounds.get(asset_id)
        self._content_bounds[fork_id] = None if bounds is None else QRectF(bounds)
        self._revision += 1
        return fork_id

    def restore(self, asset_id: uuid.UUID, snapshot: PlacedAssetSnapshot) -> None:
        """Create or replace one asset with an exact retained snapshot."""
        resource_kind = self._resource_kind(snapshot.mode)
        existing = self._resources.get(asset_id)
        if existing is None:
            self._resources.create(
                resource_kind,
                editable=False,
                resource_id=asset_id,
            )
        self._assets[asset_id] = snapshot
        self._content_bounds[asset_id] = _optional_image_content_bounds(snapshot.image)
        if existing is None:
            pass
        elif existing.kind is not resource_kind:
            self._resources.set_kind(asset_id, resource_kind)
        else:
            self._resources.touch(asset_id)
        self._revision += 1

    def restore_payload(
        self,
        asset_id: uuid.UUID,
        snapshot: PlacedAssetSnapshot,
    ) -> None:
        """Restore provenance beneath an already restored project-resource record."""
        resource = self._resources.get(asset_id)
        if resource is None or resource.kind is not self._resource_kind(snapshot.mode):
            raise ValueError("placed payload does not match its resource record")
        self._assets[asset_id] = snapshot
        self._content_bounds[asset_id] = _optional_image_content_bounds(snapshot.image)
        self._revision += 1

    def remove(self, asset_id: uuid.UUID) -> bool:
        """Remove one unreachable placed source."""
        if asset_id not in self._assets:
            return False
        self._resources.remove(asset_id)
        self._assets.pop(asset_id)
        self._content_bounds.pop(asset_id, None)
        self._revision += 1
        return True

    def discard_payload(self, asset_id: uuid.UUID) -> bool:
        """Discard provenance while a transaction restores resource records."""
        removed = self._assets.pop(asset_id, None) is not None
        if removed:
            self._content_bounds.pop(asset_id, None)
            self._revision += 1
        return removed

    def begin_reload(self, asset_id: uuid.UUID, path: Path | None = None) -> int | None:
        """Advance generation and mark a linked source as loading."""
        current = self._assets.get(asset_id)
        if (
            current is None
            or current.mode is not PlacedAssetMode.LINKED
            or current.image is None
        ):
            return None
        generation = current.generation + 1
        self._assets[asset_id] = PlacedAssetSnapshot(
            image=current.image,
            source_size=current.source_size,
            mode=current.mode,
            source_path=current.source_path if path is None else Path(path),
            status=PlacedAssetStatus.LOADING,
            error=None,
            keep_fallback=current.keep_fallback,
            fingerprint=current.fingerprint,
            content_revision=current.content_revision,
            generation=generation,
        )
        self._resources.touch(asset_id)
        self._revision += 1
        return generation

    def complete_reload(
        self,
        asset_id: uuid.UUID,
        generation: int,
        image: QImage,
        path: Path,
        fingerprint: FileFingerprint,
    ) -> PlacedAssetSnapshot | None:
        """Publish decoded pixels only when their generation is current."""
        current = self._assets.get(asset_id)
        if (
            current is None
            or current.mode is not PlacedAssetMode.LINKED
            or current.generation != generation
            or image.isNull()
        ):
            return None
        updated = PlacedAssetSnapshot(
            image=QImage(image),
            source_size=image.size(),
            mode=PlacedAssetMode.LINKED,
            source_path=Path(path),
            status=PlacedAssetStatus.READY,
            error=None,
            keep_fallback=current.keep_fallback,
            fingerprint=fingerprint,
            content_revision=current.content_revision + 1,
            generation=generation,
        )
        self._assets[asset_id] = updated
        self._content_bounds[asset_id] = _image_content_bounds(image)
        self._resources.touch(asset_id)
        self._revision += 1
        return updated

    def fail_reload(
        self,
        asset_id: uuid.UUID,
        generation: int,
        message: str,
        *,
        missing: bool,
    ) -> PlacedAssetSnapshot | None:
        """Retain last valid pixels while publishing a current link failure."""
        current = self._assets.get(asset_id)
        if current is None or current.generation != generation:
            return None
        updated = PlacedAssetSnapshot(
            image=current.image,
            source_size=current.source_size,
            mode=current.mode,
            source_path=current.source_path,
            status=(PlacedAssetStatus.MISSING if missing else PlacedAssetStatus.ERROR),
            error=message,
            keep_fallback=current.keep_fallback,
            fingerprint=current.fingerprint,
            content_revision=current.content_revision,
            generation=generation,
        )
        self._assets[asset_id] = updated
        self._resources.touch(asset_id)
        self._revision += 1
        return updated

    def embed(self, asset_id: uuid.UUID) -> PlacedAssetSnapshot | None:
        """Detach one linked source from external provenance without changing pixels."""
        current = self._assets.get(asset_id)
        if current is None or current.mode is not PlacedAssetMode.LINKED:
            return None
        updated = PlacedAssetSnapshot(
            image=current.image,
            source_size=current.source_size,
            mode=PlacedAssetMode.EMBEDDED,
            source_path=None,
            status=PlacedAssetStatus.READY,
            error=None,
            keep_fallback=True,
            fingerprint=None,
            content_revision=current.content_revision,
            generation=current.generation + 1,
        )
        self._assets[asset_id] = updated
        self._resources.set_kind(asset_id, ProjectResourceKind.IMPORTED_RASTER)
        self._revision += 1
        return updated

    @property
    def resources(self) -> ProjectResourceStore:
        """Return the authoritative resource identity owner."""
        return self._resources

    @staticmethod
    def _resource_kind(mode: PlacedAssetMode) -> ProjectResourceKind:
        """Map provenance mode to its project-resource content kind."""
        return (
            ProjectResourceKind.LINKED_RASTER
            if mode is PlacedAssetMode.LINKED
            else ProjectResourceKind.IMPORTED_RASTER
        )


def _optional_image_content_bounds(image: QImage | None) -> QRectF | None:
    """Return alpha-tight bounds when retained pixels are available."""
    return None if image is None else _image_content_bounds(image)


def _image_content_bounds(image: QImage) -> QRectF | None:
    """Compute alpha-tight bounds once when placed pixels enter the store."""
    pixels, _backing = qimage_to_numpy_const_view_bgra32(image)
    occupied = occupied_channel_bounds(pixels[:, :, 3])
    if occupied is None:
        return None
    return QRectF(
        float(occupied.x),
        float(occupied.y),
        float(occupied.width),
        float(occupied.height),
    )
