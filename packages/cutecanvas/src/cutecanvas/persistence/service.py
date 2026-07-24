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
from .capture import capture_composition
from .codec import CompositionArchiveCodec
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
