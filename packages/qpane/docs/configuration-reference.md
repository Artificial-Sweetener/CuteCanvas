# Configuration Reference

This page is the complete reference for QPane's viewer and renderer settings.
The mapping below is checked against `Config().as_dict()` during repository
validation, so it is also an exact statement of the shipped defaults.

Most applications should begin with `Config()` and change only the opinions
that matter to their workflow. Pass the object to `QPane(config=...)`, or call
`applySettings()` to replace settings on an existing widget.

## Complete Default Mapping

```python
config = {
    "cache": {
        "mode": "auto",
        "headroom_percent": 0.1,
        "headroom_cap_mb": 4096,
        "budget_mb": None,
        "weights": {
            "tiles": 55.0,
            "pyramids": 45.0,
            "extensions": {},
        },
        "prefetch": {
            "pyramids": 2,
            "tiles": 2,
            "tiles_per_neighbor": 4,
            "extensions": {},
        },
        "tiles": {"mb": -1},
        "pyramids": {"mb": -1},
        "extensions": {},
    },
    "placeholder": {
        "source": None,
        "panzoom_enabled": False,
        "drag_out_enabled": False,
        "zoom_mode": "fit",
        "locked_zoom": None,
        "locked_size": None,
        "scale_mode": "auto",
        "display_size": None,
        "min_display_size": None,
        "max_display_size": None,
        "scale_factor": 1.0,
    },
    "tile_size": "auto",
    "tile_overlap": 8,
    "min_view_size_px": 128,
    "canvas_expansion_factor": 1.4,
    "safe_min_zoom": 0.001,
    "drag_out_enabled": True,
    "normalize_zoom_on_screen_change": False,
    "normalize_zoom_for_one_to_one": False,
    "smooth_zoom_enabled": True,
    "smooth_zoom_duration_ms": 80,
    "smooth_zoom_burst_duration_ms": 20,
    "smooth_zoom_burst_threshold_ms": 25,
    "smooth_zoom_fallback_fps": 60.0,
    "smooth_zoom_use_display_fps": True,
    "touch_navigation_enabled": True,
    "palm_rejection_ms": 800,
    "touch_inertia_enabled": True,
    "touch_inertia_deceleration": 4500.0,
    "diagnostics_overlay_enabled": False,
    "diagnostics_domains_enabled": (),
    "draw_tile_grid": False,
}
```

## Cache Policy

`cache.mode` selects how QPane establishes its byte budget.

* `"auto"` follows available system memory while preserving
  `headroom_percent`, capped by `headroom_cap_mb`.
* `"hard"` uses `budget_mb` as a deterministic process budget.
`cache.weights` divides the shared budget between visible tile products and
image pyramids. The values are relative weights, not percentages; `55/45` and
`110/90` describe the same split. Extension owners may publish additional
named consumers through `weights.extensions` and `cache.extensions` without
changing QPane's built-in schema.

The `tiles.mb` and `pyramids.mb` values are resolved allocations. Leave them at
`-1` for coordinated budgeting. Positive values are useful only when a host
needs an explicit per-consumer ceiling and understands that it is constraining
the shared policy.

## Neighbor Prefetch

`cache.prefetch.pyramids` controls how many catalog neighbors receive
speculative pyramid work. `cache.prefetch.tiles` controls how many neighbors
receive tile work, and `tiles_per_neighbor` bounds each neighbor's request.
Prefetch never outranks visible work and is cancelled when rapid navigation
makes it stale.

Set these values to zero for strictly demand-driven rendering. Inspect
`catalogPrefetchState()` or enable the `swap` diagnostics domain before tuning;
an apparently generous setting can be counterproductive on slow storage or a
tight cache budget.

## Placeholder Presentation

`placeholder.source` accepts a file path or `None`. File-backed placeholders
decode outside the GUI thread. `setPlaceholderImage()` is the corresponding
facade method when the host already has a decoded `QImage`.

`panzoom_enabled` and `drag_out_enabled` are deliberately independent from the
ordinary content policy. A welcome image can stay fixed while real images
remain interactive. `zoom_mode` accepts `"fit"`, `"one_to_one"`, or
`"locked"`; `locked_zoom` supplies the scale for the locked mode.

