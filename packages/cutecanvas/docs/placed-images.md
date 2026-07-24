# Placed Images

A placed image is a non-destructive image layer. It keeps an original asset
separate from the document transform, so the user can move, scale, rotate, and
duplicate it without repeatedly resampling source pixels.

## Embed an Image

Embedded assets travel with the editable document:

```python
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

layer_id = canvas.placeEmbeddedAsset(
    QImage("sticker.png"),
    placement=QRectF(200.0, 120.0, 640.0, 640.0),
    label="Sticker",
)
```

The returned UUID identifies the new layer. It can be selected, moved,
transformed, reordered, hidden, duplicated, or removed like any other eligible
document layer.

## Link a File

A linked asset records its source path and can be refreshed when the file
changes:

```python
from pathlib import Path

layer_id = canvas.placeLinkedAsset(
    Path("artwork.png"),
    label="Linked artwork",
    keep_fallback=True,
)
```

`keep_fallback=True` stores enough image data for the document to remain
visible when the original file is temporarily unavailable. Read
`placedAssetState(scene_id, layer_id)` to inspect mode, status, path, source
size, and revision.

Use `refreshPlacedAsset()` after an external change, or `relinkPlacedAsset()`
when the user chooses a new file. Both operations update the placed source
without discarding the layer's transform or stack position.

## Embed a Linked Asset

`embedPlacedAsset(scene_id, layer_id)` converts a linked layer to embedded
storage. Its appearance and transform remain unchanged, while future document
saves no longer depend on the external path.

## Duplicate Without Resampling

`duplicateLayer(scene_id, layer_id)` creates another layer instance that
references the same immutable source. Each instance keeps independent
placement, visibility, effects, and policy while sharing renderer products.

## Rasterize for Pixel Editing

Placed assets reject direct painting and pixel deletion. Rasterize when the
user chooses to edit their pixels:

```python
raster_layer_id = canvas.rasterizeLayer(
    scene.scene_id,
    layer_id,
)
```

The replacement is an editable raster at the current placed resolution. It no
longer follows or refreshes the original asset. This is a document edit and
participates in normal undo and redo.

Pass `pixel_size` when the host needs an explicit rasterization resolution.
Otherwise CuteCanvas chooses the layer's current source resolution.

## Save and Restore

Editable document persistence keeps embedded bytes, linked paths, fallback
data, transforms, and layer identity. A flattened image export contains only
the rendered result inside document bounds.

## Related Docs

* [Documents and Layers](scenes.md): Arrange and control layer instances.
* [Painting](painting.md): Work with editable raster layers.
* [Interaction and Tools](interaction-modes.md): Move, transform, and snap.

**Continue →** [Vector Layers](vector-layers.md)
