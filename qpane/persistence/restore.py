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

from ..composition.layers import CompositionLayerSourceKind, ImageSceneLayerStore
from ..masks.mask import MaskAssetStore
from ..masks.surface import MaskSurfaceSnapshot
from .model import CompositionArchiveSnapshot


class CompositionArchiveRestorer:
    """Apply archive state across composition and mask owners with rollback."""

    def __init__(
        self,
        *,
        layers: ImageSceneLayerStore,
        masks: MaskAssetStore,
    ) -> None:
        """Bind authoritative owners mutated by restoration."""
        self._layers = layers
        self._masks = masks

    def restore(self, archive: CompositionArchiveSnapshot) -> None:
        """Apply ``archive`` atomically from the caller's perspective."""
        previous_layers = self._layers.layers_for_image(archive.image_id)
        mask_ids = self._mask_ids(archive)
        previous_masks: dict[uuid.UUID, MaskSurfaceSnapshot | None] = {
            mask_id: self._snapshot(mask_id) for mask_id in mask_ids
        }
        try:
            for mask_id, snapshot in archive.masks.items():
                self._masks.restore_mask(mask_id, snapshot)
            self._layers.replace_image_layers(archive.image_id, archive.layers)
        except Exception:
            for mask_id, snapshot in previous_masks.items():
                if snapshot is None:
                    self._masks.delete_mask(mask_id)
                else:
                    self._masks.restore_mask(mask_id, snapshot)
            if previous_layers:
                self._layers.replace_image_layers(archive.image_id, previous_layers)
            raise

    def _snapshot(self, mask_id: uuid.UUID) -> MaskSurfaceSnapshot | None:
        """Return one pre-restore surface snapshot when it exists."""
        layer = self._masks.get_layer(mask_id)
        return None if layer is None else layer.surface.snapshot()

    @staticmethod
    def _mask_ids(archive: CompositionArchiveSnapshot) -> set[uuid.UUID]:
        """Return all mask source identifiers referenced by an archive."""
        return {
            layer.source_id
            for layer in archive.layers
            if layer.source_kind is CompositionLayerSourceKind.MASK
        }
