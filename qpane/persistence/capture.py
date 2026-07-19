#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Capture authoritative composition and raster-source state for persistence."""

from __future__ import annotations

import uuid

from ..composition.layers import CompositionLayerSourceKind, ImageSceneLayerStore
from ..masks.mask import MaskAssetStore
from ..raster.assets import EditableRasterAssetStore
from .model import CompositionArchiveSnapshot


def capture_image_composition(
    image_id: uuid.UUID,
    layers: ImageSceneLayerStore,
    masks: MaskAssetStore,
    rasters: EditableRasterAssetStore,
) -> CompositionArchiveSnapshot:
    """Return a detached durable snapshot for one catalog image composition."""
    instances = layers.layers_for_image(image_id)
    if not instances:
        raise KeyError("image composition does not exist")
    mask_surfaces = {}
    color_surfaces = {}
    for instance in instances:
        if instance.source_kind is CompositionLayerSourceKind.MASK:
            layer = masks.get_layer(instance.source_id)
            if layer is None:
                raise KeyError(f"mask source {instance.source_id} does not exist")
            mask_surfaces[instance.source_id] = layer.surface.snapshot()
        elif instance.source_kind is CompositionLayerSourceKind.RASTER:
            asset = rasters.get(instance.source_id)
            if asset is None:
                raise KeyError(f"raster source {instance.source_id} does not exist")
            color_surfaces[instance.source_id] = asset.surface.snapshot()
    return CompositionArchiveSnapshot(
        image_id=image_id,
        layers=instances,
        masks=mask_surfaces,
        rasters=color_surfaces,
    )
