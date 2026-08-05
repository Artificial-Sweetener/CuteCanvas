# Maintenance Tools

This directory contains scripts for local profiling plus enforcement of code
quality, architectural boundaries, and documentation consistency.

## Headless pan performance harness

`pan_performance_harness.py` forces Qt's `offscreen` platform before importing
PySide and drives a production QPane through real Qt mouse pan events without
opening a desktop window. It measures wall latency across input dispatch,
render planning, surface scrolling, edge repair, backing-buffer painting,
widget presentation, and the complete paint event. The measured pass performs
no frame capture or clean redraw.

After timing finishes, the harness replays the exact measured pan history
through selected checkpoints in `pan_render_harness.py`. Those differential
checks compare incremental pixels with clean redraws without contaminating the
performance samples.

Run the reported 4K/500% workload and save a baseline:

```powershell
.venv\Scripts\python tools\pan_performance_harness.py `
    --profile 4k-5x `
    --output pan-performance-artifacts\4k-baseline.json
```

Compare a later renderer change against that baseline:

```powershell
.venv\Scripts\python tools\pan_performance_harness.py `
    --profile 4k-5x `
    --compare pan-performance-artifacts\4k-baseline.json `
    --output pan-performance-artifacts\4k-after.json
```

The command exits with status 1 for a material baseline regression or a pixel
mismatch. JSON contains every raw frame, p90/p95/p99/max phase summaries,
repair-frame summaries, viewport and backing-buffer geometry, correctness
checkpoints, and artifact paths for failures.

The command rejects any Qt platform other than `offscreen`, keeping recursive
profiling fully headless and results comparable with baselines produced by the
same workload. Use `--no-correctness` only when repeatedly profiling a known
code path and run the default correctness replay before accepting an
optimization.

`cutecanvas_pan_performance_harness.py` drives the production CuteCanvas
document path with the same headless timing boundary. Its default workload is a
3840×2160 logical viewport at DPR 1.75 and 500% zoom. The immutable primary
metric is synchronous pointer dispatch through the presented paint event; the
acceptance target is p95 below 30 ms with no 100 ms frame.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "1.75"
$env:PYTHONPATH = "$PWD\packages\qpane\src;$PWD\packages\cutecanvas\src"
.venv\Scripts\python tools\cutecanvas_pan_performance_harness.py `
    --document C:\Users\imkno\test.cutecanvas `
    --output pan-performance-artifacts\cutecanvas-4k-5x.json
```

The document replay reports exact mismatch checkpoints separately while
accepting a maximum one-channel delta of one from Qt smooth-pixmap rounding.
Any larger difference fails, saves both frames, and exits with status 1. The
exact small-viewport pan oracle remains bit-for-bit and catches stale rows,
columns, wrapping faults, and alpha corruption.

## Record and replay real navigation

The demo can record the exact Qt event stream delivered while a person pans and
zooms. Launch it with an output trace and the composition being profiled:

```powershell
.venv\Scripts\python examples\cutecanvas_demo.py --skip-menu `
    --navigation-document C:\Users\imkno\test.cutecanvas `
    --navigation-trace-output pan-performance-artifacts\user-navigation.json
```

Press `F9`, reproduce the slow interaction, then press `F9` again. The trace
stores delivered mouse, wheel, and Space-key events with their real cadence,
logical viewport, DPR, display refresh rate, navigation settings, initial and
final zoom/pan, and the composition SHA-256.

Replay the trace through the production input and rendering path with offscreen
Qt:

```powershell
.venv\Scripts\python tools\cutecanvas_navigation_trace_harness.py `
    --trace pan-performance-artifacts\user-navigation.json `
    --correctness-steps 8 `
    --output pan-performance-artifacts\user-navigation-replay.json
