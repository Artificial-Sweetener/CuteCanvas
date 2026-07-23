**← Previous:** [Touch and Pen Input](touch-and-pen.md)

# Diagnostics and Debugging

## See the Renderer at Work

QPane performs visible tile rendering, pyramid generation, cache coordination,
prefetch, retry, and viewport refinement in the background. The diagnostics HUD
makes that work observable when you are tuning a deployment, investigating
stutter, or validating a custom source.

Diagnostics are ordinary supported product behavior, not a stripped-down debug
print. Hosts can use the built-in overlay, request detached records for their
own UI, and add focused providers without reaching into renderer internals.

## Quick Start

```python
viewer.setDiagnosticsOverlayEnabled(True)
print(viewer.diagnosticsOverlayEnabled())
```

The toggle works before the window is shown. `diagnosticsOverlayToggled` emits
the resulting `bool`, so a menu action remains synchronized when another part
of the host changes it.

> **Heads-up:** The HUD intentionally draws over content. It is excellent for
> development and support sessions, but most end-user workflows should leave it
> hidden until requested.

## The Summary

Available base rows describe the current frame rather than promising a fixed
list. Typical values include:

* paint and presentation latency;
* zoom, device-pixel ratio, and smooth-zoom scheduling;
* total coordinated cache use and budget;
* navigation/swap latency;
* active raster or sampled-vector resolution; and
* worker and refinement state relevant to the visible frame.

Rows appear only when their owner has meaningful data. This keeps an ordinary
single-image viewer concise while a large raster/vector scene can expose the
extra work it is actually doing.

## Drill Down by Domain

`diagnosticsDomains()` returns the domains available in the mounted viewer.
Use the `DiagnosticsDomain` enum when the host wants typed built-in names:

```python
from qpane import DiagnosticsDomain

if DiagnosticsDomain.CACHE.value in viewer.diagnosticsDomains():
    viewer.setDiagnosticsDomainEnabled(DiagnosticsDomain.CACHE, True)
```

`diagnosticsDomainEnabled()` checks one domain. Unknown or unavailable names
raise `ValueError`, catching stale developer-menu wiring instead of creating a
checkbox that controls nothing.

### Cache

The `cache` domain expands the total into tile, pyramid, extension, retained,
and eviction information. Watch whether settled products approach the budget
and whether useful products churn during ordinary navigation. Persistent churn
usually calls for a larger budget, different weights, or less speculative
prefetch—not an unbounded cache.

### Swap

The `swap` domain shows catalog navigation, neighboring prefetch, and renderer
handoff information. A high swap latency with idle workers points toward source
decode or storage; a deep speculative queue suggests prefetch is too generous
for the workload.

### Render

The `render` domain exposes visible planning, damage, tile completion, and
refinement. Use it when investigating incomplete frames, unnecessary redraw,
or a custom provider that appears to invalidate too broadly.

### Executor

The `executor` domain shows worker use, pending work, category distribution,
and rejection/backpressure. Visible tiles should outrank pyramids and
speculative work. A growing queue is evidence to profile; it is not by itself a
reason to raise `max_workers`.

### Retry

The `retry` domain identifies transient failures and bounded retry state for
resources such as file-backed tiles. Repeated growth normally indicates an I/O
or provider problem that the host should surface rather than hide.

## Gather Records Programmatically

`gatherDiagnostics()` returns a detached `DiagnosticsSnapshot` containing
`DiagnosticRecord` rows. This is the right boundary for a status panel, support
bundle, or test assertion:

```python
snapshot = viewer.gatherDiagnostics()
for record in snapshot.records:
    print(record.formatted())
```

`diagnostics()` returns the live `Diagnostics` broker for advanced integration.
Prefer snapshots for ordinary display so host widgets do not accidentally hold
provider or renderer lifetimes.

`createStatusOverlay(parent=...)` creates QPane's compact host-placeable HUD.
Use it when the application wants the standard diagnostic presentation in a
dock or status area rather than over the image.

## Add a Host Provider

Register source-neutral application data with
`registerDiagnosticsProvider()`. A provider returns `DiagnosticRecord` values
and may belong to a named detail domain:

```python
from qpane import DiagnosticRecord


def application_records(_pane):
    return (DiagnosticRecord("Review queue", "12 remaining"),)


viewer.registerDiagnosticsProvider(
    application_records,
    domain="host",
    detail=True,
)
```

Providers must be fast, side-effect free, and safe to call during HUD refresh.
Do not perform file I/O, wait for workers, or scan a document in a diagnostics
callback. Maintain the expensive state at its real owner and expose a cheap
snapshot here.

## Stay in Sync

`diagnosticsDomainToggled` emits `(domain, enabled)` after a successful change:

```python
def on_domain_toggled(domain, enabled):
    print(f"{domain}: {'on' if enabled else 'off'}")


viewer.diagnosticsDomainToggled.connect(on_domain_toggled)
```

Configuration supplies startup state through
`diagnostics_overlay_enabled`, `diagnostics_domains_enabled`, and
`draw_tile_grid`. Runtime facade calls are better for a developer menu because
they do not reapply unrelated settings.

## Diagnosing Performance Responsibly

Use diagnostics to form a hypothesis, then profile the authoritative owner.
QPane's abuse tests distinguish isolated wall latency from contention-safe
thread CPU time under xdist. A performance budget should measure QPane's work,
not another worker's scheduling delay, and must never be weakened merely to
turn a regression green.

For visual failures, compare settled frames after all required products publish
and also inspect the interactive sequence. A correct final image does not excuse
flicker, stale strips, incomplete vector tiles, or GUI-thread stalls on the way
there.

## Related Docs

* [Configuration](configuration.md): cache, concurrency, and startup diagnostic
  policy.
* [Rendering SDK](rendering-sdk.md): provider revisions, damage, and product
  behavior.
* [Extensibility](extensibility.md): custom diagnostics, overlays, tools, and
  effects.

**Continue →** [Extensibility](extensibility.md)
