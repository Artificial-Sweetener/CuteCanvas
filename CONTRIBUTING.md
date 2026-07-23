# Contributing to QPane and CuteCanvas

This repository is a two-package monorepo:

- **QPane** is the independently published PySide6 viewer, viewport, rendering
  engine, and declarative raster/vector SDK.
- **CuteCanvas** is the independently published document editor built on
  QPane.

Every contribution must preserve the one-way dependency
`CuteCanvas -> QPane`. Read the root `AGENTS.md` and the nearest package
`AGENTS.md` before editing; together they define the authoritative engineering
and ownership rules.

## Development environment

The supported local command environment is Windows PowerShell. Create the
standard environment and install both packages in editable mode with:

```powershell
python tools\setup_dev.py
.venv\Scripts\Activate.ps1
```

The equivalent manual setup is:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools\setup_hooks.py
```

`requirements-dev.txt` installs QPane and CuteCanvas from their independent
package roots plus the shared repository tooling. Product-specific optional
dependencies remain declared by the package that owns them.

## Product boundaries

### QPane

QPane owns immutable render scenes and layers, source identity and revisions,
raster/vector providers, semantic vector values, viewport transforms,
navigation input, hit testing, clipping, compositing, damage, pyramids, tiles,
refinement, cache coordination, render concurrency, and catalog-oriented viewer
conveniences.

QPane must remain useful without CuteCanvas. It never imports editor concepts
or CuteCanvas, and its renderer must not gain mask-, selection-, tool-, or
document-specific paths. Generic renderer performance work belongs in QPane so
every consumer benefits.

The supported public surface is defined by
`packages/qpane/src/qpane/qpane.pyi`. Its documentation is under
`packages/qpane/docs`, and its single public example is
`examples/qpane_demo.py`.

### CuteCanvas

CuteCanvas owns documents, editable layer stacks, policy and locks, history,
selections, editable raster and coverage storage, masks, painting, placed
assets, vector authoring, tools and overlays, move/transform workflows,
persistence, and SAM.

CuteCanvas consumes QPane's supported public SDK. It must not reproduce QPane's
scene, vector-value, transform, cache, damage, input, scheduling, or rendering
systems. If profiling identifies a source-neutral renderer limitation, improve
QPane in the same change and validate both packages.

The supported public surface is defined by
`packages/cutecanvas/src/cutecanvas/cutecanvas.pyi`. Its documentation is under
`packages/cutecanvas/docs`, and its single public example is
`examples/cutecanvas_demo.py`.

## Architecture and implementation

Before editing, identify the authoritative owner, dependency direction, state
lifetime, public boundary, and performance contract. Add characterization tests
before behavior-critical structural work.

Keep state and the behavior that mutates or interprets it together. Use explicit
typed methods and injected collaborators across boundaries. Do not reach into
private collaborator state, duplicate responsibility, add internal compatibility
shims, or enlarge mixed-responsibility files. Complete structural migrations:
update every caller, remove replaced code, and update the relevant ownership
guide.

All new or changed Python code requires accurate type annotations and
docstrings. Public QWidget methods and signals use Qt-style `camelCase`;
internal APIs use `snake_case`; enum classes use `PascalCase` with
`UPPER_CASE` members. Use `(str, Enum)` for Python 3.10 compatibility.

Heavy work never blocks the GUI thread. Caches are explicit and byte-bounded.
Interactive changes must account for input storms, stale asynchronous results,
teardown, redraw correctness, large images, and undo/redo chronology.

## Public API Trinity

A public change updates all four pillars for the affected package in the same
work:

1. stub and exports;
2. implementation;
3. API reference and narrative documentation; and
4. the package's one polished public-only demo.

Examples use only supported public APIs. Documentation describes the resulting
product directly and does not preserve removed architecture as an alternative.

Run the examples from the repository root:

```powershell
.venv\Scripts\python examples\qpane_demo.py
.venv\Scripts\python examples\cutecanvas_demo.py
```

## Verification

Run focused tests after each meaningful slice. Use mounted Qt tests and the
established abuse harness for lifecycle, input, repaint, undo/redo, cache,
concurrency, and performance-sensitive work. The harness's shared timing helper
uses wall time in isolation and contention-safe timing under xdist; do not
weaken a budget to hide a regression.

Before reporting completion, run the hook-equivalent checks and complete suite
inside `.venv`:

```powershell
.venv\Scripts\python -m ruff check --fix .
.venv\Scripts\python -m black .
.venv\Scripts\python tools\fix_encoding.py
.venv\Scripts\python tools\check_docstrings.py
.venv\Scripts\python tools\check_api_order.py
.venv\Scripts\python tools\check_consistency.py
.venv\Scripts\python tools\add_license_headers.py
.venv\Scripts\python -m pytest -n auto
git diff --check
```

When packaging or public boundaries change, also build both distributions and
verify them from isolated installs. QPane must install and run without
CuteCanvas; CuteCanvas must run against the QPane version range declared in its
metadata.

## Commits and releases

Commit only when requested. Commit subjects follow Conventional Commits:

```text
type(scope)!: subject
```

Use `!` when the public change is breaking. QPane and CuteCanvas are released
independently:

- `qpane-vX.Y.Z` builds and publishes QPane;
- `cutecanvas-vX.Y.Z` builds and publishes CuteCanvas.

Do not combine package contents, versions, extras, or release tags.
