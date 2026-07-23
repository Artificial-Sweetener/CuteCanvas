# Monorepo Engineering Standards

This repository contains the independently published QPane and CuteCanvas
packages. Every contribution must prioritize stability, consistency,
performance, and polish.

Read `CONTRIBUTING.md` before editing. The nearest package `AGENTS.md` adds
product-specific ownership and verification rules without replacing this file.

## Production quality

- Stability is more important than velocity. Bugs, stale frames, flicker,
  surprising behavior, excessive allocation, and unexplained latency are
  failures.
- Never commit temporary `TODO`s, debug output, commented-out code, knowingly
  incomplete migrations, or compatibility scaffolding.
- Fail gracefully at the appropriate boundary. User actions, invalid external
  data, rejected work, teardown, and stale asynchronous results must not crash
  a Qt application.
- Preserve interactive responsiveness and bounded memory. Heavy work never
  blocks the GUI thread.

## Package dependency direction

The only allowed product dependency is:

```text
CuteCanvas -> QPane
QPane      x  CuteCanvas
```

QPane must never import CuteCanvas. CuteCanvas may use only QPane's supported
public facade and rendering SDK, never private QPane modules or attributes.
Cross-package changes are normal when the authoritative owner is in QPane, but
they must preserve this dependency direction.

Shared concepts have one representation and one behavior owner. Do not create
parallel scene, vector, transform, cache, damage, scheduling, input, or render
systems in CuteCanvas to work around a QPane limitation.

The current package split intentionally permits breaking the old combined
QPane editor API. Remove replaced APIs completely. Do not add deprecation
adapters, forwarding namespaces, aliases, or a QPane dependency on CuteCanvas.

## Ownership and separation of concerns

Before extending a module, class, subsystem, or workflow, identify:

- the concern and authoritative state owner;
- the dependency direction;
- the public/private boundary;
- the behavior and performance contracts; and
- whether the change introduces a distinct responsibility or change cadence.

Place code by ownership, not proximity or minimal diff size. A stateful owner
owns the behavior that mutates, validates, interprets, or coordinates its
state. Collaborators communicate through explicit public methods, protocols,
or injected dependencies and never reach into private collaborator state.

Do not create or enlarge large mixed-responsibility files. When a blast-area
owner is already mixed, characterize relevant behavior, extract the concern
completely, update every caller, delete replaced code, and update the nearest
ownership map. Never defer directly related ownership cleanup.

DRY primarily means single ownership. Consumers may observe, delegate, adapt,
or cache derived results, but must not reproduce another component's state,
geometry, lifecycle, history, permissions, invalidation, cache, scheduling, or
rendering rules.

## Structural changes

Behavior-critical structural work follows this order:

1. Add or identify characterization and regression protection.
2. Establish the new authoritative boundary.
3. Migrate every caller as a complete vertical slice.
4. Remove replaced types, files, code paths, and tests.
5. Run focused behavior, abuse, and performance gates.

Internal compatibility is not required. Prefer clean replacement over shims,
and leave the code looking as if the resulting architecture were original.

## Typing, documentation, and code style

- Type hints and docstrings are mandatory for every new or changed module,
  class, function, method, property, and public value.
- Public docstrings use concise Google-style sections when arguments, returns,
  exceptions, or side effects are non-obvious. Internal docstrings state the
  concern directly.
- Use expressive, precise names. Comments explain only genuinely non-obvious
  constraints; code and extracted methods explain behavior.
- Public QWidget methods and Qt signals use `camelCase`. Internal methods and
  non-widget domain APIs use `snake_case`. Enum classes use `PascalCase` and
  members use `UPPER_CASE`.
- Keep module order predictable: docstring, imports, logger, public values,
  primary implementations, then private details.
- Use `(str, Enum)` rather than `StrEnum` for Python 3.10 support.

## Public API Trinity

Each published package has one authoritative typed contract. A public change
updates all four pillars in the same work:

1. typed contract/stub and exports;
2. implementation;
3. API reference and narrative documentation; and
4. that package's single polished public-only demo.

Examples must never use private internals. Documentation describes the product
as it exists after the change, not removed architecture or migration history.

## Tests, abuse, and performance

Add or update tests with every behavioral or structural change. Mount real Qt
widgets where lifecycle, input, repaint, timing, or user workflow matters.
Use the established abuse harness for rapid switching, cancellation, stale
work, input storms, teardown, cache pressure, undo/redo, and redraw equality.

Use the centralized timing utility. Isolated tests measure wall latency; xdist
tests use its contention-safe timing policy. Do not weaken a budget to make a
regression pass. Profile first, then fix the authoritative owner.

Run focused tests after each major slice. Before reporting completion, run the
root hook-equivalent checks and complete parallel suite in `.venv`:

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

Build both wheels and validate them in isolated environments when packaging,
dependencies, exports, or public boundaries change.

## Git and workspace care

- Preserve unrelated worktree changes and never use destructive reset or
  checkout commands.
- Use `apply_patch` for source and documentation edits.
- Commit only when explicitly asked.
- Commits use `type(scope): subject`; append `!` for a public breaking change.
- Complete the same checks as the commit hooks before reporting success.
