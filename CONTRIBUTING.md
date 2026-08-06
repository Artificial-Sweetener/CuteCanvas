# Contributing to Ferrastra, QPane, and CuteCanvas

This repository is a three-package monorepo:

- **Ferrastra** is the independently published, CPU-first, Qt-neutral native
  graphics product engine.

- **QPane** is the independently published PySide6 viewer, viewport, rendering
  engine, and declarative raster/vector SDK.
- **CuteCanvas** is the independently published document editor built on
  QPane.

Every contribution must preserve `CuteCanvas -> QPane`, `CuteCanvas -> Ferrastra`,
and `QPane -> Ferrastra`; reverse and lateral edges are forbidden. Read
`FERRASTRA_DESIGN.md`, the root `AGENTS.md`, and the nearest package
`AGENTS.md` before editing. Read `RCANDY_DESIGN.md` for graph, operation,
structured-authoring, language, or generated-effect work. Together these files
define the authoritative engineering and ownership rules.

## Development environment

The supported local command environment is Windows PowerShell. Create the
standard environment and install all three packages in editable mode with:

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

`requirements-dev.txt` installs Ferrastra, QPane, and CuteCanvas from their
independent package roots plus the shared Python, Rust, packaging, and policy
tooling. The pinned Rust toolchain is declared in `rust-toolchain.toml`.

## Product boundaries

### Ferrastra

Ferrastra owns typed native products, source stores, immutable evaluation graphs,
spatial demand and damage, bounded evaluation, numerical operations, native
edit sessions, R-Candy declarative authoring, and their correctness and
performance contracts. R-Candy lowers to the canonical graph and has no runtime,
host-policy, or document authority. Ferrastra imports no Qt, QPane, CuteCanvas,
application, document, viewport, tool, history, or presentation concepts. Only
`ferrastra-python` may use PyO3.

Stage 0 intentionally exposes package identity without graphics or language
behavior. It may contain non-production schemas and fixtures that prove planned
contracts, but no parser, placeholder graph API, mock production operation, or
empty language crate. Add a crate only with executable code for its declared
responsibility, and declare every operation contract before implementation.
Crate and adapter edges are enforced by `ARCHITECTURE_POLICY.toml`; numerical
migrations are activated in `FERRASTRA_OWNERSHIP.toml` when their canonical owner
moves to Ferrastra.

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
`packages/qpane/examples/qpane_demo.py`.

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
`packages/cutecanvas/examples/cutecanvas_demo.py`.

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

Rust modules begin with `Responsibility:` and `Does not own:` documentation.
Unsafe Rust is denied unless an explicit safety owner, focused proof, fuzz
coverage, `SAFETY.md`, and an active architecture waiver exist. Use the pinned
`rustfmt`, Clippy, and `cargo-deny` gates; global Rayon execution is forbidden
because callers own execution and memory budgets.

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
.venv\Scripts\python packages\ferrastra\examples\ferrastra_demo.py
.venv\Scripts\python packages\qpane\examples\qpane_demo.py
.venv\Scripts\python packages\cutecanvas\examples\cutecanvas_demo.py
```

## Verification

End each work turn with the smallest focused tests and checks that directly cover
the changed behavior, policy, or artifact. Use mounted Qt tests and the abuse
harness for lifecycle, input, repaint, undo/redo, cache, concurrency, and
performance-sensitive work. The shared timing helper uses wall time in isolation
and contention-safe timing under xdist; do not weaken a budget to hide a
regression.

Run `.venv\Scripts\python tools\test.py changed` for the policy-required focused
proof. Use `.venv\Scripts\python tools\test.py list` to discover product, behavior
area, and proof-kind targets, or `tools\test.py explain <path>` to inspect why a
path selects its groups. Product tests live under their owning package as
`tests/<behavioral-area>/<proof-kind>/test_*.py`; repository-policy tests live
beside the tools they protect.

Complete suites are commit gates rather than turn-completion gates. Select the
gate from the staged diff:

```powershell
.venv\Scripts\python tools\test.py staged --commit
```

- Production/runtime Python changes or Python test changes run the complete
  Python gate and suite.
- Rust production changes or Rust test changes run the complete Rust gate and
  workspace suite.
- Changes spanning both runtimes run both gates.
- Documentation-only `docs` commits and other staged diffs that change neither
  production/runtime source nor tests run only focused validation for the changed
  artifacts.
- Packaging, dependencies, native bindings, hooks, CI, and build configuration
  run their dedicated validation even when a complete runtime suite is not
  required.

The complete Python and Rust gates inside `.venv` are:

```powershell
.venv\Scripts\python -m ruff check --fix .
.venv\Scripts\python -m black .
.venv\Scripts\python tools\fix_encoding.py
.venv\Scripts\python tools\check_docstrings.py
.venv\Scripts\python tools\check_api_order.py
.venv\Scripts\python tools\check_consistency.py
.venv\Scripts\python tools\check_architecture.py
.venv\Scripts\python tools\check_ferrastra_operations.py
.venv\Scripts\python tools\check_ferrastra_ownership.py
.venv\Scripts\python tools\check_ferrastra_benchmarks.py
.venv\Scripts\python tools\add_license_headers.py
.venv\Scripts\python -m ruff check --config ruff-ferrastra.toml .
.venv\Scripts\python -m pyright -p pyright-ferrastraconfig.json
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-features
cargo deny check
.venv\Scripts\python -m pytest -n auto
git diff --check
```

When Ferrastra packaging or its public boundary changes, run
`.venv\Scripts\python tools\verify_ferrastra_wheel.py`. When QPane or CuteCanvas
packaging changes, run `.venv\Scripts\python tools\verify_python_wheels.py`.
The verifier installs QPane without CuteCanvas, then installs CuteCanvas against
the exact QPane wheel and version range declared in its metadata.

## Commits and releases

Commit only when requested. Each commit delivers one coherent user- or
integrator-meaningful outcome. Subjects feed generated changelogs and follow
Conventional Commits:

```text
type(scope)!: subject
```

Use a changelog-ready outcome rather than implementation mechanics in the
subject. Use `!` when the public change is breaking and explain compatibility
impact and migration in the body. Keep supporting tests, documentation, cleanup,
and refactoring with the outcome they support; do not create WIP, checkpoint,
miscellaneous, or file-movement diary commits.

All packages are released independently:

- `ferrastra-vX.Y.Z` builds and publishes Ferrastra;
- `qpane-vX.Y.Z` builds and publishes QPane;
- `cutecanvas-vX.Y.Z` builds and publishes CuteCanvas.

Do not combine package contents, versions, extras, or release tags.
