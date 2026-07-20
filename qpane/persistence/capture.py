#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Capture authoritative composition and raster-source state for persistence."""

from __future__ import annotations

from ..composition.layers import CompositionLayerStore, instance_resources
from ..composition.model import CompositionRecord
from ..masks.mask import MaskAssetStore
from ..masks.source_reference import MaskAssetReference
from ..placed.source_reference import PlacedAssetReference
from ..placed.store import PlacedAssetStore
from ..raster.assets import EditableRasterAssetStore
from ..raster.source_reference import EditableRasterReference
from ..vector.source_reference import VectorDocumentReference
from ..vector.store import VectorAssetStore
from .model import CompositionArchiveSnapshot


def capture_composition(
    document: CompositionRecord,
    layers: CompositionLayerStore,
    masks: MaskAssetStore,
    rasters: EditableRasterAssetStore,
    placed_assets: PlacedAssetStore,
    vectors: VectorAssetStore,
) -> CompositionArchiveSnapshot:
    """Return a detached durable snapshot for one composition document."""
    instances = layers.layers_for_composition(document.composition_id)
    mask_surfaces = {}
    color_surfaces = {}
    placed_snapshots = {}
    vector_documents = {}
    for instance in instances:
        for source in instance_resources(instance):
            if isinstance(source, MaskAssetReference):
                layer = masks.get_layer(source.mask_id)
                if layer is None:
                    raise KeyError(f"mask source {source.mask_id} does not exist")
                mask_surfaces[source.mask_id] = layer.surface.sparse_snapshot()
            elif isinstance(source, EditableRasterReference):
                asset = rasters.get(source.raster_id)
                if asset is None:
                    raise KeyError(f"raster source {source.raster_id} does not exist")
                color_surfaces[source.raster_id] = asset.surface.sparse_snapshot()
            elif isinstance(source, PlacedAssetReference):
                snapshot = placed_assets.get(source.asset_id)
                if snapshot is None:
                    raise KeyError(f"placed source {source.asset_id} does not exist")
                placed_snapshots[source.asset_id] = snapshot
            elif isinstance(source, VectorDocumentReference):
                vector_document = vectors.get(source.vector_id)
                if vector_document is None:
                    raise KeyError(f"vector source {source.vector_id} does not exist")
                vector_documents[source.vector_id] = vector_document
    return CompositionArchiveSnapshot(
        document=document,
        layers=instances,
        masks=mask_surfaces,
        rasters=color_surfaces,
        placed_assets=placed_snapshots,
        vectors=vector_documents,
    )
