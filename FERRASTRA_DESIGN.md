# Ferrastra Native Graphics Engine

- **Status:** Normative implementation charter
- **Applies to:** Ferrastra and its integration boundaries with QPane and CuteCanvas
- **Audience:** engineers implementing Ferrastra, engineers migrating QPane or CuteCanvas behavior into Ferrastra, reviewers, and maintainers
- **License:** GPL-3.0-or-later
- **Minimum release targets:** Windows x64 (`x86_64-pc-windows-msvc`), Linux x64 (`x86_64-unknown-linux-gnu`), and Apple Silicon macOS (`aarch64-apple-darwin`)
- **Authoring-language charter:** `RCANDY_DESIGN.md`

---

## 1. Executive decision

Ferrastra will be a **CPU-first, Qt-neutral, document-neutral native graphics engine** shared by QPane and CuteCanvas.

Ferrastra will provide two native execution models:

1. An **immutable, typed, spatial, revision-aware evaluation DAG** for nondestructive derived content.
2. **Transactional native edit sessions** for mutable source operations such as brush painting, erase, clone, smudge, fill, and other ordered edits.

The permanent responsibility split is:

```text
CuteCanvas authors
    documents, resources, layers, tools, history,
    effect stacks, persistence, editor policy
            │
            │ compiles authoring state
            ▼
Ferrastra evaluates
    native source stores, typed DAG, raster/vector operations,
    region planning, caches, edit sessions, immutable products
            │
            │ supplies exact or explicitly approximate products
            ▼
QPane presents
    viewport, navigation, physical tile demand, retained frames,
    Qt adaptation, final widget composition and interaction
```

The compact rule is:

> **CuteCanvas authors. Ferrastra evaluates. QPane presents.**

R-Candy is Ferrastra's typed declarative authoring frontend. It lowers source
and structured edits to the same canonical `GraphDefinition` used by Rust,
Python, and CuteCanvas. It does not enter the evaluation runtime or change the
responsibility split above. `RCANDY_DESIGN.md` is normative for its language,
artifact, structured-authoring, and host-admission contracts.

This document is normative. An implementation that reaches the correct pixels while violating the ownership, dependency, product, memory, or module-responsibility rules below is not an acceptable implementation.

---

## 2. Why Ferrastra exists

The current monorepo already contains most of the platform around a native graphics engine:

- CuteCanvas has a durable acyclic project-resource graph with stable identities, dependency edges, cycle rejection, reverse dependents, and transitive revisions.
- QPane has source-neutral tile and region sampling contracts, physical viewport tile demand, coherent batch publication, latest-only cancellation, native-work scheduling categories, and coordinated byte-bounded caches.
- CuteCanvas has sparse editable raster and coverage stores, revisioned resources, unified history, editing tools, masks, selections, and vector authoring.
- QPane has immutable raster/vector presentation products, semantic vector sources, visibility, hit testing, clipping, pyramids, tiles, refinement, and retained-frame navigation.

However, canonical numerical work is currently spread across several owners:

- Qt smooth scaling and `QPainter` transforms.
- Python loops and data structures.
- NumPy array operations and temporary allocations.
- QPane’s generic raster SDK.
- CuteCanvas-specific numerical implementations.

That distribution causes five problems:

1. **No single numerical authority.** The same semantic operation can have unrelated Qt and NumPy implementations.
2. **Ownership inversion.** CuteCanvas sometimes asks QPane—the presentation package—to define canonical editable pixels.
3. **No general nondestructive operation DAG.** The durable resource graph tracks ownership and invalidation, but not executable image operations.
4. **Limited regional reuse.** Derived products are not uniformly identified, cached, invalidated, or evaluated by exact requested region and scale.
5. **Difficult optimization.** Improving one algorithm or memory path does not automatically benefit every consumer.

Ferrastra corrects those problems without moving document semantics into Rust and without moving viewport policy out of QPane.

---

## 3. Goals

Ferrastra must make the following outcomes natural rather than exceptional.

### 3.1 Architectural goals

- One authoritative implementation of every canonical raster, coverage, vector, compositing, and analysis operation.
- A typed operation DAG where type, spatial dependency, revision, scale, quality, memory, and provenance are explicit.
- Native nondestructive editing as a foundational assumption, not a later effect layer.
- Clear package ownership with mechanically enforced dependency direction.
- Source files and crates with one responsibility and one reason to change.
- A public operation SDK that makes correct new operations easier to write than bespoke pipelines.
- One canonical graph and operation-description surface that Rust, Python,
  R-Candy, structured model tools, and visual authoring can share without
  semantic adapters.
- Explainable planning, caching, invalidation, and execution.

### 3.2 Performance goals

- Extremely fast CPU raster work on ordinary desktop hardware.
- High-performance vector querying, transformation, compositing, and rasterization.
- Region-limited work for large images and sparse documents.
- Reusable multiresolution products for QPane navigation and exact settled rendering.
- No GUI-thread blocking for expensive operations.
- No unbounded native thread pool or hidden memory cache.
- Small steady-state allocation rates for interactive tools.
- Explicit p50, p95, and p99 latency and memory gates.

### 3.3 Editing goals

- Persistent effects remain graph nodes and do not rewrite sources.
- Painting and smudge use bounded native sessions and commit new source revisions atomically.
- Undo can retain prior copy-on-write revisions rather than full-image copies where practical.
- Adjustment layers, masks, group isolation, clipping groups, opacity, and blend modes compile into one canonical composition DAG.
- Raster and vector content remain in their native product domains until an explicit operation requires conversion.

### 3.4 User-feature goals

Ferrastra must eventually provide world-class implementations of, at minimum:

- Lanczos-3 resampling.
- NoHalo resampling.
- LoHalo resampling.
- Color to Alpha.
- Gaussian blur and common convolution/filter operations.
- Coverage and mask operations.
- Blend and composition operations.
- Native paint, clone, smudge, erase, and fill primitives.
- A serious CPU vector engine.

NoHalo, LoHalo, and Color to Alpha are named user-facing requirements. Ferrastra will preserve the goals users value in those operations while defining its own faster, better-specified canonical implementations rather than line-porting another engine.

---

## 4. Non-goals

The following are explicitly not Ferrastra responsibilities.

- Qt widgets, `QImage`, `QPixmap`, `QPainter`, dialogs, windows, or event handling.
- CuteCanvas documents, layers, selected objects, tool icons, undo labels, persistence files, or application policy.
- QPane viewport state, visible-versus-guard tile priority, retained frames, repaint timing, or widget composition.
- A mandatory node-editor user interface.
- A JavaScript or browser frontend.
- Language parsing, source formatting, model orchestration, package acquisition,
  or host trust policy inside the graph compiler or runtime.
- Replacing Qt image decoding, encoding, ICC profile interpretation, or display conversion in the first implementation.
- A GPU-first architecture.
- A global application scheduler owned by Ferrastra.
- A compatibility wrapper around every current QPane or CuteCanvas private API.
- A miscellaneous native utility package.

Ferrastra may eventually support optional GPU backends, external stores, persistent caches, and more color formats. The CPU implementation remains the canonical always-available reference backend.

---

## 5. Terminology

### Authoring model

The human-facing document representation owned by CuteCanvas: resources, layers, groups, masks, effect stacks, metadata, and editor commands.

### Durable resource DAG

CuteCanvas’s persistent dependency graph. It answers which project resources depend on which other project resources and owns resource identity, lifetime, and transitive revision changes.

### Evaluation DAG

Ferrastra’s executable graph. It answers which typed computations produce a requested output region at a requested scale and quality.

### Source product

An immutable revision of authoritative raster, coverage, vector, or other source content.

### Derived product

An immutable result created by evaluating an operation over one or more inputs.

### Product key

A strong content identity derived from operation semantics, parameters, inputs, output port, region, scale, quality, format, and working-space rules.

### Node ID

A stable authoring identity used by graph patches, source maps, diagnostics, and
undo. It is not computational content identity.

### Graph revision ID

The identity of one accepted graph edit revision, including authoring-only
changes recorded by that revision.

### Graph content ID

The identity of the normalized computation. It excludes labels, prose, source
formatting, comments, examples, tags, and control layout.

### Backward demand

Planning from requested output toward required upstream input regions.

### Forward damage

Planning from a changed input region toward downstream regions whose cached results are no longer valid.

### Interactive quality

An explicitly approximate product suitable for active manipulation. It is never labeled or cached as exact output.

### Exact quality

The canonical operation result under its declared numerical contract.

### Presentation product

A QPane-owned Qt-native image, pixmap, retained frame, or vector display object. Presentation products are not Ferrastra’s canonical document products.

---

## 6. Permanent ownership map

### 6.1 CuteCanvas owns authoring and editor semantics

CuteCanvas continues to own:

- Document identity, canvas, metadata, and persistence.
- Project-resource identity, sharing, lifetimes, and durable dependency edges.
- Ordered layer and group authoring models.
- Masks and selections as editor concepts.
- Effect stacks and user-visible parameters.
- Tools, interaction modes, and operation availability policy.
- Unified chronological undo/redo and atomic editor transactions.
- Rasterize, bake, merge, flatten, and export commands.
- Compiling CuteCanvas state into an Ferrastra graph definition.
- Translating native edit-session results into document resource revisions and history.

CuteCanvas must not implement canonical pixel loops once the corresponding Ferrastra operation exists.

### 6.2 QPane owns viewport demand and Qt presentation

QPane continues to own:

- QWidget integration and all Qt GUI-thread requirements.
- Pan, zoom, rotation, projection, visibility, hit testing, and clipping.
- Physical viewport tile geometry, visible/guard/overview/prefetch demand, and urgency.
- Retained frames and immediate transformed navigation previews.
- Qt-native presentation caches and final widget composition.
- QPane source protocols and immutable render scenes.
- Scheduling and cancellation policy for presentation-oriented work.
- Converting or wrapping completed Ferrastra products into Qt presentation products.

QPane may request exact pixels from Ferrastra. It must not own the canonical numerical implementation of those pixels.

### 6.3 Ferrastra owns native graphics computation

Ferrastra owns:

- Framework-neutral product and pixel contracts.
- Canonical typed graph, operation-descriptor, diagnostic, patch, analysis, and
  computational-identity contracts shared by every authoring frontend.
- Native raster, coverage, and vector stores.
- Copy-on-write source revisions and bounded edit transactions.
- Typed graph definitions, validation, compilation, and optimization.
- Backward demand and forward damage propagation.
- Internal evaluation tiling and halo planning.
- Intermediate-product caching and source-level multiresolution products.
- Canonical raster, coverage, vector, compositing, color, and analysis operations.
- Native paint, clone, smudge, erase, and fill sessions.
- CPU dispatch, scratch memory, cancellation polling, and evaluation diagnostics.

