#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Private durable composition archive round-trip and validation tests."""

from __future__ import annotations

import json
import uuid
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage

from qpane import RasterExtentPolicy
from qpane.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from qpane.masks.mask import MaskAssetStore
from qpane.persistence import (
    CompositionArchiveCodec,
    CompositionArchiveRestorer,
    capture_image_composition,
)
from qpane.scene.model import LayerInteractionPolicy, LayerPlacement
from qpane.scene.raster import LayerTransform, RasterBounds


def test_private_archive_round_trip_restores_order_transform_and_off_canvas_pixels(
    tmp_path,
) -> None:
    """Every durable authoring value should survive a private archive round trip."""
    image_id = uuid.uuid4()
    layers = ImageSceneLayerStore()
    layers.ensure_image(image_id, LayerPlacement(0.0, 0.0, 8.0, 6.0))
    masks = MaskAssetStore()
    mask_id = masks.create_mask(QImage(8, 6, QImage.Format_Grayscale8))
    mask = masks.get_layer(mask_id)
    assert mask is not None
    expanded_bounds = RasterBounds(-3, -2, 13, 10)
    mask.surface.set_extent_policy(RasterExtentPolicy.EXPAND_ON_WRITE)
    mask.surface.set_bounds(expanded_bounds)
    mask.surface.mutate(lambda pixels, _image: pixels.__setitem__((1, 1), 217))
    mask_instance = CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source_kind=CompositionLayerSourceKind.MASK,
        source_id=mask_id,
        transform=LayerTransform(1.0, 1.0, 12.0, -4.0),
        opacity=0.35,
        tint=QColor(12, 34, 56, 200),
        interaction=LayerInteractionPolicy(selectable=True, movable=True),
        role="mask",
        label="Off canvas",
    )
    assert layers.add_layer(image_id, mask_instance)
    assert layers.reorder_layer(image_id, mask_instance.layer_id, 0)
    archive_path = tmp_path / "composition.qpc"
    codec = CompositionArchiveCodec()

    codec.write(capture_image_composition(image_id, layers, masks), archive_path)
    decoded = codec.read(archive_path)
    restored_layers = ImageSceneLayerStore()
    restored_layers.ensure_image(image_id, LayerPlacement(0.0, 0.0, 8.0, 6.0))
    restored_masks = MaskAssetStore()
    CompositionArchiveRestorer(
        layers=restored_layers,
        masks=restored_masks,
    ).restore(decoded)

    assert restored_layers.layers_for_image(image_id) == layers.layers_for_image(
        image_id
    )
    restored_mask = restored_masks.get_layer(mask_id)
    assert restored_mask is not None
    restored = restored_mask.surface.snapshot()
    assert restored.bounds == expanded_bounds
    assert restored.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
    assert restored.pixels[1, 1] == 217
    assert restored.pixels.shape == (10, 13)


def test_archive_rejects_unknown_version_before_restoration(tmp_path) -> None:
    """Readers should reject future formats without returning partial state."""
    path = tmp_path / "future.qpc"
    manifest = {
        "format": "qpane-composition",
        "version": 999,
        "image_id": str(uuid.uuid4()),
        "layers": [],
        "masks": {},
    }
    with zipfile.ZipFile(path, "w") as container:
        container.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="version"):
        CompositionArchiveCodec().read(path)


def test_archive_write_replaces_destination_without_leaving_temp_files(
    tmp_path,
) -> None:
    """Successful writes should atomically replace an existing archive path."""
    image_id = uuid.uuid4()
    layers = ImageSceneLayerStore()
    layers.ensure_image(image_id, LayerPlacement(0.0, 0.0, 2.0, 2.0))
    masks = MaskAssetStore()
    path = tmp_path / "composition.qpc"
    path.write_bytes(b"old")

    CompositionArchiveCodec().write(
        capture_image_composition(image_id, layers, masks),
        path,
    )

    assert zipfile.is_zipfile(path)
    assert not tuple(tmp_path.glob(".composition.qpc.*.tmp"))
