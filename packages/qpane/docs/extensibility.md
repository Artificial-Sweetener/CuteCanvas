**← Previous:** [Diagnostics](diagnostics.md)

# Extensibility

QPane is an opinionated viewer with deliberate extension boundaries. A host can
draw chrome, inspect scene geometry, emphasize rendered content, contribute
diagnostics, add a viewer tool, or provide a new raster source without taking
ownership of the renderer itself.

Choose the narrowest hook that matches the job. That keeps custom code fast and
lets improvements to tiling, clipping, damage, refinement, and high-DPI
behavior benefit it automatically.

## 1. Content Overlays

Use `registerOverlay()` for a watermark, scale bar, reticle, status label, or
other chrome relative to the base raster presentation.

```python
from PySide6.QtCore import Qt


def draw_zoom(painter, state):
    rect = state.qpane_rect.adjusted(12, 12, -12, -12)
    painter.setPen(Qt.GlobalColor.yellow)
    painter.drawText(
        rect,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        f"Zoom: {state.zoom * 100:.1f}%",
    )


viewer.registerOverlay("zoom-label", draw_zoom)
```

The callback receives a `QPainter` and an overlay state. Useful fields include:

* `qpane_rect` — logical widget bounds for HUD placement;
* `physical_viewport_rect` — device-pixel-aware render bounds;
* `zoom` and `current_pan` — the authoritative viewport state;
* `transform` — source-image to panel mapping; and
* `source_image` — the resolved base catalog image, not a flattened scene.

Registration order is draw order. Names must be unique so independently owned
extensions can remove themselves with `unregisterOverlay()` without disturbing
others.

Overlay callbacks run on the GUI paint path. Keep them allocation-light and
never decode files, scan a full image, wait for a worker, or mutate the scene.

## 2. Scene Overlays

Use `registerSceneOverlay()` when chrome needs ordered layer geometry rather
than one base image:

```python
from PySide6.QtGui import QColor, QPen


def draw_layer_frames(painter, state):
    painter.setPen(QPen(QColor("deepskyblue"), 1.0))
    for layer in state.layers:
        if layer.visible:
            painter.drawRect(layer.panel_bounds)


viewer.registerSceneOverlay("layer-frames", draw_layer_frames)
```

`SceneSnapshotOverlayState` identifies the scene and exposes its scene bounds,
viewport, zoom, and ordered `SceneSnapshotOverlayLayer` tuple. Each layer
contains stable layer/source identity, label, role, metadata, scene placement,
source size, source-to-panel transform, panel bounds, and visibility.

This is a prepared observational view model. It does not expose mutable scene
internals, and it does not ask the host to reproduce clipping or viewport
projection. Remove the contribution with `unregisterSceneOverlay()`.

## 3. Content-Aware Layer Effects

An overlay is ideal when the host already knows what to paint. Use a layer
presentation effect when the renderer must derive a tint, outline, glow, or
bounds treatment from the pixels it actually presents.

```python
from PySide6.QtGui import QColor
from qpane import LayerPresentationStyle

scene = viewer.scene()
if scene is not None and scene.layers:
    target = scene.layers[-1]
    effect_id = viewer.addLayerPresentationEffect(
        scene.scene_id,
        target.layer_id,
        LayerPresentationStyle.outline(
            QColor("deepskyblue"),
            width=2.0,
        ),
    )
```

Content tint, outline, and glow use resolved visible coverage, so raster,
vector, hybrid, clipping, opacity, and transient sampled products agree.
`LayerPresentationStyle.bounds()` instead draws a cosmetic product-bounds
rectangle.

Update and inspect effects without editing a scene:

```python
viewer.updateLayerPresentationEffect(
    effect_id,
    LayerPresentationStyle.tint(QColor("deepskyblue"), opacity=0.2),
)
print(viewer.layerPresentationEffects())
viewer.removeLayerPresentationEffect(effect_id)
```

`clearLayerPresentationEffects()` can target a scene, a layer, or every active
registration. Effects are transient renderer presentation: they do not mutate
source pixels, scene values, persistence, or export output, and QPane retires
them when their target disappears.

## 4. Custom Viewer Tools

Subclass `ViewerTool` when pointer or keyboard input needs a new meaning. The
tool owns its transient interaction; QPane remains the owner of viewport
geometry, event capture, fault containment, and rendering.

