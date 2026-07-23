**← Previous:** [Getting Started](getting-started.md)

# Documents and Layers

A CuteCanvas document has its own canvas, title, layer stack, policies,
selection, and undo history. It does not belong to a catalog image. You may
start with an empty canvas or use an image to choose the initial size and first
layer.

This page covers document and layer structure. Painting, masks, selections,
and direct-manipulation tools have focused guides of their own.

## Create an Empty Document

Use the typed document collection for ordinary application code:

```python
from PySide6.QtCore import QRectF

document = canvas.editor.documents.create(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="Untitled",
)
document.open()
```

The canvas remains 1920 × 1080 even when the document is empty or every layer
moves outside it. It defines the visible and exported document region; it does
not restrict where unbounded layer content may be stored.

Create several documents the same way. Iterate `canvas.editor.documents` in
browser order and use `canvas.editor.documents.current` for the open document.

## Start from an Image

An image enters the source catalog once, then any number of documents can use
it:

```python
from pathlib import Path

from PySide6.QtGui import QImage

image = QImage("photo.png")
image_map = canvas.imageMapFromLists(
    [image],
    paths=[Path("photo.png")],
)
image_id = next(iter(image_map))
canvas.setImagesByID(image_map, current_id=image_id)

document_id = canvas.createCompositionFromImage(
    image_id,
    title="Photo study",
)
document = canvas.editor.documents.get(document_id)
```

The seed image becomes the first ordinary layer. The host decides whether that
layer is fixed or editable by supplying a `LayerPolicy`.

```python
from cutecanvas import LayerPolicy

movable_image = LayerPolicy(
    selectable=True,
    movable=True,
    pixel_editable=False,
    reorderable=True,
    removable=True,
)

document_id = canvas.createCompositionFromImage(
    image_id,
    title="Layout",
    interaction=movable_image,
)
```

`pixel_editable=False` keeps the source image unchanged. The layer can still be
moved and transformed. A user may rasterize a placed image or work on a new
paint layer when direct pixel changes are needed.

## Add Another Catalog Image

Add a new layer instance to the open document:

```python
from PySide6.QtCore import QRectF

layer_id = canvas.addCatalogImageLayer(
    image_id,
    placement=QRectF(240.0, 120.0, 960.0, 540.0),
    label="Reference",
    interaction=movable_image,
)
```

Several layer instances may use the same image source. They share decoded
pixels and render products, while keeping independent position, transform,
visibility, opacity, policy, and order.

Removing one layer does not remove the source from the catalog. Removing the
catalog source removes layers that refer to it.

## Understand Layer Order

`DocumentHandle.layers` is ordered from bottom to top. The last item is the
topmost layer:

```python
document = canvas.editor.documents.current
if document is not None:
    for layer in reversed(document.layers):
        print(layer.state.label)
```

Move a layer to another stack index with `move_to()`:

```python
layer = document.layers[-1]
layer.move_to(0)
```

Index `0` is the bottom of the stack. Reordering creates one undoable document
edit and respects the layer's `reorderable` policy.

## Select a Layer

Layer selection chooses the target for layer commands and direct pixel edits.
It is separate from pixel selection:

```python
layer = document.layers[-1]
if layer.select():
    print(layer.state.label)
```

`selectedLayerChanged` tells an inspector when to refresh. `selectedLayer()`
returns the current `LayerSelectionSnapshot`, and `clearSelectedLayer()` clears
it.

Pointer selection uses visible content. Transparent pixels fall through to a
covered layer below, which keeps layer targeting aligned with what the user can
actually see.

## Show, Hide, Reorder, and Remove

Layer handles cover the common structural edits:

```python
layer.set_visible(False)
layer.set_visible(True)
layer.move_to(0)
layer.remove()
```

These changes belong to the document's undo history. They do not alter the
underlying source, and changing one instance does not affect another instance
of the same source.

`LayerPolicy` controls what the user and host are allowed to do with a layer:

* `selectable` allows direct layer selection.
* `movable` allows position and affine-transform changes.
* `pixel_editable` allows pixel commands when the source itself supports them.
* `reorderable` allows stack-order changes.
* `removable` allows the instance to be deleted.

Permission cannot create a capability the source does not have. Marking a
linked image as pixel-editable does not silently rewrite it; the operation state
instead explains that it must be rasterized first.

Update policy at any time:

```python
layer.set_policy(
    LayerPolicy(
        selectable=True,
        movable=False,
        pixel_editable=False,
        reorderable=False,
        removable=False,
    )
)
```

## Move a Layer from Host Code

Use the handle for simple placement commands:

```python
from PySide6.QtCore import QPointF

layer.translate(QPointF(32.0, -12.0))
layer.center(horizontally=True, vertically=False)
```

