# Diagnostics

CuteCanvas includes QPane's live rendering diagnostics and adds editor records
for painting, masks, background work, and optional model activity. The overlay
is useful while tuning a host application or investigating an interaction that
does not stay within its latency budget.

## Show the Overlay

```python
canvas.setDiagnosticsOverlayEnabled(True)
```

`diagnosticsOverlayEnabled()` reports the current state. Connect
`diagnosticsOverlayToggled` when a menu action or settings page needs to follow
changes made elsewhere.

The base rows report paint time, zoom, smooth-zoom cadence, cache use, content
swap latency, and the active pyramid level. Feature rows appear only when their
owner is active.

## Choose Diagnostic Domains

Domains add detail without filling the canvas with unrelated records:

```python
from cutecanvas import DiagnosticsDomain

canvas.setDiagnosticsDomainEnabled(DiagnosticsDomain.CACHE, True)
canvas.setDiagnosticsDomainEnabled(DiagnosticsDomain.EXECUTOR, True)
canvas.setDiagnosticsDomainEnabled(DiagnosticsDomain.MASK, True)
```

The available domains are:

* `CACHE` for retained raster products and memory pressure.
* `SWAP` for navigation, prefetch, and renderer queue activity.
* `EXECUTOR` for accepted, running, pending, retained, rejected, and completed
  execution work.
* `RETRY` for resource retry activity.
* `MASK` for mask strokes, autosave, and mask jobs.
* `SAM` for predictor state, embedding cache use, and model workers.

Use `diagnosticsDomains()` to discover the domains in the running build and
`diagnosticsDomainEnabled()` to inspect one. Unknown or unavailable domains are
rejected rather than silently ignored.

`diagnosticsDomainToggled` emits the canonical domain string and its new state:

```python
def update_diagnostics_action(domain: str, enabled: bool) -> None:
    actions_by_domain[domain].setChecked(enabled)


canvas.diagnosticsDomainToggled.connect(update_diagnostics_action)
```

## Read the Useful Signals

When an operation feels slow, start with the smallest relevant view:

* Paint time and pyramid level show whether the visible frame is expensive.
* Cache totals and domain rows show whether useful render products are being
  retained.
* Swap and prefetch rows show whether navigation waits for source work.
* Executor rows show aggregate queue depth, retained bytes, rejection, and
  cancellation.
* Mask rows separate stroke rendering, commit work, and autosave activity.
* Model rows distinguish predictor setup from inference and embedding reuse.

The values are observations, not controls. Change cache or feature settings,
or adjust the host-owned execution policy, reproduce the same workflow, and
compare the records again.

## Add Host Records

Diagnostics providers return `DiagnosticRecord` values. Register a provider
when host-owned work needs to appear beside the renderer and editor records.
Keep the provider quick: it runs while the overlay snapshot is prepared.

See [QPane Diagnostics](../../qpane/docs/diagnostics.md) for the provider API
and overlay lifecycle shared by both packages.

## Related Docs

* [Configuration](configuration.md): Enable the overlay and seed domains.
* [Masks and SAM](masks-and-sam.md): Configure mask and model work.
* [QPane Diagnostics](../../qpane/docs/diagnostics.md): Renderer records and
  custom providers.

**Continue →** [Extensibility](extensibility.md)
