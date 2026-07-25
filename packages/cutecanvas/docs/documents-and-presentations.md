# Documents and Presentations

## Own the Work Outside the Widget

`CanvasDocument` is the durable owner of editable work. Create it where your
application owns a project, workflow, or tab, then mount it wherever the user
needs to see or edit that work.

```python
from PySide6.QtGui import QImage
from cutecanvas import CanvasDocument

document = CanvasDocument()
first_id = document.create_composition_from_image(
    QImage("first.png"),
    title="First pass",
)
second_id = document.create_composition_from_image(
    QImage("second.png"),
    title="Second pass",
)
```

Each composition keeps its own coordinate space and native dimensions. A
smaller first pass is not enlarged merely because a later pass has more
pixels.

Close a host-owned document when its project closes:

```python
document.close()
```

Widgets created with `document=document` do not close it for you.

## Mount an Editing View

`CuteCanvas` is one focused view session over a document:

```python
from cutecanvas import CuteCanvas

canvas = CuteCanvas(document=document, features=("mask",))
canvas.openComposition(first_id)
```

Activation, viewport state, active tools, and transient presentation belong to
the view session. Layer content and history belong to the document. Two
widgets can therefore edit or inspect the same content without sharing an
accidental active composition.

Pass the same `CanvasViewSession` when a view session should move between
widget shells. Pass separate sessions when the widgets need independent
activation.

`CuteCanvas.document` returns the mounted `CanvasDocument`, and
`CuteCanvas.viewSession` returns that widget's `CanvasViewSession`. The
session publishes a `CanvasSessionSnapshot` whenever activation or
presentation changes, so host chrome can observe view state without treating
it as editable document content.

## Link Inspection Deliberately

`CanvasWorkspace` supplies the common multi-view arrangements:

```python
from cutecanvas import CanvasWorkspace

workspace = CanvasWorkspace(document=document)
workspace.setTabbedPresentation((first_id, second_id), linked=True)
```

Every target in one workspace shares its `CanvasDocumentRuntime`. That binding
owns document-scoped work and one freshness decision for replaceable
operations, while each target keeps a receiver-safe view scope. Pass an
existing `document_runtime` when other editor views mount the same document.
Otherwise the workspace creates and closes the document binding and its
bounded standalone execution runtime.

`CuteCanvas.documentRuntime` returns the binding already used by an editor.
Pass it to another `CuteCanvas` or `CanvasWorkspace` when those views should
share document mutation freshness while retaining independent viewport and
tool state.

Linked inspection stores the visible region in normalized composition
coordinates. Switching from a 1,000-pixel composition at 200% to a
2,000-pixel composition shows the same detail at 100%. A target-local 100%
request remains local; it is not mislabeled as 100% on a different native
resolution.

Use an unlinked presentation when each view should remember its own region:

```python
workspace.setTabbedPresentation((first_id, second_id), linked=False)
```

## Responsive Grids

Grids arrange independent targets without synthesizing a larger document:

```python
workspace.setGridPresentation(document.composition_ids())
```

QPane calculates the frames in physical pixels, then converts them to Qt
logical coordinates. Fractional display scaling cannot accumulate gaps,
overlap, or a drifting final edge. Target identities remain stable across
resizes, so hit testing and future prefetch decisions address content rather
than cell numbers.

## Compare Independent Targets

Comparison keeps both compositions in their own render views:

```python
from cutecanvas import ComparisonOrientation

workspace.setComparisonPresentation(
    first_id,
    second_id,
    split_position=0.5,
    orientation=ComparisonOrientation.VERTICAL,
)
```

The divider snaps to one physical-pixel boundary. Both views remain linked by
normalized inspection by default, even when their native dimensions differ.
Dragging the divider changes presentation state, not document history.
`ComparisonOrientation.VERTICAL` creates a left-to-right reveal, while
`ComparisonOrientation.HORIZONTAL` creates a top-to-bottom reveal.

## Choose How Much Editing to Expose

The same document model serves inspection, mask-focused work, and full editing:

