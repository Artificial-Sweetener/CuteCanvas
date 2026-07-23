# Viewer Workflows

QPane is ready to use as an image viewer before you configure anything. Drag to
pan, use the wheel to zoom around the pointer, and double-click to switch
between Fit and 1:1.

This guide shows how to connect those built-in viewer behaviors to the rest of
your application.

## Show One Image

Use `setImage()` for a preview, inspector, or any view where the host replaces
one image at a time:

```python
from PySide6.QtGui import QImage

image = QImage("example.png")
if image.isNull():
    raise RuntimeError("Could not open example.png")

source = viewer.setImage(image)
```

The returned `RasterSource` is reusable. If you later build a layered scene
from the same pixels, keep the source and place it in that scene instead of
creating another one.

`currentImage` returns the base `QImage` currently associated with the viewer.
`currentImagePath` returns its optional path. Neither property creates a
flattened copy of a layered scene.

## Build a Review Queue

Use the catalog when users browse several images. Each call to `addImage()`
returns a stable entry that contains its label, path, dimensions, ID, and
reusable raster source:

```python
from pathlib import Path

first = viewer.addImage(
    QImage("scan_001.tif"),
    label="Scan 001",
    path=Path("scan_001.tif"),
)
second = viewer.addImage(
    QImage("scan_002.tif"),
    label="Scan 002",
    path=Path("scan_002.tif"),
    select=False,
)

viewer.selectCatalogImage(first.entry_id)
viewer.selectNextImage()
viewer.selectPreviousImage()
```

Selection wraps through the catalog order. QPane remembers the normalized pan
and zoom for each image, so returning to an image restores the area the user
was inspecting.

Connect `catalogSelectionChanged` to keep the window title or a host-owned list
in sync:

```python
def show_selected_entry(entry):
    window.setWindowTitle(entry.label if entry is not None else "No image")


viewer.catalogSelectionChanged.connect(show_selected_entry)
```

Use `viewer.catalog().entries` to rebuild a list and
`viewer.catalog().current` to mark its selected row. The catalog exposes
immutable entries, so your UI can read them without taking ownership of QPane's
navigation state.

## Add Fit and 1:1 Actions

The built-in navigation tool already handles double-click Fit/1:1. Toolbar and
menu actions call the same viewport owner:

```python
fit_action.triggered.connect(viewer.setZoomFit)
native_action.triggered.connect(viewer.setZoom1To1)

viewer.zoomChanged.connect(
    lambda zoom: zoom_label.setText(f"{zoom * 100:.0f}%")
)
```

Use `applyZoom()` for an editable percentage control. It clamps unsafe values
and accepts an optional `QPointF` anchor. `currentPan()`, `setPan()`, and
`currentZoom()` support explicit host controls without bypassing the built-in
tool.

Call `setPanZoomLocked(True)` when an application state must hold the view
still. The lock covers mouse, touch, and programmatic navigation through the
built-in tool as one policy.

## Link Several Images

Linked images share one normalized view. This is useful for inspecting the
same region across frames or processing results:

```python
viewer.setAllImagesLinked(True)
```

For several independent groups, pass `LinkedGroup` values to
`setLinkedImageGroups()`. QPane validates that groups contain at least two
unique entries and do not overlap. `linkGroupsChanged` tells host controls when
the definitions change.

## Compare Two Images

QPane can reveal one catalog image over another without changing the selected
entry:

```python
from qpane import ComparisonOrientation

viewer.selectCatalogImage(first.entry_id)
viewer.setComparisonImage(second.entry_id)
viewer.setComparisonSplit(0.5, ComparisonOrientation.VERTICAL)
```

The image boundary is draggable. QPane owns its hit area and cursor behavior,
while the host chooses whether to draw a visible divider. For a quick command
that compares the current image with its next catalog neighbor, call
`compareWithNextImage()`.

Use `comparisonState()` to update buttons and sliders:

```python
def update_compare_controls(state):
    compare_action.setChecked(state.enabled)
    split_slider.setValue(round(state.split_position * 100))


viewer.comparisonChanged.connect(update_compare_controls)
```

`clearComparison()` returns to the selected image. See
[Catalog and Navigation](catalog-and-navigation.md) for custom link groups,
divider overlays, and differently sized comparison images.

## Design the Empty Viewer

An empty QPane is blank by default. A placeholder can welcome users, explain a
drop target, or show application artwork:

```python
from qpane import Config, QPane

config = Config().configure(
    placeholder={
        "source": "assets/welcome.png",
        "panzoom_enabled": False,
        "drag_out_enabled": False,
        "zoom_mode": "fit",
    }
)
viewer = QPane(config=config)
```

File-backed placeholders decode in the background. Call `placeholderState()`
or connect `placeholderChanged` when host UI needs loading and error state.
`setPlaceholderImage()` accepts an image your application already decoded.

The placeholder's pan, zoom, and drag-out choices apply only while the viewer
is empty. Selecting catalog content or presenting a scene restores the normal
content policy.

## Copy or Drag the Current Image

`copyCurrentImageToClipboard()` performs the ordinary Copy action and returns
`False` when no base image is available:

```python
copy_action.triggered.connect(viewer.copyCurrentImageToClipboard)
```

Cursor mode can start an operating-system drag for a path-backed current image
when `Config.drag_out_enabled` is true. `dragOutRequested` reports that the
drag started; the host does not need to recreate the image payload.

## Present a Temporary Scene

The catalog remains intact when a host calls `setScene()`. This makes a contact
sheet, analysis overlay, or temporary presentation easy to enter and leave:

```python
viewer.setScene(contact_sheet)

# Selecting a catalog row restores its normal one-image view.
viewer.selectCatalogImage(first.entry_id)
```

Call `clear()` to remove the current presentation while keeping catalog
resources. Call `clearCatalog()` only when the application intends to release
the review queue too.

## Watch the Viewer Work

The built-in diagnostics HUD shows render timing, cache use, tile and pyramid
work, navigation swaps, and background queues:

```python
viewer.setDiagnosticsOverlayEnabled(True)
```

Use it while testing large images or tuning memory. The complete workflow is in
[Diagnostics and Debugging](diagnostics.md).

## Related Docs

* [Getting Started](getting-started.md): create the widget and load its first
  image.
* [Catalog and Navigation](catalog-and-navigation.md): catalog state, linking,
  comparison, prefetch, and events.
* [Configuration](configuration.md): memory, placeholders, navigation feel,
  touch, and concurrency.
* [Rendering SDK](rendering-sdk.md): build layered raster and vector scenes.