Ferrastra must not interpret CuteCanvas layer or tool concepts or QPane viewport concepts.

### 6.4 R-Candy owns declarative language concerns

R-Candy is part of the Ferrastra product but remains outside computation and
runtime crates. It owns grammar, syntax, spans, name and package resolution,
type checking against Ferrastra descriptors, graph lowering, source maps,
canonical formatting, and language diagnostics. It performs no evaluation,
package acquisition, filesystem or network access, host policy, model
orchestration, or document work. Detailed ownership and artifact rules are in
`RCANDY_DESIGN.md`.

---

## 7. Dependency direction

The allowed product dependency graph is:

```text
CuteCanvas ─────► QPane
     │
     └──────────► Ferrastra

QPane ─────────► Ferrastra

Ferrastra ✕ QPane
Ferrastra ✕ CuteCanvas
QPane  ✕ CuteCanvas
```

Applications may depend on all three.

The Rust crate dependency graph must remain acyclic and conform to the allowlist in Section 10.

Within Ferrastra, `ferrastra-rcandy` may depend on `ferrastra-core` and
`ferrastra-graph`; computation, graph, engine, and runtime crates never depend on
it. `ferrastra-python` may depend on it only when exposing the implemented
`ferrastra.rcandy` surface. Evaluation of a serialized `GraphDefinition` never
requires R-Candy.

---

## 8. Architectural invariants

These invariants apply from the first commit.

1. **No Qt in Ferrastra.** No Ferrastra crate or Python binding imports or links Qt.
2. **No document semantics in Ferrastra.** No layer IDs, tool state, undo commands, file dialogs, or CuteCanvas types cross into Ferrastra.
3. **No viewport policy in Ferrastra.** Requests carry generic region, scale, quality, urgency, budget, and cancellation—not visible/guard/pan concepts.
4. **No canonical numerical duplicates.** Once an operation migrates, QPane and CuteCanvas delete their independent numerical implementation.
5. **No anonymous pixel buffers.** Format, channel order, alpha representation, transfer behavior, dimensions, and stride are explicit.
6. **No implicit alpha or color behavior.** Every operation declares supported semantics.
7. **No whole-image fallback for a regional request unless the operation formally requires it.** Such operations must report that requirement during planning.
8. **No hidden global thread pool.** Native parallelism uses a caller-supplied budget.
9. **No hidden unbounded cache.** Every retained byte participates in explicit accounting.
10. **No partially published exact product.** Publication is atomic at the caller or runtime boundary.
11. **No persistent effect implemented only as a presentation effect.** Canonical document effects are Ferrastra graph operations.
12. **No one-off public resize/filter functions as the primary integration API.** QPane and CuteCanvas call through typed operation and request contracts.
13. **No mixed-responsibility production modules.** Each source file has one declared responsibility and one reason to change.
14. **No generic dumping-ground modules.** Production modules named `utils`, `common`, `helpers`, `misc`, or equivalent are forbidden.
15. **No unsafe Rust without an explicit safety owner and tests.** Unsafe code is isolated, documented, reviewed, fuzzed, and excluded from ordinary operation modules.
16. **No random quality behavior.** Interactive, exact, and export behavior are deterministic and explicit.
17. **No operation without a semantic ID and version.** Crate versions do not substitute for operation semantics.
18. **No operation without backward-demand, forward-damage, memory, cancellation, and conformance definitions.**
19. **No frontend-specific graph semantics.** Rust builders, Python builders,
    R-Candy lowering, CuteCanvas compilation, and structured tools produce the
    same canonical graph contract.
20. **No silent source/graph divergence.** An authored source and executable
    graph are published together or explicitly detached as required by
    `RCANDY_DESIGN.md`.
21. **No authoring prose in computation identity.** Labels, comments, tags,
    examples, search metadata, and control layout do not invalidate products.
22. **No generated or imported bypass.** Every graph passes Ferrastra validation
    and host admission regardless of its author.

---

## 9. Repository layout

The target monorepo layout is:

```text
Cargo.toml
rust-toolchain.toml

crates/
├── ferrastra-core/
├── ferrastra-store/
├── ferrastra-graph/
├── ferrastra-rcandy/          # introduced when executable language work begins
├── ferrastra-runtime/
├── ferrastra-raster/
├── ferrastra-engine/
├── ferrastra-vector/          # introduced when vector implementation begins
├── ferrastra-paint/           # introduced when native edit sessions begin
└── ferrastra-python/

packages/
├── ferrastra/
│   ├── pyproject.toml
│   ├── src/ferrastra/
│   ├── src/ferrastra/py.typed
│   ├── src/ferrastra/ferrastra.pyi
│   ├── docs/
│   └── tests/
├── qpane/
│   └── src/qpane/ferrastra/
└── cutecanvas/
    └── src/cutecanvas/ferrastra/

tools/
├── check_architecture.py
├── check_ferrastra_operations.py
└── ferrastra_benchmarks.py

tests/
├── test_ferrastra_architecture.py
├── test_ferrastra_qpane_integration.py
└── test_ferrastra_cutecanvas_integration.py
```

Do not create empty placeholder crates solely to satisfy this diagram. Create a crate when its responsibility has executable code, but preserve the dependency and ownership plan from the start.

---

## 10. Rust crate responsibilities and allowed dependencies

### 10.1 `ferrastra-core`

Owns only stable value contracts:

- Strong IDs and semantic operation IDs.
- Integer and floating regions.
- Coordinate and sample-center conventions.
- Transforms and scale footprints.
- Product kinds and product specifications.
- Pixel and coverage format descriptions.
- Borrowed product views.
- Operation descriptors and operation trait contracts.
- Typed parameter values, units, exposure classes, structured diagnostic
  records, and request-analysis contracts.
- Quality, edge, alpha, and working-space enums.
- Cancellation and execution budgets.
- Errors and evaluation reports.

Must not own storage, graph mutation, scheduling, caches, operation implementations, Python, or Qt.

Allowed internal dependencies: none.

### 10.2 `ferrastra-store`

Owns native retained data:

- Immutable products.
- Raster, coverage, and vector source stores.
- Sparse tiles and copy-on-write revisions.
- Edit transactions and damage reports.
- Pinning, leases, and retained-byte accounting.
- External or file-backed store interfaces later.

Allowed internal dependencies: `ferrastra-core`.

Must not own graph planning, operation implementations, application scheduling, or Python.

### 10.3 `ferrastra-graph`

Owns graph structure and compilation:

- Typed nodes, ports, connections, and outputs.
- Graph transactions and immutable graph revisions.
- Versioned graph serialization, normalization, and unknown-record retention.
- Cycle rejection and type checking.
- Bounds and product inference.
- Stable node, graph-revision, and graph-content identities.
- Transactional patches with base revisions and exact preconditions.
- Nested graph expansion and compound operation templates.
- Dead-node elimination and common-subexpression sharing.
- Optimization metadata and compiled plan representation.

Allowed internal dependencies: `ferrastra-core`.

Must not execute kernels, own caches, retain source pixels, or import operation implementation crates.

### 10.4 `ferrastra-rcandy`

Owns declarative language behavior:

- Tokens, syntax, spans, and typed syntax trees.
- Name, operation-version, and supplied package-lock resolution.
- Type checking against Ferrastra operation descriptors.
- Lowering to canonical `GraphDefinition` and source-map construction.
- Canonical formatting and language diagnostics.

Allowed internal dependencies: `ferrastra-core`, `ferrastra-graph`.

It must not own graph semantics, operation descriptors, evaluation, scheduling,
caches, stores, package acquisition, host policy, model orchestration, Python,
Qt, QPane, or CuteCanvas. Create the crate only when executable parser or
compiler work begins.

### 10.5 `ferrastra-runtime`

Owns evaluation lifecycle:

- Backward demand and forward damage.
- Internal work partitioning and halo planning.
- Intermediate-product cache.
- Multiresolution source selection.
- Latest-only request adoption where requested by the caller.
- Bounded native parallel execution.
- Scratch arenas and memory admission.
- Evaluation traces, provenance, and profiling.

Allowed internal dependencies: `ferrastra-core`, `ferrastra-store`, `ferrastra-graph`.

Runtime invokes operations through traits declared in `ferrastra-core`. It must not directly depend on `ferrastra-raster`, `ferrastra-vector`, or `ferrastra-paint`.

### 10.6 `ferrastra-raster`

Owns canonical pure raster and coverage operations:

- Resampling and transforms.
- Filters and convolution.
- Color and alpha operations.
- Coverage algebra and morphology.
- Compositing and blend kernels.
- Analysis operations.
- Scalar reference and optimized CPU implementations.

Allowed internal dependencies: `ferrastra-core` and, only where required for owned products or scratch, `ferrastra-store`.

Must not own graph planning, runtime scheduling, Python bindings, or Qt adaptation.

### 10.7 `ferrastra-vector`

Owns framework-neutral vector computation:

- Native vector products and spatial indices.
- Path geometry, stroking, clipping, boolean operations, and offsets.
- Bounds and region queries.
- Vector-to-coverage and vector-to-raster operations.
- Cached flattened/tessellated products.

Allowed internal dependencies: `ferrastra-core`, `ferrastra-store`.

Text shaping remains outside Ferrastra initially; shaped glyph outlines may enter as vector products.

### 10.8 `ferrastra-paint`

Owns stateful native editing execution:

- Brush, erase, clone, smudge, heal, dodge/burn, and related sessions.
- Canonical stroke resampling and deterministic jitter.
- Tip projection and coverage.
- Pickup reservoirs and session-local scratch.
- Ordered chunk processing and dirty bounds.

Allowed internal dependencies: `ferrastra-core`, `ferrastra-store`, `ferrastra-raster`.

Must not own CuteCanvas tools, undo, resource selection, or publication policy.

### 10.9 `ferrastra-engine`

Owns facade assembly only:

- First-party operation registry.
- Runtime/store/graph construction.
- Stable high-level Rust API.
- Feature selection for the published engine.

Allowed internal dependencies: implemented Ferrastra computation, store, graph,
runtime, and operation crates. It does not depend on `ferrastra-rcandy`.

No algorithms or planning logic may live here.

### 10.10 `ferrastra-python`

Owns the Python boundary only:

- PyO3 module definitions.
- Python buffer-protocol validation.
- Exception translation.
- Generated operation schemas and stubs.
- The `ferrastra.rcandy` binding and typed Python surface when implemented.
- Opaque handles for graph revisions, stores, products, sessions, and cancellation.

Allowed internal dependencies: `ferrastra-engine`, the minimum supporting
Ferrastra crates, and `ferrastra-rcandy` only for the public language surface.

Only this crate may depend on PyO3 or Python/NumPy binding crates. It must not contain kernels, graph planning, cache policy, or package-specific adapters.

---

## 11. Source-file responsibility standard

Single responsibility is a release gate, not reviewer preference.

