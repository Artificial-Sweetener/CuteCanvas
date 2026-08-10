# Host Cookbook

CuteCanvas supplies the editor; the host supplies the application around it.
That means your project owns the document lifetime, your actions choose which
tools and commands are visible, and your panels observe public snapshots rather
than reaching into the widget.

This guide assembles those pieces into a practical host. Use the
[API Reference](api-reference.md) for exhaustive member details.

## Let the Project Own the Document

Create the document beside the host's project or tab state, then mount it in a
canvas:

```python
import sys

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QMainWindow
from cutecanvas import CanvasDocument, CuteCanvas

app = QApplication(sys.argv)

document = CanvasDocument()
composition_id = document.create_composition(
    QRectF(0.0, 0.0, 1920.0, 1080.0),
    title="Untitled",
)

canvas = CuteCanvas(document=document, features=("mask",))
canvas.openComposition(composition_id)

window = QMainWindow()
window.setCentralWidget(canvas)
window.resize(1200, 800)
window.show()
app.exec()
```

The document can outlive this widget and can be mounted by another view. It
owns resources, compositions, layer structure, selections, and chronological
history. The canvas owns the active tool and viewport for this particular view.

## Build Tool Actions Around Modes

Use the stable control-mode values rather than importing tool classes:

```python
brush_action.triggered.connect(
    lambda: canvas.setControlMode(canvas.CONTROL_MODE_DRAW_BRUSH)
)
move_action.triggered.connect(
    lambda: canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
)
transform_action.triggered.connect(
    lambda: canvas.setControlMode(canvas.CONTROL_MODE_TRANSFORM)
)

canvas.controlModeChanged.connect(tool_strip.set_active_mode)
```

`controlModeChanged` is authoritative even when the editor falls back from a
tool that is no longer valid for the selected layer. Do not leave checked-state
ownership in each `QAction`.

Before enabling a command, ask the editor about the actual intent. The answer
accounts for host policy, the selected layer, source capabilities, locks, and
the current pointer target:

```python
from cutecanvas import EditorIntent

state = canvas.editorOperationState(EditorIntent.DELETE_PIXELS)
delete_action.setEnabled(state.allowed)
delete_action.setToolTip(state.denial or "Delete selected pixels")
```

## Populate a Layer Panel from Snapshots

`getCompositionSnapshot()` returns detached rows for the current document. Use
it to rebuild a tree after structural changes:

```python
def refresh_layer_tree() -> None:
    snapshot = canvas.getCompositionSnapshot()
    rows = []
    for current_id in snapshot.order:
        composition = snapshot.compositions[current_id]
        rows.append((composition.composition_id, composition.title, None))
        rows.extend(
            (composition.composition_id, layer.label, layer.layer_id)
            for layer in composition.layers
        )
    layer_tree.replace_rows(rows)


canvas.compositionChanged.connect(refresh_layer_tree)
canvas.compositionSelectionChanged.connect(refresh_layer_tree)
canvas.selectedLayersChanged.connect(refresh_layer_tree)
```

Snapshots are observations, not a second document model. Keep stable UUIDs in
tree items and ask CuteCanvas for fresh state after a signal; do not mutate or
cache an old snapshot as authority.

Select through the public facade when the user clicks a layer row:

```python
canvas.setSelectedLayer(composition_id, layer_id)
```

Use `setSelectedLayers()` when the host supports multi-layer movement. The
ordered selection has one active member, which is the target for commands that
operate on a single layer.

## Keep Brush Controls Honest

Brush controls should follow the active preset and target:

```python
canvas.brushPresetChanged.connect(brush_panel.set_preset)
canvas.paintColorChanged.connect(brush_panel.set_color)
canvas.paintTargetChanged.connect(brush_panel.set_target)

size_slider.valueChanged.connect(canvas.setBrushSize)
color_button.colorChanged.connect(canvas.setPaintColor)
```

The same preset drives color painting, mask painting, and painted pixel
selection. The target decides what the stroke edits. The explicit Eraser mode
always removes alpha or coverage without asking the host to rewrite the preset.

