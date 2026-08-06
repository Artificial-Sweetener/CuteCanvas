# Ferrastra Rust Workspace Guidance

The root `AGENTS.md`, `FERRASTRA_DESIGN.md`, `RCANDY_DESIGN.md`, and
`ARCHITECTURE.md` apply. This file defines Rust-specific implementation and
proof requirements for every crate under `crates/`.

## Crate and module ownership

Create a crate only when executable code begins for the sole responsibility
assigned in `ARCHITECTURE.md`. Crate dependencies follow the checked-in allowlist
and remain acyclic. Algorithms, planning, storage, runtime policy, bindings, and
facade assembly stay in their declared owners; convenience is not a reason to
cross an edge.

`ferrastra-engine` owns stable high-level Rust assembly when its authorized phase
begins. Its public API gives consumers coherent construction and evaluation
workflows without requiring manual assembly of operation registries, graph
compilers, stores, runtimes, schedulers, or caches. It contains no algorithms,
planning logic, storage implementation, or binding policy.

`ferrastra-rcandy` is created only when executable parser or compiler work
begins. It owns syntax, supplied-lock resolution, type checking, graph lowering,
source maps, formatting, and language diagnostics. Computation, graph, engine,
runtime, store, and operation crates never depend on it. It performs no I/O,
package acquisition, host policy, model orchestration, graph execution, or
Python binding work.

Every production module begins with module documentation containing
`Responsibility:` and `Does not own:`. Public items have accurate Rustdoc that
states contracts, errors, panics, safety, units, coordinate spaces, and ownership
when applicable. Keep modules cohesive and within the repository structural
limits; do not create generic utility, helper, common, manager, service, or
facade dumping grounds.

## Rust implementation

- Use the workspace toolchain, edition, minimum Rust version, dependency policy,
  formatting, and lint configuration. Every crate inherits workspace lints.
- Treat warnings as errors. Do not lower workspace lint levels. A suppression
  uses the narrowest scope and states the invariant that justifies it.
- Use domain types for products, regions, formats, revisions, budgets, and
  semantic identities. Do not encode invariants in primitive tuples, magic
  values, or untyped maps.
- Check integer conversion and arithmetic at dimensions, offsets, strides,
  regions, allocation sizes, and FFI boundaries. Reject invalid or overflowing
  inputs before allocation or pointer access.
- Return typed `Result` errors with actionable context. Do not use `unwrap`,
  `expect`, `panic!`, `todo!`, `unimplemented!`, or `dbg!` in workspace code.
- Keep deterministic behavior independent of task partition, thread count, tile
  boundaries, and hash iteration. Make alpha, color, edge, coordinate, quality,
  and rounding semantics explicit.
- Account for destination, scratch, retained, pinned, evictable, and in-flight
  memory. Avoid hidden full-image copies and per-item allocation in hot loops.
- Use caller-supplied execution and memory budgets. Do not create global thread
  pools, hidden caches, unbounded queues, detached work, or nested parallelism
  outside the supplied budget.
- Poll cancellation at a documented bounded interval. Cancelled or failed work
  publishes no partial exact product or source revision.

Before implementing an operation, complete the operation-entry contract in
`FERRASTRA_DESIGN.md` and the public-authoring requirements in
`RCANDY_DESIGN.md`, including semantic identity, exposure, descriptor metadata,
products, typed parameters and units, demand, damage, numerical semantics,
capability and cost analysis, diagnostics, memory, cancellation, quality,
conformance, cross-frontend construction, tile equivalence, performance gates,
and the implementation being replaced.

## Unsafe code and FFI

Unsafe Rust is denied. An exception requires a focused module, explicit safety
owner, active architecture waiver, `SAFETY.md`, documented invariants, safe
encapsulation, focused tests, Miri where applicable, and fuzz coverage at the
boundary. Keep unsafe blocks minimal and never use unsafe code solely to avoid
measuring or fixing a safe implementation.

Only `ferrastra-python` may depend on PyO3 or Python/NumPy binding crates. The
binding crate owns validation, conversion, exception mapping, module
registration, and opaque handle exposure; it does not own kernels, stores,
planning, scheduling, or cache policy.

No panic or Rust unwind may cross the FFI boundary. Validate Python buffers and
array metadata before constructing native views. Borrowed memory has an explicit
lifetime, and writable memory has exclusive unpublished ownership. Release the
Python interpreter lock around long-running native work after native inputs own
or safely borrow every required resource.

## Verification

Organize Rust tests by owning crate, module responsibility, and proof kind. Unit
tests live beside focused implementation details. Crate integration tests prove
only contracts owned by that crate. Cross-crate and cross-language conformance
fixtures live with the Ferrastra product test owner and call supported crate or
package boundaries.

`packages/ferrastra/TEST_POLICY.toml` maps every Ferrastra crate and production
area to required unit, integration, conformance, property, fuzz, Miri, benchmark,
cross-language, and packaging proof. A new crate, module responsibility,
operation, public contract, parser, serializer, unsafe boundary, or optimization
updates that map in the same work.

- Prove numerical code against an independent scalar oracle or fixed golden
  contract. Add the property, seam, stride, empty-region, cancellation,
  allocation, memory-admission, and deterministic-partition cases required by
  the operation contract.
- Every public graph operation uses shared conformance fixtures for descriptor
  completeness, identity, demand, damage, color and alpha, coordinates, units,
  quality, tiling, cancellation, memory, diagnostics, and performance.
- Graph, patch, serializer, descriptor, and R-Candy tests use deliberately
  invalid and unknown records in addition to successful round trips. Equivalent
  Rust, Python, and language fixtures produce the same normalized computation.
- Fuzz parsers, buffer validation, serialization, graph validation, patches,
  package locks, diagnostics, and unsafe or FFI boundaries. Run Miri for
  applicable unsafe, aliasing, and lifetime-sensitive code.
- Apply mutation or deliberately nonconforming-implementation tests to graph
  validation, identity, transaction atomicity, demand and damage, admission,
  parser recovery, and FFI validation so the suite proves sensitivity to broken
  rules.
- Add benchmarks with explicit inputs, compiler profile, CPU architecture,
  thread budget, memory budget, percentiles, and regression thresholds. Optimize
  only after profiling and preserve the scalar correctness oracle.
- End each work turn with formatting, Clippy, tests, and architecture checks
  focused on the affected crates and behavior. Before committing Rust production
  or test changes, run the complete workspace formatting, all-target/all-feature
  Clippy, tests, dependency policy, architecture, and policy-selected
  cross-language, packaging, and platform gates. Rust documentation-only commits
  require focused documentation and diff validation.
- Verify native boundary changes through the built Python wheel rather than the
  monorepo source tree.
