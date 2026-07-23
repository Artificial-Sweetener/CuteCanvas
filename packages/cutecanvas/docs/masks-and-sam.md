**← Previous:** [Pixel Selections](pixel-selections.md)

# Masks and SAM

A CuteCanvas mask is an editable grayscale layer. White coverage marks the
included region, black marks the excluded region, and values between them keep
soft edges.

Masks can contain brush strokes, imported grayscale pixels, rectangles,
ellipses, and paths at the same time. They remain normal document layers, so
users can select, move, transform, reorder, hide, and save them with the rest of
the document.

## Enable Mask Tools

Mask editing ships in the normal CuteCanvas package. Request it when creating
the widget:

```python
from cutecanvas import CuteCanvas

canvas = CuteCanvas(features=("mask",))
```

The optional `sam` extra adds MobileSAM, Torch, and model support:

```bash
pip install "cutecanvas[sam]"
```

Then request both features:

```python
canvas = CuteCanvas(features=("mask", "sam"))
```

`maskFeatureAvailable()` and `samFeatureAvailable()` report what this widget
successfully activated. A missing optional model or runtime does not prevent the
rest of the editor from opening.

## Create a Mask

Create a blank mask in the open document:

```python
from PySide6.QtCore import QSize

mask_id = canvas.createBlankMask(QSize(1920, 1080))
if mask_id is not None:
    canvas.setActiveMaskID(mask_id)
```

The size is the mask's initial local raster extent, not the document identity.
An empty document can create a mask just as easily as an image-seeded document.

Import an existing mask with:

```python
mask_id = canvas.loadMaskFromFile("existing-mask.png")
```

Color images are converted to 8-bit coverage. The returned UUID identifies the
mask resource; its document layer has its own layer ID and transform.

## Choose the Active Mask

Only one mask receives mask-specific painting at a time:

```python
canvas.setActiveMaskID(mask_id)
print(canvas.activeMaskID())
```

`listMasksForImage()` returns `MaskInfo` rows for the active composition when
called without an image ID. Each row includes label, overlay color, opacity,
active state, and its scene and layer IDs.

Catalog-oriented applications may pass an image ID to address that image's
generated document. A document-and-layer tree should instead use
`getCompositionSnapshot()`, which lists masks beside every other layer type.

## Set the Overlay Color

Mask pixels remain grayscale even though the editor displays them as a colored
overlay:

```python
from PySide6.QtGui import QColor

canvas.setMaskProperties(
    mask_id,
    color=QColor("magenta"),
    opacity=0.5,
)
```

Changing the overlay color does not rewrite mask coverage. It updates the live
presentation immediately.

## Paint a Mask

Make the mask active and choose Brush:

```python
canvas.setActiveMaskID(mask_id)
canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

The shared `BrushPreset` controls size, hardness, opacity, flow, spacing,
smoothing, pressure, tilt, texture, and jitter. On a mask, the brush writes
coverage instead of RGB color.

Mouse, touch, and active pens use the same stroke path. A pressure-sensitive
pen changes the diameter when pressure is enabled. Two fingers navigate before
a stroke begins, and recent pen input suppresses accidental palm painting.

An active pixel selection constrains both the preview and committed stroke.
Pixels outside the selection never flash on screen temporarily.

## Draw Mask Shapes

Rectangle, ellipse, and lasso mask tools keep their geometry editable:

```python
canvas.setControlMode(canvas.CONTROL_MODE_MASK_RECTANGLE)
canvas.setControlMode(canvas.CONTROL_MODE_MASK_ELLIPSE)
canvas.setControlMode(canvas.CONTROL_MODE_MASK_LASSO)
```

The same modifiers used by selection tools apply: Shift adds, Alt subtracts,
and Shift+Alt intersects. Shift constrains rectangles and ellipses after the
gesture starts, while Alt draws around the starting point as a center.

Use `configureCoverageShapes(feather_radius=...)` before drawing to create a
soft retained edge.

Retained shapes do not force painted regions to become vector geometry. A mask
keeps each contribution in the form that best represents it and evaluates them
together for display or export.

## Create Exact Regions from Host Code

The coverage facade creates the same shapes without simulating pointer input.
With an active mask, target coordinates are mask-local:

```python
from PySide6.QtCore import QRectF

canvas.editor.coverage.rectangle(
    QRectF(100.0, 80.0, 640.0, 360.0),
)
```

Normalized coordinates make proportional layouts independent of pixel size:

```python
from PySide6.QtCore import QPointF, QRectF
from cutecanvas import CoverageCoordinateSpace

# Exact left half.
canvas.editor.coverage.rectangle(
    QRectF(0.0, 0.0, 0.5, 1.0),
    coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
)

# Exact top quarter.
canvas.editor.coverage.rectangle(
    QRectF(0.0, 0.0, 1.0, 0.25),
    coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
)

