#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Transactional application of validated private composition archives."""

from __future__ import annotations

import uuid

from ..composition.service import CompositionService
from ..masks.mask import MaskAssetStore
from ..masks.source_reference import MaskAssetReference
from ..placed.model import PlacedAssetSnapshot
from ..placed.source_reference import PlacedAssetReference
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..raster.source_reference import EditableRasterReference
from ..raster.sparse_grid import SparseRasterSnapshot
from ..vector.model import VectorDocument
from ..vector.source_reference import VectorDocumentReference
from ..vector.store import VectorAssetStore
from .model import CompositionArchiveSnapshot


class CompositionArchiveRestorer:
    """Apply archive state across composition and mask owners with rollback."""

    def __init__(
        self,
        *,
        compositions: CompositionService,
        masks: MaskAssetStore,
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

    def restore(self, archive: CompositionArchiveSnapshot) -> None:
        """Apply ``archive`` atomically from the caller's perspective."""
        mask_ids = self._mask_ids(archive)
        previous_masks: dict[uuid.UUID, SparseRasterSnapshot | None] = {
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
        try:
            for mask_id, snapshot in archive.masks.items():
                self._masks.restore_mask(mask_id, snapshot)
            for raster_id, snapshot in archive.rasters.items():
                self._rasters.restore(raster_id, snapshot)
            for asset_id, snapshot in archive.placed_assets.items():
                self._placed_assets.restore(asset_id, snapshot)
            for vector_id, document in archive.vectors.items():
                if vector_id != document.vector_id:
                    raise ValueError("vector archive key must match document identity")
                self._vectors.restore(document)
            self._compositions.restore_document(archive.document, archive.layers)
        except Exception:
            for mask_id, snapshot in previous_masks.items():
                if snapshot is None:
                    self._masks.delete_mask(mask_id)
                else:
                    self._masks.restore_mask(mask_id, snapshot)
            for raster_id, snapshot in previous_rasters.items():
                if snapshot is None:
                    self._rasters.remove(raster_id)
                else:
                    self._rasters.restore(raster_id, snapshot)
            for asset_id, snapshot in previous_placed.items():
                if snapshot is None:
                    self._placed_assets.remove(asset_id)
                else:
                    self._placed_assets.restore(asset_id, snapshot)
            for vector_id, document in previous_vectors.items():
                if document is None:
                    self._vectors.remove(vector_id)
                else:
                    self._vectors.restore(document)
            raise

    def _snapshot(self, mask_id: uuid.UUID) -> SparseRasterSnapshot | None:
        """Return one pre-restore surface snapshot when it exists."""
        layer = self._masks.get_layer(mask_id)
        return None if layer is None else layer.surface.sparse_snapshot()

    def _raster_snapshot(self, raster_id: uuid.UUID) -> SparseRasterSnapshot | None:
        """Return one pre-restore color surface snapshot when it exists."""
        asset = self._rasters.get(raster_id)
        return None if asset is None else asset.surface.sparse_snapshot()

    @staticmethod
    def _mask_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all mask source identifiers referenced by an archive."""
        return {
            layer.source.mask_id
            for layer in archive.layers
            if isinstance(layer.source, MaskAssetReference)
        }

    @staticmethod
    def _raster_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all editable raster identifiers referenced by an archive."""
        return {
            layer.source.raster_id
            for layer in archive.layers
            if isinstance(layer.source, EditableRasterReference)
        }

    @staticmethod
    def _placed_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all placed identifiers referenced by an archive."""
        return {
            layer.source.asset_id
            for layer in archive.layers
            if isinstance(layer.source, PlacedAssetReference)
        }

    @staticmethod
    def _vector_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all vector identifiers referenced by an archive."""
        return {
            layer.source.vector_id
            for layer in archive.layers
            if isinstance(layer.source, VectorDocumentReference)
        }
