# Repository Engineering Standards

This repository contains the independently published Ferrastra, QPane, and
CuteCanvas products. `FERRASTRA_DESIGN.md` is the implementation charter for
native graphics work. `RCANDY_DESIGN.md` is the charter for Ferrastra's
declarative graph-authoring language and structured authoring surface.
`ARCHITECTURE.md` and the checked-in architecture policy define enforceable
ownership and dependency boundaries.

Read `CONTRIBUTING.md` before editing. This file applies to the entire
repository. The nearest package or crate `AGENTS.md` adds local ownership and
verification requirements without repeating or replacing this file.

Instruction files and committed documentation must not contain developer-specific
absolute paths, usernames, hostnames, shell profiles, local operating-system
assumptions, or hardware details. Product platform requirements and reproducible
reference environments are repository facts and must remain explicit.

## Production quality

- Preserve stability, correctness, responsiveness, bounded memory, consistency,
  and visual polish. Stale frames, flicker, surprising behavior, excessive
  allocation, and unexplained latency are defects.
- Do not commit temporary `TODO`s, debug output, commented-out code, incomplete
  migrations, placeholder production APIs, or internal compatibility scaffolding.
- Fail at the boundary that can act on the failure. Invalid external data,
  rejected work, cancellation, teardown, and stale asynchronous results must not
  crash a host application or publish partial state.
- Keep expensive decoding, evaluation, rasterization, I/O, and waiting off GUI
  threads. Make ownership, cancellation, lifetimes, and memory bounds explicit.

## Product ownership and dependencies

The allowed product dependencies are:

```text
CuteCanvas -> QPane
CuteCanvas -> Ferrastra
QPane      -> Ferrastra
```

No reverse or lateral product dependency is allowed. Applications may depend on
all three products.

- Ferrastra owns typed native products, source stores, immutable evaluation
  graphs, spatial demand and damage, bounded evaluation, canonical numerical
  operations, native edit sessions, canonical graph-authoring contracts,
  R-Candy, and their correctness and performance contracts. It contains no Qt,
  application, document, viewport, tool, history, or presentation concepts.
- QPane owns immutable render scenes and sources, viewport transforms and demand,
  navigation input, hit testing, clipping, compositing, damage, pyramids, tiles,
  refinement, presentation caches, render concurrency, and Qt presentation.
- CuteCanvas owns documents, editable resources and layers, policy and locks,
  history, selections, masks, painting, authoring tools, transforms, persistence,
  and editor workflows.

CuteCanvas uses only QPane's supported public facade and rendering SDK. QPane and
CuteCanvas use Ferrastra through focused adapters owned by the consuming package.
Ferrastra never imports or links QPane, CuteCanvas, or Qt. QPane never imports
CuteCanvas.

The QPane adapter translates generic product demand, execution budgets, and
completed native products without moving viewport policy, retained frames,
GUI-thread rules, or Qt presentation into Ferrastra. The CuteCanvas adapter
compiles authoring state and adopts immutable native revisions without moving
documents, commands, tools, history, resource selection, locks, or publication
policy into Ferrastra.

R-Candy is part of Ferrastra rather than a fourth product. It lowers source to
the same canonical graph constructed by Rust, Python, and host adapters. Engine,
graph, and runtime crates never depend on the language crate. CuteCanvas owns
model interaction, trust, package acquisition, document binding, previews,
publication, and undo; QPane remains syntax-neutral. Generated or imported
graphs pass R-Candy checks when applicable, Ferrastra validation, and host
admission as separate gates.

A shared concept has one representation and one behavior owner. Do not create
parallel scene, vector, transform, cache, damage, scheduling, input, numerical,
or rendering systems to bypass an owning package. Cross-package fixes follow the
authoritative owner even when they require a coordinated change in more than one
package.

## Ownership and separation of concerns

