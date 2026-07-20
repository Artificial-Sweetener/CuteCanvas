**← Previous:** [Catalog and Navigation](catalog-and-navigation.md)

# Interaction Modes

Modes define the relationship between the pointer and the image. Whether you are building a read-only viewer, a mask editor, or an inpainting workflow, the Control Mode determines what happens when a user clicks, drags, or scrolls.

## Switching Modes
Use `QPane.setControlMode` to switch tools. You can check which mode is active with `QPane.getControlMode` or see the full list of registered tools via `QPane.availableControlModes`.

Activate `QPane.CONTROL_MODE_MOVE` for selection-aware direct manipulation. With an active pixel selection, dragging selected, nontransparent content lifts an unresolved fragment; transparent RGBA pixels and zero mask coverage are excluded. Release keeps the fragment floating, Enter anchors it, Escape cancels it, and Alt begins a copy. Switching tools preserves floating pixels, including temporary Spacebar Pan/Zoom. Without pixel selection, the same tool moves a policy-enabled layer. The demonstration clears committed selections with `Ctrl+D`.

```python
from qpane import QPane

# Switch to Pan/Zoom (default navigation)
viewer.setControlMode(QPane.CONTROL_MODE_PANZOOM)

# Switch to a static cursor (good for read-only states)
viewer.setControlMode(QPane.CONTROL_MODE_CURSOR)

# Move selected pixels, or a movable layer when there is no pixel selection
viewer.setControlMode(QPane.CONTROL_MODE_MOVE)

# Transform the selected movable layer with direct-manipulation handles
viewer.setControlMode(QPane.CONTROL_MODE_TRANSFORM)

# Pixel-selection tools share one composition-scoped selection.
viewer.setControlMode(QPane.CONTROL_MODE_SELECT_RECTANGLE)
```

> **Heads-up:** `QPane.setControlMode` will ignore requests for mask or selection modes if the catalog is empty (check `QPane.placeholderActive()` to see if the placeholder is currently shown).

### Building a Toggle
QPane doesn't cycle modes automatically, but you can easily build a toggle button.

```python
# Cycle through available modes
modes = viewer.availableControlModes()
current = viewer.getControlMode()

if modes:
    # Find current index and step forward
    next_index = (modes.index(current) + 1) % len(modes)
    viewer.setControlMode(modes[next_index])
```

## Built-in Modes
QPane comes with core navigation modes ready to use. You can refer to them via the `ControlMode` enum or the string constants on `QPane`.

* **Pan/Zoom (`ControlMode.PANZOOM`):** The default. Mouse users drag to pan and scroll to zoom. Touch users drag with one finger, pan and pinch simultaneously with two fingers, and double tap to toggle between fit and 1:1. Wheel steps snap to 100% when crossing it, so you never skip the native scale. Use `QPane.CONTROL_MODE_PANZOOM` when a toolbar or shortcut should return to normal navigation.
* **Cursor (`ControlMode.CURSOR`):** "Look but don't touch." The viewport stays locked, and drag/scroll events are ignored. Use `QPane.CONTROL_MODE_CURSOR` for read-only states, kiosks, or hosts that handle pointer events outside the viewer.
* **Move (`ControlMode.MOVE`):** Lifts active pixel selection coverage from the selected editable mask or RGBA layer. The live preview moves both pixels and marching ants without changing durable storage; pointer release retains the fragment for repeated movement or explicit resolution. Enter anchors to the source, Escape cancels losslessly, Alt starts a copy, and the public floating-pixel APIs support another compatible layer or a newly created layer. Tool switches release pointer ownership without resolving the fragment, so temporary Spacebar Pan/Zoom preserves its exact position. Resolution is one atomic undoable edit. An active selection owns the gesture, so pressing outside its coverage does not fall through to an underlying layer. When no pixel selection exists, dragging selects and moves the top covered layer whose policy allows both operations. Mouse, pen, and one-finger touch share this path. Arrow keys nudge by one local pixel, Shift+Arrow nudges by ten, and Shift constrains a drag to the nearest 45-degree direction.
* **Transform (`ControlMode.TRANSFORM`):** Shows a content-tight affine box around the selected movable layer. Drag the corner circles to scale proportionally, hold Shift to scale freely, drag side circles to scale one axis, or drag outside the box to rotate. Shift snaps rotation to 15-degree increments, Alt transforms about the center, and Ctrl+Shift-drag on a side circle skews. Enter or an interior double-click applies the cumulative transform as one undoable edit; Escape cancels it. Temporary tool switches preserve unresolved geometry.

