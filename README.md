<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/2b10acf82f3b0aaf5844ba992653bbd7f00f1462/assets/logos/cutecanvas-logo-on-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/2b10acf82f3b0aaf5844ba992653bbd7f00f1462/assets/logos/cutecanvas-logo-on-light.svg">
    <img alt="CuteCanvas — PySide6 Graphics Editor" src="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/2b10acf82f3b0aaf5844ba992653bbd7f00f1462/assets/logos/cutecanvas-logo.svg" width="640">
  </picture>
</h1>

<p align="center">
  <a href="https://pypi.org/project/cutecanvas/"><img src="https://img.shields.io/pypi/v/cutecanvas?label=PyPI" alt="CuteCanvas on PyPI"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/actions/workflows/verify.yml"><img src="https://img.shields.io/github/actions/workflow/status/Artificial-Sweetener/CuteCanvas/verify.yml?branch=main&amp;label=Tests" alt="Test status"></a>
  <a href="https://pypi.org/project/cutecanvas/"><img src="https://img.shields.io/pypi/dm/cutecanvas?label=downloads" alt="PyPI downloads"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"></a>
  <a href="https://pyside.org/"><img src="https://img.shields.io/badge/PySide6-6.7.3%2B-41CD52?logo=qt&amp;logoColor=white" alt="PySide6 6.7.3+"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later license"></a>
</p>

**CuteCanvas** is an open-source graphics editor package for PySide6. It gives Python developers the complete document, layer, mask, selection, painting, transform, tool, history, persistence, and rendering infrastructure needed to build an editor for any purpose.

CuteCanvas is the editor you put inside your own application. You decide what the work means, what the interface looks like, which tools are available, what users may change, and how the result fits into everything around it.

Underneath CuteCanvas is **[QPane](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/qpane/README.md)**, the independently useful image viewer and raster/vector rendering SDK in this repository. Integrate QPane directly as a high-performance viewer or use its rendering SDK to compose and interact with raster, vector, and hybrid visual content. CuteCanvas adds the complete editing system on top.

## Highlights

* **A graphics editor you can import:** `CuteCanvas` is a `QWidget` with public documents, focused facades, Qt signals, and typed configuration for ordinary PySide6 integration.
* **Real editable documents:** Keep raster pixels, vector objects, text, masks, selections, placed assets, nested compositions, transforms, canvas geometry, and policy as distinct durable state.
* **Raster and vector authoring:** Paint and erase pixels, draw shapes and paths, edit text, fill regions, clone rendered content, and choose when retained content becomes directly editable pixels.
* **Serious masking and selection tools:** Combine soft raster coverage with retained vector shapes, edit polygons before closing them, move selected nontransparent pixels, and optionally add MobileSAM-assisted selection.
* **Direct manipulation that understands the document:** Move, scale, rotate, skew, align, snap, and reshape shared layer edges with coherent previews and atomic history.
* **Host-owned behavior:** Build a complete editor, a mask-only workstation, a locked review surface, a domain-specific annotation tool, or a purpose-built visual product with rules entirely owned by the host.
* **One history for the work:** Painting, masks, selections, layer operations, transforms, floating pixels, resources, and document changes undo and redo in the order the user performed them.
* **More than one view of the same work:** Mount one editable document in editors, linked tabs, native-size views, responsive grids, comparisons, and host-defined presentations.
* **Python outside, native performance underneath:** Python keeps product logic portable and expressive, Qt performs compiled graphics and image I/O, NumPy processes bulk pixels and coverage, and QPane renders the current viewport demand.
* **True FOSS:** Every supported CuteCanvas and QPane capability ships as GPLv3-or-later software for every user.

## Build the Editor Your Product Needs

Every visual product brings its own purpose, data model, permissions, interface, and workflow. CuteCanvas supplies the difficult editing infrastructure while your application remains the product.

Lock a source image and expose a focused mask-authoring surface with brushes, editable polygons, soft coverage, and optional model-assisted selection. Put two compositions into a linked comparison and let the user inspect the same region at each source's native scale. Combine refreshable linked images with editable text and vectors, then save the complete project graph or export the finished pixels.

