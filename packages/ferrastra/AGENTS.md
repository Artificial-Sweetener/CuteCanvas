# Ferrastra Package Guidance

The root `AGENTS.md`, `FERRASTRA_DESIGN.md`, and `ARCHITECTURE.md` apply. This file
adds Ferrastra-specific implementation rules.

## Product identity

Ferrastra is a CPU-first, Qt-neutral, document-neutral native graphics product
engine. It evaluates typed immutable products through spatially planned graphs
and owns transactional native source editing. It does not own authoring models,
tools, undo, viewport policy, Qt adaptation, or presentation.

## Boundaries

Only `crates/ferrastra-python` may depend on PyO3 or Python/NumPy binding crates.
Python code under this package exposes typed public contracts and adapts the
private native extension; it never imports QPane, CuteCanvas, or PySide6.

Introduce a Rust crate only with executable code for its declared owner. Follow
the crate dependency allowlist in `ARCHITECTURE_POLICY.toml`. Production Rust
modules declare `Responsibility:` and `Does not own:` in module documentation.
Unsafe Rust requires `SAFETY.md`, a precise waiver, focused tests, Miri where
applicable, and fuzz coverage at the boundary.

## Stage 0 boundary

Stage 0 exposes package identity so independent native wheel building,
installation, typing, and architecture enforcement are executable. It contains
no graphics kernel or placeholder engine API. Add product, graph, runtime,
store, raster, vector, or painting contracts only in their authorized phase.

## Verification

Run Rust formatting, Clippy, tests, architecture and ownership checks, strict
Pyright, the Ferrastra package tests, and an isolated wheel installation. The
installed wheel must import without Qt, QPane, or CuteCanvas present.
