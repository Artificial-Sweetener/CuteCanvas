#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Authoritative storage and provenance transitions for placed raster assets."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtGui import QImage

from .model import (
    FileFingerprint,
    PlacedAssetMode,
    PlacedAssetSnapshot,
    PlacedAssetStatus,
)


class PlacedAssetStore:
    """Own placed raster pixels, provenance, status, and source revisions."""

    def __init__(self) -> None:
        """Initialize an empty asset store."""
        self._assets: dict[uuid.UUID, PlacedAssetSnapshot] = {}
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
        self._revision += 1
        return resolved_id

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
        self._revision += 1
        return resolved_id

    def get(self, asset_id: uuid.UUID) -> PlacedAssetSnapshot | None:
        """Return a detached immutable snapshot when present."""
        snapshot = self._assets.get(asset_id)
        return None if snapshot is None else snapshot

    def restore(self, asset_id: uuid.UUID, snapshot: PlacedAssetSnapshot) -> None:
        """Create or replace one asset with an exact retained snapshot."""
        self._assets[asset_id] = snapshot
        self._revision += 1

    def remove(self, asset_id: uuid.UUID) -> bool:
        """Remove one unreachable placed source."""
        if self._assets.pop(asset_id, None) is None:
            return False
        self._revision += 1
        return True

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
        self._revision += 1
        return updated