### 11.1 Mandatory module declaration

Every production Rust module begins with a module-level documentation block containing:

```rust
//! Responsibility: Build scale-aware Lanczos coefficient tables.
//!
//! Does not own: destination traversal, graph planning, caching, Python bindings,
//! or QPane product policy.
```

Every new or changed QPane/CuteCanvas adapter module keeps the repository’s existing module-docstring standard and states the concern directly.

### 11.2 File-size gates

- **Soft ceiling:** 350 nonblank, noncomment production lines.
- **Hard gate:** 500 nonblank, noncomment production lines.
- Generated files, large static test fixtures, and declarative tables may be excluded.
- A hard-gate exception requires an exact, bounded entry in the owning package's `ARCHITECTURE_WAIVERS.toml`; mixed ownership also requires a linked current debt snapshot.
- Waivers may not be used for files that combine planning, execution, storage, binding, or package-adapter responsibilities.

Line count is not the definition of responsibility, but it is a useful structural alarm.

### 11.3 Forbidden combinations in one production file

A single file must not contain more than one of the following concerns:

- Graph definition or graph mutation.
- Graph compilation or optimization.
- Demand/damage planning.
- Runtime scheduling.
- Cache retention and eviction.
- Source-store mutation.
- Numerical kernel implementation.
- Python binding code.
- QPane Qt adaptation.
- CuteCanvas authoring compilation.
- Operation metadata generation.

### 11.4 Forbidden dumping grounds

Production paths named any of the following are prohibited unless they are generated or contain a narrowly defined public type family:

```text
utils
helpers
common
misc
shared
manager
service
engine.py / engine.rs containing multiple unrelated systems
```

Names such as `coefficient_table`, `damage_propagation`, `product_cache`, or `qimage_adapter` are expected.

### 11.5 Complete extraction rule

When migrating one current responsibility into Ferrastra:

1. Add characterization and numerical-oracle tests.
2. Establish the Ferrastra owner.
3. Migrate every caller in the vertical slice.
4. Delete the old numerical implementation.
5. Delete obsolete tests and public exports.
6. Update ownership documentation and enforcement allowlists.

No compatibility shim is required for internal APIs. Leave the code as though Ferrastra had always been the numerical owner.

---

## 12. Core product model

### 12.1 Product kinds

The initial product model must support:

```rust
pub enum ProductKind {
    Raster,
    Coverage,
    Vector,
    Graphic,
    Scalar,
    Color,
    Transform,
    Metadata,
}
```

Not every product kind needs a complete implementation in the first milestone, but graph and operation contracts must not assume all edges are RGBA images.

### 12.2 Pixel and coverage formats

Ferrastra must use explicit semantic formats, for example:

```rust
pub enum RasterFormat {
    Rgba8PremultipliedEncoded,
    Rgba16PremultipliedLinear,
    Rgba32FloatPremultipliedLinear,
}

pub enum CoverageFormat {
    Coverage8,
    Coverage16,
    Coverage32Float,
}
```

Every format specifies:

- Channel order.
- Channel width and representation.
- Alpha representation.
- Transfer behavior.
- Memory layout and alignment requirements.
- Supported operations and conversions.

The first executable milestone may implement only `Rgba8PremultipliedEncoded` and `Coverage8`, but the type system must preserve the distinction.

### 12.3 Coordinate convention

One convention applies everywhere:

- Integer regions are half-open: `[x, x + width) × [y, y + height)`.
- Pixel samples are located at pixel centers.
- Empty regions are valid no-op requests.
- Negative dimensions are invalid.
- Overflow is checked.
- Floating source rectangles use a documented source-coordinate space.
- Destination sample centers map to source sample centers through one canonical formula.
- Strides use one unit consistently in each public type and are never inferred from buffer length.

The resampling test corpus must lock down half-pixel and tile-phase behavior.

### 12.4 Immutable products

Pure evaluation produces immutable products:

```text
input products + operation + request
    → immutable output product
```

Callers may provide unpublished mutable destination storage for efficiency. That memory becomes an immutable product only after successful completion and atomic publication.

### 12.5 Strong product identity

Use a strong structured or cryptographic content identity. A 256-bit BLAKE3-derived key is the recommended baseline.

A product key includes:

- Semantic operation ID and version.
- Normalized parameters.
- Input product keys.
- Output port.
- Requested region.
- Scale or transform footprint.
- Quality tier.
- Pixel/product format.
- Working color and alpha semantics.
- Time/frame key for time-varying operations.

The Rust crate version is not part of numerical semantics except where a bug fix intentionally creates a new operation semantic version.

---

## 13. Source stores and revisions

Ferrastra eventually provides:

```text
RasterStore
CoverageStore
VectorStore
```

### 13.1 Raster and coverage stores

Required capabilities:

- Sparse zero-default tiled storage.
- Finite or expandable logical bounds.
- Copy-on-write immutable revisions.
- Tile-level sharing across revisions.
- Bounded reads and writes.
- Padded reads outside allocated tiles according to edge policy.
- Content/occupancy bounds.
- Exact damage regions on commit.
- Explicit retained-byte accounting.
- Pinning and leases during evaluation.
- Optional memory-mapped or disk-backed storage later.

The current `SparseRasterGrid`, `ColorRasterSurface`, and coverage-surface behavior are characterization inputs, not permanent native interfaces.

### 13.2 Edit transactions

Native mutation uses explicit transactions:

```rust
let mut edit = raster_store.begin_edit(base_revision)?;
edit.write(region, pixels)?;
let committed = edit.commit()?;

committed.revision;
committed.damage;
committed.retained_bytes;
```

Rules:

- Uncommitted edits are not visible as source revisions.
- Cancellation publishes nothing.
- A commit returns an immutable revision and exact damage.
- CuteCanvas owns the semantic command and history entry.
- Ferrastra owns memory safety, tile sharing, and revision identity.

### 13.3 Vector stores

The aspirational vector store supports:

- Immutable vector revisions.
- Stable object and geometry identity.
- Ordered objects and group/instance relationships.
- Paths and parametric shapes.
- Styles and transforms.
- Spatial indexing and region queries.
- Bounds and hit-test acceleration.
- Shaped glyph-outline products supplied by a text shaper.

---

## 14. Evaluation DAG

### 14.1 Graph definition

A graph definition contains:

- Stable schema version, `GraphRevisionId`, and `GraphContentId`.
- Stable authoring `NodeId` values and named typed ports.
- Operation semantic IDs, versions, and normalized typed parameters with units.
- Typed constants, parameter references, and connections.
- Declared graph inputs and named outputs.
- Source revision handles, explicit coordinates, seeds, and capabilities.
- Exposed effect parameters and optional compound definitions.
- Authoring metadata segregated from computational identity.

Graph definitions are immutable once committed and serialize canonically.
Unavailable operation versions and unknown records round-trip without loss but
cannot compile for evaluation. Rust, Python, R-Candy, CuteCanvas, and structured
tools construct this one schema. `RCANDY_DESIGN.md` defines the coordinated
source artifact without making source executable authority.

### 14.2 Graph editing

CuteCanvas must not resend an untyped full graph on every parameter drag.
Ferrastra exposes typed graph transactions and serializable `GraphPatch` values:

```python
edit = graph.begin_edit()
edit.set_parameter(blur_node, "sigma", 12.0)
edit.replace_source_revision(source_node, new_revision)
next_graph = edit.commit()
```

Every patch names its base `GraphRevisionId` and exact preconditions. Validation
and commit are atomic: stale or invalid patches return structured diagnostics or
conflicts and publish nothing. Accepted patches preserve unchanged `NodeId`
values. The runtime retains unchanged compiled state and caches by computational
identity. Whole-graph replacement remains an explicit import operation rather
than the only editing mechanism.

### 14.3 Graph validation

Compilation rejects:

- Cycles.
- Missing nodes or ports.
- Type-incompatible connections.
- Unsupported format, alpha, color, edge, or quality combinations.
- Invalid parameter ranges.
- Invalid parameter units, coordinates, or deterministic-seed contracts.
- Unbounded operations without declared domain policy.
- Operations lacking demand/damage behavior.
- Source revisions unavailable to the selected runtime.
- Capabilities unavailable to the selected execution contract.

Retention and executability are separate states: serialization preserves an
unknown operation record, while compilation reports its unavailable semantic
version with stable node and port targets.

### 14.4 Compiled execution graph

Compilation performs, where valid:

- Type and output inference.
- Bounds inference.
- Dead-node elimination.
- Nested graph expansion.
- Common-subexpression sharing.
- Constant folding.
- Transform folding.
- Color/alpha conversion insertion.
- Rasterization-boundary placement.
- Point-operation fusion.
- Cache-boundary selection.
- Scale and multiresolution planning.
- Backend selection.
- Stable execution-task identities.

Compilation is separate from evaluation. Kernel code must not mutate the graph.

---

## 15. Spatial planning: backward demand and forward damage

Every operation must define both.

### 15.1 Backward demand

Given an output request, determine required upstream inputs.

Examples:

```text
Curves:
    input region = output region

Gaussian blur:
    input region = output region expanded by kernel support

Affine transform:
    input region = inverse-mapped output footprint + sampler support

Composite:
    aligned output region from all contributing inputs

Vector rasterize:
    vector objects intersecting requested region + antialiasing support
```

### 15.2 Forward damage

Given changed input region, determine invalid downstream regions.

Examples:

```text
Curves:
    output damage = input damage

Gaussian blur:
    output damage = input damage expanded by support

Affine transform:
    output damage = forward-mapped input damage + filter support

Vector rasterize:
    output damage = raster bounds of old and new changed geometry
```

### 15.3 Region sets

Planning should operate on normalized region sets, not only one rectangle. The runtime may coalesce regions for cost reasons, but must retain exact validity and damage semantics.

### 15.4 Cache subtraction

Before propagating demand upstream, subtract cached valid regions precisely. Avoid all-or-nothing cache decisions that recompute a complete requested rectangle when only a small missing region exists.

---

## 16. Internal tiling and QPane integration

QPane and Ferrastra tile grids remain independent.

### QPane tile ownership

QPane decides:

- Physical viewport tile geometry.
- Visible, guard, overview, continuity, detail, and prefetch lanes.
- Urgency and cancellation policy.
- Qt presentation caching.
- Atomic adoption of one viewport generation.

### Ferrastra tile ownership

Ferrastra decides:

- Internal source and intermediate tile sizes.
- Operation halos and overlap.
- Cache locality.
- SIMD-friendly row/block geometry.
- Parallel work granularity.
- Scratch-memory fit.
- Coalescing of neighboring requests.

An Ferrastra adapter implements QPane’s `RenderTileBatchSource` or a successor public protocol. One QPane request batch becomes one generic Ferrastra output batch. Ferrastra may evaluate the batch using any internal partitioning but returns all requested products coherently.