```

Replay configures the recorded DPR before importing Qt, preserves recorded
event cadence by default, measures each input-to-present frame, verifies final
navigation-state drift, and checks completed pan releases against independently
composed reference frames at the full physical viewport resolution. Each
correctness checkpoint reconstructs its ring-buffer history independently,
replays the original time interval, and derives the expected current
presentation geometry from the retained buffer plan. Settled checkpoints allow
only Qt's one-channel rounding difference. Active checkpoints additionally
allow a bounded sparse population of filtered tile-edge pixels: no more than
0.1 percent may differ by more than eight channel values, and no more than 512
physical pixels or 0.01 percent of the physical viewport, whichever is larger,
may differ by more than 64. A displaced tile, stale strip, opaque background,
or settled mismatch exceeds those bounds and fails. Pass
`--correctness-event 359` to isolate one exact event or repeat that option for
several events. Pass `--no-cadence` only when intentionally stress-testing the
same event sequence at maximum delivery rate.

JSON reports all navigation timing under `summaries` and left-button
mouse-move timing under `pan_summaries`. The sub-30 ms target uses only those
pan frames, so wheel zoom and post-zoom redraws do not contaminate the pan
latency result.

The default raster tile size is automatic and resolves from physical viewport
size, including DPR. Pass `--tile-size 1536` to benchmark a strict host tile
size without changing the document configuration. The JSON workload records
the resolved size used by the renderer.

The same trace can be projected into a larger logical viewport and DPR. Replay
scales pointer coordinates and physical pan state so the captured gestures
retain their relative path:

```powershell
.venv\Scripts\python tools\cutecanvas_navigation_trace_harness.py `
    --trace pan-performance-artifacts\user-navigation.json `
    --logical-width 3840 --logical-height 2160 `
    --device-pixel-ratio 1.75 `
    --output pan-performance-artifacts\user-navigation-4k-dpr175.json
```

## 1. `check_consistency.py` (The "Trinity" Check)

This is the primary validation tool for all three published packages. It treats
the Ferrastra, QPane, and CuteCanvas root stubs plus QPane's typed integration
SDK as the authoritative public contracts, then verifies implementation,
documentation, examples, configuration defaults, and package boundaries
against them.

**Usage:**
```powershell
.venv\Scripts\python tools\check_consistency.py
```

**Checks Performed:**
- **Implementation Reality:** Verifies every exported root-facade and QPane SDK
  symbol against its typed contract, including public class members.
- **Demo Compliance:** Ensures each package's tutorial imports only its
  supported public facade and that both product demos are present.
- **Documentation Completeness:** Requires same-block API explanations and
  meaningful narrative guide coverage for every public symbol in each package.
- **Config Accuracy:** Compares each package's documented configuration mapping
  with the exact runtime defaults.
- **Package Boundaries:** Enforces `CuteCanvas -> QPane`, rejects the reverse
  dependency, and permits CuteCanvas to consume QPane only through `qpane` or
  the explicit `qpane.sdk` namespaces.

**Output:**
- `SUCCESS`: All checks passed.
- `FAILED`: Lists specific violations (e.g., "Demo uses hidden method", "Missing doc for symbol X").

## 2. `check_api_order.py`

Enforces the physical layout of the main `qpane.py` file to match the project's architectural guidelines.

**Usage:**
```bash
python tools/check_api_order.py
```

**Checks Performed:**
- **Public API Visibility:** Ensures all methods defined in `qpane.pyi` are physically located *above* the `# Internal Implementation` banner in `qpane.py`.
- **Internal Encapsulation:** Ensures all methods *not* in `qpane.pyi` are located *below* the banner.

**Output:**
- `SUCCESS`: File layout is correct.
- `[FAIL] API Organization Violation`: Lists methods that are in the wrong section (Hidden Public API or Leaking Internal API).

## 3. `check_docstrings.py`

A linter that enforces the project's documentation standards.

**Usage:**
```bash
python tools/check_docstrings.py
```

**Checks Performed:**
- Scans `qpane/` and `examples/` directories.
- Ensures every module, class, and function has a docstring.
- Skips property setters (assuming the getter is documented) and empty `__init__.py` files.

**Output:**
- `SUCCESS`: No missing docstrings found.
- `FAILED`: Lists files and line numbers where docstrings are missing, along with a summary of the guidelines.

## 4. `add_license_headers.py`

Automates copyright compliance for the project.

**Usage:**
```bash
python tools/add_license_headers.py
```

**Actions:**
- Scans all git-tracked `.py` and `.pyi` files.
- Adds the standard GPLv3-or-later license header if it is missing.
- Updates the header if an older version is detected.

**Output:**
- Prints the path of any file that was updated or added.

## 5. `fix_encoding.py`

Ensures cross-platform compatibility by enforcing UTF-8 encoding.

**Usage:**
```bash
python tools/fix_encoding.py
```

**Actions:**
- Attempts to read every tracked Python file as UTF-8.
- If reading fails, it tries fallback encodings (like `cp1252` or `latin1`).
- If a fallback succeeds, it re-saves the file as valid UTF-8.

**Output:**
- Reports files that were converted or files that could not be recovered.
