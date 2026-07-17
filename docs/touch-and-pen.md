# Touch and Pen Input

QPane accepts touchscreen and active-pen input directly through Qt. Host applications do not need platform-specific Windows Ink, AppKit, or XInput2 handlers. Mouse input keeps its existing behavior, while touch and tablet events use a separate direct-input path so synthesized mouse events cannot duplicate an edit.

## Expected Gestures

| Context | Gesture | Result |
| --- | --- | --- |
| Pan/zoom | One-finger drag | Pans the image under the finger. |
| Pan/zoom | Two-finger drag or pinch | Pans and zooms around the live contact centroid. |
| Pan/zoom | Double tap | Toggles fit and native 1:1 zoom using Qt's platform double-click interval. |
| Pan/zoom | Release after a drag | Continues with bounded translation inertia when enabled. |
| Brush | One-finger tap or drag | Paints a fixed-size mask stroke using the configured brush diameter. |
| Brush | Two contacts before painting wins | Navigates without creating a mask edit. |
| Brush | Active-pen hover | Shows the configured brush size and paint or erase identity without editing the mask. |
| Brush | Active-pen contact | Paints immediately with subpixel coordinates and optional pressure sizing. |
| Brush | Eraser end of an active pen | Erases without requiring the Alt modifier. |
| Smart Select | One-finger drag | Draws the selection rectangle. |
| Smart Select | Two contacts before selection wins | Navigates the viewport. |
| Comparison | Touch near the split boundary | Drags the divider using a 44-pixel touch target. |

Contact-count transitions are re-anchored before another transform is applied, so adding or removing a finger does not jump the content. A gesture keeps its winner for the rest of the contact sequence: once a brush stroke or selection has started, another contact cannot silently turn that edit into navigation.

## Brush and Stylus Behavior

Brush feedback follows the active physical device. A mouse uses the platform brush cursor. The first genuine mouse movement after touch or pen input restores that cursor immediately, while synthesized mouse packets produced from handled touch or tablet input are ignored. Touch and active pens use a canvas overlay so feedback is not limited by platform cursor-image dimensions.

A one-finger brush contact shows the fixed configured diameter as soon as the contact begins. The ring follows the finger while painting and disappears on release or cancellation. If a second contact makes navigation win, the ring disappears and no mask edit is created. Touchscreens and passive capacitive styluses provide no position before contact, so they cannot display a pre-contact preview.

An active pen shows a floating ring while Qt reports hover movement. Hover uses the nominal configured brush diameter because contact pressure is not known yet. The eraser end shows the erase indicator. On contact, the ring follows the subpixel tip position and changes to the pressure-adjusted diameter used by the stroke. Releasing a hover-capable pen restores the nominal ring; leaving digitizer proximity, leaving the widget, changing tools, navigating to other content, or cancelling input removes it.

Touch painting uses `default_brush_size` directly. Active pens preserve Qt's floating-point tablet coordinates and map contact pressure to diameter:

```text
diameter = brush_size * (minimum_ratio + (1 - minimum_ratio) * pressure ** gamma)
```

The default minimum ratio is `0.15`, which keeps light contacts visible while preserving useful pressure range. Set `pen_pressure_enabled=False` for a fixed-size stylus. Stroke samples are deterministically resampled into overlapping dabs before preview and worker rendering, so the provisional mask and committed mask use the same geometry. Each captured contact produces one undo entry, regardless of how many tablet packets it contains.

Recent pen activity suppresses single-touch painting for `palm_rejection_ms`. Two-finger navigation can still win during that window. This policy gives the pen priority without disabling the non-dominant hand's navigation gesture.

Active-pen hover is a hardware capability rather than a Windows-wide guarantee. Hover-capable digitizers report in-range tablet movement through Qt. Contact-only active pens continue to paint with pressure when available but remove feedback on release. Passive styluses are indistinguishable from fingers and therefore use fixed-size touch behavior without hover, pressure, eraser identity, or subpixel tablet packets.

## Configuration

```python
from qpane import Config, QPane

config = Config(
    touch_navigation_enabled=True,
    touch_paint_enabled=True,
    stylus_paint_enabled=True,
    pen_pressure_enabled=True,
    pen_pressure_min_ratio=0.15,
    pen_pressure_gamma=1.0,
    palm_rejection_ms=800,
    touch_inertia_enabled=True,
    touch_inertia_deceleration=4500.0,
)

viewer = QPane(config=config, features=("mask",))
```

Disabling `touch_paint_enabled` leaves two-finger navigation available in Brush mode. Disabling `stylus_paint_enabled` makes QPane ignore tablet events, allowing a host-level handler to own them. Viewport locking blocks touch navigation while leaving mask-tool policy independent.

## Automated and Hardware Testing

The test suite uses Qt Test's synthetic touchscreen device plus constructed `QTabletEvent` and `QMouseEvent` objects. These tests run without touch hardware and verify event delivery, capture, cancellation, pen pressure, eraser identity, subpixel coordinates, hover-capability fallback, proximity cleanup, palm arbitration, touch-to-mouse restoration, synthesized-event rejection, rendered ring geometry, contact transitions, pan/pinch math, inertia, mask output, and undo grouping. GitHub Actions runs the same suite on Windows, macOS, and Linux.

Run the standalone input laboratory to inspect the same transitions interactively without tablet hardware:

```powershell
python -m examples.demonstration.touch_and_pen_simulator
```

The controls simulate pen and eraser hover, pressure-sensitive contact, proximity leave, one-finger touch painting, two-finger navigation, and returning to a genuine mouse. Synthetic packets travel through QPane's normal QWidget event surface rather than calling its input internals.

Synthetic events do not emulate a particular digitizer driver, operating-system edge gesture, physical hover range, cursor latency, or device sampling rate. Before a release, perform a short exploratory pass on at least one Windows pen display and one macOS trackpad or tablet configuration to evaluate latency and driver-specific behavior. The automated suite remains the regression gate; hardware testing validates the physical feel.

The implementation follows Qt's documented [touch event capture and cancellation model](https://doc.qt.io/qt-6/qtouchevent.html), [tablet pressure and eraser model](https://doc.qt.io/qt-6/qtabletevent.html), and [Qt Test touch-device API](https://doc.qt.io/qt-6/qtest.html).

## Related Docs

* [Interaction Modes](interaction-modes.md): Mode switching and navigation behavior.
* [Masks and SAM](masks-and-sam.md): Mask lifecycle, editing, and undo.
* [Configuration Reference](configuration-reference.md): All input defaults and valid ranges.
