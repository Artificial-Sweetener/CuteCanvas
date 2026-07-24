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
"""Transactional application of validated private composition archives."""

from __future__ import annotations

import uuid

from qpane.sdk.vector import VectorDocument

from ..composition.service import CompositionService
from ..coverage import CoverageAssetSnapshot
from ..masks.mask import MaskAssetStore
from ..placed.model import PlacedAssetSnapshot
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..raster.sparse_grid import SparseRasterSnapshot
from ..resources import ProjectResourceKind
from ..vector.store import VectorAssetStore
from .model import CompositionArchiveSnapshot


class CompositionArchiveRestorer:
    """Apply archive state across composition and mask owners with rollback."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        masks: MaskAssetStore | None,
        rasters: EditableRasterAssetStore,
        placed_assets: PlacedAssetStore,
        vectors: VectorAssetStore,
    ) -> None:
        """Bind authoritative owners mutated by restoration."""
        self._compositions = compositions
        self._layers = compositions.layers
        self._masks = masks
        self._rasters = rasters
        self._placed_assets = placed_assets
        self._vectors = vectors
        if rasters.resources is not placed_assets.resources:
            raise ValueError("persistence owners must share one project resource store")
        self._resources = rasters.resources

    def restore(self, archive: CompositionArchiveSnapshot) -> None:
        """Apply ``archive`` atomically from the caller's perspective."""
        mask_ids = self._mask_ids(archive)
        if mask_ids and self._masks is None:
            raise RuntimeError("restoring masks requires the CuteCanvas mask feature")
        previous_masks: dict[uuid.UUID, CoverageAssetSnapshot | None] = {
            mask_id: self._snapshot(mask_id) for mask_id in mask_ids
        }
        raster_ids = self._raster_ids(archive)
        previous_rasters: dict[uuid.UUID, SparseRasterSnapshot | None] = {
            raster_id: self._raster_snapshot(raster_id) for raster_id in raster_ids
        }
        placed_ids = self._placed_ids(archive)
        previous_placed: dict[uuid.UUID, PlacedAssetSnapshot | None] = {
            asset_id: self._placed_assets.get(asset_id) for asset_id in placed_ids
        }
        vector_ids = self._vector_ids(archive)
        previous_vectors: dict[uuid.UUID, VectorDocument | None] = {
            vector_id: self._vectors.get(vector_id) for vector_id in vector_ids
        }
        previous_resources = self._resources.records()
        try:
            self._resources.install(archive.resources.values())
            for mask_id, snapshot in archive.masks.items():
                assert self._masks is not None
                self._masks.restore_mask(mask_id, snapshot)
            for raster_id, snapshot in archive.rasters.items():
                self._rasters.restore_payload(raster_id, snapshot)
            for asset_id, snapshot in archive.placed_assets.items():
                self._placed_assets.restore_payload(asset_id, snapshot)
            for vector_id, document in archive.vectors.items():
                if vector_id != document.vector_id:
                    raise ValueError("vector archive key must match document identity")
                self._vectors.restore(document)
            self._compositions.restore_documents(
                dict(archive.documents),
                dict(archive.layer_stacks),
            )
        except Exception:
            self._resources.restore_state(previous_resources)
            for mask_id, snapshot in previous_masks.items():
                assert self._masks is not None
                if snapshot is None:
                    self._masks.delete_mask(mask_id)
                else:
                    self._masks.restore_mask(mask_id, snapshot)
            for raster_id, snapshot in previous_rasters.items():
                if snapshot is None:
                    self._rasters.discard_payload(raster_id)
                else:
                    self._rasters.restore_payload(raster_id, snapshot)
            for asset_id, snapshot in previous_placed.items():
                if snapshot is None:
                    self._placed_assets.discard_payload(asset_id)
                else:
                    self._placed_assets.restore_payload(asset_id, snapshot)
            for vector_id, document in previous_vectors.items():
                if document is None:
                    self._vectors.remove(vector_id)
                else:
                    self._vectors.restore(document)
            raise

    def _snapshot(self, mask_id: uuid.UUID) -> CoverageAssetSnapshot | None:
        """Return one complete pre-restore hybrid snapshot when it exists."""
        if self._masks is None:
            return None
        layer = self._masks.get_layer(mask_id)
        return None if layer is None else layer.coverage.state_snapshot()

    def _raster_snapshot(self, raster_id: uuid.UUID) -> SparseRasterSnapshot | None:
        """Return one pre-restore color surface snapshot when it exists."""
        asset = self._rasters.get(raster_id)
        return None if asset is None else asset.surface.sparse_snapshot()

    @staticmethod
    def _mask_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all mask source identifiers referenced by an archive."""
        return {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.COVERAGE
        }

    @staticmethod
    def _raster_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all editable raster identifiers referenced by an archive."""
        return {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.RASTER
        }

    @staticmethod
    def _placed_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all placed identifiers referenced by an archive."""
        return {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind
            in {
                ProjectResourceKind.IMPORTED_RASTER,
                ProjectResourceKind.LINKED_RASTER,
            }
        }

    @staticmethod
    def _vector_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all vector identifiers referenced by an archive."""
        return {
            resource_id
            for resource_id, resource in archive.resources.items()
            if resource.kind is ProjectResourceKind.VECTOR
        }
