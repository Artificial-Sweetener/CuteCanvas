# Catalog and Navigation

CuteCanvas keeps source images separate from editable documents. The catalog is
an ordered library of images that a host can browse, reuse in several documents,
or open as a ready-made one-image document. A document owns layer placement,
visibility, effects, and editing state; the catalog owns the shared source.

## Build a Catalog

Use `CuteCanvas.imageMapFromLists()` when an application already has images and
optional source paths:

```python
from PySide6.QtGui import QImage
from cutecanvas import CuteCanvas

canvas = CuteCanvas()
images = [QImage("one.png"), QImage("two.png")]
paths = ["one.png", "two.png"]

image_map = CuteCanvas.imageMapFromLists(images, paths=paths)
first_id = next(iter(image_map))
canvas.setImagesByID(image_map, current_id=first_id)
```

Every image must be valid. The helper raises `ValueError` when the image, path,
and optional ID lists have different lengths.

`canvas.getCatalogSnapshot()` returns detached entries and ordering for a host
sidebar. `canvas.imageIDs()`, `canvas.imagePath()`, `canvas.allImages()`, and
`canvas.allImagePaths()` provide smaller views of the same catalog.

## Open Catalog Images

Each catalog image has a generated document containing one image layer. Open
that document with `setCurrentImageID()`:

```python
image_ids = canvas.imageIDs()
canvas.setCurrentImageID(image_ids[0])
```

The active source is available through `currentImageID()`, `currentImage()`,
and `currentImagePath()`. Pass `None` to `setCurrentImageID()` to return to the
empty canvas.

`currentImage()` is the original catalog image. It is not a flattened export of
the active document.

## Reuse a Source in an Editable Document

Start a document from one catalog image, then add another source as a layer:

```python
from PySide6.QtCore import QRectF

first_id, second_id = canvas.imageIDs()[:2]
document_id = canvas.createCompositionFromImage(
    first_id,
    title="Layout",
)
document = canvas.editor.documents.get(document_id)
if document is not None:
    document.open()

canvas.addCatalogImageLayer(
    second_id,
    placement=QRectF(120.0, 80.0, 640.0, 480.0),
    label="Foreground",
)
```

Both layers use the catalog sources through QPane's normal tile and pyramid
renderer. Reusing a catalog image does not duplicate its source cache, and each
layer still keeps its own transform and editing policy.

## Keep a Browser in Sync

Use `getCompositionSnapshot()` for a document tree. Its `order` lists documents
in display order, and each entry's `layers` are stored from bottom to top:

```python
snapshot = canvas.getCompositionSnapshot()
for document_id in snapshot.order:
    document = snapshot.compositions[document_id]
    add_document_row(document_id, document.title)
    for layer in reversed(document.layers):
        add_layer_row(
            document_id,
            layer.layer_id,
            layer.label,
            visible=layer.visible,
        )
```

Connect these signals instead of maintaining a second copy of document state:

* `catalogChanged` after catalog structure changes.
* `catalogSelectionChanged` when the active catalog image changes.
* `compositionChanged` after document or layer structure changes.
* `compositionSelectionChanged` when another document opens.
* `selectedLayerChanged` when layer selection changes.

## Navigate a Review Set

Applications that only need an ordered image review flow can move through the
catalog directly:

```python
image_ids = canvas.imageIDs()
current_id = canvas.currentImageID()
index = image_ids.index(current_id) if current_id in image_ids else -1
canvas.setCurrentImageID(image_ids[(index + 1) % len(image_ids)])
```

`setAllImagesLinked(True)` gives catalog images shared pan and zoom state.
`setLinkedGroups()` creates smaller synchronized groups.

## Compare Two Sources

The comparison view reveals a second catalog source across a movable split:

```python
from cutecanvas import ComparisonOrientation

first_id, second_id = canvas.imageIDs()[:2]
canvas.setCurrentImageID(first_id)
canvas.setComparisonImageID(second_id)
canvas.setComparisonSplit(0.5, ComparisonOrientation.VERTICAL)
```

Read `comparisonState()` to synchronize host controls, connect
`comparisonChanged` for updates, and call `clearComparisonImage()` to finish.
The built-in divider can be disabled with
`setComparisonDividerInteractive(False)` when the host supplies its own
interaction.

## Remove Sources

`removeImageByID()` and `removeImagesByID()` remove catalog entries and their
generated documents. Explicit documents that reference those sources retain
their own document rules. `clearImages()` empties the catalog and returns the
canvas to its placeholder.

## Related Docs

* [Documents and Layers](scenes.md): Build and edit independent documents.
* [Placed Images](placed-images.md): Add embedded or linked files without a
  catalog entry.
* [QPane Catalog and Navigation](../../qpane/docs/catalog-and-navigation.md):
  Viewer-only catalog workflows inherited by the canvas.

**Continue →** [Interaction and Tools](interaction-modes.md)