`translate()` preserves scale, rotation, reflection, and skew. `center()`
aligns the chosen content center with the document canvas.

Use `set_transform()` when the host owns the complete affine value:

```python
from PySide6.QtGui import QTransform

transform = QTransform()
transform.translate(400.0, 240.0)
transform.rotate(15.0)
transform.scale(0.75, 0.75)
layer.set_transform(transform)
```

The Move and Transform tools use these same document operations. Their
gesture behavior, snapping, and temporary navigation are covered in
[Interaction and Tools](interaction-modes.md).

## Choose the Bounds Used for Manipulation

The rectangle used for selection, snapping, and transform handles does not have
to match raster storage. The default follows visible painted content, excluding
transparent padding.

`LayerGeometryPolicy` lets a host choose a different meaning when its domain
needs one:

* content bounds follow visible nontransparent pixels or painted vectors;
* source bounds follow the complete source extent;
* storage bounds follow allocated raster storage;
* clip bounds follow an explicit clip;
* authored bounds follow retained geometry; and
* custom bounds use a rectangle supplied by the host.

Apply the policy through `layer.set_geometry()`. `layerLocalBounds()` reports
the bounds selected by the current policy, while `layerTransform()` reports the
independent local-to-document transform.

## Layer Types

Every layer shares the same document structure. Its source determines what can
be edited:

* **Catalog images** reuse source pixels and are ideal for review or fixed
  backgrounds.
* **Paint layers** store editable RGBA pixels sparsely.
* **Masks** store soft grayscale coverage from brush strokes, shapes, paths,
  and imported images.
* **Placed images** remain linked or embedded and transform without changing
  their source until rasterized.
* **Vector layers** retain shapes, paths, and text at full precision.

Selection, visibility, ordering, transforms, policies, snapping, history, and
persistence apply to all of them through the same layer model.

## Inspect Documents for a Layer Tree

`getCompositionSnapshot()` returns every document and its layers without
opening each one:

```python
snapshot = canvas.getCompositionSnapshot()

for document_id in snapshot.order:
    entry = snapshot.compositions[document_id]
    print(entry.title)
    for layer in reversed(entry.layers):
        print("  ", layer.label or layer.source_kind)
```

`CompositionEntry.layers` is bottom-to-top; most layer trees display it in
reverse. Each `CompositionLayerEntry` includes stable layer and source IDs,
label, source kind, visibility, opacity, policy, and transform.

Use `compositionChanged` to rebuild the tree and
`compositionSelectionChanged` to update its active document row. The snapshot
is a view for host UI, not a second document model.

## Document Policy

`CompositionPolicy` controls document-level actions:

```python
from cutecanvas import CompositionPolicy

document.set_policy(
    CompositionPolicy(
        removable=True,
        comparison_enabled=False,
    )
)
```

Layer policy and document policy solve different problems. A non-removable
document can still contain removable layers. A removable document can still
contain a locked background.

## Build a Host-Defined Layout

`CompositionRequest` and `CatalogLayerRequest` are useful when the host already
has a complete review grid or contact-sheet layout. Each request supplies the
canvas and an ordered tuple of image-layer placements. `composeScene()` stores
the result as a normal document.

Use `fitSceneRect()` to fit an image inside a slot while preserving aspect
ratio, or `fillSceneRect()` to cover the slot. `CompositionTemplate` and
`TemplateBindings` let a host reuse the same arrangement with different
catalog sources.

These request values are layout conveniences. The resulting document and
layers use the same handles, snapshots, policies, rendering, and history as
documents created one step at a time.

## Hit Test and Draw Host Chrome

`sceneHitTest()` returns the topmost eligible layer under a widget point along
with panel, document, and source coordinates. It does not select or navigate;
the host decides what a click means.

Use `registerSceneOverlay()` for labels, hover outlines, guides, or badges tied
to projected layer geometry. The callback receives prepared panel-space bounds
and transforms, so it does not need to duplicate viewport math.

Use a layer presentation effect when an outline, glow, or tint must follow the
actual rendered content. See [Extensibility](extensibility.md) for both paths.

## Related Docs

* [Getting Started](getting-started.md): create and save the first document.
* [Interaction and Tools](interaction-modes.md): Move, Transform, snapping,
  selections, and temporary navigation.
* [Painting](painting.md): sparse raster layers, brush targets, and fill.
* [Placed Images](placed-images.md): linked and embedded image layers.
* [Vector Layers](vector-layers.md): retained shapes, paths, and text.
* [Pixel Selections](pixel-selections.md): edit part of a raster or mask.
* [Masks and AI Selection](masks-and-sam.md): mask layers, shape authoring,
  painting, export, and autosave.
* [API Reference](api-reference.md): ad-hoc layout requests, templates, clips,
  and every document and layer value.

**Continue →** [Interaction and Tools](interaction-modes.md)
