# Mounted QPane abuse harness

This harness mounts the production `QPane` widget on Qt's offscreen platform and
drives its normal event handlers. It is intended for sustained assistant-led
investigation of painting, input arbitration, rendering, cache, history, and
lifecycle faults. It does not replace focused unit tests or physical-device
testing.

The harness uses genuine Qt mouse and touch frames plus pressure-bearing tablet
events. Its independent visual oracle samples expected stroke geometry without
calling QPane's mask rasterizer. Every action observes the composited pixels from
`QWidget.grab()`, so a correct backing mask that disappears from the mounted
scene is still a failure.

## Running campaigns

Run the bounded cross-device profile used by GitHub Actions:

```powershell
.venv\Scripts\python -m tests.harness --profile ci
```

Run a longer local campaign over 4096-pixel images and ten deterministic seeds:

```powershell
.venv\Scripts\python -m tests.harness --profile soak
```

Campaign bounds can be overridden while retaining deterministic generation:

```powershell
.venv\Scripts\python -m tests.harness --profile soak --seed 200 --seeds 25 --random-strokes 60 --image-size 4096
```

The command returns a nonzero exit code on the first invariant violation and
prints machine-readable JSON. The default artifact directory is
`qpane-abuse-artifacts/`.

## Replaying and reducing failures

Every failure writes the before, current, and difference frames alongside its
report and exact JSON trace. Release-continuity failures also preserve every
distinct frame from pointer-up through render idle. Replay that sequence without
regenerating it:

```powershell
.venv\Scripts\python -m tests.harness --replay qpane-abuse-artifacts\seed-200\trace.json --image-size 4096
```

Delta reduction repeatedly mounts fresh QPane instances and removes actions only
when the same failure phase and message remain reproducible:

```powershell
.venv\Scripts\python -m tests.harness --replay qpane-abuse-artifacts\seed-200\trace.json --image-size 4096 --minimize
```

The reduced sequence is written as `minimized-trace.json` beside the seed's
artifacts.

`PointerTransitionProbe` delivers explicit Qt events through the normal
`QApplication`/`QWidget` path and records their order, receiver, source,
pointing-device type, acceptance, controller modality, touch claim, direct-input
cursor suppression, cursor shape, cursor pixmap size, and hotspot. It is intended
for focused transition traces that complement the longer visual campaigns.

## Current invariants

The deterministic trace and seeded extensions verify:

- live mask feedback at contact and throughout fast, slow, sparse, and
  intersecting strokes;
- preservation of earlier segments while a stroke remains in motion and after
  asynchronous work settles;
- mouse, direct touch, and pressure-bearing pen paths;
- all nine ordered mouse/touch/pen transitions through two-level undo, redo,
  intersecting strokes, and redo-history branching;
- repeated same-position touch-to-mouse cursor handoffs on 2048- and
  4096-pixel images, including stale touchscreen metadata, centered cursor
  hotspots, active-mask switches, and independent histories;
- immediate brush-cursor restoration on every touch release or cancellation,
  before any mouse, focus, enter, or window-lifecycle event can mask a failure;
- mouse ownership across unsynthesized, system-, Qt-, and
  application-synthesized event sources while rejecting touchscreen- and
  stylus-tagged promoted duplicates;
- frame-by-frame visual continuity from the first pointer-up frame until every
  mask worker and prefetch reports idle;
- fully overlapping no-op strokes without render-revision churn, release flash,
  or empty undo entries;
- palm rejection without a mask or history mutation;
- visible non-mutating pen hover previews and real proximity-leave cleanup;
- second-finger rollback, pan, pinch, and unchanged mask history;
- high-contrast mouse cursor restoration after direct input across Qt-, system-,
  and application-synthesized event sources;
- independent undo/redo removal, restoration, and branching expectations;
- semantic pixel stability during waits and exact stability during settled idle
  windows; and
- clean image removal while mask workers are active.

## Responding to a failure

Treat a harness failure as evidence to reduce and explain, not as a request for a
local exception. Reproduce the trace, minimize it, identify the authoritative
owner of the violated state or lifecycle, and add both an owner-level regression
and a mounted reproducer. Repair the ownership boundary or source algorithm, then
rerun the reduced trace, nearby seeds, the soak profile, and the full project
checks.

Appropriate fixes do not inflate deadlines, weaken the visual oracle, duplicate
production state in a consumer, add test-only production hooks, special-case a
device sequence, or preserve an internal compatibility shim. If the failure is a
harness modeling error, encode the real platform policy explicitly and add the
complementary negative case.

Synthetic input cannot reproduce driver firmware, digitizer sampling, operating
system edge gestures, or physical hover latency. Release validation still
includes exploratory testing on representative hardware.