The same public surface can add a domain-specific tool and overlay, assign each layer the operations that make sense, arrange several views around one document, or hand rendered results to the rest of the application. CuteCanvas's shared document and rendering foundations support everything from a compact annotation step to a review workstation, a structured asset editor, or a complete creative environment.

## CuteCanvas Is Built on QPane

**QPane is a high-performance image viewer and raster/vector rendering SDK for PySide6.** It provides the viewport, fluid pan and zoom, large-image tiling, scene composition, comparison, hit testing, overlays, caching, and background rendering underneath CuteCanvas.

CuteCanvas adds documents, editable layers, masks, selections, painting, transforms, tools, history, and persistence on top of that foundation.

If CuteCanvas is more editor than your application needs, install QPane directly for a polished image viewer. You can also build on the same public rendering SDK CuteCanvas uses to create your own visualizations, review surfaces, comparison tools, compositors, and interactive graphics workflows.

**[Read the QPane README →](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/qpane/README.md)**

## Python on Top, Native Work Underneath

Python owns the flexible control plane: documents, tools, policy, host integration, and workflow. Qt performs rasterization, compositing, transforms, image decoding, and image encoding in compiled code. NumPy performs bulk pixel and coverage operations on native arrays. QPane renders what the viewport demands, retains useful products, tracks damage, reuses unchanged presentation, and moves expensive work through bounded background execution while the GUI thread stays responsive.

CuteCanvas follows the same model. Sparse raster layers allocate touched regions and keep empty space virtual. Immutable resources can be shared by several layer instances. Live previews publish the state needed for the interaction, and completed edits settle atomically into the document.

The renderer is CPU-first by design. It remains useful in AI, scientific, and production applications where the GPU may already have a more important job than drawing the interface.

## Installation

Install the complete editor:

```bash
pip install cutecanvas
```

Masking, selections, painting, vectors, transforms, and persistence are part of the normal package. The optional `sam` extra adds AI-assisted selection:

```bash
pip install "cutecanvas[sam]"
```