Before extending a module, class, subsystem, or workflow, identify its concern,
authoritative state owner, dependency direction, public boundary, behavior and
performance contracts, and change cadence. Place code by ownership rather than
proximity or minimal diff size.

A state owner owns the behavior that mutates, validates, interprets, coordinates,
or publishes that state. Collaborators use explicit public methods, protocols,
or injected dependencies and never reach into private collaborator state. DRY
means single ownership; consumers may observe, delegate, adapt, or cache derived
results but must not reproduce authoritative rules or state.

Do not add behavior to a mixed-responsibility file. If existing code touched by
the work mixes responsibilities:

1. Characterize the existing behavior with tests.
2. Identify the authoritative owners.
3. Extract each touched responsibility into cohesive, focused files.
4. Migrate every caller completely.
5. Remove replaced code and temporary bridges.
6. Verify behavior and the resulting ownership boundaries.

Do not defer this blast-area work, hide it behind a forwarding shim, or move
lines into a generic dumping ground. A structural waiver can exempt a justified
size or policy gate; it never authorizes mixed ownership or new behavior in a
mixed file.

Production modules have one concern and one reason to change. The structural
soft ceiling is 350 nonblank, noncomment lines and the hard gate is 500. File
size is an ownership alarm, not proof of cohesion. Architecture debt and waiver
records describe only current facts; update or delete stale facts and rely on
Git for history.

## Structural changes and migrations

Behavior-critical structural work follows this order:

1. Add or identify characterization and regression protection.
2. Establish the authoritative boundary.
3. Migrate every caller as a complete vertical slice.
4. Remove replaced types, exports, files, code paths, tests, and bridges.
5. Update ownership maps and enforcement rules.
6. Run focused correctness, abuse, performance, and packaging gates.

Internal compatibility is not a goal. Preserve compatibility only at supported
public or host-facing contracts unless the work explicitly changes that
contract. Do not add deprecation adapters, forwarding namespaces, aliases, or
dual canonical implementations for internal migrations.

When numerical ownership moves to Ferrastra, characterize the existing result,
define the operation contract required by `FERRASTRA_DESIGN.md` and
`RCANDY_DESIGN.md`, migrate every
consumer through its package-owned adapter, delete the former implementation,
and activate the ownership check that prevents its return. Presentation-only
approximations remain distinct from exact products in identity, caching, and
diagnostics.

## Python engineering

- Support the Python versions declared by package metadata. Use Python 3.10
  syntax and `(str, Enum)` instead of `StrEnum` while Python 3.10 is supported.
- Add accurate type annotations and docstrings to every new or changed module,
  class, function, method, property, and public value. Resolve typing failures at
  their source; any suppression is exact, narrow, and justified.
- Public docstrings use concise Google-style sections when parameters, returns,
  exceptions, or side effects need explanation. Internal docstrings state the
  owned concern directly.
- Validate untrusted data at package and FFI boundaries. Preserve exception
  causes, use stable domain exceptions for expected failures, and catch broad
  exceptions only where the boundary can recover, translate, or report them.
- Use explicit ownership and lifetime management for Qt objects, workers,
  callbacks, temporary buffers, and external resources. Teardown and
  cancellation paths receive the same tests as successful paths.
- Avoid mutable default arguments, implicit process-global state, import-time
  work, service locators, and stringly typed internal contracts.
- Public QWidget methods and Qt signals use `camelCase`. Internal methods and
  non-widget domain APIs use `snake_case`. Enum classes use `PascalCase`; enum
  members and constants use `UPPER_CASE`.
- Keep module order predictable: docstring, imports, logger, public values,
  primary implementations, then private details. Use expressive names; comments
  explain only constraints that code cannot state clearly.

## Integration and public contracts

Treat integration quality as product behavior. Each product provides one obvious
supported starting point, task-oriented APIs, predictable defaults, explicit
lifecycle and resource ownership, and actionable failures. Common workflows
require minimal assembly and no knowledge of private collaborators, schedulers,
caches, workers, native representations, or incidental identifiers. Advanced
control uses focused protocols, builders, handles, or subfacades without
bypassing the same authoritative boundary.

