# Project Resources

CuteCanvas stores content as project resources. Compositions contain ordered layer
instances that reference those resources. A layer owns placement, visibility,
opacity, effects, and interaction policy; its resource owns the pixels, vector
objects, coverage, provenance, or nested composition being displayed.

This distinction lets several layers share content without sharing placement.
It also lets a host fork one layer's resource before editing when independent
content is required.

## Start with an Image

Load an image and create an independent composition in one step:

```python
from pathlib import Path

from PySide6.QtGui import QImage

path = Path("example.png")
image = QImage(str(path))
if image.isNull():
    raise RuntimeError(f"Could not open {path}")

composition_id = canvas.createCompositionFromImage(
    image,
    title=path.stem,
    label="Background",
)
```

The imported pixels become an ordinary project resource and the composition gets
one ordinary layer instance. The layer may be moved, hidden, reordered,
transformed, duplicated, or removed according to host policy. Rasterize it when
direct pixel editing is needed.

## Share or Fork Content

Duplicate a layer when two independently positioned instances should share the
same content:

```python
composition = canvas.editor.compositions.current
if composition is not None and composition.layers:
    original = composition.layers[-1]
    duplicate = original.duplicate()
```

Edits to a shared editable resource appear through every instance. Fork the
resource before editing when only one layer should change:

```python
if duplicate is not None:
    independent_resource_id = duplicate.fork_resource()
```

Layer identity stays stable while its resource reference changes, so selection,
placement, opacity, effects, stack order, and history remain attached to the
same layer.

## Rasterize for Pixel Editing

Imported images, linked images, vector artwork, and nested compositions all use
the same conversion command:

```python
request_id = original.rasterize()
```

Rasterization evaluates the resource at its natural size unless the host
provides a `QSize`. It then replaces only that layer's resource reference with
editable pixels. The layer keeps its identity, transform, visibility, opacity,
effects, and stack position. `CuteCanvas.layerRasterizationCompleted` reports
the terminal result, and undo restores the original resource.

## Nest Compositions

A composition is itself a renderable resource. Place one open composition inside
another to build reusable live content:

```python
from PySide6.QtCore import QRectF

card_id = canvas.createCompositionFromImage(
    QImage("card.png"),
    title="Card",
)
layout_id = canvas.createComposition(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="Layout",
)
card = canvas.editor.compositions.get(card_id)
layout = canvas.editor.compositions.get(layout_id)
if card is not None and layout is not None:
    layout.place_composition(
        card,
        placement=QRectF(160.0, 120.0, 800.0, 600.0),
    )
```

Changes inside the nested composition invalidate every direct and transitive
reference. Cycles are rejected before a layer or dependency graph is changed.

## Keep a Browser in Sync

Use `getCompositionSnapshot()` for a composition tree. Its `order` lists compositions
in display order, and each entry's `layers` are stored from bottom to top:

```python
snapshot = canvas.getCompositionSnapshot()
for composition_id in snapshot.order:
    composition = snapshot.compositions[composition_id]
    add_composition_row(composition_id, composition.title)
    for layer in reversed(composition.layers):
        add_layer_row(
            composition_id,
            layer.layer_id,
            layer.label,
            visible=layer.visible,
        )
```

Connect these signals instead of maintaining a second copy of composition state:

* `compositionChanged` after composition or layer structure changes.
* `compositionSelectionChanged` when another composition opens.
* `selectedLayerChanged` when layer selection changes.

## Save the Complete Graph

Saving a composition follows nested-composition and shared-resource dependencies.
One archive contains the root composition, every nested composition required to render it,
each layer stack, and one copy of every referenced payload:

```python
root = canvas.editor.compositions.get(layout_id)
if root is not None:
    canvas.editor.persistence.save(root, "layout.cutecanvas")
```

Loading validates identities, dependencies, and cycles before installing the
graph. A failed load leaves the open project unchanged.

## Related Docs

* [Compositions and Layers](scenes.md): Build and edit independent compositions.
* [Placed Images](placed-images.md): Add embedded or linked files and choose
  when to rasterize them.

**Continue →** [Interaction and Tools](interaction-modes.md)