The sizing fields control how the placeholder occupies an empty viewer:

* `locked_size` fixes source-space dimensions.
* `scale_mode` selects automatic, display-size, or scale-factor behavior.
* `display_size`, `min_display_size`, and `max_display_size` constrain the
  rendered footprint.
* `scale_factor` applies an additional positive multiplier.

Real catalog content and an explicit `setScene()` always take precedence over
the placeholder. `placeholderState()` reports loading, errors, and whether the
placeholder is active.

## Tiles and Canvas

`tile_size` accepts `"auto"` or a positive integer. The default automatic
policy selects a bounded power-of-two source-space tile edge from the
viewport's physical pixel area: 512 pixels for typical 1080p viewports, 1024
pixels around physical 4K, 2048 pixels for intermediate high-resolution
viewports, and at most 4096 pixels for ultra-high-DPR viewports. Above physical
4K, the policy deliberately reduces the target number of viewport tiles to
amortize software-rendering overhead. It uses resize debounce and hysteresis so
ordinary window movement does not churn the cache. The active cache allocation
can lower an automatic choice to retain a useful working set.

A positive integer is a strict host override. QPane preserves that exact tile
edge across viewport and DPR changes. Changing between automatic buckets, or
changing an explicit tile size, cancels incompatible tile work and invalidates
the old grid before the next frame is planned; tiles from different grids are
never merged or reused as if they were equivalent.

`tile_overlap` supplies neighboring pixels for filtered transforms so seams do
not appear between independently sampled products.

`min_view_size_px` prevents the viewport from collapsing below a useful
physical size. `canvas_expansion_factor` reserves navigation room outside the
scene, and `safe_min_zoom` is the numerical floor applied before transform
math. These values are renderer geometry, not document or layer bounds.

## Mouse and Zoom Feel

`drag_out_enabled` lets the cursor tool initiate an operating-system image
drag. It does not affect panning.

`normalize_zoom_on_screen_change` preserves apparent scale when a window moves
between displays with different device-pixel ratios.
`normalize_zoom_for_one_to_one` interprets 1:1 through physical display pixels
instead of logical Qt pixels.

Smooth zoom is enabled by default:

* `smooth_zoom_duration_ms` is the ordinary interpolation window.
* `smooth_zoom_burst_duration_ms` shortens animation during rapid wheel input.
* `smooth_zoom_burst_threshold_ms` decides when input counts as a burst.
* `smooth_zoom_fallback_fps` is used when display refresh is unavailable.
* `smooth_zoom_use_display_fps` follows the active screen's refresh rate when
  Qt reports it.

Disabling `smooth_zoom_enabled` applies each requested scale immediately while
retaining pointer anchoring.

## Touch Navigation

`touch_navigation_enabled` enables one-finger pan and two-finger pinch
navigation. `palm_rejection_ms` suppresses touch promoted immediately after pen
activity. This is input arbitration, not a painting policy; custom tools use
the same normalized pointer stream.

`touch_inertia_enabled` continues a deliberate pan after release.
`touch_inertia_deceleration` is measured in logical pixels per second squared;
higher values stop sooner.

## Diagnostics

`diagnostics_overlay_enabled` controls the built-in HUD at startup.
`diagnostics_domains_enabled` is the tuple of detail domains initially visible
in the snapshot, such as `"tiles"`, `"pyramids"`, or `"swap"`.
`draw_tile_grid` adds the renderer's tile grid for visual diagnosis. It is a
debugging aid and should normally remain off.

Runtime controls are available through `setDiagnosticsOverlayEnabled()` and
`setDiagnosticsDomainEnabled()`; changing them does not require rebuilding the
widget.

## Execution Policy

Worker capacity is intentionally absent from `Config`: it belongs to the
execution runtime rather than a viewer preferences snapshot. Pass
`DefaultExecutionPolicy` as `execution_policy` when QPane should own its
standalone runtime. Pass a host-owned `ExecutionRuntime` as
`execution_runtime` when several widgets or the surrounding application share
one admission authority.

The default policy bounds accepted work and retained bytes, applies fair
semantic urgency, and limits resource classes independently. See
[Advanced Renderer Integration](integration-sdk.md) for the complete execution
contract and custom backend seam.
