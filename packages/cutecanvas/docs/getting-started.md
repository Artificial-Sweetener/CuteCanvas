# Getting Started

## Welcome to CuteCanvas

CuteCanvas is a layered image editor you can place inside a PySide6
application. It supplies the canvas, documents, layers, tools, selections,
masks, transforms, and undo history. Your application supplies the surrounding
windows, actions, docks, and workflow.

This guide starts with an image, turns it into an editable document, adds a
paint layer, and saves the result in CuteCanvas's editable document format.

## Install CuteCanvas

The normal package contains the complete editor, including masks and selection
tools:

```bash
pip install cutecanvas
```

Install the optional `sam` extra when your application will offer AI-assisted
selection:

```bash
pip install "cutecanvas[sam]"
```

## Create the Widget

Create `CuteCanvas` after `QApplication`, then add it to a window like any
other `QWidget`:

```python
import sys

from PySide6.QtWidgets import QApplication, QMainWindow
from cutecanvas import CuteCanvas

app = QApplication(sys.argv)

window = QMainWindow()
canvas = CuteCanvas(features=("mask",))
window.setCentralWidget(canvas)
window.resize(1200, 760)
window.show()

app.exec()
```

That widget already has smooth pan and zoom, high-DPI rendering, the document
system, and the requested mask tools. Mask support ships with CuteCanvas;
`features=("mask",)` simply turns those tools on for this widget. Add `"sam"`
to the tuple after installing the optional extra.

## Start a Document with an Image

First load the image into CuteCanvas's source catalog. The catalog keeps one
reusable copy of the source even when several documents or layers use it:

```python
from pathlib import Path

from PySide6.QtGui import QImage

image_path = Path("example.png")
image = QImage(str(image_path))
if image.isNull():
    raise RuntimeError(f"Could not open {image_path}")

image_map = CuteCanvas.imageMapFromLists(
    [image],
    paths=[image_path],
)
image_id = next(iter(image_map))
canvas.setImagesByID(image_map, current_id=image_id)
```

Now create an editable document from that source:

```python
document_id = canvas.createCompositionFromImage(
    image_id,
    title="Example document",
)

document = canvas.editor.documents.get(document_id)
if document is None:
    raise RuntimeError("The document was not created")

document.open()
```

The image is now an ordinary layer. CuteCanvas does not turn the first image
into a permanently special background. Your host may lock it in place, or let
the user select, move, transform, hide, reorder, and remove it.

You can also begin with an empty canvas:

```python
from PySide6.QtCore import QRectF

document = canvas.editor.documents.create(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="Empty document",
)
document.open()
```

## Work with Documents and Layers

`canvas.editor.documents` is the friendly entry point for document UI. It can
create a document, find one by ID, report the current document, and iterate in
browser order.

Each document exposes its layers from bottom to top:

```python
from PySide6.QtCore import QPointF

document = canvas.editor.documents.current
if document is not None and document.layers:
    top_layer = document.layers[-1]
    top_layer.select()
    top_layer.translate(QPointF(24.0, 0.0))
    top_layer.center(vertically=False)
```

Document and layer handles keep identity, not a private copy of mutable state.
If undo or another action changes the document, the next handle operation sees
the latest state. A removed document or layer fails clearly when accessed.

Layer changes apply to the open document. Call `document.open()` before using
one of its layer handles when your application keeps several documents.

## Add a Paint Layer

Create an empty transparent layer, make it the current layer and paint target,
then activate the brush:

```python
paint_layer_id = canvas.createPaintLayer(label="Paint")
scene = canvas.currentScene()

if scene is not None and paint_layer_id is not None:
    canvas.setSelectedLayer(scene.scene_id, paint_layer_id)
    canvas.setPaintTarget(scene.scene_id, paint_layer_id)
    canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

The layer stores only touched regions. Painting near one corner of an 8K
document does not allocate an 8K transparent image first.

Use `setPaintColor()` and `setBrushPreset()` to build brush controls. The same
brush engine paints color layers, masks, and painted selections.

## Add a Mask

A blank mask becomes another layer in the open document:

```python
mask_id = canvas.createBlankMask(image.size())
if mask_id is not None:
    canvas.setActiveMaskID(mask_id)
    canvas.setControlMode(canvas.CONTROL_MODE_MASK_RECTANGLE)
