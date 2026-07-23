# Getting Started

## Welcome to QPane

QPane is a PySide6 widget for fast, CPU-first tiled image viewing. It slots
into your Qt app without leaning on the GPU, handling large images and smooth
zooming right out of the box. The same widget also accepts immutable raster and
vector scenes when your application needs a custom presentation.

## Install and Import

Install QPane from PyPI. The normal package includes the viewer, rendering SDK,
diagnostics, comparison workflow, and extension primitives.

```bash
pip install qpane
```

```python
from qpane import QPane
```

## Spin Up the Widget

Create `QPane` after your `QApplication` is ready, then add it to a layout like
any other `QWidget`.

```python
import sys

from PySide6.QtWidgets import QApplication, QMainWindow
from qpane import QPane

app = QApplication(sys.argv)
window = QMainWindow()
viewer = QPane()
window.setCentralWidget(viewer)
window.resize(1100, 720)
window.show()
app.exec()
```

That small program already has cursor-anchored wheel zoom, drag panning,
double-click Fit/1:1 switching, high-DPI rendering, and the tiled large-image
pipeline. QPane's defaults are opinions rather than requirements; pass a
`Config` or call `applySettings()` when the host needs a different feel.

## Show One Image

Use `setImage()` when the host owns one transient image and does not need a
catalog. QPane retains the `QImage` through Qt's implicit sharing, creates a
reusable `RasterSource`, and fits it by default.

```python
from PySide6.QtGui import QImage

source = viewer.setImage(QImage("example.png"))
print(source.source_id, source.size)
```

Calling `setImage()` returns the public `RasterSource`. Keep it when the same
pixels will appear in another `RenderScene`; reusing the source preserves
identity and lets QPane reuse derived render products.

## Build a Catalog

For a gallery or review queue, add images to QPane's ordered `ViewerCatalog`.
Each returned `ViewerCatalogEntry` contains the stable resource identity,
label, optional path, dimensions, and reusable source.

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
)

viewer.selectCatalogImage(first.entry_id)
viewer.selectNextImage()
viewer.selectPreviousImage()
```

QPane remembers the viewport for each catalog image. Moving away and returning
restores that image's zoom and pan. Use `setAllImagesLinked(True)` when every
image should share one normalized review position instead.

> **Pro tip:** Supply your own `source_id` to `addImage()` when identity must
> survive catalog rebuilds or application restarts. Otherwise QPane creates a
> UUID for you.

## React to Navigation

Do not poll the widget to discover what changed. Connect to
`catalogSelectionChanged`; it emits the selected `ViewerCatalogEntry` or
`None`, whether the change came from user navigation or host code.

```python
def on_image_changed(entry):
    if entry is None:
        window.setWindowTitle("No image")
        return
    window.setWindowTitle(entry.label)

viewer.catalogSelectionChanged.connect(on_image_changed)
```

The catalog itself is available through `catalog()`. Its `entries` and
`current` properties are immutable snapshots suitable for host-owned list
widgets, while mutations continue to go through the supported catalog or
QPane facade.

## Inspect the Visible Content

The ordinary viewer conveniences follow the scene currently being presented:

* `currentImage` returns the base `QImage` when one is available.
* `currentImagePath` returns its source path or `None`.
* `copyCurrentImageToClipboard()` copies it and reports whether it succeeded.
* `scene()` returns the active immutable `RenderScene`.
* `currentZoom()` and `currentPan()` report the viewport transform.

Use `setZoomFit()`, `setZoom1To1()`, `applyZoom()`, and `setPan()` for explicit
host controls. `setPanZoomLocked()` disables every navigation path together,
including mouse, touch, and programmatic interaction through the built-in
tool.

## Present a Custom Scene

Catalog viewing is a convenience built on the public renderer. A host can use
the same path directly:

```python
from PySide6.QtCore import QSize
from qpane import LayerTransform, RenderLayer, RenderScene

scene = RenderScene.from_size(
    QSize(1600, 900),
    (
        RenderLayer(first.source),
        RenderLayer(
            second.source,
            transform=LayerTransform(dx=800.0, dy=0.0),
            opacity=0.75,
        ),
    ),
)
viewer.setScene(scene)
```

Scenes describe presentation; they do not own mutable editor state. Sources
can be shared by several layers or scenes without copying their pixels. QPane
handles visibility, clipping, tiling, vector sampling, damage, refinement, and
cache scheduling behind this boundary.

## Next Steps

You have a running viewer. Continue with the part that matches your host:

* **Refine the feel:** [Configuration](configuration.md) covers zoom, cache,
  placeholders, touch navigation, and concurrency.
* **Manage a review queue:** [Catalog and Navigation](catalog-and-navigation.md)
  explains selection, linking, comparison, and prefetch.
* **Build layered presentations:** [Rendering SDK](rendering-sdk.md) teaches
  raster, vector, hybrid, clipping, transforms, effects, and hit testing.
* **Observe real workloads:** [Diagnostics](diagnostics.md) shows memory,
  render timing, tile work, and custom diagnostic providers.

**Continue →** [Configuration](configuration.md)