QPane’s current `RenderTileWorkCoordinator` remains the presentation-level work owner during the first migrations.

---

## 17. Runtime, scheduling, memory, and publication

### 17.1 CPU-first execution

The CPU implementation is always available and defines canonical correctness.

Each important operation should eventually have:

- Scalar reference implementation.
- Portable optimized implementation.
- Runtime CPU feature detection.
- AVX2/AVX-512 specialization where useful.
- ARM NEON specialization.
- Operation-specific parallel thresholds.
- Reusable coefficient and scratch storage.

### 17.2 Caller-supplied execution budget

Ferrastra accepts:

```rust
pub struct ExecutionBudget {
    pub threads: usize,
    pub scratch_bytes: usize,
    pub cancellation: CancellationToken,
    pub deadline: Option<Instant>,
}
```

No operation creates an unconstrained global pool. Nested parallelism must be explicit and budget-aware.

### 17.3 Cancellation

- Cancellation uses a native atomic token.
- Long kernels poll at a documented bounded interval.
- No Python callback is invoked from inner loops.
- Cancellation is distinct from failure.
- Cancelled exact products are never published.
- Stateful sessions leave their last committed source revision valid.

### 17.4 Memory

- Destination and scratch requirements are estimated before execution.
- Scratch storage is reusable and caller/runtime budgeted.
- Operations do not silently allocate multiple complete images.
- Caches expose usage, pinned, evictable, and in-flight byte counts.
- QPane’s global cache coordinator should eventually budget Ferrastra cache consumers.

### 17.5 Atomic publication

A pure output or requested batch is published only after all required output is complete and validated.

If cancellation, stale generation, or failure occurs, publish nothing from that generation.

---

## 18. Cache model

Ferrastra’s cache is regional, multiscale, multiquality, and content addressed.

A cache entry is identified by:

```text
node/product identity
output port
region
scale/footprint
quality
format
working-space semantics
```

A cache value records:

- Immutable product handles.
- Exact valid regions.
- Retained bytes.
- Pin count.
- Source/product provenance.
- Generation and evaluation timing.
- Backend and operation implementation used.

Required behavior:

- Multiple spatial entries per node.
- Multiple scales and quality tiers.
- Shared-subgraph reuse.
- Partial validity and exact subtraction.
- Atomic batch insertion.
- Global byte budget integration.
- Optional persistent disk cache later.

QPane’s presentation cache remains distinct because it retains Qt-native products and DPR-specific state.

---

## 19. Quality model

Use deterministic quality tiers:

```rust
pub enum QualityTier {
    Interactive,
    Exact,
    Export,
}
```

Rules:

- Quality participates in product identity.
- Exact means the canonical operation contract.
- Interactive approximations are explicitly declared per operation.
- Export may use higher precision or stricter error policy but may not silently change document semantics.
- No probabilistic or random quality selection.

QPane may continue to use Qt retained-frame transforms for immediate navigation. Ferrastra interactive or exact products replace those previews when ready.

---

## 20. Operation SDK

Adding a correct operation should require declaring semantics, not rebuilding engine plumbing.

A first-party operation declaration should generate or register:

- Semantic ID and version.
- Exposure class and stable category.
- Typed ports.
- Parameter schema and normalization.
- Defaults, hard limits, recommended ranges, units, and enum values.
- Supported formats, alpha, working spaces, edge modes, and quality tiers.
- Coordinate, deterministic-seed, demand, damage, support, displacement, and
  locality behavior.
- Capability requirements and request-sensitive cost and memory analysis.
- Graph-builder method.
- Cache-key serialization.
- Python binding and stub.
- Summary, detailed behavior, use cases, composition guidance, warnings,
  inappropriate uses, and control hints.
- Conformance-test scaffold.
- Benchmark registration.

Conceptually:

```rust
#[ferrastra::operation(
    id = "ferrastra.resample.lanczos3",
    version = 1,
    category = Transform,
    inputs(source = Raster),
    outputs(result = Raster),
    deterministic = true,
    tile_equivalent = true
)]
pub struct Lanczos3 {
    pub edge: EdgeMode,
    pub working_space: WorkingSpace,
}
```

The descriptor separates computation from authoring metadata. Computation fields
govern validation, identity, compilation, and conformance. Prose, examples, tags,
search data, translated labels, and control layout guide humans and authoring
tools without changing products. CuteCanvas decides final UI presentation.

Every entry point is classified as `public_graph`, `host_only`, `session_only`,
or `internal`. R-Candy and structured graph tools expose only `public_graph`
operations. Stateful edit sessions, runtime administration, stores, schedulers,
caches, and host resource policy never masquerade as graph operations.

### 20.1 Operation categories

Provide focused category helpers:

- `PointOperation`
- `AreaOperation`
- `TransformOperation`
- `CompositeOperation`
- `GeneratorOperation`
- `AnalysisOperation`
- `VectorOperation`

Stateful tools use a separate session API rather than pretending to be pure graph filters.

### 20.2 Compound operations

Complex effects may compile to internal graph templates.

Example drop shadow:

```text
source alpha
    → dilate
    → blur
    → colorize
    → offset
    → composite beneath source
```

The user may see one effect while Ferrastra evaluates reusable primitive nodes.

---

## 21. Resampling family

Ferrastra’s resampling system is a shared operation family, not unrelated functions.

```rust
pub enum ResampleFilter {
    Nearest,
    Bilinear,
    Area,
    BicubicMitchell,
    Lanczos2,
    Lanczos3,
    NoHalo,
    LoHalo,
}
```

Each canonical algorithm retains a distinct semantic operation identity.

### 21.1 Two transform classes

#### Axis-aligned resize

Used for ordinary scale changes and pyramid products. Usually separable horizontal and vertical processing.

#### General transform sampler

Used for rotation, skew, anisotropic scale, perspective, and local nonlinear warps. Requires local transform/Jacobian-aware sampling and often elliptical weighted averaging.

Do not force both into one implementation with ambiguous semantics.

### 21.2 Lanczos-3

Canonical operation:

```text
ferrastra.resample.lanczos3@1
```

Must define:

- Pixel-center mapping.
- Three-lobe sinc window.
- Scale-aware support widening for minification.
- Coefficient normalization.
- Edge behavior.
- Premultiplied-alpha handling.
- Working-space behavior.
- Integer rounding.
- Destination crop and tile semantics.

Performance requirements:

- Polyphase coefficient tables.
- Separable passes.
- Reusable row scratch.
- SIMD channel processing.
- Coefficient reuse across same-scale request batches.
- Identity and exact-integer-transform fast paths.
- Pyramid/source-level selection for severe reduction.
- Exact tile-seam equivalence.

A separate future operation such as `ferrastra.resample.ewa-lanczos3@1` handles general affine/perspective transforms.

### 21.3 NoHalo

Canonical operation:

```text
ferrastra.resample.nohalo@1
```

User-visible objective:

- Strong edge preservation.
- Locally bounded reconstruction.
- Minimal ringing.
- Good arbitrary-transform behavior.
- Anisotropic minification support.

Design requirements:

- Shared Jacobian-adaptive sampler engine.
- Local inverse-Jacobian analysis per affine tile or adaptive microtile.
- Explicit pyramid/source-level selection from transform singular values.
- Dynamic support rather than one fixed source window.
- Locally bounded reconstruction during magnification.
- Elliptical weighted averaging during minification.
- SIMD-friendly span traversal.
- Premultiplied-alpha and working-space contracts.
- A distinct nonnegative coverage variant.

Ferrastra must implement this independently from prior source code and validate it against a broad visual/numerical corpus. Matching another engine byte-for-byte is not the goal.

### 21.4 LoHalo

Canonical operation:

```text
ferrastra.resample.lohalo@1
```

User-visible objective:

- Sharper reconstruction than NoHalo.
- Controlled negative-lobe behavior.
- Significantly less visible ringing than ordinary sharp cubic or Lanczos under difficult transforms.

Design requirements:

- Shared adaptive sampling engine with NoHalo.
- Explicit sharpening/reconstruction curve and EWA downsampling definition.
- Dynamic support and pyramid selection.
- Deterministic transition across magnification/minification axes.
- Explicit gamut, alpha, and working-space behavior.
- SIMD and block-coherent transform planning.
- Objective tests for overshoot, undershoot, local bounds, aliasing, and acutance.

NoHalo and LoHalo are explicit operation choices. Any `Auto` policy belongs to QPane or CuteCanvas and must record the selected algorithm in product keys and diagnostics.

---

## 22. Color to Alpha

Color to Alpha must be a first-class point-operation family, not a UI-specific effect.

The operation solves an inverse compositing problem against a target color and should support useful multi-output products.

Required operations:

### Classic behavior

```text
ferrastra.color.color-to-alpha-classic@1
```

- Familiar encoded-RGB behavior.
- Explicit target color.
- Explicit transparency/opacity thresholds.
- Stable handling near channel extrema.
- Original alpha incorporated explicitly.

### Linear-light behavior

```text
ferrastra.color.color-to-alpha-linear@1
```

- Declared linear working space.
- Inverse compositing solved in that space.
- Premultiplied linear output.
- Conversion only at explicit graph boundaries.

### Matte extraction

A multi-output operation that returns:

- Decontaminated foreground raster.
- Coverage matte.

Perceptual color-distance/tolerance should be a separate primitive or compound branch, not an ambiguous mode inside the inverse-compositing kernel.

Color to Alpha is an early implementation target because it validates:

- Point-operation fusion.
- Explicit color and alpha semantics.
- Multi-output nodes.
- Parameter schemas.
- Raster and coverage products.

---

## 23. Raster and coverage operation families

Ferrastra must eventually include at least the following canonical families.

### Resampling and transforms

- Nearest.
- Bilinear.
- Area reduction.
- Mitchell bicubic.
- Lanczos2 and Lanczos3.
- NoHalo and LoHalo.
- EWA resampling.
- Affine and perspective transforms.
- Mesh/displacement transforms later.

### Point color and alpha

- Premultiply/unpremultiply.
- Encoded/linear conversion for supported working formats.
- Exposure.
- Levels.
- Curves.
- Color matrix.
- Channel mixer.
- Hue/saturation.
- White balance.
- LUT application.
- Threshold and posterize.
- Color to Alpha and matte extraction.

### Area filters

- Gaussian blur.
- Box blur.
- Motion blur.
- Sharpen/unsharp mask.
- General convolution.
- Sobel/edge detection.
- Median/rank filters.
- Edge-aware blur as a later advanced operation.

### Coverage

- Add, subtract, intersect, replace, multiply, and constrain.
- Invert and threshold.
- Feather.
- Grow/shrink.
- Dilate/erode.
- Distance transform.
- Connected components.
- Occupancy and bounds.
- Coverage-specific resampling.

