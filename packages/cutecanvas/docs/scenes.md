**← Previous:** [Getting Started](getting-started.md)

# Compositions and Layers

A CuteCanvas composition has its own canvas, title, layer stack, policy, and
selection. Compositions live together in one host-owned `CanvasDocument` and
share its chronological history and reusable resources. You may start with an
empty composition or use an image to choose the initial size and first layer.

This page covers composition and layer structure. Painting, masks, selections,
and direct-manipulation tools have focused guides of their own.

## Create an Empty Composition

Use the typed composition collection for ordinary application code:

```python
from PySide6.QtCore import QRectF

composition = canvas.editor.compositions.create(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="Untitled",
)
composition.open()
```

The canvas remains 1920 × 1080 even when the composition is empty or every layer
moves outside it. It defines the visible and exported composition region; it does
not restrict where unbounded layer content may be stored.

Create several compositions the same way. Iterate `canvas.editor.compositions`
in browser order and use `canvas.editor.compositions.current` for the open one.

## Start from an Image

Import detached pixels and create a composition containing one ordinary layer:

```python
from PySide6.QtGui import QImage

image = QImage("photo.png")
if image.isNull():
    raise RuntimeError("Could not load photo.png")

composition_id = canvas.createCompositionFromImage(
    image,
    title="Photo study",
    label="Photo",
)
composition = canvas.editor.compositions.get(composition_id)
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

composition_id = canvas.createCompositionFromImage(
    image,
    title="Layout",
    label="Photo",
    interaction=movable_image,
)
```

`pixel_editable=False` keeps the source image unchanged. The layer can still be
moved and transformed. A user may rasterize a placed image or work on a new
paint layer when direct pixel changes are needed.

## Share, Fork, and Nest Content

Duplicating a layer creates another instance of the same project resource.
Both instances reuse pixels or vector content while keeping independent
placement, visibility, opacity, policy, and order:

```python
scene = canvas.currentScene()
if scene is not None and scene.layers:
    source_layer_id = scene.layers[-1].layer_id
    duplicate_id = canvas.duplicateLayer(scene.scene_id, source_layer_id)
```

An edit to shared editable content appears through both instances. Fork the
selected instance when it should become independent:

```python
if scene is not None and duplicate_id is not None:
    resource_id = canvas.forkLayerResource(scene.scene_id, duplicate_id)
```

Compositions are resources too. Place another open composition as a live nested
layer:

```python
layer_id = canvas.placeComposition(
    other_composition_id,
    label="Reusable artwork",
)
```

Edits inside the nested composition invalidate its parents automatically. Saving
the outer composition follows these dependencies and stores the complete editable
resource graph.

## Understand Layer Order

`CompositionHandle.layers` is ordered from bottom to top. The last item is the
topmost layer:

```python
composition = canvas.editor.compositions.current
if composition is not None:
    for layer in reversed(composition.layers):
        print(layer.state.label)
```

Move a layer to another stack index with `move_to()`:

```python
layer = composition.layers[-1]
layer.move_to(0)
```

Index `0` is the bottom of the stack. Reordering creates one undoable
composition edit and respects the layer's `reorderable` policy.

## Select a Layer

Layer selection chooses the target for layer commands and direct pixel edits.
It is separate from pixel selection:

```python
layer = composition.layers[-1]
if layer.select():
    print(layer.state.label)
```

`selectedLayers()` returns the ordered layer selection with its active member
last, while `selectedLayer()` returns only that active member. Hosts can replace
the complete selection with `setSelectedLayers()` or replace it with one member
through `setSelectedLayer()`. `selectedLayersChanged` updates multi-selection
UI, `selectedLayerChanged` updates active-layer controls, and
`clearSelectedLayer()` clears the complete set.

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

These changes belong to the `CanvasDocument` undo history. They do not alter the
underlying source, and changing one instance does not affect another instance
of the same source.

`LayerPolicy` controls what the user and host are allowed to do with a layer:

* `selectable` allows direct layer selection.
* `movable` allows position and local-to-scene mapping changes.
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
aligns the chosen content center with the composition canvas.

Use `set_transform()` when the host owns the complete affine, projective, or
piecewise mapping:

```python
from PySide6.QtGui import QTransform

transform = QTransform()
transform.translate(400.0, 240.0)
transform.rotate(15.0)
transform.scale(0.75, 0.75)
layer.set_transform(transform)
```

For a finite deformation cage, pass QPane's immutable
`PiecewiseLayerTransform` or `BilinearLayerTransform`. `layerTransform()` and layer snapshots return that
value unchanged; ordinary affine and projective mappings remain detached
`QTransform` values for familiar Qt integration.

The Move and Transform tools use these same composition operations. Their
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
independent local-to-composition transform.

## Layer Types

Every layer shares the same composition structure. Its source determines what can
be edited:

* **Imported images** preserve their source pixels until rasterized.
* **Paint layers** store editable RGBA pixels sparsely.
* **Masks** store soft grayscale coverage from brush strokes, shapes, paths,
  and imported images.
* **Placed images** remain linked or embedded and transform without changing
  their source until rasterized.
* **Vector layers** retain shapes, paths, and text at full precision.

Selection, visibility, ordering, transforms, policies, snapping, history, and
persistence apply to all of them through the same layer model.

## Inspect Compositions for a Layer Tree

`getCompositionSnapshot()` returns every composition and its layers without
opening each one:

```python
snapshot = canvas.getCompositionSnapshot()

for composition_id in snapshot.order:
    entry = snapshot.compositions[composition_id]
    print(entry.title)
    for layer in reversed(entry.layers):
        print("  ", layer.label or layer.source_kind)
```

`CompositionEntry.layers` is bottom-to-top; most layer trees display it in
reverse. Each `CompositionLayerEntry` includes stable layer and source IDs,
label, source kind, visibility, opacity, policy, and transform.

Use `compositionChanged` to rebuild the tree and
`compositionSelectionChanged` to update its active composition row. The
snapshot is a view for host UI, not a second content model.

## Composition Policy

`CompositionPolicy` controls composition-level actions:

```python
from cutecanvas import CompositionPolicy

composition.set_policy(CompositionPolicy(removable=True))
```

Layer policy and composition policy solve different problems. A non-removable
composition can still contain removable layers. A removable composition can still
contain a locked background.

## Build a Host-Defined Layout

Create a composition, add or place its resources, and set each layer transform
through the same public layer API used by interactive tools. `fitSceneRect()`
fits a source inside a slot while preserving aspect ratio, and
`fillSceneRect()` covers the slot.

For repeated layouts, keep the composition and layer IDs in host state or save a
`.cutecanvas` archive as the reusable starting point. The result uses the same
handles, rendering, history, and persistence as a composition assembled by a
user.

## Hit Test and Draw Host Chrome

`sceneHitTest()` returns the topmost eligible layer under a widget point along
with panel, scene, and source coordinates. It does not select or navigate;
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
* [API Reference](api-reference.md): every composition, resource, and layer value.

**Continue →** [Interaction and Tools](interaction-modes.md)
