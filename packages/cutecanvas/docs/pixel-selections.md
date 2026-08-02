# Pixel Selections

Layer selection chooses a layer. Pixel selection chooses the part of that layer
an edit may affect.

CuteCanvas stores pixel selection as 8-bit coverage in document coordinates.
Coverage may be fully selected, fully clear, or anywhere in between, so soft
edges survive Delete, Fill, painting, and movement.

## Draw a Selection

Activate one of the three selection tools:

```python
canvas.setControlMode(canvas.CONTROL_MODE_SELECT_RECTANGLE)
canvas.setControlMode(canvas.CONTROL_MODE_SELECT_ELLIPSE)
canvas.setControlMode(canvas.CONTROL_MODE_SELECT_LASSO)
```

Dragging normally replaces the current selection. Hold Shift to add, Alt to
subtract, or Shift+Alt to keep only the overlap.

Rectangle, ellipse, and lasso selections retain their shape geometry. Imported
coverage and painted selection strokes may live beside those shapes in the
same selection. The animated boundary is cached until coverage changes, keeping
large selections responsive while the user pans and zooms.

The composition canvas is the shared aperture for selection and mask shapes.
During an out-of-bounds drag, the live boundary, committed coverage, and later
animated boundary all remain clipped to the same canvas edge.

Use `configureCoverageShapes(feather_radius=...)` before a gesture to create a
soft retained edge.

## Inspect and Clear the Selection

The focused facade returns the current selection snapshot:

```python
selection = canvas.editor.selection.state
if selection is not None and selection.has_selection:
    print(selection.bounds)
```

`bounds` is the smallest document rectangle containing nonzero coverage.
`coverage` is a detached grayscale `QImage` for that rectangle.

Clear it with:

```python
canvas.editor.selection.clear()
```

The demo binds this action to `Ctrl+D`. Escape cancels an unfinished selection
gesture without clearing a selection that was already committed.

Selection belongs to the document. Switching documents restores each
document's own selection instead of moving one global selection between them.

## Select All, Invert, or Select Layer Content

The standard commands use:

```python
canvas.selectAllPixels()
canvas.invertPixelSelection()
canvas.clearPixelSelection()
```

To select the visible coverage of a layer:

```python
scene = canvas.currentScene()
layer = canvas.selectedLayer()
if scene is not None and layer is not None:
    canvas.selectLayerCoverage(scene.scene_id, layer.layer_id)
```

For a mask this selects its painted coverage. For an editable RGBA layer it
selects nontransparent pixels. Transparent storage around content is excluded.

## Supply Coverage from Host Code

`setPixelSelection()` accepts an 8-bit grayscale image and the document
rectangle where it belongs:

```python
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from cutecanvas import PixelSelectionMode

coverage = QImage(320, 180, QImage.Format_Grayscale8)
coverage.fill(255)

canvas.setPixelSelection(
    coverage,
    QRect(40, 60, 320, 180),
    PixelSelectionMode.REPLACE,
)
```

The image dimensions must match the rectangle. Use `ADD`, `SUBTRACT`, or
`INTERSECT` to combine it with existing coverage.

For exact rectangles, ellipses, and polygons, point the coverage facade at the
pixel selection and author retained geometry:

```python
from PySide6.QtCore import QRectF

canvas.setPixelSelectionPaintTarget()
canvas.editor.coverage.rectangle(QRectF(100.0, 80.0, 640.0, 360.0))
```

See [Masks and AI Selection](masks-and-sam.md) for normalized coordinates that
divide a target into exact halves, quarters, or grids.

## Delete Selected Pixels

Select an editable mask or RGBA layer, create a pixel selection, then call:

```python
canvas.deleteSelectedPixels()
```

Delete applies the soft selection coverage. Fully selected pixels become
transparent or clear; partially selected pixels are reduced proportionally.
Pixels outside the selection remain unchanged.

The operation creates one entry in the document history. The visible frame is
updated before the command returns to user interaction, so immediate undo does
not show a stale pre-delete frame.

If the selected layer cannot accept direct pixel edits, the command returns
`False`. Ask `editorOperationState(EditorIntent.DELETE_PIXELS)` to explain why
and to discover an available next action such as rasterization.

## Fill the Selection

`fillSelection()` writes the current paint color into an editable RGBA target,
or full coverage into a mask target:

```python
canvas.fillSelection()
```

Soft edges are preserved. The fill is one undoable edit and uses the same paint
target shown by `paintTargetState()`.

Paint Bucket solves a different problem: it samples connected or matching
pixels from the active target, then fills that region. Configure it before
activating the tool:

```python
canvas.configurePaintBucket(
    tolerance=20,
    contiguous=True,
    antialias=True,
)
canvas.setControlMode(canvas.CONTROL_MODE_PAINT_BUCKET)
```

Bucket work runs in the background. A changed document, target, or source
revision makes stale work harmless instead of applying it to the wrong state.
An active selection limits the result.

## Move Selected Pixels

Move gives pixel selection priority over whole-layer movement:

```python
canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
```

Begin the drag on selected, nontransparent content. CuteCanvas lifts only the
meaningful payload, not every transparent pixel inside the selection's bounding
rectangle.

The lifted pixels remain temporary after release. `floatingPixelEditState()`
reports their source, cut/copy mode, offset, and current bounds.

Resolve them in one of four ways:

```python
# Put them back into the source layer at the new position.
canvas.anchorFloatingPixels()

# Send them to another compatible layer.
canvas.anchorFloatingPixels(destination_scene_id, destination_layer_id)

# Create a new layer from the floating pixels.
new_layer_id = canvas.promoteFloatingPixels(label="Moved pixels")

# Restore the exact pre-lift state.
canvas.cancelFloatingPixels()
```

Hold Alt when beginning a drag to copy instead of cut. Enter anchors to the
source. Escape cancels. Holding Space to pan preserves the exact unresolved
position.

Anchoring to a fixed raster clips writes at that raster's local bounds. An
unbounded raster keeps off-canvas or negative-coordinate content while
allocating only touched regions.

## Selection and Painting

An active pixel selection constrains brush strokes on masks and color layers.
The live preview and committed stroke use the same coverage, so paint does not
flash outside the selection before the final result appears.

To paint the selection itself, call `setPixelSelectionPaintTarget()` before
activating Brush. This lets users refine a selection with the same brush preset
used elsewhere in the editor.

## Keep Actions Synchronized

Connect `pixelSelectionChanged` for Select All, Invert, Deselect, Delete, and
Fill availability. Connect `floatingPixelEditChanged` for Anchor, New Layer,
destination, and Cancel controls. Connect `sceneEditHistoryChanged` for Undo
and Redo.

Do not infer floating state from the active tool. An unresolved edit may remain
active while the user temporarily pans or chooses another tool.

## Related Docs

* [Interaction and Tools](interaction-modes.md): selection gestures, Move,
  Transform, and temporary navigation.
* [Documents and Layers](scenes.md): layer selection, policy, order, and raster
  extent.
* [Masks and AI Selection](masks-and-sam.md): mask coverage, retained shapes,
  painting, and export.
