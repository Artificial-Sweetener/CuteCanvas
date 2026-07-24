**← Previous:** [Documents and Layers](scenes.md)

# Interaction and Tools

CuteCanvas tools turn pointer, keyboard, touch, and pen input into editor
actions. The active tool stays selected while documents change, and holding
Space temporarily gives input to Pan/Zoom without cancelling unfinished work.

This guide explains the built-in tools and the host policies that control them.

## Connect a Toolbar

Activate a tool with its public mode ID:

```python
canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
```

Read the current mode and available modes with:

```python
print(canvas.getControlMode())
print(canvas.availableControlModes())
```

`controlModeChanged` keeps checkable toolbar actions synchronized:

```python
def update_tool_actions(mode):
    move_action.setChecked(mode == canvas.CONTROL_MODE_MOVE)
    transform_action.setChecked(mode == canvas.CONTROL_MODE_TRANSFORM)


canvas.controlModeChanged.connect(update_tool_actions)
```

The focused facade offers the same path:

```python
canvas.editor.tools.activate(canvas.CONTROL_MODE_TRANSFORM)
print(canvas.editor.tools.active)
```

## Built-in Tools

CuteCanvas includes:

* **Pan/Zoom** for navigation.
* **Cursor** for a neutral pointer and configured image drag-out.
* **Move** for selected pixels or whole layers.
* **Transform** for affine layer manipulation.
* **Rectangle, Ellipse, and Lasso Select** for pixel selection.
* **Brush** for mask and RGBA painting.
* **Clone Stamp** for revision-stable rendered sampling onto RGBA layers.
* **Paint Bucket** for selection-constrained flood fill.
* **Rectangle, Ellipse, and Lasso Mask** for retained mask shapes.
* **Vector Shape, Path, Nodes, and Text** for vector authoring.
* **Smart Select** when the optional model feature is active.

The demo presents these as one restrained tool strip. Options appear only when
the active tool needs them.

## Pan and Zoom

Pan/Zoom uses the QPane navigation system underneath CuteCanvas:

* drag to pan;
* use the wheel to zoom around the pointer;
* double-click to switch between Fit and 1:1;
* drag with one finger to pan;
* use two fingers to pan and pinch; and
* hold Space from another tool for temporary navigation.

The temporary switch changes input ownership only. It does not commit, cancel,
or move an unfinished selection, floating-pixel edit, transform, vector path,
or brush transaction.

## Select Pixels

Rectangle, ellipse, and lasso selection tools edit one soft selection attached
to the open document:

```python
canvas.setControlMode(canvas.CONTROL_MODE_SELECT_RECTANGLE)
```

Drag normally to replace the selection. Hold Shift to add, Alt to subtract,
or Shift+Alt to keep only the overlap. For rectangles and ellipses, Shift also
constrains proportions once the gesture begins, and Alt draws around the start
point as a center.

The selection boundary follows nonzero coverage. Soft edges remain soft even
though the animated boundary marks a single threshold for display.

`Ctrl+D` clears a committed selection in the demo. Escape cancels a selection
gesture still being drawn; it does not unexpectedly clear an existing
selection.

See [Pixel Selections](pixel-selections.md) for host-authored coverage, Delete,
fill, and movement.

## Move Selected Pixels

When a pixel selection exists, Move acts on the selected part of the selected
editable layer:

```python
canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
```

The press must begin on selected, nontransparent content. Transparent RGBA
pixels and zero mask coverage do not become payload merely because they lie
inside the selection rectangle.

Dragging lifts the payload into a temporary floating edit. The source appears
cut during the preview, but its stored pixels remain untouched until the edit
is resolved. After release, the user may drag again or choose one of these
actions:

* Enter anchors to the source layer.
* Alt at the start of a drag makes a copy.
* `anchorFloatingPixels()` can send it to another compatible layer.
* `promoteFloatingPixels()` creates a new layer.
* Escape or `cancelFloatingPixels()` restores the original state.

One successful resolution creates one history entry containing the complete
source, destination, selection, and layer-selection change.

## Move a Whole Layer

Without a pixel selection, Move chooses a layer. It prefers the selected layer
when the pointer is over its visible content; otherwise it may select the
topmost eligible content under the pointer.

Layer policy must allow selection and movement. Transparent padding does not
capture the gesture. Hover feedback shows which content will move, and that
feedback disappears during the drag.

Arrow keys nudge by one local pixel. Shift+Arrow nudges by ten. Holding Shift
during a pointer drag constrains movement to the nearest 45-degree direction.

The live preview uses the same transform and clipping rules as the committed
frame, so content does not temporarily escape a fixed clip or leave stale
strips behind.

## Transform a Layer

Transform draws a content-tight box around the selected movable layer:

```python
canvas.setControlMode(canvas.CONTROL_MODE_TRANSFORM)
```

Eight circular handles appear at the corners and side centers:

* drag a corner to scale proportionally;
* hold Shift on a corner to scale each axis freely;
* drag a side handle to scale one axis;
* drag outside the box to rotate;
* hold Shift while rotating to use 15-degree steps;
* hold Alt to transform around the center; and
* hold Ctrl+Shift while dragging a side handle to skew.

Enter or an interior double-click applies the complete transform as one undoable
edit. Escape restores the exact starting transform. Holding Space to navigate
preserves the unresolved transform and its handle state.

