**← Previous:** [Configuration Reference](configuration-reference.md)

# Catalog and Navigation

QPane's catalog is an ordered inventory for applications that review more than
one image. It owns stable raster-source identity, labels, optional paths, one
selection, neighboring prefetch, and remembered viewport state. It does not
turn images into editor documents: each selection is presented through the
same immutable `RenderScene` pipeline available to SDK users.

## Build an Image Catalog

Add decoded `QImage` values through the viewer facade. QPane creates a
`RasterSource`, appends a `ViewerCatalogEntry`, and selects it unless
`select=False` is requested.

```python
from pathlib import Path

from PySide6.QtGui import QImage
from qpane import QPane

viewer = QPane()
first = viewer.addImage(
    QImage("one.png"),
    label="One",
    path=Path("one.png"),
)
second = viewer.addImage(
    QImage("two.png"),
    label="Two",
    path=Path("two.png"),
    select=False,
)
```

Always reject a null `QImage` at your loading boundary. QPane also validates
the input, but the host can give users a better message while it still knows
which file or decoder failed.

### Understanding Entries

`ViewerCatalogEntry` is an immutable row model:

* `entry_id` is the stable source UUID used by selection and linking.
* `label` is the human-readable host label.
* `path` is optional provenance for clipboard, drag-out, and display.
* `size` is a detached intrinsic `QSize`.
* `source` is the reusable `RasterSource` used by render scenes.

Pass `source_id=` to `addImage()` when identity must survive application
restarts. Otherwise QPane creates one. Reusing `entry.source` in a custom scene
does not duplicate pixels, pyramids, or settled tile products.

### Drive a Host List

`QPane.catalog` returns the public `ViewerCatalog` owned by a mounted viewer.
Its tuple snapshots are safe to read while building a sidebar:

```python
for entry in viewer.catalog().entries:
    add_row(
        row_id=entry.entry_id,
        label=entry.label,
        selected=entry is viewer.catalog().current,
    )
```

Use the facade for ordinary mutations:

* `selectCatalogImage(entry_id)` selects an explicit row.
* `selectNextImage()` and `selectPreviousImage()` wrap through the order.
* `removeCatalogImage(entry_id)` returns the removed entry.
* `clearCatalog()` releases the inventory and reveals the placeholder.

The catalog also exposes focused source operations for advanced hosts, such as
replacing a source in place. Its signals carry immutable entries rather than
requiring a second host-maintained identity map.

## React to Navigation

Connect to `catalogSelectionChanged` instead of polling:

```python
def refresh_active_row(entry):
    if entry is None:
        clear_active_row()
        return
    select_row(entry.entry_id)

viewer.catalogSelectionChanged.connect(refresh_active_row)
viewer.catalogChanged.connect(rebuild_rows)
```

`catalogChanged` reports structural or metadata changes. Selection changes are
separate so a large host model does not rebuild merely because the user pressed
Next.

The familiar image conveniences follow the presented base raster:
`currentImage`, `currentImagePath`, and `copyCurrentImageToClipboard()`. They
return no flattened scene or effect output. Use the rendering SDK when an
application needs explicit composition or export semantics.

## Programmatic View Control

The built-in pan/zoom tool handles drag panning, wheel zoom, and double-click
Fit/1:1. Host controls use the same viewport owner:

* `setZoomFit()` frames the complete scene.
* `setZoom1To1(anchor=None)` selects native logical-pixel scale.
* `applyZoom(zoom, anchor=None)` clamps and applies an explicit scale.
* `currentZoom()` returns the settled zoom.
* `setPan()` and `currentPan()` write and read the pan offset.
* `setPanZoomLocked()` changes every navigation route together.

The optional `QPointF` anchor keeps a panel point stationary during a zoom.
This is useful for a status-bar percentage field whose action should feel like
wheel zoom around the last inspected position.

`physicalViewportRect()` reports the device-pixel viewport used by rendering.
`panelHitTest()` converts a widget point into raw and clamped scene/image
coordinates without duplicating QPane's DPI and viewport math.

## Remembered and Linked Views

Each catalog entry normally has independent normalized pan and zoom. Moving
away and returning restores where the user was inspecting.

Call `setAllImagesLinked(True)` for synchronized review. To link only selected
sets, supply stable `LinkedGroup` values:

```python
import uuid

from qpane import LinkedGroup

viewer.setLinkedImageGroups(
    (
        LinkedGroup(
            group_id=uuid.uuid4(),
            members=(first.entry_id, second.entry_id),
        ),
    )
)
```