```python
from cutecanvas import CanvasInteractionMode

workspace.setInteractionMode(CanvasInteractionMode.READ_ONLY)
workspace.setInteractionMode(CanvasInteractionMode.MASK_AUTHORING)
workspace.setInteractionMode(CanvasInteractionMode.FULL_EDITOR)
```

These named modes apply the ordinary `EditorPolicy`. Applications with a more
specific capability mix can set an explicit policy on each canvas.
`CanvasInteractionMode` is only a convenient policy profile:
`CuteCanvas.setInteractionMode` applies it and `CuteCanvas.interactionMode`
reports the active profile. Fine-grained hosts can independently grant
`EditorCapability.MANAGE_LAYERS`, `EditorCapability.EDIT_RESOURCES`, and
`EditorCapability.EDIT_VECTORS` alongside selection, painting, movement, or
transform capabilities.

## Provide Drag-out Data

QPane owns the native drag lifecycle. CuteCanvas resolves the subject to a
stable `CanvasContentReference`, and your provider decides what leaves the
application.

```python
from pathlib import Path

from PySide6.QtCore import QUrl
from qpane.sdk.ui import OutboundDragPayload


class CompanionFileProvider:
    def __init__(self, path_for_reference):
        self._path_for_reference = path_for_reference

    def materialize(self, subject, complete):
        path = Path(self._path_for_reference(subject.subject_id))
        complete(
            OutboundDragPayload(
                urls=(QUrl.fromLocalFile(str(path)),),
                text=subject.label,
            ),
            None,
        )
        return None


workspace.setOutboundMimeProvider(CompanionFileProvider(companion_path))
```

`OutboundDragPayload` also accepts arbitrary `OutboundMimeItem` values and a
preview image. A provider may finish later and return a cancellation object.
Starting another drag or closing the view cancels stale work; a late completion
cannot start a drag on the wrong target.
For one view, `CuteCanvas.setOutboundMimeProvider` installs the same policy and
`CuteCanvas.clearOutboundMimeProvider` cancels pending work before removing it.

Install a `subject_resolver` when a gesture should address a layer or another
host-defined subject instead of the active composition.

## Render Current Pixels for Export

`CanvasContentReference` records the content revision observed by the host.
Use it to request an image without flattening the editable document or
blocking the GUI thread:

```python
from PySide6.QtCore import QRectF, QSize

reference = document.content_reference(first_id)


def projection_finished(result):
    if result.succeeded and result.image is not None:
        result.image.save("first-pass.png")


canvas.projectionCompleted.connect(projection_finished)
handle = canvas.requestProjection(
    reference,
    source_bounds=QRectF(0.0, 0.0, 1024.0, 1024.0),
    pixel_size=QSize(2048, 2048),
)
```

`CuteCanvas.requestProjection` creates a `CanvasProjectionRequest` and returns
a `CanvasProjectionHandle`; `CuteCanvas.projectionCompleted` publishes its
one terminal `CanvasProjectionResult`. Each result has a
`CanvasProjectionStatus` of completed, cancelled, rejected, stale, or failed.
The request samples the mounted QPane scene renderer. It supports composition
and layer references, explicit source-space bounds, and an independent output
resolution. `handle.cancel()` stops work that is no longer useful. A result is
reported as stale instead of publishing pixels when the referenced layer or
composition changes before completion.

This is a useful building block for a deferred `OutboundMimeProvider`: project
the requested reference, encode the host's preferred file variant, then
complete the drag payload. The host still owns filenames, companion formats,
temporary-file lifetime, and every custom MIME value.

## Add a Host Presentation

Register a `CanvasPresentationProvider` when tabs, grid, and comparison do not
cover an application layout. The provider receives a
`CanvasPresentationContext` with validated target IDs and a supported
`create_view` function. It arranges views; it does not copy document state or
construct another renderer.

The `CanvasPresentationKind` value in each `CanvasPresentation` distinguishes
single, tabbed, grid, comparison, and custom arrangements. Comparison uses a
`CanvasComparison` value for the two targets and divider configuration.

Stable `CanvasContentKind` values identify whether a reference addresses a
composition, layer, or resource. `CanvasDocument.resolve_content()` returns
`ResolvedCanvasContent`, allowing a host to reject stale references before a
deferred export or drag completes.