### Compositing

- Porter-Duff operators.
- Complete documented blend-mode set.
- Mask application.
- Opacity.
- Group isolation.
- Clipping-group semantics.
- Adjustment/backdrop composition.

### Analysis

- Histograms.
- Min/max/mean.
- Image difference.
- Content hashes/signatures.
- Connected-region analysis.
- Color sampling and statistical outputs.

---

## 24. Vector engine

Raster performance alone does not satisfy Ferrastra’s specification.

The aspirational vector engine provides:

- Immutable vector products and revisions.
- Stable object, geometry, and style identities.
- Spatial indices and region queries.
- Paths and parametric shapes.
- Transforms.
- Stroke expansion.
- Offset paths.
- Boolean operations.
- Intersections and clipping.
- Simplification and flattening.
- Bounds and hit-test acceleration.
- Instances/repeated geometry.
- Vector-to-coverage.
- CPU antialiased tile rasterization.
- Cached flattened/tessellated products.

The graph preserves vectors as long as possible:

```text
VectorSource
    → VectorTransform
    → Boolean
    → Stroke
    → VectorProduct
```

A raster-only operation inserts an explicit boundary:

```text
VectorProduct
    → Rasterize(region, scale)
    → GaussianBlur
    → RasterProduct
```

Text shaping may remain Qt-owned initially:

```text
Qt text shaping
    → immutable positioned glyph outlines
    → Ferrastra VectorProduct
```

QPane may present vector-preserving products through Qt while Ferrastra supplies exact raster products for filtered branches.

---

## 25. Stateful native edit sessions

Pure graph operations are immutable. Painting and smudge are ordered stateful edits and use a separate API.

### 25.1 Session ownership

CuteCanvas owns:

- Tool semantics.
- Pointer and pressure interpretation.
- Target resource and selection policy.
- Stroke begin/update/end.
- Undo grouping.
- Publication and document revision adoption.

Ferrastra owns:

- Canonical stroke resampling.
- Deterministic jitter.
- Dab generation.
- Tip projection.
- Sampling and color mixing.
- Premultiplied compositing.
- Constraint coverage.
- Scratch and pickup state.
- Dirty bounds.
- Ordered chunk execution.

### 25.2 Chunk equivalence

The following must produce identical pixels and session state:

```text
process(samples[0:N]); process(samples[N:M])
```

and:

```text
process(samples[0:M])
```

for the same initial state and source conditions.

### 25.3 Commit model

One logical stroke commits one new source revision. The DAG then invalidates and reevaluates only affected downstream regions.

Do not retain every dab as a permanent graph node unless a future explicitly procedural brush feature chooses that representation.

---

## 26. Qt integration boundary

Ferrastra requires Qt adapters but does not contain Qt.

### 26.1 QPane adapter

`qpane/ferrastra/` owns:

- Mapping detached `QImage` storage to supported Ferrastra buffer views.
- Validating format, stride, lifetime, and implicit sharing.
- Allocating unpublished destination images.
- Converting completed Ferrastra products to QImage/QPixmap presentation products.
- QPane-specific product and cache identity adaptation.
- Mapping QPane cancellation and execution budget into Ferrastra.

It does not choose operation semantics beyond QPane presentation policy.

### 26.2 CuteCanvas adapter

`cutecanvas/ferrastra/` owns:

- Compiling document resources/effects into graph definitions.
- Mapping editable source handles to Ferrastra revisions.
- Translating selection/mask and raster data contracts.
- Adopting native edit-session results into history and resource state.
- CuteCanvas-specific errors and diagnostics.

It does not contain kernels or QPane presentation behavior.

### 26.3 QImage rules

- Ferrastra operates on CPU-accessible buffers, never QPixmap.
- Read-only QImage views are borrowed only for the duration of one call and are not retained.
- Writable destination QImages are detached, unpublished, and not concurrently accessed.
- GUI-thread publication happens after worker completion.
- Qt remains responsible for file decode/encode, ICC/profile boundaries, display conversion, and widget presentation initially.

---

## 27. Current-code migration map

This section identifies current responsibilities that Ferrastra should absorb. Symbols and file paths are from the current monorepo snapshot.

### 27.1 Phase-one exact resampling

| Current location | Current behavior | Final owner/action |
|---|---|---|
| `packages/qpane/src/qpane/rendering/pyramid.py` | Generates pyramid levels with `QImage.scaled(..., SmoothTransformation)` | QPane retains level policy/cache; Ferrastra produces exact level pixels through `Lanczos3@1` or selected filter |
| `packages/qpane/src/qpane/raster/affine_resampling.py` | Generic affine raster projection through QPainter | Replace implementation with Ferrastra transform operation; eventually remove generic numerical ownership from QPane SDK |
| `packages/qpane/src/qpane/raster/image_conversion.py` | `*_at_size` helpers combine buffer conversion and Qt resampling | Split conversion from resampling; remove scaling behavior from conversion helpers |
| `packages/cutecanvas/src/cutecanvas/coverage/projection.py` | Coverage NumPy → QImage → QPainter transform → NumPy | CuteCanvas adapter calls Ferrastra coverage transform directly |
| `packages/cutecanvas/src/cutecanvas/editor/fragment_projection.py` | Commits transformed raster and coverage through QPane/Qt resampling | CuteCanvas owns command; Ferrastra owns exact raster and coverage projection |
| `packages/qpane/src/qpane/rendering/layer_rasterization.py` and `packages/cutecanvas/src/cutecanvas/placed/rasterization.py` | Generic editable placed-image rasterization through QPainter | CuteCanvas calls Ferrastra directly; QPane retains mixed-scene rasterization only |
| `packages/cutecanvas/src/cutecanvas/raster/color_surface.py` | Strided sparse sample followed by Qt smoothing | Exact sampled products come from Ferrastra; any crude preview is explicitly interactive only |
| `packages/cutecanvas/src/cutecanvas/coverage/raster_sampling.py` | Strided coverage and QPainter scaling | Ferrastra coverage sampling operation |

### 27.2 Foundational numerical migration

| Current location | Responsibility to move |
|---|---|
| `packages/cutecanvas/src/cutecanvas/coverage/operations.py` | Coverage algebra |
| `packages/qpane/src/qpane/hybrid/evaluation.py` | Coverage combine and feather kernels; retain/split Qt vector-path rasterization initially |
| `packages/cutecanvas/src/cutecanvas/fill/flood.py` | Flood fill and contiguous traversal |
| `packages/cutecanvas/src/cutecanvas/masks/image_ops.py` | Connected components, morphology, bounds and mask image operations |
| `packages/cutecanvas/src/cutecanvas/raster/pixel_translation.py` | Selection-aware pixel translation and compositing |
| `packages/cutecanvas/src/cutecanvas/raster/content_bounds.py` | Occupancy/content-bound kernels |
| `packages/cutecanvas/src/cutecanvas/raster/revision_reader.py` | Native sampling/interpolation primitives where numerical |

### 27.3 Native source-store migration

| Current location | Final direction |
|---|---|
| `packages/cutecanvas/src/cutecanvas/raster/sparse_grid.py` | Characterization specification for native sparse raster/coverage stores |
| `packages/cutecanvas/src/cutecanvas/raster/color_surface.py` | Python facade over Ferrastra RasterStore revisions |
| `packages/cutecanvas/src/cutecanvas/coverage/surface.py` | Python facade over Ferrastra CoverageStore revisions |
| Raster and coverage snapshots/history | Retain CuteCanvas semantic history; use immutable native revision handles and bounded patch products |

### 27.4 Native painting migration

| Current location | Final direction |
|---|---|
| `packages/cutecanvas/src/cutecanvas/painting/dab_engine.py` | Ferrastra canonical stroke resampling/dab generation |
| `packages/cutecanvas/src/cutecanvas/painting/compositor.py` | Ferrastra paint compositing |
| `packages/cutecanvas/src/cutecanvas/painting/tip_projection.py` | Ferrastra tip projection/cache |
| `packages/cutecanvas/src/cutecanvas/painting/rendering.py` | Remove split QPainter/NumPy numerical authority; CuteCanvas keeps orchestration |
| `packages/cutecanvas/src/cutecanvas/painting/clone_compositor.py` | Ferrastra clone session/kernel |
| Future smudge | Ferrastra stateful smudge session with CuteCanvas tool owner |

### 27.5 Mask and coverage presentation

Move only canonical numerical work, not presentation ownership.

| Current location | Final direction |
|---|---|
| `packages/cutecanvas/src/cutecanvas/masks/file_io.py` | Qt decodes; CuteCanvas chooses fit policy; Ferrastra resamples into CoverageStore |
| `packages/cutecanvas/src/cutecanvas/masks/render_products.py` | Exact coverage scaling from Ferrastra; retain Qt presentation product creation |
| `packages/cutecanvas/src/cutecanvas/masks/render_cache.py` | Retain presentation cache; replace exact scaling/math with Ferrastra products |
| `packages/cutecanvas/src/cutecanvas/masks/rasterizer.py` | Ferrastra coverage colorization/border primitives; CuteCanvas owns style |

### 27.6 Later vector and composition migration

| Current location | Final direction |
|---|---|
| `packages/qpane/src/qpane/vector/model.py` | Candidate semantic basis for Ferrastra vector products; QPane public API becomes adapter over framework-neutral engine values |
| `packages/qpane/src/qpane/vector/drawing.py` | Retain Qt presentation initially; move spatial query/path computation/rasterization to Ferrastra over time |
| `packages/qpane/src/qpane/vector/tile_source.py` | Ferrastra native vector tile evaluation; QPane retains demand and Qt adaptation |
| `packages/cutecanvas/src/cutecanvas/resources/composition_rendering.py` | Eventually evaluate compiled Ferrastra composition roots instead of recursively rasterizing a QPane scene |
| `packages/qpane/src/qpane/rendering/scene_region.py` | Retain mixed QPane scene rasterization until full Ferrastra composition DAG replaces canonical document composition |

### 27.7 Deferred shared-edge resize migration

The first Shared Edge Resize implementation remains within the current product
boundaries. CuteCanvas owns edge eligibility, common-corner rail constraints,
snapping policy, participant selection, the coupled transient mapping set,
commands, persistence, and history. QPane owns generic affine, projective, and
bounded piecewise mapping, immutable scene presentation, demand, hit testing,
damage, and Qt rendering. The initial implementation does not depend on
Ferrastra.

After the corresponding native geometry and source-store contracts exist,
Ferrastra absorbs only the source-neutral numerical work:

- Robust finite-line projection, collinearity, overlap, and support-extent
  analysis.
- Source-neutral collinear-rail analysis, constrained endpoint projection,
  boundary-vertex insertion, and deterministic finite-cage triangulation for
  fixed-opposite-end pivots.
- Revision-keyed straight-boundary products for native raster, coverage, and
  vector sources.
