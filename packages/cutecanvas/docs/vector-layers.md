# Vector Layers

Vector layers retain shapes, paths, and text as editable objects. QPane samples
them at the scale needed for the current view, so zooming does not turn their
authoritative geometry into one canvas-sized bitmap.

## Create a Vector Layer

```python
from PySide6.QtCore import QSize

layer_id = canvas.createVectorLayer(
    QSize(1200, 800),
    label="Shapes",
)
scene = canvas.currentScene()
```

The layer participates in the same document stack, transform system, snapping,
visibility, effects, and history as raster and mask layers.

## Add a Shape

```python
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from cutecanvas import VectorShapeKind, VectorStyle

if scene is not None and layer_id is not None:
    object_id = canvas.addVectorShape(
        scene.scene_id,
        layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(80.0, 80.0, 420.0, 240.0),
        VectorStyle(
            fill=QColor("mediumaquamarine"),
            stroke=QColor("white"),
            stroke_width=6.0,
        ),
    )
```

The Shape tool uses the same operation through direct manipulation. Set
`setVectorToolShape()` and `setVectorToolStyle()` before activating
`CONTROL_MODE_VECTOR_SHAPE` to seed its options.

## Add a Path

Paths are built from immutable commands:

```python
from PySide6.QtCore import QPointF
from cutecanvas import VectorPathCommand, VectorPathCommandKind

commands = (
    VectorPathCommand(VectorPathCommandKind.MOVE, (QPointF(100.0, 500.0),)),
    VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(300.0, 300.0),)),
    VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(500.0, 500.0),)),
    VectorPathCommand(VectorPathCommandKind.CLOSE),
)

canvas.addVectorPath(scene.scene_id, layer_id, commands)
```

The Path and Edit Nodes tools author and adjust the same retained command
model. Node edits, style changes, object transforms, ordering, and removal are
normal history operations.

## Add Text

```python
from cutecanvas import VectorTextContent, VectorTextStyle

text_id = canvas.addVectorText(
    scene.scene_id,
    layer_id,
    QRectF(100.0, 100.0, 700.0, 160.0),
    VectorTextContent(
        "A quiet afternoon",
        style=VectorTextStyle(
            families=("Noto Sans", "Sans Serif"),
            font_size=48.0,
            color=QColor("white"),
        ),
    ),
)
```

Text keeps Unicode content, paragraph settings, styled spans, and requested
font families. `vectorTextFontResolutions()` reports the family Qt resolved on
the current system. Convert text to paths only when the document should stop
depending on font resolution.

## Inspect and Select Objects

`vectorDocumentState(scene_id, layer_id)` returns the current immutable
document snapshot. Use `setSelectedVectorObjects()` and
`clearVectorSelection()` for host object lists, while
`vectorSelectionChanged` keeps those lists synchronized.

Layer selection and vector-object selection answer different questions. A
selected vector layer may contain zero, one, or several selected objects.

## Use Vector Geometry as Coverage

`convertVectorToPixelSelection()` samples chosen objects into the active pixel
selection. `setVectorMask()` attaches retained objects as a non-destructive mask
for another layer. The vector objects remain editable while QPane provides the
raster coverage needed for drawing and hit testing.

## Rasterize When Needed

```python
raster_layer_id = canvas.rasterizeLayer(
    scene.scene_id,
    layer_id,
)
```

Rasterization replaces retained objects with editable pixels at the chosen
resolution. Use it for pixel painting or filters that require a raster target.
The operation is reversible through document history, but the resulting layer
does not continue to behave as vector content.

## Related Docs

* [Documents and Layers](scenes.md): Layer order, transforms, and policies.
* [Masks and SAM](masks-and-sam.md): Retained coverage shapes and mask export.
* [QPane Rendering SDK](../../qpane/docs/rendering-sdk.md): Vector sampling,
  hybrid sources, cache behavior, and render contracts.

**Continue →** [Pixel Selections](pixel-selections.md)