A facade may be an object, module, or cohesive group of entry points. Do not
force unrelated responsibilities into one class or expose internal architecture
merely to avoid designing a public workflow. Prove integration through public-only
demos, isolated consumer tests, and documentation that starts from user goals.

Each published product has one authoritative typed contract. A public change
updates these four artifacts in the same work:

1. typed contract and exports;
2. implementation;
3. API reference and narrative documentation; and
4. the product's single polished public-only demo.

Examples and tests of public behavior use supported APIs rather than private
internals. Documentation describes the resulting product directly and does not
preserve removed architecture, migration history, or nonexistent alternatives.

## Test ownership and design

- Treat tests, fixtures, harnesses, selectors, and test policy as production
  code. They follow the same ownership, cohesion, typing, naming, structural,
  and review standards as runtime code.
- Product runtime tests live under the product that owns the behavior. Root tests
  cover only repository policy and orchestration. Organize product tests first by
  behavioral subsystem and then by proof kind: unit, contract, integration, Qt,
  abuse, performance, or packaging.
- Give each test module one behavioral concern and each test a name that states
  the contract and outcome. Do not organize tests around implementation history,
  incidental imports, issue numbers, or catch-all regression files.
- Before changing behavior, identify its owning test area and existing
  characterization. Add the regression or characterization first when the
  current contract is not already protected. Update tests in the same change as
  behavior or structure.
- Unit tests isolate one owner. Contract tests exercise supported public
  boundaries. Integration tests prove collaboration among authoritative owners.
  Mount real Qt objects when lifecycle, input, repaint, timing, or user workflow
  matters.
- Expected results come from explicit contracts, independent oracles, fixed
  canonical fixtures, or externally observable behavior. Do not reproduce the
  production algorithm in the test and mistake agreement for proof.
- Tests are deterministic and order-independent. Use controlled clocks,
  synchronization, seeds, schedulers, and resources instead of arbitrary sleeps,
  retries, timing luck, shared mutable process state, or collection order.
- Fixtures and harnesses have one product and behavioral owner. Keep their scope
  as narrow as the state they provide; teardown and failure paths receive direct
  proof.
- Use the abuse harness for rapid switching, cancellation, stale work, input
  storms, teardown, cache pressure, undo/redo, and redraw equality. Use the
  centralized timing utility for wall latency in isolation and its contention-
  safe policy under parallel execution.
- Treat correctness, performance, memory, cancellation, and responsiveness
  budgets as contracts. Profile and fix the authoritative owner; never weaken an
  assertion, selection rule, oracle, budget, or workload to make a change pass.
- Coverage is a discovery signal, not proof of useful assertions or sufficient
  test selection.

## Test selection and gates

- Each product owns a `TEST_POLICY.toml` snapshot mapping every production area
  and public boundary to its required local test areas, proof kinds, abuse
  scenarios, performance gates, packaging checks, and platform requirements.
  A consumer records its subscriptions to external public contracts in its own
  policy. The root runner aggregates these policies without owning product test
  decisions.
- End every behavioral work turn with `tools/test.py changed`. It selects the
  minimum policy-required proof for staged, unstaged, and untracked worktree
  changes and prints the changed path and policy rule responsible for every
  selected group. Do not report completion from a manually reduced selection.
- Before committing runtime or test changes, run
  `tools/test.py staged --commit`. The staged gate includes the complete affected
  product suites and every policy-required contract, abuse, performance,
  packaging, binding, build, and platform gate. Changes spanning Python and Rust
  run both runtimes' applicable gates.
- Direct test commands are valid for diagnosis and iteration. They do not replace
  the policy-selected turn or commit command.