- Exact raster and coverage resampling for an explicit CuteCanvas bake,
  rasterize, merge, or flatten command.

Ferrastra never receives layer identities, snap priorities or thresholds, tool
state, locks, participant-selection policy, preview ownership, or undo semantics.
Each numerical migration characterizes the existing result, switches every
consumer through its product-owned adapter, removes the replaced implementation,
and activates an ownership check against duplicate numerical authority.

---

## 28. Responsibilities that remain outside Ferrastra

The following current paths should not be moved wholesale into Rust:

### QPane/Qt presentation

- `rendering/widget_surface.py`
- `rendering/navigation_buffer.py`
- `rendering/frame_buffer_presenter.py`
- `rendering/item_compositor.py` initially
- `rendering/presentation_effect_compositor.py` for transient effects
- QWidget/input/overlay modules

### CuteCanvas editor semantics

- Document/resource/layer stores as semantic owners.
- Tools and input interpretation.
- Shared-edge eligibility, snapping policy, participant selection, and
  coupled parallel-resize and endpoint-pivot constraints.
- History and undo labels.
- Operation availability policy and locks.
- Persistence and migrations.
- Layer inspector and application UI.

### Qt boundary services

- File decode/encode.
- ICC/profile interpretation and display conversion initially.
- Native text shaping initially.
- Immediate retained-frame zoom/pan previews.

---

## 29. Architectural enforcement tests

Architecture gates must be merged before the first production kernel.

### 29.1 Repository checker

Use `tools/check_architecture.py`. It must fail CI for:

- Forbidden crate dependency edges according to Section 10.
- Any computation, graph, engine, or runtime dependency on `ferrastra-rcandy`.
- Any R-Candy dependency on runtime, stores, operation implementations, Python,
  Qt, QPane, CuteCanvas, or host policy.
- Qt dependencies or `PySide6` imports anywhere in Ferrastra.
- PyO3/Python dependencies outside `ferrastra-python`.
- QPane or CuteCanvas types referenced by Ferrastra.
- Direct `ferrastra` imports outside `qpane/ferrastra/` and `cutecanvas/ferrastra/`, except public package facades/tests.
- CuteCanvas imports of QPane private modules; extend the existing Trinity boundary checker.
- Generic dumping-ground module names.
- Production files over the hard line-count gate without an active waiver.
- Missing module responsibility declarations.
- Unsafe modules without `SAFETY.md` ownership and allowlist entries.
- Use of a global Rayon pool or equivalent unbounded global parallelism.
- Operation definitions missing semantic IDs, versions, exposure class, complete
  computational contracts, or required authoring metadata.

Add `tests/test_ferrastra_architecture.py` to characterize the checker with deliberate invalid fixtures, following the existing `test_trinity_contracts.py` style.

### 29.2 Canonical-operation ownership checker

Add `tools/check_ferrastra_ownership.py` with migration-stage allowlists.

As operations migrate, it must ban old numerical implementations. Examples:

- After pyramid migration, exact QPane pyramid paths may not call `QImage.scaled`.
- After affine migration, CuteCanvas may not import `AffineImageResampler` from QPane.
- After conversion split, `numpy_to_qimage_*_at_size` no longer exists.
- After paint migration, canonical document painting may not use QPainter ellipses/gradients or independent NumPy compositing.
- After coverage migration, coverage algebra exists only in Ferrastra.

Temporary presentation paths remain explicitly allowlisted by path and reason.

### 29.3 Crate compile-boundary tests

- `ferrastra-core` compiles with no std features that require Python or application frameworks.
- Operation implementation crates compile without `ferrastra-runtime`.
- `ferrastra-graph` compiles without operation implementation crates.
- `ferrastra-graph`, `ferrastra-runtime`, and `ferrastra-engine` compile without
  `ferrastra-rcandy`, and `ferrastra-rcandy` compiles without runtime or host
  crates once it exists.
- `ferrastra-runtime` tests use injected test operations, proving no direct dependency on first-party raster/vector crates.

### 29.4 Public API and packaging tests

Extend existing packaging contracts to verify:

- `ferrastra` builds and installs independently.
- QPane declares a bounded Ferrastra compatibility range once it depends on Ferrastra.
- CuteCanvas declares bounded QPane and Ferrastra ranges.
- Each wheel discovers only its own Python package.
- Ferrastra’s stubs and PEP 561 marker are packaged.
- QPane installs without CuteCanvas.
- Ferrastra installs without QPane, CuteCanvas, or Qt.
- Isolated-wheel integration uses built artifacts, not sibling source imports.

---

## 30. Numerical and runtime conformance

Every operation must enter a common conformance suite.

Required categories:

- Scalar/reference oracle tests.
- Golden fixtures.
- Randomized property tests.
- Tight and padded strides.
- Cropped and offset views.
- Empty and one-pixel regions.
- Every supported edge mode.
- Transparent pixels with nonzero hidden RGB.
- Encoded and linear working modes.
- Monolithic versus tiled equivalence.
- Horizontal, vertical, and four-way tile seams.
- Different valid thread budgets.
- Cancellation at multiple progress points.
- Memory-estimate and scratch-budget enforcement.
- Deterministic product keys.
- FFI fuzzing and panic containment.
- Cross-platform output contract.
- Canonical graph round trips and unknown-operation preservation.
- Rust-builder, Python-builder, R-Candy-lowering, and structured-tool graph
  equivalence for shared fixtures.
- Graph-content identity isolation from prose and authoring metadata.
- Transactional patch atomicity, stale-base rejection, and unaffected-branch
  product-key preservation.

### 30.1 Sampler corpus

Lanczos3, NoHalo, and LoHalo require a shared corpus containing:

- One- and two-pixel inputs.
- Checkerboards and repeated high-frequency patterns.
- Fine diagonals and curves.
- Text and line art.
- High-contrast luminance and chroma edges.
- Premultiplied transparency edges.
- Rotation, shear, anisotropic scale, and perspective.
- Severe minification.
- Exact tile boundaries.

Track:

- Aliasing energy.
- Overshoot and undershoot.
- Local-bound violations.
- Ringing extent.
- Edge acutance.
- Structural similarity.
- Throughput and latency.
- Scratch and retained bytes.

External engines may be comparison oracles, not compatibility requirements.

---

## 31. Performance standard

Performance budgets are product contracts and must be measured on documented reference hardware.

The first implementation milestone must establish a checked-in benchmark manifest containing:

- Reference CPU and architecture.
- Compiler profile and feature flags.
- Input formats and dimensions.
- Thread and memory budgets.
- p50/p95/p99 limits.
- Maximum allocation/scratch limits.
- Cancellation-latency limits.

Required benchmark families:

### Resampling

- 75%, 50%, 25%, and severe minification.
- 1080p, 4K, and larger output products.
- Transparent edges.
- One tile versus batch.
- Cached versus uncached coefficients and source levels.

### Regional evaluation

- Small visible region from a very large sparse source.
- Overlapping neighboring requests.
- Partial cache hit with small missing region.
- Damage propagation through multi-node graphs.

### Painting

- Ordinary and very large brush diameters.
- Soft and textured tips.
- Clone and smudge chunks.
- p95/p99 chunk time and unpublished queue depth.

### Vector

- Large object counts with small requested region.
- Path boolean/stroke operations.
- Rasterization throughput and region-query scaling.

Do not relax a budget to land an implementation. Profile and fix the authoritative owner.

---

## 32. Explainability and diagnostics

Ferrastra must make performance and correctness inspectable.

Validation, compilation, patch, analysis, and execution failures use structured
diagnostics with stable codes; severity; graph, node, port, parameter, package,
and optional frontend source-span targets; expected and actual values; concise
text; related records; and safe machine-readable repairs where available.
Frontend source spans annotate Ferrastra targets and never enter graph identity.

For any product, the runtime can report:

- Graph revision.
- Source revisions and product provenance.
- Nodes executed and skipped.
- Cache hits, misses, and missing regions.
- Requested and required input regions.
- Internal tile/work partition.
- Source pyramid/mipmap level selected.
- Sampler and backend chosen.
- Operations fused.
- Pixels and bytes read/written.
- Scratch and retained-byte peaks.
- Thread budget and parallelism used.
- Cancellation or stale-generation reason.
- Per-operation timing.

Public developer tooling should eventually expose:

```python
compiled.explain(request)
compiled.dump_graph()
compiled.profile(request)
runtime.cache_report()
runtime.product_provenance(product_key)
```

QPane and CuteCanvas diagnostics should adapt these records rather than reproduce them.

Before execution, request-aware analysis accepts graph output, region, scale,
quality, format, capabilities, execution budget, and host limits. It reports
locality, support, displacement, input expansion, required capabilities,
dominant work, duplicated expensive branches, avoidable conversions, possible
fusion, intermediate and retained memory, and interactive-quality availability.
The result is a deterministic admission input with explicit assumptions, not an
exact wall-clock prediction. Imported and generated graphs pass authoring checks,
Ferrastra validation, and host admission as distinct gates.

---

## 33. Implementation phases

Each phase is a complete architectural slice with exit criteria. Do not merge partial migrations that leave two canonical owners.

### Phase 0 — Charter and enforcement

Deliver:

- This design document in the repository.
- `RCANDY_DESIGN.md` adopted as the normative authoring-language charter and
  reconciled with product, crate, identity, admission, and phase boundaries.
- Ferrastra ownership sections added to root and package `AGENTS.md` files.
- Rust workspace skeleton.
- `check_architecture.py` and characterization tests.
- Crate dependency allowlist.
- Module responsibility and line-count gates.
- Licensing/header support for Rust files.
- CI jobs for formatting, Clippy, Rust tests, architecture checks, and isolated Python wheel builds.
- Non-production graph, descriptor, diagnostic, patch, unknown-record, and
  cross-frontend fixtures sufficient to verify the planned contracts without
  exposing speculative production APIs.

Exit criteria:

- No production behavior changes.
- No parser, R-Candy crate, production graph API, placeholder operation, or
  language-server surface.
- Existing QPane/CuteCanvas suite passes.
- Deliberate architecture violations fail tests.
- A new engineer can identify the owner and allowed dependencies of every Ferrastra crate.

### Phase 1 — Typed spatial graph baseline

Implement:

- Core IDs, regions, transforms, formats, quality, alpha, color, and edge contracts.
- Operation semantic identity, exposure class, complete descriptor, and trait.
- Versioned typed `GraphDefinition`, `NodeId`, `GraphRevisionId`,
  `GraphContentId`, and immutable graph revisions.
- Typed values and units, canonical serialization and normalization, exposed
  parameters, and unknown-record preservation.
