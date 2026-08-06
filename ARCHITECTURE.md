# Repository architecture and enforcement

`FERRASTRA_DESIGN.md` is the engine implementation charter and
`RCANDY_DESIGN.md` is the declarative-authoring charter. This document is the
compact owner and tool map used during daily development.
`ARCHITECTURE_POLICY.toml` is the machine-readable dependency and structural
policy.

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

R-Candy is a Ferrastra authoring frontend, not a fourth product. It lowers
source to canonical `GraphDefinition` values and has no runtime, document, host,
or presentation authority. CuteCanvas may use `ferrastra.rcandy`; QPane remains
syntax-neutral.

## Crate owners and allowed internal dependencies

| Crate | Sole owner | Allowed Ferrastra dependencies |
|---|---|---|
| `ferrastra-core` | Stable value and operation contracts | None |
| `ferrastra-store` | Immutable products, stores, revisions, leases | `ferrastra-core` |
| `ferrastra-graph` | Typed graph structure and compilation | `ferrastra-core` |
| `ferrastra-rcandy` | Syntax, resolution, typing, lowering, source maps, formatting | `ferrastra-core`, `ferrastra-graph` |
| `ferrastra-runtime` | Demand, damage, scheduling, caches, traces | `ferrastra-core`, `ferrastra-store`, `ferrastra-graph` |
| `ferrastra-raster` | Canonical raster and coverage operations | `ferrastra-core`, optionally `ferrastra-store` |
| `ferrastra-vector` | Framework-neutral vector computation | `ferrastra-core`, `ferrastra-store` |
| `ferrastra-paint` | Transactional native editing execution | `ferrastra-core`, `ferrastra-store`, `ferrastra-raster` |
| `ferrastra-engine` | First-party assembly and stable Rust facade | Implemented computation, store, graph, runtime, and operation crates |
| `ferrastra-python` | Python buffers, exceptions, schemas, opaque handles, R-Candy binding | `ferrastra-engine`, minimum supporting crates, optionally `ferrastra-rcandy` |

Only `ferrastra-python` may depend on PyO3 or Python/NumPy binding crates. A crate
is added to the workspace when executable code for its owner begins. Stage 0
therefore contains `ferrastra-python`, which executes the independent native wheel
boundary, and no empty engine or language crates. Computation, graph, engine,
and runtime crates never depend on `ferrastra-rcandy`; serialized graphs execute
without it.

## Source responsibility

Every production Rust module starts with:

```rust
//! Responsibility: State the one concern owned by this module.
//!
//! Does not own: Name adjacent concerns that remain elsewhere.
```

New QPane and CuteCanvas adapter modules state their concern in the module
docstring. The structural soft ceiling is 350 nonblank, noncomment lines and
the hard gate is 500 for every product implementation module. Exact typed
contracts or generated artifacts use an explicit reviewed policy category when
the implementation-module metric is inapplicable.

Production paths named `utils`, `helpers`, `common`, `misc`, `shared`,
`manager`, or `service` are rejected in protected Ferrastra and adapter roots.
Names identify the owned concern directly.

## Architecture state

Each product owns `ARCHITECTURE_DEBT.toml` and `ARCHITECTURE_WAIVERS.toml` in
its package root. These files are current snapshots rather than review logs;
Git supplies their history.

Debt records identify exact mixed source paths, their assessed fingerprint,
current responsibilities, and the next ownership extraction. A staged change
to known debt must reconcile that snapshot. Resolution deletes the debt record
and every linked remediation waiver.

Waivers identify one exact path and rule, owner, current justification, chore
reference, review date, and line cap. A structural waiver covers a genuinely cohesive exception.
A remediation waiver links to same-product debt, states a tighter next limit,
and exists only while that mixed file exceeds the hard gate. Expired, unused,
unbounded, misowned, globbed, stale, or incorrectly linked records fail. A
waiver never authorizes mixed ownership or behavior added to mixed code.

## Migration ownership

`FERRASTRA_OWNERSHIP.toml` records planned numerical migrations. A migration marked
`migrated` activates every forbidden legacy pattern in its entry. Presentation
exceptions are exact paths with reasons, not general fallback permission. A
migration is incomplete until the old canonical implementation is deleted and
the ownership check prevents its return.

## Required local gates

```powershell
.venv\Scripts\python tools\check_architecture.py
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
exposure class, complete computation and authoring descriptor, input and output
products, typed parameters and units, backward demand, forward damage,
coordinate, numerical and alpha semantics, edge behavior, quality tiers,
product-key inputs, capability and request-analysis behavior, retained and
scratch memory, cancellation, parallelism, structured diagnostics, an
independent oracle, tile equivalence, cross-frontend construction when public,
performance budgets, and the implementation it replaces.

## Graph authoring contract

Rust builders, Python builders, R-Candy, CuteCanvas, and structured tools produce
one versioned `GraphDefinition`. `NodeId`, `GraphRevisionId`, `GraphContentId`,
and `ProductKey` have separate purposes. Patches name a base revision, enforce
preconditions, and commit atomically. Unknown operations survive serialization.
Authoring prose never changes computational identity.

R-Candy compilation is deterministic and performs no I/O. A host supplies exact
catalog and package resolution, then applies trust, capability, graph-limit,
request-cost, and memory admission after Ferrastra validation. Source and graph
publish together or become explicitly detached; they never diverge silently.

Ferrastra is a CPU-first, typed, spatial, revision-aware graphics product engine.
It evaluates immutable raster, coverage, vector, mixed graphic, and analysis
products through a demand-driven DAG. Exact results are immutable, cacheable,
tile-equivalent, atomically published, explainable, and reproducible under
their documented contract.