```python
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QPainter, QPen
from qpane import QPane, ViewerTool


class InspectionTool(ViewerTool):
    """Show a small crosshair over valid scene content."""

    def __init__(self, pane: QPane) -> None:
        """Retain the supported facade used for hit testing."""
        super().__init__()
        self._pane = pane
        self._position: QPointF | None = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track pointer feedback without changing scene content."""
        self._position = QPointF(event.position())
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear transient feedback at the widget boundary."""
        del event
        self._position = None
        self.signals.repaint_overlay_requested.emit()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw only when the pointer projects into the active scene."""
        if self._position is None:
            return
        hit = self._pane.panelHitTest(self._position)
        if hit is None:
            return
        painter.setPen(QPen(Qt.GlobalColor.cyan, 1.0))
        painter.drawEllipse(self._position, 8.0, 8.0)
        painter.drawText(
            self._position + QPointF(12.0, -8.0),
            f"{hit.raw_point.x():.0f}, {hit.raw_point.y():.0f}",
        )

    def getCursor(self) -> QCursor:
        """Return a familiar precision cursor."""
        return QCursor(Qt.CursorShape.CrossCursor)


viewer.registerTool("inspect", lambda: InspectionTool(viewer))
viewer.setControlMode("inspect")
```

The optional `dependencies=` callback supplies a focused activation port when
a reusable tool needs host services. It is evaluated at activation rather than
becoming a global service locator.

Use `ViewerToolSignals` for repaint, cursor, pan, or zoom requests instead of
reaching into private viewport state. `unregisterTool()` removes an inactive
extension. See [Interaction Modes](interaction-modes.md) for normalized pointer
and touch primitives.

## 5. Diagnostics Providers

`registerDiagnosticsProvider()` adds cheap host records to the live broker:

```python
from qpane import DiagnosticRecord


def queue_diagnostics(_pane):
    return (
        DiagnosticRecord("Host queue", "3 pending"),
        DiagnosticRecord("Workspace", "Review"),
    )


viewer.registerDiagnosticsProvider(
    queue_diagnostics,
    domain="host",
    detail=True,
)
```

Providers receive the public viewer facade and yield `DiagnosticRecord`
instances. QPane contains provider failures so one optional row cannot crash a
paint. The callback still must be fast and side-effect free.

## 6. Custom Raster Sources

`RasterSource.from_image()` covers immutable in-memory images. Implement
`RasterSourceProvider` when content is file-backed, generated, sparse, or live.
The source binds that provider to stable identity, local `RasterBounds`, and a
revision.

The provider contract returns only requested source regions and output sizes.
QPane decides what is visible, chooses pyramid/sample density, schedules work,
clips, caches, and composites. A provider must be safe for concurrent reads and
must return detached images.

Implement `SparseRasterSourceProvider` when the source can enumerate bounded
patches instead of materializing transparent gaps. Implement
`RasterHitTestProvider` when accurate nontransparent hit testing can be answered
more cheaply than sampling a full region.

`RasterProductPolicy` distinguishes settled cacheable content from volatile
samples. Publish a new revision and `RasterSourcePatch` damage when live
content changes; do not reuse a revision for different pixels. That contract
lets QPane invalidate only affected products.

## 7. Vector and Hybrid Sources

`VectorSource` wraps an immutable semantic `VectorDocument`. QPane samples it
at visible scale, caches complete products, and refines asynchronously. Hosts
retain real paths, shapes, style, and Unicode text instead of allocating a
canvas-sized raster.

`HybridSource` combines semantic vector primitives with region-sampled raster
coverage. A `HybridRasterSampler` receives a source-local rectangle and exact
output size on a worker and returns detached grayscale coverage. This is useful
for source types whose authoritative representation naturally contains both
forms.

Do not add a second host-side tile pyramid for these sources. The public source
contract exists so QPane's unified cache, damage, scheduling, clipping, and
presentation effects apply to every kind of content.

## Rules of the Road

1. **Use stable unique names.** Overlay and tool registrations belong to the
   host component that created them.
2. **Respect coordinate spaces.** Use `panelHitTest()`, supplied transforms,
   and scene overlay geometry instead of recomputing DPI math.
3. **Keep paint callbacks cheap.** Prepare expensive state at its real owner
   and draw a snapshot.
4. **Publish immutable render values.** Revisions and damage describe changes;
   render workers never observe a half-mutated object.
5. **Request, do not reach.** Tools and extensions use signals, ports, facade
   methods, and typed snapshots—not private renderer attributes.
6. **Clean up by owner.** Unregister named contributions when their host
   component is disposed.

## Related Docs

* [Interaction Modes](interaction-modes.md): viewer tools and input lifecycle.
* [Rendering SDK](rendering-sdk.md): scenes, sources, vectors, hybrid sampling,
  clipping, and rendering behavior.
* [Advanced Renderer Integration](integration-sdk.md): supported engine-host
  contracts for products that own scene providers, caches, or scheduling.
* [Diagnostics](diagnostics.md): built-in domains and provider guidance.

**Continue →** [API Reference](api-reference.md)
