# Host Cookbook

QPane is ready to use as soon as it has an image. A real host usually adds a
catalog, a few viewport actions, comparison controls, diagnostics, and its own
application chrome around that viewer. This guide shows how those pieces fit
together without turning the host into a second rendering engine.

Use the [API Reference](api-reference.md) when you need an exhaustive list of
members. The recipes here stay focused on complete application tasks.

## Build a Small Viewer Window

Create `QPane` after `QApplication` and treat it like any other `QWidget`:

```python
import sys

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMainWindow
from qpane import QPane

app = QApplication(sys.argv)

viewer = QPane()
viewer.setImage(QImage("example.png"))

window = QMainWindow()
window.setCentralWidget(viewer)
window.resize(1200, 800)
window.show()
app.exec()
```

`setImage()` is the shortest path for a preview or inspector whose host
replaces one image at a time. It returns a reusable `RasterSource`, so keep that
source when the same pixels will later appear in a custom scene.

## Let the Host Own Navigation

For a review queue, add images to QPane's catalog and keep the surrounding list
or thumbnail strip synchronized from catalog signals:

```python
from pathlib import Path

first = viewer.addImage(
    QImage("scan-001.tif"),
    label="Scan 001",
    path=Path("scan-001.tif"),
)
viewer.addImage(
    QImage("scan-002.tif"),
    label="Scan 002",
    path=Path("scan-002.tif"),
    select=False,
)

viewer.catalogSelectionChanged.connect(
    lambda entry: window.setWindowTitle(entry.label if entry else "No image")
)
viewer.selectCatalogImage(first.entry_id)
```

Use `catalog()` to rebuild a host model after `catalogChanged`. Use
`selectNextImage()` and `selectPreviousImage()` for actions or shortcuts rather
than duplicating wraparound and selection rules in the host.

QPane remembers inspection by catalog identity. If the host is about to unmount
the viewer while the catalog is active, capture the current catalog inspection.
After mounting that viewer again with its final geometry, restore the inspection
so the user returns to the same normalized region:

```python
viewer.captureCatalogInspection()
window.takeCentralWidget()

# Mount the same viewer elsewhere, then restore after layout has set its size.
other_window.setCentralWidget(viewer)
viewer.restoreCatalogInspection()
```

## Add Fit, 1:1, and Navigation Lock

Viewport actions should call the viewer instead of manipulating its transform:

```python
fit_action.triggered.connect(viewer.setZoomFit)
native_action.triggered.connect(viewer.setZoom1To1)

viewer.zoomChanged.connect(
    lambda zoom: zoom_label.setText(f"{zoom * 100:.0f}%")
)
```

`setZoom1To1()` maps one source pixel to one physical display pixel, including
on high-DPI screens. `applyZoom()` is the right choice for a slider or numeric
control because it uses the same clamping and anchor rules as pointer input.

Lock pan and zoom when another host interaction temporarily owns the viewport:

```python
viewer.setPanZoomLocked(True)
try:
    run_host_drag()
finally:
    viewer.setPanZoomLocked(False)
```

## Compare Two Catalog Images

Comparison is a presentation of two existing catalog sources, not a new merged
image. The selected image remains the primary side:

```python
viewer.setComparisonPair(first.entry_id, second.entry_id)
viewer.setComparisonDividerInteractive(True)

viewer.comparisonChanged.connect(update_comparison_controls)
```

The built-in divider owns pointer input only around its visible seam. The rest
of the viewport keeps normal pan and zoom behavior. Call `clearComparison()` to
return to the selected catalog image.

## Present a Custom Scene

Use a `RenderScene` when the host needs layers, transformed sources, vector
content, clipping, or presentation effects. QPane still owns culling, tiles,
damage, caching, and final presentation:

```python
from PySide6.QtCore import QSize
from qpane import LayerTransform, RasterSource, RenderLayer, RenderScene

source = RasterSource.from_image(QImage("overlay.png"))
scene = RenderScene.from_size(
    QSize(1200, 800),
    (
        RenderLayer(
            source,
            transform=LayerTransform(dx=100.0, dy=80.0),
            label="Overlay",
        ),
    ),
)
viewer.setScene(scene)
```

The [Rendering SDK](rendering-sdk.md) covers raster, vector, hybrid,
projective, piecewise, and bilinear sources without asking the host to flatten
them first.

## Share One Runtime Across Viewers

A standalone viewer creates and owns a bounded default runtime. Applications
with several viewers should share one runtime so all of them participate in the
same execution and memory policy:

```python
from qpane import QPane
from qpane.sdk.execution import create_default_execution_runtime

runtime = create_default_execution_runtime()
left_viewer = QPane(execution_runtime=runtime)
right_viewer = QPane(execution_runtime=runtime)
```

Close the widgets before closing the host-owned runtime. A custom execution
backend is an advanced integration; use it only when the application already
owns scheduling and admission policy. The lifecycle contract is documented in
[Advanced Renderer Integration](integration-sdk.md).

## Make Rendering Observable

The built-in HUD is the quickest way to investigate cache pressure, refinement,
or slow source work:

```python
viewer.setDiagnosticsOverlayEnabled(True)
viewer.diagnosticsOverlayToggled.connect(diagnostics_action.setChecked)
```

Use `gatherDiagnostics()` for a detached snapshot in a host support panel.
Register a diagnostics provider only for fast host-owned records; diagnostics
collection runs in the same interaction-sensitive process as the viewer.

## Clean Up Host-Owned Extensions

Registrations have explicit owners. Unregister tools, overlays, scene overlays,
effects, and diagnostics providers when the corresponding host object closes.
Then close the viewers and finally any shared runtime. That order prevents a
late callback from targeting deleted Qt state.

## Related Docs

* [Getting Started](getting-started.md): Mount the widget and show the first
  image or scene.
* [Viewer Workflows](viewer-workflows.md): Catalog, comparison, placeholders,
  clipboard operations, and diagnostics.
* [Rendering SDK](rendering-sdk.md): Build raster, vector, and hybrid scenes.
* [Extensibility](extensibility.md): Add viewer tools, overlays, sources, and
  diagnostics providers.

**Continue →** [API Reference](api-reference.md)
