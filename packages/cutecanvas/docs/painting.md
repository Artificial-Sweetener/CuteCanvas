# Painting

The brush paints color, mask coverage, or pixel-selection coverage through one
stroke engine. The active target decides what a stroke means; brush spacing,
softness, dynamics, preview, history, and damage tracking stay the same.

## Create a Paint Layer

Open a document before creating editable content:

```python
from cutecanvas import RasterExtentPolicy

layer_id = canvas.createPaintLayer(
    label="Paint",
    extent_policy=RasterExtentPolicy.UNBOUNDED,
)
scene = canvas.currentScene()

if scene is not None and layer_id is not None:
    canvas.setSelectedLayer(scene.scene_id, layer_id)
    canvas.setPaintTarget(scene.scene_id, layer_id)
    canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

An unbounded paint layer stores touched regions without allocating one
transparent image as large as the document. Pixels may remain outside the
document canvas and return when the layer moves. Export clips the rendered
result to document bounds.

Choose `FIXED` when writes must remain inside existing storage, or
`EXPAND_ON_WRITE` when storage should grow as new regions are painted.

The visible layer selection is always the brush destination. If that layer
cannot store pixels, the default editor policy creates an unbounded paint
layer directly above it, selects the new layer, and continues the same
gesture. The layer creation and the stroke are separate undoable edits. A
host that requires explicit layer creation can reject this behavior:

```python
from cutecanvas import EditorPolicy, NonEditablePaintPolicy

canvas.setEditorPolicy(
    EditorPolicy(noneditable_paint=NonEditablePaintPolicy.REJECT)
)
```

`setPaintTarget(scene_id, layer_id)` also selects that layer. Painting never
uses an invisible destination that disagrees with the layer shown as selected.

## Configure the Brush

`BrushPreset` is an immutable description of the brush:

```python
from PySide6.QtGui import QColor
from cutecanvas import BrushDynamics, BrushPreset

preset = BrushPreset(
    name="Soft color",
    size=72.0,
    hardness=0.35,
    opacity=0.9,
    flow=0.65,
    spacing=0.12,
    smoothing=0.25,
    dynamics=BrushDynamics(
        pressure_size=0.8,
        pressure_opacity=0.4,
        minimum_pressure_ratio=0.15,
    ),
)

canvas.setBrushPreset(preset)
canvas.setPaintColor(QColor("cornflowerblue"))
```

The same preset produces the same dab sequence for preview and commit. Mouse,
touch, and pen input enter that sequence through device-specific samples rather
than separate painting implementations.

## Retouch with Clone Stamp

Clone Stamp uses the active brush preset on an editable RGBA layer. Activate
the tool, select the source layer, and Alt-click the source point. Then select
an editable destination or let the first stroke create one:

```python
from PySide6.QtCore import QPointF

canvas.editor.clone_stamp.activate()
canvas.editor.clone_stamp.set_source(QPointF(240.0, 180.0))
```

The point passed from host code is in scene coordinates. Direct interaction
uses the same command when the user Alt-clicks the canvas.

Choose whether separate strokes retain the source-to-destination offset and
which rendered product supplies pixels:

```python
from cutecanvas import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampTransform,
)