- Cycle/type/unit/capability validation with stable structured diagnostics.
- Transactional `GraphPatch` with base revisions and preconditions.
- Request-analysis schema for capability, locality, cost, and memory admission.
- Minimal compiled plan.
- One native raster source product.
- Backward demand and forward damage for source and identity/pass-through operations.
- Runtime with cancellation, memory budget, product publication, and trace.
- Product-key generation.
- Rust and Python graph construction and serialization parity.

First executable graph:

```text
RasterSource → Identity → Output
```

Exit criteria:

- Regional request returns exact source pixels.
- Damage is propagated correctly.
- Product identity is deterministic.
- Runtime and operation implementation crates remain decoupled.
- Equivalent Rust and Python fixtures normalize to the same graph content ID.
- Authoring metadata changes do not change graph content or product identity.
- Invalid patches reject atomically and unknown operations round-trip unchanged.

### Phase 2 — Lanczos3 vertical slice

Implement:

```text
RasterSource → Lanczos3@1 → Output
```

Deliver:

- Scalar reference resampler.
- Optimized CPU Lanczos3.
- Required-source-region planning.
- Exact tile-seam equivalence.
- Premultiplied-alpha and working-space contracts.
- Coefficient/scratch reuse.
- Python binding.
- QPane QImage adapter.
- QPane Ferrastra-backed tile/source adapter.

Migrate QPane pyramid generation as the first production consumer.

Delete the old exact Qt pyramid scaling path in the same vertical slice.

Exit criteria:

- Existing pyramid lifecycle and revision tests pass.
- New numerical and seam tests pass on all supported platforms.
- Interactive QPane navigation does not regress.
- Repeated pyramid scales reuse products/coefficients.
- Isolated Ferrastra and QPane wheels pass integration.

### Phase 3 — Complete current exact-resampling ownership migration

Migrate and delete old implementations for:

- QPane affine raster projection.
- QPane conversion helpers that scale.
- CuteCanvas coverage projection.
- CuteCanvas floating-fragment projection.
- Placed-image rasterization.
- Sparse editable-raster exact minification.
- Sparse coverage exact sampling.
- Mask import exact resampling.

Introduce coverage-specific resampling rather than using photographic Lanczos by default.

Exit criteria:

- CuteCanvas no longer uses QPane as a generic numerical resampler.
- QPane’s raster conversion helpers only adapt representation.
- Ownership checker bans reintroduction of removed Qt numerical paths.

### Phase 4 — NoHalo, LoHalo, and Color to Alpha

Deliver:

- Shared adaptive transform-sampler planner.
- `NoHalo@1` scalar and optimized CPU implementations.
- `LoHalo@1` scalar and optimized CPU implementations.
- `ColorToAlphaClassic@1`.
- `ColorToAlphaLinear@1`.
- Multi-output matte extraction.
- Sampler visual/numerical benchmark corpus.
- QPane filter policy hooks without making QPane the algorithm owner.

Exit criteria:

- Exact semantics and operation keys are documented.
- Tile and block partition do not change results.
- Algorithms meet documented quality and performance thresholds.

### Phase 5 — Foundational raster and coverage operations

Migrate:

- Coverage algebra.
- Feathering and morphology.
- Flood fill and connected components.
- Content bounds and occupancy.
- Selection-aware pixel translation.
- Core compositing primitives.
- Gaussian blur and convolution framework.

Split QPane hybrid evaluation so Qt vector-path rasterization remains a focused adapter while generic coverage math moves to Ferrastra.

Exit criteria:

- One numerical authority for every migrated operation.
- Existing mask, selection, hybrid, and translation behavior remains characterized.
- 4K/background performance gates improve or remain within current budgets.

### Phase 6 — Native source stores

Implement:

- RasterStore and CoverageStore.
- Sparse tiles and copy-on-write revisions.
- Edit transactions and exact damage.
- Pinning, leases, content bounds, and byte accounting.
- CuteCanvas facades replacing Python sparse-grid internals.
- History integration through revision handles.

Exit criteria:

- Current sparse and editable-raster behavior is preserved.
- Undo can switch revisions without full-image copies for ordinary bounded edits.
- Store memory participates in coordinated budgets.

### Phase 7 — Native paint/edit sessions

Implement and migrate:

- Canonical stroke resampling and deterministic brush RNG contract.
- Brush, erase, textured tips, clone, smudge, fill, and related sessions.
- Reusable scratch/tip/pickup storage.
- Ordered chunk processing and chunk equivalence.
- One source revision per committed logical edit.

Exit criteria:

- QPainter and NumPy no longer define canonical document painting pixels.
- Large-brush p95/p99 latency meets established budgets.
- Existing painting, clone, selection, undo, and abuse tests pass.

### Phase 8 — Per-layer nondestructive effect DAG

CuteCanvas adds persistent effect descriptors and graph compilation for:

- Transform.
- Blur.
- Levels/curves/exposure.
- Color operations.
- Masks.
- Opacity.
- Initial blend operations.
- Coordinated R-Candy-authored artifacts when the language surface is available,
  including source, resolved package lock, source map, canonical graph,
  diagnostics, generated controls, and transactional source or graph edits.

QPane consumes compiled graph roots through source-neutral sampled products.

Exit criteria:

- Effects can be edited without rewriting source pixels.
- Parameter changes invalidate only affected graph products/regions.
- Export and viewport use the same canonical exact graph result.
- Failed source compilation preserves the last valid executable graph, and
  unavailable operations remain losslessly retained without evaluation.

### Phase 9 — Native vector engine

Implement:

- VectorStore revisions and spatial indexing.
- Paths, transforms, bounds, hit-test support.
- Stroke expansion, clipping, booleans, and offsets.
- Vector-to-coverage and CPU rasterization.
- Framework-neutral vector graph operations.
- QPane vector adapter and migration plan.

Exit criteria:

- Large vector scenes evaluate requested regions without replaying irrelevant objects.
- Vectors remain vector until explicit rasterization.
- QPane can present vector-preserving products or exact raster branches.

### Phase 10 — Full composition DAG

Move canonical document composition into Ferrastra:

- Full blend-mode set.
- Masks and opacity.
- Group isolation.
- Clipping groups.
- Adjustment layers and backdrop inputs.
- Nested composition roots.
- Shared-subgraph and stack-segment caching.

CuteCanvas remains the layer-stack authoring model. QPane becomes the viewport/presentation consumer of Ferrastra document products.

Exit criteria:

- Native nondestructive adjustment layers are complete.
- Merge/bake/flatten are explicit CuteCanvas commands.
- Nested composition rendering no longer requires recursive QPane scene rasterization as the canonical path.

### Phase 11 — Advanced runtime

Required for full large-document ambitions, but may follow the initial feature-complete editor release:

- Out-of-core file-backed stores.
- Persistent product cache.
- More operation fusion.
- Expanded SIMD specialization.
- Advanced work stealing under strict budgets.
- Optional GPU backend.
- Native export pipelines.
- Graph profiler/inspector UI adapters.

### R-Candy authoring track

R-Candy follows the dependency-ordered track in `RCANDY_DESIGN.md`: Stage 0
architecture, Phase 1 shared graph and catalog contracts, complete descriptors
with the first real operations, a structured authoring prototype, the minimal
compiler and Python surface, CuteCanvas authored-effect integration, then
packages and language tooling. The parser does not block native operation work,
and native runtime work never waits on or depends on the parser.

---

## 34. Initial executable work packages

Stage 0 establishes the workspace, architecture charter, verification, and
enforced ownership boundaries. Native behavior begins with these
dependency-ordered work packages:

1. **`feat(ferrastra-core): define products, regions, semantics, and operation contracts`**
   Include typed values, units, descriptor exposure, diagnostics, and analysis;
   no kernel yet.

2. **`feat(ferrastra-graph): add immutable typed graph and compiler baseline`**
   Add canonical serialization, content identity, transactional patches, and
   unknown-record preservation; source and identity nodes only.

3. **`feat(ferrastra-runtime): add regional evaluation, damage, identity, and trace`**
   No QPane integration yet.

4. **`feat(ferrastra-raster): implement Lanczos3 scalar oracle`**
   Full conformance tests before optimization.

5. **`perf(ferrastra-raster): add optimized Lanczos3 CPU backend`**
   Same semantic ID; output must remain within the exact contract.

6. **`feat(ferrastra-python): expose graph, source, cancellation, and resample contracts`**
   Prove graph construction parity and add independent wheel and isolated tests.

7. **`feat(qpane): adopt Ferrastra for exact pyramid generation`**
   Add adapter, migrate every caller, delete the old exact Qt path, and preserve QPane lifecycle tests.

8. **`test(ownership): forbid exact Qt pyramid scaling`**
   Convert the migration decision into a permanent architecture gate.

9. **`feat(ferrastra-raster): begin adaptive sampler framework`**
   Use it as the foundation for NoHalo and LoHalo, not as a one-off second resampler.

10. **`test(ferrastra-authoring): prove structured graph authoring workflows`**
   Exercise catalog discovery, construction, patching, validation, analysis,
   and preview admission before introducing textual syntax.

11. **`feat(ferrastra-rcandy): compile minimal typed effects`**
   Add the crate only with executable parsing, resolution, lowering, source-map,
   diagnostic, and formatting responsibilities; expose it through
   `ferrastra.rcandy` with cross-frontend conformance.

Broad operation migration begins only after the graph and runtime baseline is
executable and verified.

---

## 35. Feature-complete checklist

Ferrastra is **not feature complete** until every required item below is satisfied. This is intentionally stricter than a first usable release.

### 35.1 Architecture and package boundaries

- [ ] Ferrastra is independently buildable and publishable.
- [ ] Ferrastra has no Qt, QPane, CuteCanvas, or application dependency.
- [ ] CuteCanvas depends on QPane and Ferrastra only through supported public contracts.
- [ ] QPane depends on Ferrastra only through its focused adapter.
- [ ] Crate and Python dependency directions are mechanically enforced.
- [ ] Mixed-responsibility production files are absent; structural waivers apply only to justified cohesive owners.
- [ ] Canonical numerical implementations have one owner.
- [ ] Isolated wheels and crates pass tests outside the monorepo source tree.

### 35.2 Typed product and numerical model

- [ ] Raster, coverage, vector, graphic, scalar, color, transform, and metadata products are represented explicitly.
- [ ] Pixel/coverage formats define channel, alpha, transfer, and layout semantics.
- [ ] Coordinates, regions, sample centers, and strides are canonical and tested.
- [ ] Operation semantic IDs and versions are stable.
- [ ] Product identities are strong, deterministic, and content based.
- [ ] Exact outputs are immutable and atomically published.

### 35.3 DAG and compiler

