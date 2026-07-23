# Touch and Pen Input

QPane accepts touchscreen and active-pen input through Qt's normal event
surface. Host applications do not need platform-specific Windows Ink, AppKit,
or XInput2 handlers. Mouse, pen, and touch are normalized before viewer tools
receive them, while gesture arbitration prevents synthesized mouse packets from
duplicating an accepted direct-input action.

## Expected Viewer Gestures

| Context | Gesture | Result |
| --- | --- | --- |
| Pan/zoom | One-finger drag | Pans the scene under the finger. |
| Pan/zoom | Two-finger drag or pinch | Pans and zooms around the live contact centroid. |
| Pan/zoom | Double tap | Toggles Fit and native 1:1 using Qt's platform double-click interval. |
| Pan/zoom | Release after a drag | Continues with bounded translation inertia when enabled. |
| Comparison | Touch near the split boundary | Drags the divider with a touch-sized hit target. |
| Custom tool | Accepted pen or touch sequence | Delivers normalized samples to that tool until release or cancellation. |

Contact-count transitions are re-anchored before another transform is applied,
so adding or removing a finger does not jump the content. A gesture keeps its
winner for the contact sequence: once navigation or a custom tool claims it,
another contact cannot silently transfer ownership halfway through.

## Gesture Arbitration

`TouchGestureArena` resolves contact intent. `TouchGestureKind` identifies the
winning gesture, while `TouchNavigationSession` retains only the transient
centroid, span, velocity, and capture information needed for navigation. The
durable viewport remains owned by QPane.

The ordinary path is exposed through `TouchNavigationPort`. This separation is
important for editor hosts: a tool may participate in input arbitration without
copying the renderer's pan, zoom, DPI, or inertia rules.

When a tool accepts a direct-input sequence, QPane ignores synthesized mouse
events generated from the same touch or tablet packets. A real mouse move can
take over pointer presentation after the direct-input sequence ends.

## Active Pen Behavior

QPane distinguishes mouse, touch, pen, and eraser through `PointerDeviceKind`.
`PointerSample` retains floating-point position, phase, pressure, modifiers,
buttons, and device identity. `PointerPhase` describes hover, press, move,
release, cancellation, and proximity transitions without making a tool decode
platform event subclasses itself.

Active-pen hover is a hardware capability, not a cross-platform guarantee.
Hover-capable digitizers report in-range movement through Qt. Contact-only
active pens still produce contact samples, while passive capacitive styluses
are indistinguishable from fingers.

Recent pen activity suppresses promoted touch for `palm_rejection_ms`. A
two-finger navigation gesture may still win during that interval, allowing the
non-dominant hand to navigate while a pen-aware extension owns precision input.
QPane does not impose brush dynamics or document edits; those policies belong
to the tool or editor using the normalized stream.

## Pointer Input for Extensions

Most extensions should subclass `ViewerTool` and override the concrete Qt event
hooks they need. Use `PointerInputController` with a `PointerInputPort` when the
same behavior must consume device-neutral samples across mouse, pen, and touch.

`ToolInputProfile` declares accepted devices and gesture expectations before a
sequence begins. That lets QPane arbitrate navigation and custom work without
probing private tool state.

Keep the responsibilities narrow:

* the input controller normalizes and routes packets;
* the gesture arena chooses an owner;
* the viewer owns pan, zoom, capture, and cancellation safety;
* the extension owns its transient interaction state;
* a higher-level application owns any durable document mutation or history.

This arrangement is why temporarily navigating does not erase or commit a
custom operation.

## Configuration

```python
from qpane import Config, QPane

config = Config(
    touch_navigation_enabled=True,
    palm_rejection_ms=800,
    touch_inertia_enabled=True,
    touch_inertia_deceleration=4500.0,
)

viewer = QPane(config=config)
```

Disabling `touch_navigation_enabled` leaves mouse navigation and custom tool
input available. `setPanZoomLocked(True)` blocks navigation as a whole while
preserving the active tool and its non-navigation policy.

Translation inertia is deliberately bounded and cancelled by new input,
content changes, viewport teardown, or a lock transition. Increase
`touch_inertia_deceleration` for a shorter coast; disable
`touch_inertia_enabled` when direct correspondence at release is more important
than momentum.

## Comparison Input

The split reveal uses a larger touch hit region than mouse input. The actual
line remains tied to rendered scene geometry, so it moves correctly with pan,
zoom, and high-DPI changes. `comparisonDividerState()` exposes the effective
hit width and projected segment for host-owned visuals.

Disable only that behavior with `setComparisonDividerInteractive(False)`.
There is no need to disable all touch navigation to present a read-only compare
boundary.

## Testing Direct Input

The QPane suite mounts real widgets and drives synthetic touchscreen,
`QTabletEvent`, and `QMouseEvent` sequences. It verifies capture,
cancellation, palm arbitration, synthesized-event rejection, contact-count
transitions, pan/pinch math, inertia, comparison dragging, teardown, and
touch-to-mouse restoration.

Synthetic packets cannot emulate a particular digitizer driver, physical hover
range, operating-system edge gesture, or device sampling rate. Before a
release, perform an exploratory pass on representative hardware to evaluate
physical latency and driver behavior. Automated mounted tests remain the
regression gate; hardware testing validates feel.

The behavior follows Qt's documented [touch event capture and cancellation
model](https://doc.qt.io/qt-6/qtouchevent.html), [tablet pressure and eraser
model](https://doc.qt.io/qt-6/qtabletevent.html), and [Qt Test touch-device
API](https://doc.qt.io/qt-6/qtest.html).

## Related Docs

* [Interaction Modes](interaction-modes.md): built-in modes and custom viewer
  tools.
* [Configuration Reference](configuration-reference.md): all input defaults
  and valid fields.
* [Extensibility](extensibility.md): overlays, tools, diagnostics, effects, and
  render sources.
