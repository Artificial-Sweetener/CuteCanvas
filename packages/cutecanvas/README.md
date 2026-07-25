# CuteCanvas

[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](../../LICENSE) [![semantic-release](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release) [![PyPI](https://img.shields.io/pypi/v/cutecanvas.svg)](https://pypi.org/project/cutecanvas/) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/) [![PySide6](https://img.shields.io/badge/PySide6-6.7.3%2B-41CD52?logo=qt&logoColor=white)](https://pyside.org)

**CuteCanvas** is an open-source layered image editor for PySide6. Add it to
your application when users need to paint, select, arrange, transform, and save
their work—not merely look at an image.

It gives you real editable documents, raster and vector layers, masks,
selections, non-destructive placed images, undo and redo, snapping, and a
complete tool system in one embeddable `QWidget`. You decide which capabilities
your application exposes and which layers users may change.

CuteCanvas uses QPane for rendering, so large editable images receive the same
tiled, CPU-first treatment as images in the QPane viewer.

## Highlights

* **A real editor in a Qt widget:** Put `CuteCanvas` in any layout and build the
  surrounding application with ordinary Qt actions, docks, and signals.
* **Independent compositions:** Start with an empty canvas or seed a composition
  from an image. Every image in a composition is an ordinary layer.
* **One document, many views:** Mount the same document in an editor, linked
  native-size tabs, a responsive grid, or an independent-target comparison.
* **Raster and vector layers:** Paint pixels, draw shapes and paths, edit text,
  and keep each kind of content editable.
* **Clone Stamp:** Retouch editable raster layers from one anchored layer, its
  visible backdrop, or the complete visible composition.
* **Masks and soft selections:** Paint or draw mask shapes, reuse mask coverage
  as a selection, and combine soft raster coverage with crisp retained shapes.
* **Move and transform:** Move whole layers or selected pixels, then scale,
  rotate, skew, align, and snap content with direct manipulation.
* **Linked and embedded images:** Place an image without changing its source,
  refresh linked files, or rasterize a layer when direct pixel editing is the
  right choice.
* **One undo history:** Layer edits, painting, selections, transforms, and
  floating pixels follow one chronological undo and redo path.
* **Host-controlled behavior:** Keep a background fixed, allow only mask
  editing, or expose the complete editor without changing the document model.
* **Host-controlled drag-out:** Resolve a composition or layer into file URLs,
  companion files, text, or custom MIME data without hard-coding storage into
  the canvas.
* **Optional AI-assisted selection:** The `sam` extra adds MobileSAM and its
  model runtime. Every ordinary mask and selection feature ships with
  CuteCanvas itself.

## Installation

```bash
# Complete editor
pip install cutecanvas

# Add AI-assisted selection
pip install "cutecanvas[sam]"
```

Installing CuteCanvas also installs QPane, its rendering dependency.

## Your First Canvas

Create the widget after `QApplication`, make a document, and add it to your
window like any other Qt widget:

```python
import sys

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QMainWindow
from cutecanvas import CanvasDocument, CuteCanvas

app = QApplication(sys.argv)

document = CanvasDocument()
composition_id = document.create_composition(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="My first canvas",
)

window = QMainWindow()
canvas = CuteCanvas(document=document, features=("mask",))
canvas.openComposition(composition_id)
window.setCentralWidget(canvas)

window.resize(1200, 760)
window.show()
app.exec()
```

That document is ready for layers, tools, selections, and history. Mask
editing is included in the normal package; `features=("mask",)` activates the
mask tools for this widget.

## Add Something Editable

An empty paint layer stores only the regions the user touches, so a large
canvas does not require one equally large transparent allocation:

```python
layer_id = canvas.createPaintLayer(label="Paint")
scene = canvas.currentScene()

if scene is not None and layer_id is not None:
    canvas.setSelectedLayer(scene.scene_id, layer_id)
    canvas.setPaintTarget(scene.scene_id, layer_id)
    canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

Use the normal Qt signals to keep your actions and panels synchronized:

```python
canvas.sceneEditHistoryChanged.connect(
    lambda can_undo, can_redo: print(can_undo, can_redo)
)
canvas.selectedLayerChanged.connect(lambda layer: print(layer))
canvas.paintTargetChanged.connect(lambda target: print(target))
```

## Documents and Layers

A `CanvasDocument` is a headless host-owned project. It owns reusable resources,
independent compositions, layer stacks, selections, and one chronological edit
history. It can exist before any widget and can be mounted by more than one
view.

A composition is one canvas-sized coordinate space inside that document. It
can begin empty or be seeded from an image. Seeding is a convenience: the image
becomes a normal layer that the host may lock, move, hide, reorder, or remove.

`canvas.editor.compositions` returns lightweight handles for ordinary application
code:

```python
from PySide6.QtCore import QPointF

composition = canvas.editor.compositions.current
if composition is not None and composition.layers:
    layer = composition.layers[-1]
    layer.select()
    layer.translate(QPointF(24.0, 0.0))
    layer.center(vertically=False)
```

Handles keep stable identity and always ask the document for current state.
They do not leave a stale private copy behind after undo, reordering, removal,
or document restoration.

## Show the Same Work More Than One Way

`CanvasWorkspace` arranges independent composition views without flattening
them into one artificial coordinate space. Its target canvases share one
document runtime, including mutation freshness and bounded execution:

```python
from cutecanvas import CanvasWorkspace

workspace = CanvasWorkspace(document_runtime=canvas.documentRuntime())
workspace.setTabbedPresentation(document.composition_ids(), linked=True)
window.setCentralWidget(workspace)
```

Linked tabs preserve the inspected normalized region while each composition
keeps its own native dimensions and local 100% zoom. The same workspace can
show a responsive grid or a two-target comparison:

```python
workspace.setGridPresentation(document.composition_ids())

first, second = document.composition_ids()[:2]
workspace.setComparisonPresentation(first, second)
```

Built-in multi-view presentations are read-only by default. Use
`setInteractionMode()` when a host deliberately wants mask authoring or full
editing in those views.

Outbound dragging is equally host-owned. Install one `OutboundMimeProvider` on
the workspace and return file URLs, a compressed companion file, text, or
application-specific MIME values for the stable content reference in each
`DragSubject`.

When the payload needs freshly rendered pixels, ask the mounted canvas for a
cancellable projection. It uses the same scene renderer as the visible canvas
and refuses to publish a result if the referenced content changes while work
is running:

```python
from PySide6.QtCore import QSize

reference = document.content_reference(first)
canvas.projectionCompleted.connect(handle_projection)
request = canvas.requestProjection(reference, pixel_size=QSize(1920, 1080))
```

## Selections, Masks, and Painting

Layer selection answers “which layer am I editing?” Pixel selection answers
“which part of it?” The rectangle, ellipse, and lasso tools build soft pixel
selections. The Move tool moves selected nontransparent pixels when a pixel
selection is active; otherwise it moves an eligible layer.

Masks use the same coverage tools. You can paint them, draw retained shapes,
fill them, move and transform them as layers, or create exact proportional
regions from host code. Export produces an ordinary grayscale mask for the
document canvas while editable document saves preserve off-canvas content and
retained shapes.

The brush system is shared by mask and color painting. A `BrushPreset` controls
size, hardness, opacity, flow, spacing, smoothing, pressure, tilt, texture, and
jitter without creating separate brush behavior for each target.

Clone Stamp uses that same brush feel and history path. Alt-click chooses a
rendered source independently from the paint destination. Each stroke samples
the anchored layer, that layer and visible layers below it, or the complete
visible composition. Overlapping strokes cannot feed their freshly written
pixels back into themselves. Rotation, scale, and reflection are applied around
the source anchor, with an on-canvas outline showing the exact sampled area.

## Move, Transform, and Snap

Move selected pixels without immediately rewriting their source. The lifted
pixels remain temporary until the user anchors them, sends them to another
compatible layer, promotes them to a new layer, or cancels the operation.

Free Transform provides corner and side handles for scale, rotation, skew, and
translation. Move and Transform both use the same snapping system. By default,
snapping follows the visible painted content instead of the transparent storage
around it; hosts can choose another geometry policy when fixed bounds are
meaningful.

## Save the Editable Work

A flattened image and an editable document solve different problems. Image
export clips the visible result to the composition canvas. A `.cutecanvas` archive
retains layers, transforms, masks, selections, linked-image information,
policies, and off-canvas content:

```python
composition = canvas.editor.compositions.current
if composition is not None:
    canvas.editor.persistence.save(composition, "example.cutecanvas")
```

Restore validates the complete archive before changing the mounted document,
so an invalid file cannot leave half-restored state behind.

## Try the Demo

The repository includes one complete CuteCanvas example. It is both a usable
small editor and a source-code tutorial for host applications:

```powershell
# From the repository root
python examples\cutecanvas_demo.py
```

The demo creates and opens compositions, manages a composition-and-layer tree,
draws and edits raster, mask, vector, and placed-image layers, exercises Move
and Transform, and saves complete editable documents using only public APIs.

## Documentation

* **[Getting Started](docs/getting-started.md):** Build the widget and your first
  editable document.
* **[Documents and Presentations](docs/documents-and-presentations.md):** Own
  documents outside widgets; mount linked tabs, grids, and comparisons; and
  provide drag-out MIME data.
* **[Project Resources](docs/project-resources.md):** Share or fork content,
  nest live documents, and persist the complete dependency graph.
* **[Documents and Layers](docs/scenes.md):** Create documents, add layers, set
  policies, arrange the stack, and inspect state.
* **[Painting](docs/painting.md):** Create sparse raster layers, configure the
  shared brush, choose targets, erase, and fill.
* **[Placed Images](docs/placed-images.md):** Embed, link, refresh, duplicate,
  and rasterize image assets.
* **[Vector Layers](docs/vector-layers.md):** Author shapes, paths, and text;
  edit objects; use vector coverage; and rasterize when needed.
* **[Interaction and Tools](docs/interaction-modes.md):** Connect tool actions
  and understand Move, Transform, snapping, and temporary navigation.
* **[Pixel Selections](docs/pixel-selections.md):** Select, delete, fill, and
  move part of a raster or mask.
* **[Masks and AI Selection](docs/masks-and-sam.md):** Paint masks, draw exact
  mask shapes, export coverage, configure autosave, and add MobileSAM.
* **[Configuration](docs/configuration.md):** Tune memory, input, brush feel,
  autosave, and background work.
* **[Touch and Pen](docs/touch-and-pen.md):** Support fingers, pressure-sensitive
  pens, palm rejection, and temporary navigation.
* **[Extensibility](docs/extensibility.md):** Add tools, overlays, effects, and
  host-owned presentation.
* **[Host Cookbook](docs/host-cookbook.md):** Connect the complete command and
  signal surface in a full editor application.
* **[Host State](docs/host-state.md):** Understand snapshots, policies, enums,
  and the values used to build application UI.
* **[Diagnostics](docs/diagnostics.md):** Observe editor and renderer work.
* **[API Reference](docs/api-reference.md):** Look up the complete public
  surface.

## License & Philosophy

CuteCanvas is **Free and Open Source Software (FOSS)**, distributed under the
**GNU General Public License v3.0 or later**.

I believe robust creative infrastructure should be a public good, not a
proprietary product. CuteCanvas is meant to give PySide6 developers a serious
starting point for editors of their own, while keeping improvements to its
rendering and editing foundations available to everyone.

## From the Developer 💖

I hope CuteCanvas saves you the months of headache it takes to build a capable,
responsive editor from scratch! If you'd like to support my work or see what
else I'm up to, here are a few links:

- **Buy Me a Coffee**: You can help fuel more projects like this at my [Ko-fi page](https://ko-fi.com/artificial_sweetener).
- **My Website & Socials**: See my art, poetry, and other dev updates at [artificialsweetener.ai](https://artificialsweetener.ai).
- **If you like this project**, it would mean a lot to me if you gave me a star here on Github!! ⭐