CuteCanvas installs QPane as its rendering dependency. Install [QPane from PyPI](https://pypi.org/project/qpane/) directly when the application needs the viewer or rendering SDK:

```bash
pip install qpane
```

## Your First Editor

Create a host-owned document, mount it in the widget, and put that widget anywhere a normal Qt widget can go:

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

The application owns the document independently from the widget. The document can outlive a view, appear in several views, and remain the authoritative editable model through save and restore.

Add an editable raster layer and activate the brush:

```python
layer_id = canvas.createPaintLayer(label="Paint")
scene = canvas.currentScene()

if scene is not None and layer_id is not None:
    canvas.setSelectedLayer(scene.scene_id, layer_id)
    canvas.setPaintTarget(scene.scene_id, layer_id)
    canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

CuteCanvas exposes ordinary Qt signals and focused public facades for toolbars, layer trees, inspectors, save actions, and application state. Host code performs complete workflows through that supported boundary.

## Editable Documents and Flattened Exports

A `CanvasDocument` owns reusable resources, independent compositions, layer stacks, selections, host policy, and one chronological history. A composition is one canvas-sized coordinate space inside that document.

A composition may begin empty or be seeded from an image. A seed image becomes an ordinary layer that policy may lock, move, transform, hide, reorder, or remove.

Layers can reference editable raster content, vector artwork, text, hybrid coverage, embedded or linked images, and even another live composition. Several layers may share one immutable resource while retaining independent placement, visibility, opacity, effects, and policy. Fork the resource when one instance needs to become independent.

Saving a `.cutecanvas` archive preserves that structure, including off-canvas material and the dependency graph required by nested compositions. Exporting an image produces the flattened result when that is what the workflow actually needs.

## Painting, Masks, and Selections

The shared brush engine paints RGBA layers, masks, and selections. A `BrushPreset` controls size, hardness, opacity, flow, spacing, smoothing, pressure, tilt, texture, and jitter. Eraser uses the same input and brush behavior while explicitly removing alpha or coverage.

Clone Stamp samples a stable rendered source from one layer, the visible backdrop below it, or the complete visible composition. Paint Bucket performs selection-constrained flood fill in the background and adopts the result as one edit.

Pixel selections and masks support rectangle, ellipse, polygon, and lasso authoring. Polygon points can be moved, inserted, or removed before the polygon closes. Soft coverage remains soft, while retained shapes stay editable alongside painted coverage.

Move lifts the selected nontransparent pixels into a reversible floating edit. The user can reposition them repeatedly, return them to the source, send them to another compatible layer, promote them to a new layer, or cancel and restore the original state.

The optional SAM integration adds model-assisted selection to the same mask and selection workflows. Manual authoring remains available, and Torch stays out of the normal installation.

## Move, Transform, Snap, and Reshape

Move works on selected pixels or complete layer sets. Free Transform provides direct translation, scale, rotation, skew, flips, and quarter-turn commands. Completed gestures and commands are undoable inside the unresolved transform, while Apply contributes one final edit to document history.

Snapping is shared by movement, transforms, selections, masks, vector shapes, and vector paths. It can align visible content, authored geometry, canvas edges and centers, guides, and a configurable grid. Rotated scale handles follow and snap along their actual manipulation axes.

Shared Edge Resize recognizes a straight boundary shared by several movable layers. Rectangular group boundaries move together, while eligible polygon endpoints move along the straight rail genuinely shared by their participants. Endpoint gestures snap to horizontal, vertical, 45-degree, and continuous stationary-edge alignments. Several adjustments can be undone, redone, and refined inside one bounded session before the complete group commits atomically.

Canvas geometry remains explicit:

* Resize canvas bounds around any of nine anchors while preserving the current sampling of every layer.
* Resample the composition and every layer to a new pixel scale using Qt's smooth or nearest policy.
* Crop layer content to the current canvas as a separate undoable operation.

Bounds resizing preserves off-canvas work for later movement, export, cropping, or canvas expansion.

## Host Control Is Part of the Editor

CuteCanvas is designed to belong to another application.

An `EditorPolicy` controls which capabilities exist in a particular workflow. Layer and composition policy control what may be selected, moved, edited, reordered, removed, or rasterized. The same decision governs built-in tools, keyboard actions, and public host commands, so a disabled operation cannot be reached through a different path.

Hosts can:

* expose the complete editor or only a focused subset such as mask authoring;
* keep source imagery locked while users edit approved layers;
* provide their own toolbars, docks, trees, inspectors, shortcuts, and contextual controls;
* register custom tools, overlays, cursors, rendered-content effects, and diagnostics;
* choose what outbound dragging means, including files, companion documents, text, or custom MIME data;
* share a bounded execution runtime across CuteCanvas editors and QPane viewers; and
* drive host state from authoritative immutable snapshots and Qt signals.

Unavailable operations report stable reasons and, where possible, the valid next action. A vector or placed-image layer presents rasterization as an explicit route to direct pixel editing.

## One Document, Many Presentations

The same editable document can appear in more than one place while retaining one authoritative state and history.

`CanvasWorkspace` can mount independent tabs, native-size views, responsive grids, and two-target comparisons over one shared document runtime. Linked inspection preserves the same normalized region across sources with different native dimensions. Each view keeps its own active target, viewport, tools, and transient interaction while durable content and history remain with the document.

Cancellable projections render a document or layer for previews, exports, drag payloads, and other host workflows. Revision checks publish results that still match the referenced content.

## Developer Experience

CuteCanvas presents one obvious starting point and keeps the machinery behind it.

* `CuteCanvas` is the embeddable widget.
* `CanvasDocument` is the headless owner of editable work.
* `canvas.editor` provides focused composition, layer, history, selection, mask, resource, persistence, projection, and tool workflows.
* Stable handles retain identity while always observing current document state.
* Immutable snapshots and Qt signals provide authoritative state for host UI.
* Typed configuration covers input, brush behavior, memory, autosave, diagnostics, and optional features.
* Live diagnostics expose paint time, cache use, render activity, execution queues, mask work, and optional model activity.
* Public tools and overlays extend the editor through its authoritative input, scene, selection, and history systems.

The complete public contract ships with type information for editors and static analysis.

## Try the Demo

The repository includes one complete CuteCanvas example. It is both a usable small editor and a source-code guide to integrating the public API:

```powershell
# From the repository root
python packages\cutecanvas\examples\cutecanvas_demo.py
```

The demo creates and opens compositions, manages a composition-and-layer tree, draws and edits raster, mask, vector, and placed-image layers, exercises selection, painting, Move, Transform, and shared-edge workflows, and saves complete editable documents.

## Documentation

* **[Getting Started](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/getting-started.md):** Build the widget and the first editable document.
* **[Documents and Presentations](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/documents-and-presentations.md):** Own documents outside widgets; resize canvases; mount linked tabs, grids, and comparisons; and provide drag-out data.
* **[Project Resources](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/project-resources.md):** Share or fork content, nest live documents, and persist the complete dependency graph.
* **[Documents and Layers](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/scenes.md):** Create documents, add layers, set policy, arrange the stack, and inspect state.
* **[Painting](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/painting.md):** Create sparse raster layers, configure brushes, choose targets, erase, clone, and fill.
* **[Placed Images](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/placed-images.md):** Embed, link, refresh, duplicate, and rasterize image assets.
* **[Vector Layers](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/vector-layers.md):** Author shapes, paths, and text; edit objects; use vector coverage; and rasterize when needed.
* **[Interaction and Tools](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/interaction-modes.md):** Connect tools and understand Move, Transform, snapping, shared edges, and temporary navigation.
* **[Pixel Selections](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/pixel-selections.md):** Select, delete, fill, and move part of a raster or mask.
* **[Masks and AI Selection](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/masks-and-sam.md):** Paint masks, draw exact shapes, export coverage, configure autosave, and add MobileSAM.
* **[Configuration](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/configuration.md):** Tune memory, input, brush feel, autosave, and background work.
* **[Touch and Pen](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/touch-and-pen.md):** Support fingers, pressure-sensitive pens, palm rejection, and temporary navigation.
* **[Extensibility](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/extensibility.md):** Add tools, overlays, effects, and host-owned presentation.
* **[Host Cookbook](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/host-cookbook.md):** Connect the complete command and signal surface in an editor application.
* **[Building Host UI](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/host-ui.md):** Drive toolbars, trees, inspectors, and contextual controls from public commands, snapshots, and signals.
* **[Diagnostics](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/diagnostics.md):** Observe editor and renderer work.
* **[API Reference](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/packages/cutecanvas/docs/api-reference.md):** Look up the complete supported surface.

## Contributing

See [CONTRIBUTING.md](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/CONTRIBUTING.md) to set up the repository, run its ownership-driven tests, and work within the CuteCanvas and QPane package boundaries.

## License & Philosophy

CuteCanvas is **Free and Open Source Software (FOSS)**, distributed under the **GNU General Public License v3.0 or later**.

I believe robust editor infrastructure should be a public good. CuteCanvas gives Python developers a serious foundation for visual products of their own, and the GPL keeps improvements to that shared foundation available to the next developer.

## From the Developer 💖

I built CuteCanvas to put documents, layers, tools, masks, transforms, history, persistence, and responsive rendering in your hands from the first day, so you can focus on the product you actually care about.

If CuteCanvas saves you that work and you would like to support mine:

* **Buy Me a Coffee:** Help fuel more projects like this at my [Ko-fi page](https://ko-fi.com/artificial_sweetener).
* **My Website & Socials:** See my art, poetry, and development updates at [artificialsweetener.ai](https://artificialsweetener.ai).
* **Star the repository:** If you like the project, it would mean a lot to me if you gave it a star here on GitHub! ⭐
