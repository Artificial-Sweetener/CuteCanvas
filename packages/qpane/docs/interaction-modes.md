**← Previous:** [Catalog and Navigation](catalog-and-navigation.md)

# Interaction Modes

An interaction mode defines what pointer input means while it is over QPane.
The viewer ships with polished navigation and cursor modes, and exposes the
same tool boundary to hosts that need measurement, annotation chrome, region
inspection, or another viewer-only workflow.

QPane tools own transient input sessions and visual feedback. They do not own
mutable documents or editor history. An editor such as CuteCanvas builds those
concerns above the viewer while continuing to use this public extension system.

## Switching Modes

Pan/Zoom is active by default. Switch modes by stable string ID:

```python
from qpane import QPane

viewer.setControlMode(QPane.CONTROL_MODE_PANZOOM)
viewer.setControlMode(QPane.CONTROL_MODE_CURSOR)

print(viewer.controlMode())
print(viewer.availableControlModes())
```

`controlModeChanged` emits after the active tool changes. An unknown ID raises
`ValueError`; a registered tool that cannot be constructed leaves the viewer
in a safe mode and reports the failure through normal logging.

### Build a Simple Toggle

```python
modes = viewer.availableControlModes()
current = viewer.controlMode()
if modes:
    next_index = (modes.index(current) + 1) % len(modes)
    viewer.setControlMode(modes[next_index])
```

A polished host usually presents named actions instead of cycling every
extension, but this is convenient for a compact inspection utility.

## Pan/Zoom

`QPane.CONTROL_MODE_PANZOOM` activates the built-in navigation implementation,
`PanZoomTool`, for familiar viewer behavior:

* Drag to pan.
* Use the wheel for pointer-anchored zoom.
* Double-click to toggle between Fit and 1:1.
* Use one-finger drag and two-finger pinch on touch hardware.
* Cross native scale through an exact 1:1 snap instead of skipping over it.

The tool delegates geometry to `NavigationInteractionPort`; it does not keep a
parallel zoom or pan model. Programmatic calls such as `setZoomFit()`,
`setZoom1To1()`, `applyZoom()`, and `setPan()` therefore agree exactly with
mouse and touch navigation. A custom port's `get_native_zoom` callback receives
the current panel-space pointer anchor, allowing a layered scene to resolve
native scale from the visible clipped source under the gesture.

`setPanZoomLocked(True)` disables all of those paths together. Use it for a
modal host state or fixed review surface rather than replacing handlers one by
one.

## Cursor

`QPane.CONTROL_MODE_CURSOR` activates `CursorTool`. It provides a neutral
pointer state and allows configured image drag-out without turning a press into
viewport movement. This is useful when the host treats QPane as a source
preview or handles clicks in surrounding UI.

When drag-out begins, QPane starts the operating-system drag and emits
`dragOutRequested` for observation. `Config.drag_out_enabled` controls ordinary
content, while the placeholder has its own `drag_out_enabled` setting.

## Register a Viewer Tool

Subclass `ViewerTool` and register a factory. The factory receives no implicit
service locator; capture only the public dependencies the tool actually needs.

```python
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QPainter
from qpane import QPane, ViewerTool


class CoordinateTool(ViewerTool):
    """Show the scene coordinate under the pointer."""

    def __init__(self, pane: QPane) -> None:
        """Retain the public facade used for hit testing."""
        super().__init__()
        self._pane = pane
        self._position: QPointF | None = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track the pointer and request transient chrome repaint."""
        self._position = QPointF(event.position())
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw source coordinates without mutating the scene."""
        if self._position is None:
            return
        hit = self._pane.panelHitTest(self._position)
        if hit is not None:
            painter.drawText(self._position, str(hit.raw_point))

    def getCursor(self) -> QCursor:
        """Use a precision cursor for inspection."""
        return QCursor(Qt.CursorShape.CrossCursor)


viewer.registerTool("coordinates", lambda: CoordinateTool(viewer))
viewer.setControlMode("coordinates")
```

Call `unregisterTool("coordinates")` when the host removes an extension. If it
is active, QPane resolves the interaction before disposing the tool and returns
to a valid built-in mode.

## Tool Signals and Fault Containment

Each tool has `ViewerToolSignals` for requests such as overlay repaint. Input
dispatch and lifecycle are owned by `ToolManager`; one extension does not get
direct access to renderer caches, private viewport state, or another tool.

`ToolInputProfile` describes the input a tool accepts. At the lower-level
boundary, QPane normalizes mouse, pen, and touch through `PointerSample`,
`PointerDeviceKind`, and `PointerPhase`. `PointerInputController` dispatches to
a `PointerInputPort` while `TouchGestureArena` arbitrates navigation gestures.

Most tools should stay at `ViewerTool`. Use the lower-level values only when a
host needs device-neutral input semantics that cannot be expressed by the
ordinary Qt event hooks.

## Coordinate and Hit-Test Rules

Tool events arrive in widget coordinates. Call `panelHitTest()` instead of
recreating viewport math:

```python
hit = viewer.panelHitTest(event.position())
if hit is not None and hit.inside_image:
    print(hit.raw_point, hit.clamped_point)
```

`PanelHitTest.panel_point` is the supplied panel coordinate. `raw_point` may be
outside the source and is appropriate for hover feedback. `clamped_point` is
safe for a pixel lookup. `inside_image` distinguishes the two cases without
rounding at the boundary.

For layered scenes, use a scene overlay or the render plan when the host needs
per-layer projected geometry. Source-specific transparency tests belong to a
`RasterHitTestProvider`, which lets the renderer answer without a full-canvas
scan.

## Comparison Divider Interaction

The comparison boundary remains draggable in both built-in modes. It is viewer
chrome, independent of the active tool, and uses the same authoritative
transformed scene geometry as rendering. A middle-button press calls the
boundary to the pointer's scene position and owns subsequent movement until
that button is released.

Use `setComparisonDividerInteractive(False)` when host policy disables direct
dragging. `comparisonDividerInteractive()` reports the setting, and
`comparisonDividerState()` supplies authoritative geometry for host-painted
chrome. Tool authors should not intercept or duplicate the divider hit region.

## Touch Navigation and Temporary Ownership

`TouchGestureArena` decides whether contacts form a pan or pinch before a tool
claims them. Active pen input suppresses promoted touch for the configured palm
rejection interval. Temporary navigation never mutates scene or extension
state; it only changes which input owner receives the current gesture.

The full contract is in [Touch and Pen Input](touch-and-pen.md).

## Interaction Rules

* **Modes persist:** catalog navigation does not silently reset the selected
  viewer tool.
* **One viewport owner:** built-in tools, host calls, and touch navigation use
  the same zoom and pan state.
* **Transient chrome stays transient:** a tool overlay never becomes scene
  content or export output.
* **Tool failures are contained:** teardown and invalid input leave a usable Qt
  widget rather than a half-active pointer session.
* **Public dependencies only:** an extension receives facade methods, typed
  ports, or immutable snapshots—not private renderer collaborators.

## Related Docs

* [Touch and Pen Input](touch-and-pen.md): touch arbitration, pen proximity,
  inertia, and normalized samples.
* [Extensibility](extensibility.md): tools, overlays, diagnostics providers,
  presentation effects, and custom sources.
* [Catalog and Navigation](catalog-and-navigation.md): the content users are
  interacting with.

**Continue →** [Touch and Pen Input](touch-and-pen.md)
