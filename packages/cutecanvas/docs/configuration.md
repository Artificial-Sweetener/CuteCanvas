# Configuration

CuteCanvas starts with practical desktop defaults. `Config` lets an application
change memory limits, navigation feel, brush input, mask autosave, optional
model setup, diagnostics, and background-work limits in one validated snapshot.

Viewport tiles and pyramids reconstruct sRGB premultiplied RGBA8 pixels in
encoded space by default. Linear-light sRGB reconstruction is an explicit live
setting and does not change document pixels:

```python
from cutecanvas import Config
from qpane import RasterReconstructionSpace

config = Config(
    viewport_reconstruction_space=RasterReconstructionSpace.SRGB_LINEAR,
)
```

## Create a Configuration

Build a `Config`, adjust it, and pass it to the widget:

```python
from cutecanvas import Config, CuteCanvas

config = Config().configure(
    smooth_zoom_duration_ms=60,
    mask_autosave_enabled=True,
)

canvas = CuteCanvas(config=config, features=("mask",))
```

The widget keeps its own copy. Reusing `config` for another window does not
make the windows share mutable settings.

Use `copy()` when several editor profiles begin with the same application
defaults:

```python
base = Config()
review = base.copy().configure(touch_paint_enabled=False)
painting = base.copy().configure(default_brush_size=48)
```

`as_dict()` returns a detached mapping suitable for a settings panel, JSON
storage, or a support report.

## Apply Settings to a Running Canvas

`applySettings()` replaces the active snapshot and reconfigures affected
services:

```python
canvas.applySettings(
    diagnostics_overlay_enabled=True,
    diagnostics_domains_enabled=("cache", "render"),
)
```

Use it for user settings and application-mode changes. It may resize caches,
cancel stale prefetch, or update feature services, so it is not a pointer-rate
animation API.

`canvas.settings` returns the current snapshot. `installedFeatures` reports
which requested optional features are active.

Unknown keys and invalid values raise immediately. This catches misspelled
performance or autosave settings instead of silently using a different policy.

## Choose a Memory Policy

QPane and CuteCanvas share one byte-counted cache budget. Raster tiles,
pyramids, mask presentation, and optional model products compete inside that
budget instead of growing independently.

`CacheMode.AUTO` observes available system memory and preserves configured
headroom. `CacheMode.HARD` uses an explicit limit:

```python
from cutecanvas import CacheMode

config.configure(
    cache={
        "mode": CacheMode.HARD,
        "budget_mb": 2048,
    }
)
```

A hard limit is useful for a kiosk, batch workstation, or application that has
several memory-intensive components. Auto mode is usually the best starting
point for a desktop editor.

Cache weights are relative. Increase one only after diagnostics shows that its
products churn during a representative workflow. Leave individual `mb` fields
at `-1` to let the shared coordinator divide the budget.

## Adjust Zoom Feel

Smooth zoom follows the active display refresh rate when Qt can report it:

```python
config.configure(
    smooth_zoom_enabled=True,
    smooth_zoom_duration_ms=80,
    smooth_zoom_burst_duration_ms=20,
    smooth_zoom_burst_threshold_ms=25,
    smooth_zoom_use_display_fps=True,
    smooth_zoom_fallback_fps=60.0,
)
```

The shorter burst duration keeps repeated wheel input responsive. Disable
smooth zoom when the application requires every requested scale to apply
immediately; pointer anchoring and safe zoom limits remain intact.

## Configure Brush and Pen Input

The basic brush and direct-input settings are independent:

```python
config.configure(
    default_brush_size=40,
    brush_scroll_increment=5,
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
```

This lets an application keep two-finger navigation while disabling one-finger
painting, or accept pen painting while reserving touch for navigation.

`BrushPreset` contains the richer per-brush choices—hardness, opacity, flow,
spacing, smoothing, texture, and dynamics. Use `setBrushPreset()` for those
instead of rebuilding the widget configuration.

See [Touch and Pen](touch-and-pen.md) for gesture ownership and pressure
behavior.

## Configure Mask Autosave

Mask autosave produces processing-ready grayscale files beside the editable
document workflow:

```python
config.configure(
    mask_autosave_enabled=True,
    mask_autosave_on_creation=True,
    mask_autosave_debounce_ms=1000,
    mask_autosave_path_template="masks/{image_name}-{mask_id}.png",
)
```

The debounce timer restarts after each edit. Complete `.cutecanvas` persistence
is separate and retains layers, retained shapes, transforms, and off-canvas
content.

`mask_undo_limit`, `mask_border_enabled`, and `mask_prefetch_enabled` control
mask history retention, optional border presentation, and presentation warmup.

## Configure SAM

SAM settings are used only when the `sam` feature is requested:

```python
config.configure(
    sam_device="cpu",
    sam_download_mode="background",
    sam_model_path=None,
    sam_model_hash="default",
    sam_cache_limit=1,
)
```

Use `cuda` or another supported device string when the application has a
matching runtime. `sam_download_mode` may be `background`, `blocking`, or
`disabled`. A custom model URL should normally include a matching SHA-256 hash.

See [Masks and SAM](masks-and-sam.md) for checkpoint readiness, progress
signals, and runtime refresh.

## Bound Background Work

CuteCanvas and its QPane renderer use one execution runtime for rendering,
painting, file work, projections, placed assets, and optional model work. A
standalone canvas creates a bounded runtime automatically. To choose a
different standalone budget, pass a typed policy to the widget:

```python
from cutecanvas import CuteCanvas
from qpane.sdk.execution import DefaultExecutionPolicy

canvas = CuteCanvas(
    execution_policy=DefaultExecutionPolicy(
        max_workers=4,
        max_accepted=256,
    )
)
```

Execution is not part of `Config` because it belongs to application runtime
ownership rather than document or editor preferences. A host can pass the same
`ExecutionRuntime` to several canvases and QPane viewers, or construct it over
a custom bounded backend. CuteCanvas submits directly to that runtime and does
not create or shut down another pool.

Several views of the same document should instead share one
`CanvasDocumentRuntime`. It keeps document work and replaceable-request
freshness under one owner while every view retains an independent delivery
scope.

When a custom runtime does not advertise stable native affinity, CuteCanvas
creates a document-owned fallback for only the work that requires it. Ordinary
editor work continues directly through the host backend. See QPane's
[Advanced Renderer Integration](../../qpane/docs/integration-sdk.md) for the
complete host contract.

## Turn on Diagnostics

Enable the live HUD at startup:

```python
config.configure(
    diagnostics_overlay_enabled=True,
    diagnostics_domains_enabled=("cache", "render"),
    draw_tile_grid=False,
)
```

Runtime methods can show the HUD or change domains without applying an entire
configuration. See [Diagnostics](diagnostics.md) for the available records and
how to add host data.

## Discover Feature Settings

`Config.feature_descriptors()` returns descriptions and validators for feature
settings. Use it when a host builds a generated preferences page. A normal
handwritten settings screen can use the typed fields and
[Configuration Reference](configuration-reference.md) directly.

## Related Docs

* [Configuration Reference](configuration-reference.md): every field and exact
  shipped default.
* [Masks and SAM](masks-and-sam.md): mask autosave and model setup.
* [Touch and Pen](touch-and-pen.md): direct input and pressure behavior.
* [Diagnostics](diagnostics.md): observe memory, rendering, execution, and editor
  features.

**Continue →** [Configuration Reference](configuration-reference.md)