## Keep Contextual Commands with Their State

Floating pixels are intentionally unresolved after a selected region moves.
Show contextual actions while `floatingPixelEditState()` reports a fragment:

```python
def refresh_floating_actions() -> None:
    state = canvas.floatingPixelEditState()
    floating_bar.setVisible(state is not None)


canvas.floatingPixelEditChanged.connect(refresh_floating_actions)
anchor_action.triggered.connect(canvas.anchorFloatingPixels)
new_layer_action.triggered.connect(canvas.promoteFloatingPixels)
cancel_action.triggered.connect(canvas.cancelFloatingPixels)
```

Apply the same pattern to transform state, Clone Stamp source state, vector
selection, and placed-asset requests: observe the owner, expose the actions that
make sense now, and send commands back through the facade.

## Save Editable Work Without Freezing the Window

For a normal Save action, use the composition persistence helper:

```python
composition = canvas.editor.compositions.current
if composition is not None:
    canvas.editor.persistence.save(composition, "project.cutecanvas")
```

An autosave or large project should separate owner-thread capture from file
I/O. Capture one immutable document snapshot while the document is authoritative,
then write that detached value on a host worker:

```python
snapshot = canvas.editor.persistence.capture_document()
disk_executor.submit(
    canvas.editor.persistence.write_document,
    snapshot,
    session_archive_path,
)
```

The user may continue editing while the snapshot is written. A later edit does
not silently change the archive already in flight.

## Show the Same Document in Several Views

Use one `CanvasDocumentRuntime` when an editor and inspection workspace share a
document. That gives them one mutation-freshness and execution owner while each
view keeps its own active composition, presentation, viewport, and tools:

```python
from cutecanvas import CanvasDocumentRuntime, CanvasWorkspace
from qpane.sdk.execution import create_default_execution_runtime

execution_runtime = create_default_execution_runtime()
document_runtime = CanvasDocumentRuntime(
    document,
    execution_runtime=execution_runtime,
)

editor = CuteCanvas(document_runtime=document_runtime, features=("mask",))
workspace = CanvasWorkspace(document_runtime=document_runtime)
workspace.setGridPresentation(document.composition_ids())
```

Use tabs for linked native-size inspection, a responsive grid for overview, or
comparison for an independent two-target reveal. These presentations change
view-session state; they do not create document history entries.

## Give the Host Final Policy

An `EditorPolicy` removes complete capabilities from a widget. Layer and
composition policies then narrow what may happen to particular content. This
lets one application mount the same document as a full editor, a mask-only
workspace, or a read-only inspector without forking the data model.

Resolve `editorOperationState()` when an action needs an explanation. A denied
operation can supply host-facing context and valid alternatives instead of
failing silently after the user clicks it.

## Export and Drag Without Giving Up Storage Ownership

Image export and editable persistence are different operations. Use a
cancellable projection when the host needs freshly rendered pixels at a chosen
size. Use `captureMaskExport()` or `captureEmbeddedImageExport()` when external
work needs detached pixels tied to an exact captured revision.

For drag-out, install an `OutboundMimeProvider`. CuteCanvas identifies the
composition or layer being dragged; the provider decides whether that identity
becomes a file URL, a companion document, text, or application-specific MIME
data. Storage paths and temporary-file policy remain in the host.

## Shut Down in Ownership Order

Close child canvases and workspaces first, then a shared
`CanvasDocumentRuntime`, then its execution runtime, and finally the document.
A standalone `CuteCanvas` owns and closes its default bindings itself. The
explicit order matters only when the host supplied those owners.

## Related Docs

* [Getting Started](getting-started.md): Build the first editable document.
* [Documents and Presentations](documents-and-presentations.md): Share document
  state across editing and inspection views.
* [Building Host UI](host-ui.md): Drive toolbars, trees, and inspectors from
  snapshots and signals.
* [Interaction and Tools](interaction-modes.md): Connect every built-in tool and
  its policy.
* [Extensibility](extensibility.md): Add host chrome, tools, effects, and policy.

**Continue →** [Building Host UI](host-ui.md)