# A normalized polygon below it.
canvas.editor.coverage.polygon(
    (
        QPointF(0.0, 0.25),
        QPointF(1.0 / 3.0, 0.25),
        QPointF(1.0 / 3.0, 1.0),
        QPointF(0.0, 1.0),
    ),
    coordinate_space=CoverageCoordinateSpace.NORMALIZED_TARGET,
)
```

`TARGET` and `NORMALIZED_TARGET` are explicit choices, so CuteCanvas never
guesses coordinate meaning from whether numbers happen to fall between zero
and one.

Use `canvas.editor.coverage.image()` to add arbitrary soft grayscale coverage.
Every coverage call participates in the same ordered add, subtract, intersect,
and replace behavior as interactive tools.

## Fill a Mask

With a mask paint target and an active pixel selection,
`fillSelection()` writes full coverage through the selection's soft edge:

```python
canvas.fillSelection()
```

Paint Bucket finds a matching region in the mask itself:

```python
canvas.configurePaintBucket(
    tolerance=16,
    contiguous=True,
    antialias=True,
)
canvas.setControlMode(canvas.CONTROL_MODE_PAINT_BUCKET)
```

Flood sampling happens in the background. A result is applied only if the
document, target, and source revision still match the request.

## Turn a Mask into a Pixel Selection

A painted mask is useful as saved selection coverage. Select its layer, then
copy its visible coverage into the document selection:

```python
mask = next(item for item in canvas.listMasksForImage() if item.mask_id == mask_id)
if mask.scene_id is not None and mask.layer_id is not None:
    canvas.selectLayerCoverage(mask.scene_id, mask.layer_id)
```

The resulting pixel selection is independent. Later mask edits do not silently
change it.

## Move and Transform a Mask

A mask is a normal layer. Select its layer, then use Move or Transform:

```python
canvas.setSelectedLayer(mask.scene_id, mask.layer_id)
canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
```

Moving changes the layer transform, not its stored coverage. Content may move
outside the document canvas and return later. Snapping follows painted coverage
by default, excluding transparent mask storage around it.

Use the same `LayerPolicy`, `LayerGeometryPolicy`, visibility, order, and
history APIs described in [Documents and Layers](scenes.md).

## Choose Fixed or Unbounded Storage

Mask placement and mask storage are separate. New masks begin with fixed local
bounds. Fixed storage clips new brush, fill, and generated coverage at that
rectangle.

Use unbounded storage when users should be able to move content off canvas and
continue painting wherever the layer now lies:

```python
from cutecanvas import RasterExtentPolicy

canvas.setRasterExtentPolicy(
    mask.scene_id,
    mask.layer_id,
    RasterExtentPolicy.UNBOUNDED,
)
```

Unbounded masks allocate only touched regions and may retain negative local
coordinates. `EXPAND_ON_WRITE` is available when a host wants explicit bounds
that grow as new writes arrive. `FIXED` remains appropriate when local extent
has domain meaning.

`rasterSurfaceState()` reports the current local bounds and policy.
`requestRasterBounds()` pads or crops storage on a worker and reports completion
through `rasterBoundsRequestCompleted`. Cropping is a real undoable edit;
changing placement is not.

## Export and Save

`getActiveMaskImage()` evaluates the current mask into a detached grayscale
`QImage` for processing or host-controlled export:

```python
mask_image = canvas.getActiveMaskImage()
if mask_image is not None:
    mask_image.save("mask.png")
```

Mask export and autosave use the document's raster window. Editable document
persistence keeps the complete mask, including retained shapes and off-canvas
coverage, so reopening a `.cutecanvas` file does not discard work that was
outside the exported rectangle.

`rasterizeMaskCoverage(mask_id)` deliberately flattens retained mask authorship
into raster coverage as one undoable edit.

## Undo and Autosave

Mask changes join the document's chronological history:

```python
canvas.editor.history.undo()
canvas.editor.history.redo()
```

The mask-named undo methods remain available for catalog-oriented mask hosts,
but they step the same document history rather than a second mask-only stack.

PNG autosave is disabled by default. Configure it when the host wants a
processing-ready mask beside the editable document:

```python
from cutecanvas import Config

config = Config().configure(
    mask_autosave_enabled=True,
    mask_autosave_debounce_ms=500,
    mask_autosave_path_template="masks/{image_id}_{mask_id}.png",
)
canvas = CuteCanvas(config=config, features=("mask",))
```

The debounce timer restarts after each edit. `maskSaved` reports the completed
mask ID and path. `mask_autosave_on_creation` controls whether a blank file is
written as soon as the layer is created.

## Use Smart Select

Smart Select appears when the `sam` feature is active:

```python
canvas.setControlMode(canvas.CONTROL_MODE_SMART_SELECT)
```

The user drags a box. CuteCanvas prepares the image embedding in the background,
runs the prediction, and adds the result to the active mask through the same
coverage history as brush and shape edits.

The first request for an image may need to prepare an embedding. Later requests
reuse a bounded cache keyed by image, device, and checkpoint.

### Checkpoint Setup

The default `background` download mode fetches missing MobileSAM weights without
blocking the window. Other deployments may choose:

* `blocking` when a startup screen must wait for a ready model;
* `disabled` when the application provisions the checkpoint itself;
* `sam_model_path` for a specific local file;
* `sam_model_url` for a host-controlled download source; and
* `sam_model_hash` for SHA-256 verification.

The built-in source uses its built-in hash. Supply a hash with a custom URL when
the application requires integrity verification.

Connect `samCheckpointStatusChanged` and `samCheckpointProgress` for download
UI. `samCheckpointReady()` and `samCheckpointPath()` report current readiness.
Call `refreshSamFeature()` after applying checkpoint-related settings at
runtime.

## Related Docs

* [Pixel Selections](pixel-selections.md): use mask coverage as a selection and
  constrain editing.
* [Interaction and Tools](interaction-modes.md): mask shape gestures, snapping,
  Move, Transform, and Paint Bucket.
* [Configuration Reference](configuration-reference.md): every mask, autosave,
  brush, and SAM setting.
* [Touch and Pen](touch-and-pen.md): pressure, hover, palm rejection, and
  gesture arbitration.

**Continue →** [Configuration](configuration.md)
