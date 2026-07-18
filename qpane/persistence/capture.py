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
from .model import CompositionArchiveSnapshot


def capture_image_composition(
    image_id: uuid.UUID,
    layers: ImageSceneLayerStore,
    masks: MaskAssetStore,
) -> CompositionArchiveSnapshot:
    """Return a detached durable snapshot for one catalog image composition."""
    instances = layers.layers_for_image(image_id)
    if not instances:
        raise KeyError("image composition does not exist")
    surfaces = {}
    for instance in instances:
        if instance.source_kind is not CompositionLayerSourceKind.MASK:
            continue
        layer = masks.get_layer(instance.source_id)
        if layer is None:
            raise KeyError(f"mask source {instance.source_id} does not exist")
        surfaces[instance.source_id] = layer.surface.snapshot()
    return CompositionArchiveSnapshot(
        image_id=image_id,
        layers=instances,
        masks=surfaces,
    )