- The root runner exposes discoverable product, behavioral-area, and proof-kind
  targeting plus list and explain modes from the same policy. Contributors do
  not need test node IDs, private module names, or fixture-layout knowledge to
  run an owned test area.
- A changed production path without exactly one product and behavioral mapping
  fails selection. A runtime change never selects zero tests. An unknown or
  ambiguous impact fails with the ownership decision required to resolve it.
- Public-boundary and shared-contract changes select the owning product's proof
  and every consumer-owned contract subscription. Adding changed paths can only
  retain or expand the required selection.
- Reconcile test policy in the same change when production ownership, test
  ownership, public contracts, dependency direction, or required proof changes.
  Remove stale mappings instead of retaining historical entries.
- A documentation-only `docs` commit and any staged diff that changes neither
  runtime source nor tests runs focused artifact validation. Determine the gate
  from staged content rather than the proposed commit type.
- Build and validate isolated artifacts when packaging, dependencies, exports,
  native bindings, or public boundaries change. Each product installs and runs
  with only its declared dependencies.
- A selected failure is evidence about the authoritative contract. Fix the
  behavior or correct a demonstrably inaccurate contract; do not bypass the
  failure with a narrower command, skip, retry, quarantine, ordering dependency,
  or increased timing budget.

## Test system proof

- Meta-tests collect the repository test inventory and prove that every runtime
  test has exactly one product, behavioral area, and proof kind; every production
  path is mapped; every required group collects tests; every test is reachable
  from a supported policy profile; and no product runtime test or fixture remains
  at the repository root.
- Meta-tests enforce test import direction, package-local fixture ownership,
  path/marker agreement, unique test identities, nonempty current policy entries,
  and the absence of stale mappings.
- Policy and selector failures identify the changed path or collected test, the
  violated invariant, the authoritative product policy, and the supported
  corrective outcomes. Do not emit a generic unclassified-test or no-tests-
  selected failure.
- Selector contract tests use synthetic worktree and staged diffs to prove exact
  area selection, public-boundary fan-out, monotonic selection, conservative
  unknown-path failure, supported-platform path normalization, and propagation
  of test-process failures.
- Every architecture, policy, schema, and boundary checker has deliberately
  invalid fixtures proving that it rejects the violations it claims to enforce.
- Critical authoritative rules use sensitivity proof. Apply mutation testing,
  deliberately nonconforming implementations, independent oracles, or fixed
  canonical fixtures to graph validation, identity, history, damage, cache
  invalidation, admission, serialization, and other high-risk logic.
- A skip or expected failure names the exact current external condition and an
  expiry, review date, or supported-platform predicate. Test policy rejects
  unexplained, broad, stale, or permanently unconditional exceptions.

## Workspace and Git

- Preserve unrelated worktree changes. Never use destructive reset or checkout
  commands to remove work that is not yours.
- Use `apply_patch` for source and documentation edits. Do not let formatters
  rewrite unrelated files.
- Do not add machine-local configuration, credentials, generated environments,
  caches, build outputs, or absolute local paths to the repository.
- Commit only when explicitly asked. Each commit delivers one coherent user- or
  integrator-meaningful outcome and is independently releasable.
- Commit subjects feed generated changelogs. Use
  `type(scope): changelog-ready outcome`; scope the primary product or repository
  concern. `feat`, `fix`, and `perf` subjects state the delivered capability,
  corrected behavior, or measurable improvement rather than implementation
  mechanics.
- Mark a public breaking change with `!` and explain the compatibility impact and
  migration in the commit body. Bodies state why the outcome matters, its
  behavioral constraints, and coordinated product effects.
- Include supporting tests, documentation, cleanup, and refactoring with the
  outcome they support. Use `refactor`, `test`, `docs`, `build`, or `chore` only
  for a coherent internal outcome. Do not create WIP, checkpoint, miscellaneous,
  or file-movement diary commits.
- Before committing, complete the gate selected by the staged diff. Before
  reporting a turn complete, report the focused verification actually run.
