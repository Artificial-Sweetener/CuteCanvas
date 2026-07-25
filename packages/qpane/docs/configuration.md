**← Previous:** [Getting Started](getting-started.md)

# Configuration

## The Config Object

QPane works out of the box with defaults that balance responsiveness, memory,
and familiar viewer behavior. If your application has different constraints,
`Config` is the single typed snapshot of those opinions.

Create it, adjust it, and pass it to the `QPane` constructor. The widget keeps
its own copy, so the same base configuration can seed several windows without
sharing mutable settings.

```python
from qpane import Config, QPane

base_config = Config()
review_config = base_config.copy().configure(
    smooth_zoom_duration_ms=60,
    cache={"mode": "hard", "budget_mb": 2048},
)

viewer = QPane(config=review_config)
```

`Config.copy()` deep-copies nested values. `Config.as_dict()` returns a plain,
detached mapping suitable for a settings panel, diagnostic report, or JSON
encoder.

> **Pro tip:** Keep one pristine application default and copy it for each
> window or workspace. That makes a user preference reset exact rather than a
> sequence of guessed inverse changes.

## Applying Changes

Use `applySettings()` when an existing viewer must adopt a new snapshot. It
applies one coherent configuration and reconfigures the affected services.

```python
viewer.applySettings(
    diagnostics_overlay_enabled=True,
    diagnostics_domains_enabled=("cache", "tiles"),
)
```

This is intentionally heavier than changing a presentation value. It may
resize caches, cancel stale prefetch, or rebuild viewport policy, so use it for
settings changes rather than pointer-rate animation. `viewer.settings` exposes
the widget's current snapshot for inspection.

`Config.configure()` accepts another mapping plus keyword overrides and merges
nested groups. Unknown keys and invalid values raise immediately:

```python
user_preferences = {
    "touch_inertia_enabled": False,
    "placeholder": {"panzoom_enabled": True},
}
config = Config().configure(user_preferences)
```

That strictness is deliberate. A misspelled performance setting should not
quietly fall back to a different runtime policy.

## Managing Memory

QPane counts retained raster products and coordinates them through one byte
budget. Choose the strategy that matches the host:

* `CacheMode.AUTO` is the normal desktop mode. It observes available system
  memory and preserves configured headroom for the OS and other applications.
* `CacheMode.HARD` uses an explicit `budget_mb`. It is appropriate for a kiosk,
  service process, or host with several memory-intensive components.

```python
from qpane import CacheMode

config.configure(
    cache={
        "mode": CacheMode.HARD,
        "budget_mb": 2048,
        "weights": {"tiles": 60.0, "pyramids": 40.0},
    }
)
```

Weights divide the shared budget between visible tile products and reusable
image pyramids. They are relative, so tune the ratio rather than trying to make
the values add to a particular number. Leave the resolved `tiles.mb` and
`pyramids.mb` fields at `-1` unless your deployment needs explicit
per-consumer ceilings.

### Prefetch Without Surprises

Catalog navigation can warm neighboring images after visible work settles.
The default keeps two neighbors eligible for pyramid work and bounds their tile
requests.

```python
config.configure(
    cache={
        "prefetch": {
            "pyramids": 1,
            "tiles": 1,
            "tiles_per_neighbor": 4,
        }
    }
)
```

Set the neighbor counts to zero for demand-only rendering. Before increasing
them, inspect `catalogPrefetchState()` and the `swap` diagnostics domain;
speculative work is useful only when storage, workers, and cache headroom can
absorb it without delaying the current frame.

## Empty States

An empty viewer is blank by default. Configure `placeholder` for a welcome
image, drop target, or application-specific instruction card.

```python
config.configure(
    placeholder={
        "source": "assets/welcome.png",
        "panzoom_enabled": False,
        "drag_out_enabled": False,
        "zoom_mode": "fit",
        "scale_mode": "logical_fit",
    }
)
```

