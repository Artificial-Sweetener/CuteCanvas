# Ferrastra architecture and enforcement

`FERRASTRA_DESIGN.md` is the implementation charter. This document is the compact
owner and tool map used during daily development. `ARCHITECTURE_POLICY.toml` is
the machine-readable dependency and structural policy.

## Permanent product ownership

```text
CuteCanvas authors documents, resources, tools, policy, and history
          │                         │
          ├──────────────► QPane presents viewport and Qt products
          │                         │
          └──────────────► Ferrastra computes typed native products
                                    ▲
QPane compiles generic demand ──────┘
```

Ferrastra never imports or links Qt, QPane, CuteCanvas, or application types.
QPane and CuteCanvas enter Ferrastra through `qpane.ferrastra` and
`cutecanvas.ferrastra`. Applications may depend on all three products.

## Crate owners and allowed internal dependencies

| Crate | Sole owner | Allowed Ferrastra dependencies |
|---|---|---|
| `ferrastra-core` | Stable value and operation contracts | None |
| `ferrastra-store` | Immutable products, stores, revisions, leases | `ferrastra-core` |
| `ferrastra-graph` | Typed graph structure and compilation | `ferrastra-core` |
| `ferrastra-runtime` | Demand, damage, scheduling, caches, traces | `ferrastra-core`, `ferrastra-store`, `ferrastra-graph` |
| `ferrastra-raster` | Canonical raster and coverage operations | `ferrastra-core`, optionally `ferrastra-store` |
| `ferrastra-vector` | Framework-neutral vector computation | `ferrastra-core`, `ferrastra-store` |
| `ferrastra-paint` | Transactional native editing execution | `ferrastra-core`, `ferrastra-store`, `ferrastra-raster` |
| `ferrastra-engine` | First-party assembly and stable Rust facade | Implemented Ferrastra crates |
| `ferrastra-python` | Python buffers, exceptions, schemas, opaque handles | `ferrastra-engine` and minimum supporting crates |

Only `ferrastra-python` may depend on PyO3 or Python/NumPy binding crates. A crate
is added to the workspace when executable code for its owner begins. Stage 0
therefore contains `ferrastra-python`, which executes the independent native wheel
boundary, and no empty engine crates.

## Source responsibility

Every production Rust module starts with:

```rust
//! Responsibility: State the one concern owned by this module.
//!
//! Does not own: Name adjacent concerns that remain elsewhere.
```

New QPane and CuteCanvas adapter modules state their concern in the module
docstring. The structural soft ceiling is 350 nonblank, noncomment lines and
the hard gate is 500. Files over the hard gate require an active entry in
`ARCHITECTURE_WAIVERS.toml`; a waiver cannot excuse mixed responsibility.

Production paths named `utils`, `helpers`, `common`, `misc`, `shared`,
`manager`, or `service` are rejected in protected Ferrastra and adapter roots.
Names identify the owned concern directly.

## Waivers

A waiver identifies one rule, one path glob, an owner, a concrete reason, a
tracking issue, and an ISO expiry date. Expired and unused waivers fail the
architecture check. Broad directory exclusions and unexplained suppressions
are not waivers.

## Migration ownership

`FERRASTRA_OWNERSHIP.toml` records planned numerical migrations. A migration marked
`migrated` activates every forbidden legacy pattern in its entry. Presentation
exceptions are exact paths with reasons, not general fallback permission. A
migration is incomplete until the old canonical implementation is deleted and
the ownership check prevents its return.

## Required local gates

```powershell
.venv\Scripts\python tools\check_ferrastra_architecture.py
.venv\Scripts\python tools\check_ferrastra_ownership.py
.venv\Scripts\python -m pyright
.venv\Scripts\python -m ruff check --config ruff-ferrastra.toml
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo deny check
```

Wheel verification builds `packages/ferrastra` with maturin, installs the artifact
into a clean environment, and imports it without Qt, QPane, CuteCanvas, or the
monorepo source tree available.

## Operation entry gate

Before an operation module is accepted it defines semantic ID and version,
input and output products, backward demand, forward damage, numerical and alpha
semantics, edge behavior, quality tiers, product-key inputs, retained and
scratch memory, cancellation, parallelism, an independent oracle, tile
equivalence, performance budgets, and the implementation it replaces.

Ferrastra is a CPU-first, typed, spatial, revision-aware graphics product engine.
It evaluates immutable raster, coverage, vector, mixed graphic, and analysis
products through a demand-driven DAG. Exact results are immutable, cacheable,
tile-equivalent, atomically published, explainable, and reproducible under
their documented contract.