`linkedImageGroups()` returns the current detached tuple and
`linkGroupsChanged` tells host chrome when to refresh. Groups require at least
two unique catalog identities and may not overlap. Removing an image repairs
membership deterministically.

Link state is normalized across image dimensions. Two same-sized registrations
therefore remain pixel-for-pixel aligned, while differently sized images keep
the equivalent proportional region in view.

## Neighbor Prefetch

After a catalog selection settles, QPane can warm nearby pyramid and tile
products. Visible rendering always has higher priority, rapid navigation
cancels stale work, and configured counts bound the queue.

```python
state = viewer.catalogPrefetchState()
print(state.pending, state.scheduled, state.completed)
```

`ViewerPrefetchSnapshot` is useful in diagnostics and performance tests; it is
not a progress contract for user-facing loading UI. Tune the behavior through
`Config.cache.prefetch` and inspect the `swap` diagnostic domain before raising
the defaults.

## Compare Images in One View

Comparison reveals a second catalog image through the active base image. The
catalog selection does not change.

```python
from qpane import ComparisonOrientation

viewer.selectCatalogImage(first.entry_id)
viewer.setComparisonImage(second.entry_id)
viewer.setComparisonSplit(0.5, ComparisonOrientation.VERTICAL)
```

For the common adjacent-image workflow, `compareWithNextImage()` selects the
next catalog resource automatically. `clearComparison()` returns to normal
single-image presentation.

`comparisonState()` returns an immutable `ComparisonState` containing enabled
state, source identity and path, split position, and orientation. Connect
`comparisonChanged` when a toolbar should mirror both host calls and built-in
divider dragging.

```python
def refresh_compare_controls(state):
    compare_button.setChecked(state.enabled)
    split_slider.setValue(round(state.split_position * 100))

viewer.comparisonChanged.connect(refresh_compare_controls)
```

Comparison works best for aligned or similarly shaped images. When dimensions
differ, QPane uses the combined presentation to establish safe Fit, 1:1, and
pan limits.

### Host-Owned Divider Chrome

The image boundary is draggable by default, but QPane does not impose a visual
divider. A host that wants one can draw it with a normal overlay using
`comparisonDividerState()`:

```python
def draw_compare_divider(painter, _overlay_state):
    divider = viewer.comparisonDividerState()
    if divider.visible_segment is not None:
        painter.drawLine(divider.visible_segment)

viewer.registerOverlay("compare-divider", draw_compare_divider)
```

The snapshot includes visible and full projected segments, orientation, hit
width, hover, drag, and interaction state. That keeps artwork host-owned while
QPane remains the authority for geometry and input.

`setComparisonDividerInteractive(False)` disables built-in dragging without
changing comparison itself. This is useful when a host provides a different
input surface or presents a read-only comparison.

## Empty Catalogs and Placeholders

Clearing the catalog presents the configured placeholder. `placeholderState()`
reports whether it is loading, active, or failed; `placeholderChanged` lets a
host update drop instructions or error UI. `setPlaceholderImage()` accepts an
already decoded host image.

Placeholder navigation and drag-out permissions are independent from ordinary
content. Selecting an image or calling `setScene()` suspends placeholder policy
automatically, and returning to an empty state restores it.

## Direct Scenes and Catalog State

`setScene()` may temporarily present an SDK scene unrelated to the catalog.
The catalog remains intact. Selecting even the already-current catalog entry
explicitly restores its normal one-image presentation. This makes a preview or
analysis view easy to enter and leave without copying the review queue.

Use `clear()` when the host wants no explicit presentation. Use
`clearCatalog()` only when it intends to remove the catalog resources as well.

## Event Summary

The navigation-related signals have deliberately narrow meanings:

* `catalogChanged` — entry order or metadata changed.
* `catalogSelectionChanged` — selected entry changed.
* `linkGroupsChanged` — synchronized-view definitions changed.
* `comparisonChanged` — reveal source, orientation, or split changed.
* `placeholderChanged` — asynchronous or active placeholder state changed.
* `sceneChanged` — the immutable presentation submitted to the renderer
  changed.
* `zoomChanged` — the settled viewport scale changed.

Keeping these separate prevents a host from rebuilding unrelated UI and makes
high-frequency navigation cheap.

**Continue →** [Interaction Modes](interaction-modes.md)