The transform keeps floating-point geometry throughout the gesture. Snapping
does not round the final layer position to integer scene coordinates.

## Snapping

Move and Transform share one snapping system. Selection movement and retained
mask-shape movement use it too.

By default, snapping follows visible content bounds. This means transparent
padding around an image or mask does not create a surprising gap. A host may
choose source, storage, clip, authored, or custom bounds for a layer when that
meaning fits its application better.

The solver considers both axes during the same pointer update. It can align:

* left, center, and right edges;
* top, center, and bottom edges;
* opposing edges for side-by-side placement;
* corners while layers overlap or sit next to one another;
* the document center and sides;
* host-authored guides; and
* an optional grid.

Once acquired, a snap remains stable until the pointer moves far enough to
break away. Hold Ctrl during a gesture to suppress snapping temporarily.

Configure the behavior through `configureSnapping()`, add exact guides with
`setSnapGuides()`, and configure a grid with `setSnapGrid()`.

## Paint and Fill

Brush mode paints the current `PaintTargetSnapshot`. That target may be an
editable RGBA layer, an active mask, or the document's pixel selection.

```python
canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
```

The brush preset and color are independent from tool activation. Changing the
color updates the live brush controls immediately for color targets. Masks use
coverage rather than RGB color while retaining their configured overlay color.

Paint Bucket samples the active target in the background and commits one edit:

```python
canvas.configurePaintBucket(
    tolerance=24,
    contiguous=True,
    antialias=True,
)
canvas.setControlMode(canvas.CONTROL_MODE_PAINT_BUCKET)
```

An active pixel selection limits both brush and bucket results, including soft
edge coverage.

## Clone Pixels

Clone Stamp writes to an editable RGBA layer. When the selected source cannot
store pixels, the normal paint policy can create and select that destination
on the first stroke:

```python
canvas.setControlMode(canvas.CONTROL_MODE_CLONE_STAMP)
```

`CuteCanvas.CONTROL_MODE_CLONE_STAMP` is the string mode constant; typed host
code may use `ControlMode.CLONE_STAMP`.

Alt-click sets the source. The source marker remains visible until the source
is replaced or cleared, and the cursor reports an unavailable destination
before a source exists. Normal painting uses the shared brush size, hardness,
opacity, flow, spacing, smoothing, dynamics, and input lifecycle.

Aligned mode preserves one source offset across successive strokes. Unaligned
mode starts every stroke from the chosen source point. The source may come
from its anchored layer, that layer and the visible layers below it, or the
complete visible composition. The anchor remains independent from the selected
paint destination. In every mode, the complete stroke reads a stable rendered
source and commits as one history edit.

## Host Capability Policy

`EditorPolicy` lets an application expose only the editing capabilities it
needs. This is separate from each layer's policy.

```python
from cutecanvas import (
    EditorCapability,
    EditorPolicy,
    NonEditablePaintPolicy,
)

canvas.setEditorPolicy(
    EditorPolicy(
        capabilities=frozenset(
            {
                EditorCapability.SELECT_PIXELS,
                EditorCapability.EDIT_PIXELS,
                EditorCapability.PAINT,
                EditorCapability.MANAGE_LAYERS,
            }
        ),
        noneditable_paint=NonEditablePaintPolicy.CREATE_RASTER_LAYER,
    )
)
```

With `NonEditablePaintPolicy.CREATE_RASTER_LAYER`, a brush gesture on a
selected non-editable layer creates and selects a real raster layer above it
before painting.
`NonEditablePaintPolicy.REJECT` leaves the selection unchanged and performs no
stroke. `MANAGE_LAYERS` is required for automatic creation.

Use `editorOperationState()` before enabling an action:

```python
from cutecanvas import EditorIntent

state = canvas.editorOperationState(EditorIntent.DELETE_PIXELS)
delete_action.setEnabled(state.allowed)
if not state.allowed:
    delete_action.setToolTip(state.denial or "Unavailable")
```

The same query drives built-in tools and public commands. A placed or vector
layer that cannot accept direct pixel edits reports a stable reason and an
available next action, such as rasterization. It does not silently convert or
ignore the request.

## Custom Tools

CuteCanvas uses QPane's public `ViewerTool` extension system. A custom editor
tool receives normal pointer lifecycle, cursor arbitration, temporary
navigation, overlay repaint requests, and teardown behavior without building a
second input dispatcher.

Register it through `registerTool()` and keep durable document changes in a
focused CuteCanvas public operation. Tools should translate input into requests;
they should not own a second layer, selection, or history model.

See [Extensibility](extensibility.md) for a complete custom tool and overlay
example.

## Related Docs

* [Documents and Layers](scenes.md): layer policies, geometry, order, and
  programmatic movement.
* [Painting](painting.md): brush targets, presets, erasing, and Paint Bucket.
* [Pixel Selections](pixel-selections.md): soft selection, Delete, Fill, and
  floating pixels.
* [Masks and AI Selection](masks-and-sam.md): mask tools and coverage.
* [Touch and Pen](touch-and-pen.md): gesture arbitration, pressure, and palm
  rejection.
* [Extensibility](extensibility.md): custom tools, overlays, and effects.

**Continue →** [Pixel Selections](pixel-selections.md)
