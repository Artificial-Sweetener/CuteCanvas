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