canvas.editor.clone_stamp.set_alignment(CloneStampAlignment.ALIGNED)
canvas.editor.clone_stamp.set_sample_mode(
    CloneStampSampleMode.VISIBLE_COMPOSITE
)
canvas.editor.clone_stamp.set_transform(
    CloneStampTransform(
        rotation_degrees=30.0,
        scale_x=1.5,
        scale_y=1.5,
        mirror_horizontal=True,
    )
)
```

`CloneStampAlignment` describes source-offset behavior between strokes.
`CloneStampAlignment.ALIGNED` retains the established offset, while
`CloneStampAlignment.UNALIGNED` begins again from the chosen source.

`CloneStampSampleMode.ANCHORED_LAYER` samples only the layer on which the
source was chosen. `CloneStampSampleMode.ANCHORED_LAYER_AND_BELOW` samples
that layer and every visible layer below it.
`CloneStampSampleMode.VISIBLE_COMPOSITE` samples all visible layers. Hidden
layers never contribute. The source layer may be placed, vector, hybrid, or
otherwise non-editable because Clone Stamp samples its rendered canvas
appearance rather than its underlying storage.

`CloneStampTransform` rotates, scales, and reflects the sampled content around
its source anchor. Scale describes the visible result: `2.0` produces cloned
content at twice its source size. `CloneStampTransform.rotation_degrees`
controls rotation. `CloneStampTransform.scale_x` and
`CloneStampTransform.scale_y` control horizontal and vertical output size.
`CloneStampTransform.mirror_horizontal` and
`CloneStampTransform.mirror_vertical` reflect either source axis
independently. The sampled-area outline uses the exact same affine mapping as
the stroke, so its size and orientation show which source pixels will
contribute before painting begins. During a stroke it follows the effective
source; after release it returns to the chosen anchor.

The source identity is independent from the selected destination. Changing
the selection after choosing a source does not move or replace the source.
Every stroke freezes its scene geometry, source range, and resource revisions.
Destination writes cannot feed back into the same stroke, and a source
revision changed during a stroke cancels the complete provisional result.
Configuration changed during an active stroke applies to the next stroke
without disturbing the one already in progress.

Each stroke is one undoable edit. Holding Space finishes the current stroke
before temporary navigation, then returns to Clone Stamp without clearing its
source or alignment state. Connect `cloneStampChanged` when host controls need
to mirror source availability or configuration.

`CloneStampFacade` is available as `canvas.editor.clone_stamp`. The equivalent
widget methods are `CuteCanvas.cloneStampState`,
`CuteCanvas.setCloneStampSource`, `CuteCanvas.clearCloneStampSource`,
`CuteCanvas.setCloneStampAlignment`, and
`CuteCanvas.setCloneStampSampleMode`, and `CuteCanvas.setCloneStampTransform`;
`CuteCanvas.cloneStampChanged` publishes the complete updated state.

`CloneStampSource.scene_id` and `CloneStampSource.scene_position` retain the
composition anchor, and `CloneStampSource.scene_point()` returns it as a
detached `QPointF`. Layer-anchored sources also provide
`CloneStampSource.layer_id`, `CloneStampSource.layer_position`, and
`CloneStampSource.layer_point()` in the layer's zero-origin source space.
Marker feedback and sampling use QPane's same typed projection, so affine
placement and nonzero raster storage bounds remain aligned.
`CloneStampState.source_set` is the concise availability check for host
controls.

## Choose a Paint Target

`setPaintTarget(scene_id, layer_id)` targets a pixel-editable raster or mask
layer. `setPixelSelectionPaintTarget()` edits the selection coverage itself.
`clearPaintTarget()` leaves the brush with no writable destination.

`paintTargetState()` returns a detached snapshot suitable for toolbar state.
Connect `paintTargetChanged` when selection or layer changes should update the
host's color and brush controls.

Brush color affects raster painting immediately. Mask and selection targets
store coverage; their visible tint comes from mask or selection presentation,
not from the raster paint color.

## Erase and Constrain Strokes

The brush tool supports paint and erase operations. A pixel selection limits
raster-layer painting to selected coverage. Soft selection edges proportionally
limit the stroke instead of becoming a binary clip.

Each pointer contact is one history edit. Undo removes the complete stroke,
including every resampled dab, without exposing a partially restored frame.

## Fill with the Paint Bucket

The bucket fills a connected color region on the active paint target:

```python
canvas.configurePaintBucket(
    tolerance=24,
    contiguous=True,
    antialias=True,
)
canvas.setControlMode(canvas.CONTROL_MODE_PAINT_BUCKET)
```

With a pixel selection active, the fill is clipped by that coverage. Use
`fillSelection()` when the intended region is exactly the selection rather
than a sampled color region.

## Keep Host Controls Synchronized

Useful signals include:

* `brushPresetChanged` for size, hardness, spacing, and dynamics controls.
* `paintColorChanged` for the active raster color.
* `paintTargetChanged` for target identity and availability.
* `cloneStampChanged` for source, alignment, and sampling configuration.
* `sceneEditHistoryChanged` for undo and redo actions.
* `rasterSurfaceChanged` after committed pixel content changes.

Do not cache an editable `QImage` in the host. The raster surface owns sparse
storage, render revisions, and damage. Use public snapshots and commands so
painting continues to benefit from tiled rendering.

## Related Docs

* [Pixel Selections](pixel-selections.md): Constrain, fill, delete, and move
  selected pixels.
* [Masks and SAM](masks-and-sam.md): Paint and export coverage layers.
* [Touch and Pen](touch-and-pen.md): Pressure, palm rejection, and direct input.

**Continue →** [Placed Images](placed-images.md)
