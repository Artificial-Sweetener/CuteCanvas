# Building Host UI

CuteCanvas deliberately does not impose one toolbar, layer panel, inspector, or
save workflow on every application. It exposes stable commands, immutable
snapshots, and Qt signals so the surrounding interface can look and behave like
the application it belongs to.

The central rule is simple: commands go into CuteCanvas; observations come back
out. A toolbar or tree may remember stable IDs, but it does not become another
owner of editor state.

## Treat Snapshots as Observations

Snapshots are detached values describing one revision. They are safe to read,
compare, hand to a Qt model, or include in diagnostics. They are not live
objects and changing them cannot edit the document.

When a signal announces a change, ask the relevant owner for a fresh snapshot:

```python
def refresh_document_tree() -> None:
    snapshot = canvas.getCompositionSnapshot()
    document_model.replace_snapshot(snapshot)


canvas.compositionChanged.connect(refresh_document_tree)
canvas.compositionSelectionChanged.connect(refresh_document_tree)
canvas.selectedLayersChanged.connect(refresh_document_tree)
```

Keep composition, layer, resource, mask, and vector-object UUIDs in model roles.
Use those IDs when sending a command back. Do not keep a snapshot and patch it
locally in the hope that it will remain synchronized after undo, removal,
resource sharing, or document restoration.

## Drive a Tool Strip from the Active Mode

Tool actions select modes through `setControlMode()`. The canvas may later
change modes because a tool becomes unavailable, a document closes, or host
policy changes, so pressed state follows `controlModeChanged`:

```python
mode_actions = {
    canvas.CONTROL_MODE_MOVE: move_action,
    canvas.CONTROL_MODE_TRANSFORM: transform_action,
    canvas.CONTROL_MODE_DRAW_BRUSH: brush_action,
    canvas.CONTROL_MODE_ERASER: eraser_action,
}

for mode, action in mode_actions.items():
    action.triggered.connect(
        lambda checked=False, selected_mode=mode: canvas.setControlMode(
            selected_mode
        )
    )


def show_active_mode(mode: str) -> None:
    for candidate, action in mode_actions.items():
        action.setChecked(candidate == mode)


canvas.controlModeChanged.connect(show_active_mode)
```

`availableControlModes()` tells a dynamic host which registered modes exist.
Feature availability and permission are separate questions: a mode can be
installed while the current layer or policy makes a particular operation
invalid.

## Explain Why an Action Is Disabled

Use `editorOperationState()` for actions whose validity depends on current
context:

```python
from cutecanvas import EditorIntent

def refresh_edit_actions() -> None:
    delete_state = canvas.editorOperationState(EditorIntent.DELETE_PIXELS)
    delete_action.setEnabled(delete_state.allowed)
    delete_action.setToolTip(
        delete_state.denial or "Delete pixels inside the current selection"
    )

    transform_state = canvas.editorOperationState(EditorIntent.TRANSFORM)
    transform_action.setEnabled(transform_state.allowed)
    transform_action.setToolTip(
        transform_state.denial or "Transform the selected pixels or layer"
    )
```

Refresh these decisions after document selection, layer selection, pixel
selection, floating-content, policy, and tool-target changes. The operation
state already combines those owners; the host should not reproduce their rules.

## Build a Composition and Layer Tree

`CompositionSnapshot` gives browser order and a row for each composition. Each
composition row contains its ordered layer rows with labels, visibility,
opacity, source kind, transform, and interaction policy.

Use facade commands for edits initiated by the tree:

```python
def select_layer(scene_id, layer_id) -> None:
    canvas.setSelectedLayer(scene_id, layer_id)


def set_layer_visible(scene_id, layer_id, visible: bool) -> None:
    canvas.setLayerVisible(scene_id, layer_id, visible)


def set_layer_opacity(scene_id, layer_id, opacity: float) -> None:
    canvas.setLayerOpacity(scene_id, layer_id, opacity)
```

Layer order in the snapshot is document order. Do not reverse it in the data
model and then compensate in every command; decide only how the view presents
bottom-to-top document order.

`selectedLayers()` reports the complete ordered layer selection, while
`selectedLayer()` reports the active member for single-target commands. Keeping
those ideas distinct lets a tree show multi-selection without guessing which
layer owns the current inspector.

## Build Brush and Paint Controls

A `BrushPreset` is the complete brush description. Read it after
`brushPresetChanged`, update the controls without re-emitting their editing
signals, and send a new preset or focused size change back through the facade.

```python
canvas.brushPresetChanged.connect(brush_panel.set_preset)
canvas.paintColorChanged.connect(color_button.setColor)
canvas.paintTargetChanged.connect(target_label.set_target)

size_slider.valueChanged.connect(canvas.setBrushSize)
color_button.colorChanged.connect(canvas.setPaintColor)
```

`paintTargetState()` distinguishes an editable raster or mask layer from pixel
selection coverage. It also gives the host enough information to label the
target without inspecting private storage.

Clone Stamp has its own detached `CloneStampState` because its source anchor,
alignment, sampling mode, and source transform are not ordinary brush preset
values. Follow `cloneStampChanged` when showing those controls.

## Show Context for Unfinished Work

Some edits deliberately remain unresolved while the user decides what to do.
Selected pixels can float after a move; a transform can wait for Apply or
Cancel; vector text can remain in an edit session.

Use the matching state and signal to show contextual controls. For floating
pixels:

```python
def refresh_floating_bar() -> None:
    state = canvas.floatingPixelEditState()
    floating_bar.setVisible(state is not None)
    if state is not None:
        floating_bar.set_offset(state.offset)


canvas.floatingPixelEditChanged.connect(refresh_floating_bar)
```

The contextual buttons call `anchorFloatingPixels()`,
`promoteFloatingPixels()`, or `cancelFloatingPixels()`. They do not directly
edit the fragment represented by the snapshot.

## Keep Undo, Save, and Dirty State Separate

`sceneEditHistoryChanged` tells Undo and Redo actions whether the chronological
document history can move in either direction:

```python
canvas.sceneEditHistoryChanged.connect(
    lambda can_undo, can_redo: (
        undo_action.setEnabled(can_undo),
        redo_action.setEnabled(can_redo),
    )
)
undo_action.triggered.connect(canvas.undoSceneEdit)
redo_action.triggered.connect(canvas.redoSceneEdit)
```

Undo availability is not the same as a host project's saved/dirty state. Track
the document revision or successful persistence point according to the host's
project model. A document may have undo history and still match its most recent
save.

## Inspect Specialized Layers Only When Needed

Open a specialized inspector from the selected layer's source kind:

* Raster state reports storage bounds, extent policy, and content or structure
  revisions useful for crop and storage controls.
* Placed-asset state reports embedded or linked provenance, loading status,
  fallback behavior, and terminal errors.
* Vector snapshots report retained objects and selection without asking the
  host to parse QPane's render scene.
* Mask state reports editable coverage identity and presentation properties.

The focused guides explain the commands for each kind. Keep the generic layer
tree generic; swapping a small inspector is cleaner than teaching the tree the
editing rules of every source.

## Related Docs

* [Host Cookbook](host-cookbook.md): Assemble a complete editor host.
* [Documents and Layers](scenes.md): Understand document structure and layer
  policy.
* [Interaction and Tools](interaction-modes.md): Activate tools and resolve
  capability policy.
* [Painting](painting.md): Configure brushes and raster targets.
* [Placed Images](placed-images.md): Present linked-asset status and actions.
* [Vector Layers](vector-layers.md): Build retained-object controls.

**Continue →** [API Reference](api-reference.md)