Use `QPane.CONTROL_MODE_TRANSFORM` when a host toolbar or shortcut should activate this transform interaction.
* **Rectangle, Ellipse, and Lasso:** Build antialiased 8-bit selection coverage in scene coordinates. Drag normally to replace, hold Shift to add, Alt to subtract, or Shift+Alt to intersect. Selection state belongs to the active composition and remains visible as animated marching ants when switching tools.

The complete built-in selection IDs are `ControlMode.SELECT_RECTANGLE`, `ControlMode.SELECT_ELLIPSE`, and `ControlMode.SELECT_LASSO`, mirrored by `QPane.CONTROL_MODE_SELECT_RECTANGLE`, `QPane.CONTROL_MODE_SELECT_ELLIPSE`, and `QPane.CONTROL_MODE_SELECT_LASSO`.

Programmatic selection uses `PixelSelectionMode`: choose `PixelSelectionMode.REPLACE`, `PixelSelectionMode.ADD`, `PixelSelectionMode.SUBTRACT`, or `PixelSelectionMode.INTERSECT` when calling `QPane.setPixelSelection`. Read `QPane.pixelSelectionState`, which returns `QPanePixelSelectionState`; its `QPanePixelSelectionState.scene_id`, `QPanePixelSelectionState.revision`, `QPanePixelSelectionState.bounds`, `QPanePixelSelectionState.coverage`, and `QPanePixelSelectionState.has_selection` values form a detached snapshot. Connect `QPane.pixelSelectionChanged` to refresh host controls, and use `QPane.selectAllPixels`, `QPane.invertPixelSelection`, or `QPane.clearPixelSelection` for standard commands.

## Host Editor Capabilities

Use `QPaneEditorPolicy` when an application wants only part of the editor. Capabilities compose independently, so an annotation host can allow selection and painting without enabling complete-layer movement or transform. The default policy enables every capability and preserves normal QPane behavior.

```python
from qpane import EditorCapability, EditorIntent, QPaneEditorPolicy

viewer.setEditorPolicy(
    QPaneEditorPolicy(
        frozenset(
            {
                EditorCapability.SELECT_PIXELS,
                EditorCapability.PAINT,
            }
        )
    )
)

delete_state = viewer.editorOperationState(EditorIntent.DELETE_PIXELS)
if not delete_state.allowed:
    print(delete_state.denial, delete_state.alternatives)
```

`QPane.editorOperationState` is the authoritative availability query for menus, shortcuts, and contextual controls. It uses the same resolution as the built-in tools: floating pixels take priority over selected pixels, selected pixels take priority over whole-layer movement, and direct pixel edits require a source that owns editable pixels. Placed assets and vector sources remain non-destructive; paint or Delete reports `direct-pixel-edit-unsupported` and advertises explicit alternatives such as rasterization instead of silently changing the source.

The `EditorCapability` enum names independent host permissions rather than source
types. `EditorCapability.SELECT_PIXELS` enables selection construction,
`EditorCapability.EDIT_PIXELS` enables selection-constrained mutation,
`EditorCapability.PAINT` enables brush transactions, and
`EditorCapability.MOVE_LAYERS` plus `EditorCapability.TRANSFORM_LAYERS` enable
whole-layer geometry changes. The immutable `QPaneEditorPolicy.capabilities` set
lets a host combine those permissions without changing any layer's intrinsic
abilities.

Use `EditorIntent` to ask about a concrete editor operation before presenting or
executing it. `EditorIntent.SELECT_PIXELS` represents selection construction,
`EditorIntent.DELETE_PIXELS` represents selection-constrained clearing,
`EditorIntent.PAINT` represents brush input, `EditorIntent.MOVE` represents
selected-pixel or whole-layer movement, and `EditorIntent.TRANSFORM` represents
their affine transform equivalent. These queries follow the same precedence and
eligibility rules as the built-in tools.

Each query returns a detached `QPaneEditorOperationState` whose
`QPaneEditorOperationState.intent` preserves the request and whose
`QPaneEditorOperationState.allowed` flag says whether it can run now. When it
cannot, `QPaneEditorOperationState.denial` gives the stable reason and
`QPaneEditorOperationState.alternatives` gives explicit next actions rather than
silently converting content. The optional `QPaneEditorOperationState.scene_id`
and `QPaneEditorOperationState.layer_id` fields identify the resolved target for
host controls that need contextual feedback.

Read `QPane.editorPolicy` whenever a host control needs the complete current
permission set. Subscribe to `QPane.editorPolicyChanged` to refresh those controls
after an actual policy replacement; setting an equal policy does not emit a
redundant notification.

Raster write extent remains a separate layer decision: `RasterExtentPolicy.FIXED` clips at hard local bounds, `RasterExtentPolicy.UNBOUNDED` accepts arbitrary local coordinates sparsely, and `RasterExtentPolicy.EXPAND_ON_WRITE` preserves the named grow-on-write policy with the same sparse backing.

