# Extensibility

CuteCanvas supplies editor state and workflows while QPane supplies the
viewport, rendering, overlays, and tool-extension boundary. Host extensions use
those public boundaries together. They do not need a second scene model or a
private hook into the widget.

## Draw Host Chrome

Use `registerOverlay()` for widget-relative artwork such as a scale, status
label, or reticle:

```python
from PySide6.QtCore import Qt


def draw_zoom(painter, state) -> None:
    rect = state.qpane_rect.adjusted(12, 12, -12, -12)
    painter.setPen(Qt.GlobalColor.yellow)
    painter.drawText(
        rect,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        f"Zoom: {state.zoom * 100:.0f}%",
    )


canvas.registerOverlay("zoom-label", draw_zoom)
```

The callback receives a painter in widget coordinates and an immutable
`OverlayState`. Registration order is drawing order. Remove the contribution
with `unregisterOverlay()` when its owning host component closes.

Overlay callbacks run during painting. Prepare expensive state elsewhere and
draw only the prepared snapshot.

## Draw Chrome for Document Layers

Use `registerSceneOverlay()` when the drawing follows layer geometry:

```python
from PySide6.QtGui import QColor, QPen


def draw_layer_names(painter, state) -> None:
    painter.setPen(QPen(QColor("cyan"), 1.0))
    for layer in state.layers:
        if not layer.visible:
            continue
        painter.drawRect(layer.panel_bounds)
        painter.drawText(
            layer.panel_bounds.adjusted(8, 8, -8, -8),
            layer.label,
        )


canvas.registerSceneOverlay("layer-names", draw_layer_names)
```

`SceneSnapshotOverlayState.layers` follows document draw order. Each entry
contains stable IDs, labels, visibility, source size, scene placement,
source-to-panel transform, and projected panel bounds. Use those values instead
of repeating viewport or high-DPI projection in host code.

Scene overlays are observational. They do not alter document history,
persistence, selection, or exported pixels.

## Highlight Rendered Content

Use `canvas.editor.effects` when an effect must follow the visible,
nontransparent content of a layer:

```python
from PySide6.QtGui import QColor
from cutecanvas import LayerPresentationStyle

composition = canvas.editor.compositions.current
if composition is not None and composition.layers:
    layer = composition.layers[-1]
    effect = layer.add_effect(
        LayerPresentationStyle.outline(QColor("cyan"), width=2.0)
    )
```

The renderer derives coverage for raster, mask, vector, hybrid, and placed
sources through one effect path. This keeps the treatment aligned with clips,
transforms, live movement, and zoom.

An effect handle can change or remove its treatment:

```python
effect.update(
    LayerPresentationStyle.tint(QColor("cyan"), opacity=0.18)
)
effect.remove()
```

Effects are temporary presentation. They do not edit source pixels, create an
undo entry, enter persistence, or appear in an exported document image.

Use an overlay for arbitrary host drawing. Use an effect when QPane must derive
the actual rendered coverage.

## Add a Tool

CuteCanvas uses QPane's public tool extension system. A custom tool subclasses
`ViewerTool`, owns its temporary interaction state, and asks the widget for
supported viewport or editor operations.

```python
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QPainter, QPen
from qpane import ViewerTool


class CoordinateTool(ViewerTool):
    """Show source coordinates under the pointer."""

    def __init__(self, canvas) -> None:
        """Keep the public canvas facade used for hit testing."""
        super().__init__()
        self._canvas = canvas
        self._position: QPointF | None = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track the pointer and request fresh tool chrome."""
        self._position = QPointF(event.position())
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear feedback outside the widget."""
        del event
        self._position = None
        self.signals.repaint_overlay_requested.emit()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw coordinates when the pointer reaches rendered content."""
        if self._position is None:
            return
        hit = self._canvas.panelHitTest(self._position.toPoint())
        if hit is None:
            return
        painter.setPen(QPen(Qt.GlobalColor.cyan, 1.0))
        painter.drawText(
            self._position + QPointF(12.0, -8.0),
            f"{hit.raw_point.x():.0f}, {hit.raw_point.y():.0f}",
        )

    def getCursor(self) -> QCursor:
        """Use a precision cursor while the tool is active."""
        return QCursor(Qt.CursorShape.CrossCursor)


canvas.registerTool("coordinates", lambda: CoordinateTool(canvas))
canvas.editor.tools.activate("coordinates")
```

`ViewerTool.signals` requests overlay repaint, cursor refresh, pan, and zoom
without exposing viewport internals. The base class provides no-op handlers, so
a tool implements only the events it owns.

Switch to another tool before calling `unregisterTool()`. The active tool owns
pointer capture until it deactivates.

## Apply Host Policy

Tools advertise actions; policy decides whether they are allowed for a
particular document and layer. Set `LayerPolicy` or `CompositionPolicy` through
their handles instead of teaching a custom tool which layer roles are editable.
The same policy then governs built-in tools, keyboard commands, and host calls.

```python
from cutecanvas import LayerPolicy

layer.set_policy(
    LayerPolicy(
        selectable=True,
        movable=True,
        pixel_editable=True,
        reorderable=True,
        removable=True,
    )
)
```

Use `editorOperationState()` when a toolbar needs to explain why an action is
unavailable before invoking it.

## Rules for Extensions

1. Keep one owner for document, selection, transform, history, and render
   state. Observe snapshots or call facades rather than mirroring them.
2. Use supplied coordinate transforms and hit tests. Do not reproduce viewport
   projection in host code.
3. Keep paint callbacks quick and allocation-light.
4. Give every registration a stable, owner-specific name and remove it during
   teardown.
5. Use tool signals and public facades. Private widget attributes are not an
   extension API.

## Related Docs

* [Interaction and Tools](interaction-modes.md): Built-in tools, selection,
  movement, and transforms.
* [Documents and Layers](scenes.md): Handles, policies, and host state.
* [QPane Extensibility](../../qpane/docs/extensibility.md): Full overlay, tool,
  diagnostics, and render-source contracts.

**Continue →** [API Reference](api-reference.md)
