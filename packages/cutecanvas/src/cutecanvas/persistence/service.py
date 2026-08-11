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
"""Authoritative document archive coordination over editor domain owners."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from ..composition.service import CompositionService
from ..masks.mask import MaskAssetStore
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..vector.store import VectorAssetStore
from .capture import capture_composition, capture_document
from .codec import CompositionArchiveCodec
from .model import CompositionArchiveSnapshot
from .restore import CompositionArchiveRestorer


class CompositionPersistenceService:
    """Save and restore complete documents without duplicating domain state."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        masks: Callable[[], MaskAssetStore | None],
        rasters: EditableRasterAssetStore,
        placed_assets: PlacedAssetStore,
        vectors: VectorAssetStore,
    ) -> None:
        """Bind every authoritative resource owner needed by the archive codec."""
        self._compositions = compositions
        self._masks = masks
        self._rasters = rasters
        self._placed_assets = placed_assets
        self._vectors = vectors
        self._codec = CompositionArchiveCodec()

    def save(self, document_id: uuid.UUID, path: Path) -> None:
        """Atomically save one complete document archive to ``path``."""
        archive = capture_composition(
            document_id,
            self._compositions,
            self._masks(),
            self._rasters,
            self._placed_assets,
            self._vectors,
        )
        self._codec.write(archive, path)

    def load(self, path: Path) -> uuid.UUID:
        """Validate and transactionally restore one document archive."""
        archive = self._codec.read(path)
        CompositionArchiveRestorer(
            compositions=self._compositions,
            masks=self._masks(),
            rasters=self._rasters,
            placed_assets=self._placed_assets,
            vectors=self._vectors,
        ).restore(archive)
        return archive.composition_id

    def save_document(self, path: Path) -> tuple[uuid.UUID, ...]:
        """Atomically save every independent composition to one archive."""
        archive = self.capture_document()
        self.write_document(archive, path)
        return archive.root_document_ids

    def capture_document(self) -> CompositionArchiveSnapshot:
        """Capture a detached snapshot of every independent composition."""
        composition_ids = self._compositions.composition_ids()
        return capture_document(
            composition_ids,
            self._compositions,
            self._masks(),
            self._rasters,
            self._placed_assets,
            self._vectors,
        )

    def write_document(
        self,
        archive: CompositionArchiveSnapshot,
        path: Path,
    ) -> None:
        """Atomically write one previously detached document snapshot."""
        self._codec.write(archive, path)

    def load_document(self, path: Path) -> tuple[uuid.UUID, ...]:
        """Validate and transactionally restore all roots from one archive."""
        archive = self._codec.read(path)
        return self.restore_document(archive)

    def restore_document(
        self,
        archive: CompositionArchiveSnapshot,
    ) -> tuple[uuid.UUID, ...]:
        """Transactionally install one previously validated document archive."""
        CompositionArchiveRestorer(
            compositions=self._compositions,
            masks=self._masks(),
            rasters=self._rasters,
            placed_assets=self._placed_assets,
            vectors=self._vectors,
        ).restore(archive)
        return archive.root_document_ids