The placeholder has its own navigation and drag-out policy. This lets an
application keep the welcome artwork fixed without disabling interaction for
real content. File-backed placeholders decode away from the GUI thread;
`placeholderState()` reports loading or error state. Use
`setPlaceholderImage()` when the host already owns a decoded `QImage`.

An explicit scene or selected catalog image always wins. Clearing that content
reveals the placeholder again without turning it into a document or catalog
entry.

## Smooth Zoom

Smooth zoom animates the transition between exact viewport scales. It never
changes the requested result or the pointer anchor.

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

Rapid wheel ticks use the shorter burst duration so input stays connected to
the hand. When Qt reports the active screen's refresh rate, QPane schedules
against it; otherwise it uses the fallback. A duration shorter than one frame
is applied immediately instead of producing an unstable one-frame animation.

`normalize_zoom_on_screen_change` preserves apparent scale across displays
with different device-pixel ratios. `normalize_zoom_for_one_to_one` makes 1:1
refer to physical rather than logical screen pixels.

## Touch and Active Pen

Touch navigation is enabled by default. One finger pans; two fingers arbitrate
into pinch navigation. Pen activity temporarily suppresses promoted touch
through `palm_rejection_ms`, which keeps custom pen-aware tools from receiving
a second synthetic gesture.

```python
config.configure(
    touch_navigation_enabled=True,
    palm_rejection_ms=800,
    touch_inertia_enabled=True,
    touch_inertia_deceleration=4500.0,
)
```

These settings describe viewport input, not an editor brush. QPane normalizes
mouse, pen, and touch for viewer tools; an application such as CuteCanvas can
build editing policy on those public primitives without adding editor state to
the renderer.

See [Touch and Pen Input](touch-and-pen.md) for gesture arbitration and
hardware-test guidance.

## Background Execution

QPane keeps decoding, pyramid generation, tile sampling, and refinement away
from the GUI thread. A standalone widget creates a bounded execution runtime
with practical defaults. Applications that want a different standalone budget
can pass a typed policy when they construct the widget:

```python
from qpane import QPane
from qpane.sdk.execution import DefaultExecutionPolicy

viewer = QPane(
    execution_policy=DefaultExecutionPolicy(
        max_workers=4,
        max_accepted=256,
    )
)
```

Execution policy is a runtime concern, not persistent viewer configuration.
Several viewers can share one runtime, and a larger application can supply an
`ExecutionRuntime` backed by its own bounded scheduler. QPane then submits
directly to that backend without creating another pool or taking ownership of
host shutdown:

```python
from qpane import QPane
from qpane.sdk.execution import create_default_execution_runtime

runtime = create_default_execution_runtime()
first = QPane(execution_runtime=runtime)
second = QPane(execution_runtime=runtime)

# Close the host-owned runtime during application teardown.
runtime.shutdown(wait=False)
```

The public backend seam is documented in
[Advanced Renderer Integration](integration-sdk.md). Tune capacity only after
profiling. Synchronous decode or raster work in an interaction handler is an
ownership bug, not a reason to add threads.

## Diagnostics and Discovery

The diagnostics HUD is off by default. Enable it at construction time or
through `applySettings()`:

```python
config.configure(
    diagnostics_overlay_enabled=True,
    diagnostics_domains_enabled=("cache", "swap"),
)
```

Domains let a host opt into detail without flooding the ordinary summary. The
tile grid is controlled independently by `draw_tile_grid` and is best reserved
for renderer investigation.

At runtime, `diagnosticsDomains()` lists available domains,
`setDiagnosticsDomainEnabled()` changes one domain, and `gatherDiagnostics()`
returns detached records suitable for a host-owned status surface.

## Related Docs

* [Configuration Reference](configuration-reference.md): every field and
  shipped default.
* [Touch and Pen Input](touch-and-pen.md): direct navigation and normalized
  pointer input.
* [Diagnostics](diagnostics.md): observing render, cache, and execution behavior.
* [Catalog and Navigation](catalog-and-navigation.md): managing a review queue.

**Continue →** [Configuration Reference](configuration-reference.md)