```

The rectangle, ellipse, and lasso mask tools keep their shapes editable. Brush
strokes and imported soft coverage can live in the same mask. You do not need
to choose one representation for the whole layer.

See [Masks and AI Selection](masks-and-sam.md) for mask appearance, painting,
autosave, grayscale export, and optional AI-assisted selection.

## Select and Move Pixels

Pixel selection is separate from layer selection. Choose a layer first, then
use a selection tool to mark the part you want to edit:

```python
canvas.setControlMode(canvas.CONTROL_MODE_SELECT_RECTANGLE)
```

After the user draws a selection, switch to Move:

```python
canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
```

Move lifts only selected nontransparent pixels. The lifted pixels remain
temporary after the drag, so the user can move them again, anchor them, send
them to another layer, make a new layer, or cancel without losing the source.

The focused selection facade is useful for menus and status UI:

```python
selection = canvas.editor.selection.state
if selection is not None and selection.has_selection:
    print(selection.bounds)

canvas.editor.selection.clear()
```

Undo and redo follow the document's single edit history:

```python
if canvas.editor.history.can_undo:
    canvas.editor.history.undo()
```

## Keep Host UI in Sync

Connect signals instead of polling the widget. These cover the controls most
editors need:

* `compositionChanged` rebuilds a document-and-layer tree.
* `compositionSelectionChanged` updates the active document row.
* `selectedLayerChanged` updates layer-specific controls.
* `pixelSelectionChanged` updates selection commands.
* `sceneEditHistoryChanged` updates Undo and Redo.
* `controlModeChanged` updates tool actions.
* `paintTargetChanged` updates brush controls.
* `maskSaved` reports a completed mask autosave.

```python
def update_history_actions(can_undo, can_redo):
    undo_action.setEnabled(can_undo)
    redo_action.setEnabled(can_redo)


canvas.sceneEditHistoryChanged.connect(update_history_actions)
```

The signals carry public values suitable for application UI. Request a fresh
document or layer snapshot when you rebuild a panel instead of reaching into a
private controller.

## Save the Editable Document

A flattened image contains the visible result. A `.cutecanvas` document keeps
the editable work: layers, masks, vectors, transforms, linked-image details,
policies, and content outside the canvas.

```python
document = canvas.editor.documents.current
if document is not None:
    canvas.editor.persistence.save(document, "example.cutecanvas")
```

Load it later with:

```python
document = canvas.editor.persistence.load("example.cutecanvas")
```

Loading validates the complete archive before replacing live state. A damaged
or unsupported file cannot leave a half-restored document mounted.

## Next Steps

You now have a working layered editor. Continue with the part your application
needs next:

* **Build the layer tree:** [Documents and Layers](scenes.md) covers layer
  order, visibility, policies, geometry, and source types.
* **Paint color:** [Painting](painting.md) covers sparse raster layers, brush
  presets, target selection, erasing, and fill.
* **Place images:** [Placed Images](placed-images.md) covers embedded and linked
  assets, refresh, duplication, and rasterization.
* **Draw vectors:** [Vector Layers](vector-layers.md) covers shapes, paths,
  text, object selection, coverage, and rasterization.
* **Wire the toolbar:** [Interaction and Tools](interaction-modes.md) explains
  Move, Transform, selection tools, snapping, and temporary navigation.
* **Edit part of a layer:** [Pixel Selections](pixel-selections.md) covers
  Delete, Fill Selection, Paint Bucket, and floating pixels.
* **Author masks:** [Masks and AI Selection](masks-and-sam.md) covers painting,
  shapes, exact host-authored coverage, autosave, and the optional model.
* **Tune the application:** [Configuration](configuration.md) covers memory,
  input, painting, autosave, and background work.

**Continue →** [Documents and Layers](scenes.md)