- [ ] Typed graph definitions and immutable graph revisions.
- [ ] Graph transactions for incremental updates.
- [ ] Cycle rejection and type validation.
- [ ] Bounds and product inference.
- [ ] Backward regional demand for every operation.
- [ ] Forward regional damage for every operation.
- [ ] Nested/compound graph support.
- [ ] Stable node identities and common-subexpression reuse.
- [ ] Dead-node elimination, constant folding, and transform folding.
- [ ] Explicit rasterization boundaries.
- [ ] Point-operation fusion and extensible optimization passes.
- [ ] Explainable compiled plans.

### 35.4 Runtime, cache, and memory

- [ ] Regional internal evaluation tiles independent of QPane tiles.
- [ ] Multi-region, multiscale, multiquality intermediate cache.
- [ ] Exact cache subtraction and partial validity.
- [ ] Shared-subgraph reuse.
- [ ] Caller-supplied thread, scratch, cancellation, and optional deadline budgets.
- [ ] No unconstrained global thread pool.
- [ ] Complete retained/pinned/evictable/in-flight byte accounting.
- [ ] Integration with the monorepo cache budget coordinator.
- [ ] Deterministic interactive/exact/export quality contracts.
- [ ] Product provenance, execution trace, cache report, and profiling APIs.

### 35.5 Native stores and editing

- [ ] Sparse RasterStore with copy-on-write immutable revisions.
- [ ] Sparse CoverageStore with copy-on-write immutable revisions.
- [ ] VectorStore with immutable revisions and spatial index.
- [ ] Bounded edit transactions and exact damage.
- [ ] Pinning/leases and memory accounting.
- [ ] CuteCanvas history uses native revision handles where appropriate.
- [ ] Brush, erase, clone, smudge, fill, and related sessions are native.
- [ ] Stateful sessions are deterministic and chunk equivalent.
- [ ] Persistent effects remain graph nodes; tools commit source revisions.
- [ ] Bake, merge, rasterize, and flatten are explicit CuteCanvas commands.

### 35.6 Required resampling and transform operations

- [ ] Nearest.
- [ ] Bilinear.
- [ ] Area reduction.
- [ ] Mitchell bicubic.
- [ ] Lanczos2.
- [ ] **Lanczos3.**
- [ ] **NoHalo.**
- [ ] **LoHalo.**
- [ ] General affine transform sampling.
- [ ] Perspective/EWA transform sampling.
- [ ] Coverage-specific range-preserving resampling.
- [ ] Multiresolution/pyramid source selection.
- [ ] Seam and phase conformance across all samplers.
- [ ] Source-neutral finite-line projection, collinearity, overlap, and
  support-extent analysis for deferred shared-edge consumers.
- [ ] Revision-keyed straight-boundary extraction for native raster and coverage
  sources without tool or document semantics.
- [ ] Coupled affine-boundary solver conformance independent of pointer, snap,
  layer, preview, and history policy.

### 35.7 Required color, alpha, filter, coverage, and composition features

- [ ] Premultiply/unpremultiply and supported working-space conversions.
- [ ] **Color to Alpha classic.**
- [ ] **Color to Alpha linear-light.**
- [ ] **Color-to-Alpha foreground + matte multi-output.**
- [ ] Gaussian blur.
- [ ] Box blur and general convolution.
- [ ] Sharpen/unsharp mask.
- [ ] Levels, curves, exposure, and color matrix.
- [ ] LUT application.
- [ ] Coverage algebra, feather, morphology, connected components, and bounds.
- [ ] Porter-Duff composition.
- [ ] Complete documented blend-mode set required by CuteCanvas.
- [ ] Masks, opacity, group isolation, clipping groups, and adjustment/backdrop semantics.
- [ ] Histogram and core analysis products.

### 35.8 Vector feature completeness

- [ ] Native vector product and store.
- [ ] Spatial region queries and stable identities.
- [ ] Path and parametric geometry.
- [ ] Revision-keyed straight-boundary products for vector sources.
- [ ] Transforms, bounds, and hit-test acceleration.
- [ ] Stroke expansion and offset paths.
- [ ] Boolean operations and intersections.
- [ ] Clipping.
- [ ] Instances/repeated geometry.
- [ ] Vector-to-coverage.
- [ ] CPU antialiased regional rasterization.
- [ ] Cached flattening/tessellation products.
- [ ] Vector-preserving DAG branches and explicit rasterization boundaries.
- [ ] QPane vector-product adapter.

### 35.9 QPane and CuteCanvas integration

- [ ] QPane exact pyramid pixels are Ferrastra-owned.
- [ ] QPane exact raster projection/resampling is Ferrastra-owned.
- [ ] QPane still owns viewport demand, retained frames, Qt presentation, and transient previews.
- [ ] CuteCanvas no longer uses QPane as a generic numerical image engine.
- [ ] CuteCanvas raster and coverage stores use Ferrastra native revisions.
- [ ] CuteCanvas compiles effect stacks into Ferrastra graphs.
- [ ] Per-layer nondestructive effects use the same exact output for viewport and export.
- [ ] Full layer/group/adjustment composition compiles into Ferrastra.
- [ ] QPane consumes Ferrastra graph outputs through source-neutral public SDK contracts.
- [ ] CuteCanvas Shared Edge Resize retains tool, snapping, participant,
  preview, and history ownership while using Ferrastra only for migrated
  source-neutral analysis and explicit bake products.
- [ ] Current specialized hybrid evaluation has been compiled into ordinary Ferrastra operations or deliberately retained only for a documented unique responsibility.

### 35.10 Quality and performance

- [ ] Every operation passes the common conformance suite.
- [ ] Samplers pass the difficult visual/numerical corpus.
- [ ] Tiled and monolithic output equivalence is proven.
- [ ] Cross-platform numerical contracts are documented and enforced.
- [ ] FFI is fuzzed and panic-safe.
- [ ] p50/p95/p99 and memory budgets are checked in CI or controlled benchmark lanes.
- [ ] Large raster and vector scenes process only requested regions.
- [ ] Interactive large-brush sessions meet declared latency budgets.
- [ ] Cancellation and stale-work latency meet declared limits.
- [ ] No GUI-thread heavy work has been introduced.

### 35.11 R-Candy and structured authoring

- [ ] Rust, Python, R-Candy, CuteCanvas, and structured tools share one
  `GraphDefinition` and produce equivalent normalized computation.
- [ ] Public graph operations have complete computation and authoring
  descriptors with explicit exposure classes.
- [ ] Graph revisions, graph content, node identities, and product keys remain
  distinct and tested.
- [ ] Unknown operations round-trip and failed source compilation preserves the
  prior valid graph.
- [ ] Graph patches are transactional, conflict-aware, and preserve unchanged
  branches.
- [ ] Request-aware analysis and host admission apply to imported and generated
  graphs.
- [ ] R-Candy compilation is deterministic, I/O-free, and locked to supplied
  operation and package resolutions.
- [ ] Evaluation crates do not depend on R-Candy and serialized graphs execute
  without its compiler.
- [ ] The R-Candy definition of done in `RCANDY_DESIGN.md` is complete.

---

## 36. Post-feature-complete aspirations

The following are valuable but are not prerequisites for declaring the original CPU-first specification complete unless product requirements make them necessary earlier:

- GPU compute backends conforming to Ferrastra operation contracts.
- Persistent cross-session derived-product disk cache.
- Remote/distributed evaluation.
- Plugin ABI for third-party native operations.
- Full internal ICC/profile engine replacing Qt boundary conversion.
- Native text shaping and font engine.
- Procedural node-editor UI.
- Collaborative graph/source revision protocols.

The architecture must permit these without requiring them in the first implementation.

---

## 37. Rejected implementation patterns

The following proposals must be rejected during review:

- “Add a fast Rust function now and design the graph later.”
- “Let Ferrastra accept QImage directly.”
- “Put the new kernel in `utils.rs`.”
- “Use QPane’s tile size as Ferrastra’s tile size.”
- “Cache only the last node result.”
- “Use a global Rayon pool and let the OS sort it out.”
- “Treat masks as grayscale photos.”
- “Implement every brush dab as a persistent DAG node.”
- “Keep the old Qt implementation as a fallback indefinitely.”
- “Let exact and interactive products share one cache key.”
- “Store CuteCanvas layer IDs or undo commands in Ferrastra.”
- “Move QPane navigation or QWidget code into Rust because Rust is faster.”
- “Build a full-image intermediate because the operation is simpler that way.”
- “Add a second blend or alpha implementation for one special source type.”
- “Expose untyped Python dictionaries as the graph API.”
- “Create one giant `engine.rs`, `runtime.rs`, or binding module containing the system.”

---

## 38. Definition of done for any Ferrastra migration

A migration is complete only when:

1. The Ferrastra responsibility is explicit and lives in the correct crate/module.
2. Numerical behavior is characterized by an independent oracle or golden contract.
3. The operation has semantic identity, demand, damage, memory, cancellation, and quality definitions.
4. QPane/CuteCanvas callers use focused adapters.
5. The old canonical implementation is deleted.
6. Architecture checks prohibit reintroduction.
7. Focused behavior, abuse, numerical, performance, and packaging tests pass.
8. Public contracts, docs, and demos are updated where the migration changes a published API.
9. Retained and scratch bytes are accounted for.
10. The resulting files remain single responsibility and within structural limits.

---

## 39. Team operating rule

Before implementing any Ferrastra feature, the engineer must write down:

1. The authoritative owner.
2. Input and output product types.
3. Semantic operation ID and version.
4. Exposure class and complete operation descriptor.
5. Typed parameters, units, ranges, defaults, and coordinate behavior.
6. Backward-demand rule.
7. Forward-damage rule.
8. Pixel/coverage/vector semantics.
9. Alpha and working-space semantics.
10. Edge behavior.
11. Exact and interactive quality behavior.
12. Product-key inputs.
13. Capability and request-analysis behavior.
14. Memory and scratch estimate.
15. Cancellation behavior.
16. Parallelism policy.
17. Structured diagnostic behavior.
18. Numerical oracle.
19. Tile-equivalence test.
20. Cross-frontend construction fixture when `public_graph`.
21. Performance gates.
22. Current QPane/CuteCanvas code that will be deleted.

If any answer is missing, implementation has not started at the correct level.

---

## 40. Final architectural statement

The repository architecture and package guidance use this permanent summary:

> Ferrastra is a CPU-first, typed, spatial, revision-aware graphics product engine. It evaluates immutable raster, coverage, vector, mixed graphic, and analysis products through a demand-driven DAG. Every operation declares its semantic identity, typed products, backward input demand, forward damage, numerical behavior, memory needs, cancellation behavior, and quality tiers. Ferrastra contains no Qt, document, tool, undo, or presentation semantics. CuteCanvas owns authoring and history. QPane owns viewport demand and Qt presentation. Stateful tools use transactional native sessions that commit new source revisions; all derived effects remain nondestructive graph products. Exact results are immutable, cacheable, tile-equivalent, atomically published, explainable, and reproducible under their documented contract.

This boundary remains authoritative throughout implementation and migration.