Host editor policy and `QPaneLayerInteractionPolicy` solve different problems. Editor policy enables application-wide capabilities. Layer interaction policy controls whether one specific layer is selectable, movable, or pixel editable. An operation proceeds only when its intrinsic source capability, layer policy, host policy, and current editor state all allow it. Clearing an existing selection remains available as a safe way to leave selection state.

When the mask feature is active, `ControlMode.DRAW_BRUSH` provides the raster mask brush. Applications using the SAM extra can also activate `ControlMode.SMART_SELECT` for box selection. These modes are unavailable when the catalog is empty. See [Masks and SAM](masks-and-sam.md) for details.

Touch and active-pen input are enabled automatically. Brush mode supports fixed-size finger painting, contact-visible touch feedback, pressure-sensitive active pens, floating pen-hover previews, eraser tips, palm rejection, and two-finger navigation. Releasing the final touch contact restores the platform brush cursor immediately; a mouse does not need to click or leave the canvas first. Moving a real mouse after pen input transfers ownership from the floating pen preview. Smart Select supports one-finger box selection and two-finger navigation. See [Touch and Pen Input](touch-and-pen.md) for the complete gesture contract, hardware limits, and simulator.

## View State
You can control how placeholder and startup image fitting works using `ZoomMode`. `ZoomMode.FIT` keeps the whole image visible, `ZoomMode.LOCKED_ZOOM` keeps the configured zoom value stable for inspection workflows, and `ZoomMode.LOCKED_SIZE` keeps the rendered placeholder size stable when the viewport changes.

Choose `PlaceholderScaleMode` based on what the empty viewer should measure against:

* `PlaceholderScaleMode.AUTO` uses QPane's default placeholder rule for normal host applications.
* `PlaceholderScaleMode.LOGICAL_FIT` fits the logical widget viewport when host chrome is measured in widget coordinates.
* `PlaceholderScaleMode.PHYSICAL_FIT` fits the device-pixel viewport when high-DPI pixel alignment matters.
* `PlaceholderScaleMode.RELATIVE_FIT` scales the placeholder relative to the configured viewport policy for specialized placeholder layouts.

Want to know how deep you are? `QPane.currentZoom` tells you the current multiplier.

## Interaction Rules
* **Persistence:** Modes stick around. If you switch to "Brush" mode and navigate to the next image, you remain in "Brush" mode.
* **Overlays:** Switching modes often changes the cursor and may show or hide overlays (like the brush circle).
* **Validation:** `setControlMode` safely handles missing features (like trying to use Smart Select without SAM installed) by logging a warning and ignoring the request. However, it raises a `ValueError` if passed an unknown mode ID.
* **Event Delivery:** Tools always expose the full Qt event surface via concrete no-op handlers, so dispatch is direct and predictable—override only what you need.
* **Layer Policy:** Scene layers are locked by default. Hosts opt a layer into movement with `QPane.setLayerInteractionPolicy`; switching to Move mode never changes policy implicitly.
* **Host Policy:** `QPane.setEditorPolicy` composes application-wide selection, pixel-edit, painting, move, and transform capabilities without changing any layer or source.
* **Pixel-Move Policy:** Selected pixels require a selected layer with `pixel_editable=True` and an intrinsically editable raster source. Layer-level `movable` policy is used only by the no-selection branch.
### Comparison Divider Interaction
Split comparison uses the normal viewer modes and belongs to the active composition. QPane owns built-in split-boundary dragging as interaction chrome, not image content. QPane does not paint a divider line or handle; the visible boundary between the base and comparison images is the drag target.

Host controls can call `QPane.setComparisonSplit` directly to move the boundary. Use `QPane.comparisonDividerState` when the host wants to draw its own divider overlay from authoritative geometry. `QPane.setComparisonDividerInteractive` disables or restores built-in dragging, and `QPane.comparisonDividerInteractive` reports the current interaction setting for checkboxes or toolbar state.

> **Pro Tip:** Want the best of both worlds? QPane includes a built-in "hold Space to pan" feature that temporarily switches to `CONTROL_MODE_PANZOOM` while the widget has focus. For a global implementation that works even when focus is elsewhere (like in the demo), see `examples/demonstration/demo_window.py`.

## Related Docs
* [Touch and Pen Input](touch-and-pen.md): Direct manipulation, pen pressure, palm rejection, and synthetic tests.
* [Masks and SAM](masks-and-sam.md): Details on the brush and smart selection tools.
* [Extensibility](extensibility.md): How to register your own custom tools and cursors.
* [Catalog and Navigation](catalog-and-navigation.md): Managing the images you are interacting with.

**Continue →** [Masks and SAM](masks-and-sam.md)
