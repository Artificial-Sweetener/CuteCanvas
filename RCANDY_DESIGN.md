# R-Candy Authoring Language

- **Status:** Normative implementation charter
- **Product:** Ferrastra
- **Public forms:** `ferrastra.rcandy`, `ferrastra-rcandy`, and `.rcandy`
- **Related charter:** `FERRASTRA_DESIGN.md`

## 1. Decision

R-Candy is Ferrastra's typed, declarative language and structured authoring
frontend for effect graphs. Humans, language models, visual editors, Rust
callers, and Python callers all author the same versioned `GraphDefinition`.
Ferrastra validates, compiles, and evaluates that graph through its ordinary
runtime.

```text
R-Candy source ───────────────┐
Structured graph tools ──────┤
CuteCanvas compilation ──────┼──> Ferrastra GraphDefinition
Rust graph construction ─────┤                 |
Python graph construction ───┘                 v
                                  Ferrastra compiler/runtime
                                               |
                                               v
                                  immutable native products
```

R-Candy is not another graphics engine, an executable Python environment, a
shader runtime, or a CuteCanvas-specific processor. It has no evaluator,
scheduler, cache, product system, pixel loops, or host policy. The concise rule
is:

> R-Candy describes Ferrastra computations. Ferrastra defines and executes
> them. A host decides whether, when, and where they may run.

R-Candy is a first-class part of the Ferrastra product and release. It is not a
fourth independently published product. The text language lives in the Python
namespace `ferrastra.rcandy`, the eventual Rust crate is `ferrastra-rcandy`, and
source files use `.rcandy`.

### 1.1 Why R-Candy exists

Ferrastra's raster, coverage, color, alpha, blend, vector, analysis, generator,
and compound operations need one precise authoring contract for Rust and Python
developers, CuteCanvas, human-written reusable recipes, structured model tools,
and future visual graph editors. Without that contract, each frontend would
invent operation names, values, validation, identity, and graph edits.

R-Candy lets a host translate artistic intent such as a restrained frosted-
acrylic treatment into discovered operations, a validated and admitted graph,
representative previews, and a few intentional controls. Once committed, the
effect is an ordinary deterministic Ferrastra graph. It does not depend on the
model, its conversation, or the R-Candy compiler to evaluate.

## 2. Scope

R-Candy eventually provides:

- a small, versioned, typed textual grammar for graph composition;
- a lexer, parser, typed syntax tree, exact source spans, and source map;
- name, operation-version, package, type, and unit resolution;
- lowering to Ferrastra's canonical `GraphDefinition`;
- a canonical formatter and structured language diagnostics;
- declared graph inputs, outputs, and intentional user-facing parameters;
- reusable compound effects and version-locked effect packages;
- structured graph discovery, construction, patching, and repair schemas;
- language-server support; and
- coordinated source, graph, and structured-editor workflows.

R-Candy does not provide:

- independent computation, scheduling, caching, tiling, products, or storage;
- arbitrary Python, native, process, filesystem, or network execution;
- hidden viewport, pointer, wall-clock, frame-counter, environment, or global
  random inputs;
- document, layer, undo, resource, trust, preview, or publication policy;
- a requirement that every graph be authored or retained as text; or
- a programmable per-pixel kernel language in its initial form.

A future safe kernel language is a separate compiler and sandboxing project. It
must produce an ordinary versioned Ferrastra operation governed by the same
operation, graph, runtime, conformance, and admission contracts.

R-Candy exposes the whole public declarative computation surface, not every
engine administration API. Every Ferrastra entry point has one exposure class:

- `public_graph`: available to graph builders, R-Candy, and structured tools;
- `host_only`: available only to trusted host integration;
- `session_only`: stateful source-editing behavior that cannot appear in an
  immutable effect graph; or
- `internal`: unavailable outside its owning crate or package boundary.

Runtime construction, schedulers, caches, native stores, leases, host resource
resolution, publication policy, and stateful edit sessions are never exposed as
R-Candy operations.

## 3. Ownership

### 3.1 Ferrastra computation contracts

Ferrastra owns canonical products and values, graph and operation schemas,
semantic operation versions, graph validation, graph compilation, demand,
damage, color, alpha, coordinate, quality, deterministic randomness, capability
and cost analysis, execution, caching, cancellation, and native products.
R-Candy consumes these contracts without reinterpreting or duplicating them.

### 3.2 R-Candy language contracts

R-Candy owns grammar, tokens, syntax, comments, source spans, name and package
resolution, type checking against Ferrastra descriptors, lowering, source maps,
canonical formatting, and language-server behavior. It adapts structured
Ferrastra diagnostics to source without becoming the authority for graph or
operation validity.

The compiler is deterministic and pure with respect to supplied inputs. It
performs no network or filesystem access. The host supplies source, a catalog
snapshot, available capability policy, and an exact resolved package lock.

### 3.3 Host authoring policy

CuteCanvas owns its source editor, natural-language and model interaction,
effect resources, source and graph persistence, document bindings, sliders,
labels, grouping, preview policy, trust, package acquisition, capability
admission, undo/redo, and publication. Other hosts own the equivalent policy for
their applications.

A host may use Ferrastra's R-Candy authoring surface and engine surface together.
It must not implement a parallel R-Candy parser, Ferrastra graph validator,
operation catalog, or computational identity algorithm.

### 3.4 Presentation

QPane presents the previous valid product during recompilation, immediate
transformed previews, and requested interactive or exact products. It may
present generic host-supplied diagnostic text, but it has no R-Candy syntax,
source-span, catalog, package, or authoring responsibility.

## 4. Canonical graph and authored artifacts

`GraphDefinition` is the canonical executable representation. R-Candy text is
one authoring projection of it. Evaluation never requires the compiler or the
original source.

The identities are distinct:

- `NodeId` is stable authoring identity for references, patches, source maps,
  diagnostics, and undo. It does not identify computed content.
- `GraphRevisionId` identifies one accepted edit revision and changes for
  authoring-only edits when the stored revision changes.
- `GraphContentId` identifies the normalized computational graph. It excludes
  prose, labels, source formatting, comments, examples, tags, control layout,
  and other authoring-only metadata.
- `ProductKey` identifies one requested product and includes graph content,
  output, inputs and source revisions, region, scale, quality, format,
  working-space rules, capability/backend semantics, and other evaluation
  inputs defined by `FERRASTRA_DESIGN.md`.

Equivalent normalized computations have the same `GraphContentId`. Changing an
operation version, connection, computational parameter, coordinate mode, seed,
or declared computational input changes it. Renaming a label or editing prose
does not. An operation descriptor likewise separates its computational contract
from authoring metadata so that documentation improvements never invalidate
products.

An R-Candy-authored effect is a coordinated artifact containing:

- source text;
- language and compiler contract versions;
- exact resolved operation and package lock;
- syntax identities and source map;
- canonical `GraphDefinition` and its schema version;
- `GraphRevisionId` and `GraphContentId`; and
- authoring metadata not embedded in computation identity.

The graph is authoritative for execution. Source is authoritative for continued
text editing only while it compiles to the stored graph revision under the
stored resolution lock. The host publishes source and graph together only after
successful compilation and admission. Failed compilation preserves the last
valid executable graph and records diagnostics without partially publishing a
new effect.

Structured graph edits must either update the syntax model and regenerate
canonical source and graph together, or explicitly detach the graph from its
former source authority. A host must never silently retain divergent source and
graph as though both describe the same revision. Formatting a representable
graph may create canonical source, but arbitrary graph-to-source conversion
cannot promise recovery of original comments, abstractions, names, or layout.

Unknown operations and unavailable versions remain losslessly serializable with
their operation identity, ports, typed values, connections, node identity, and
authoring metadata. An unavailable graph may be retained and edited without
being accepted for evaluation.

## 5. Graph construction and editing contract

The versioned `GraphDefinition` represents:

- stable schema version and graph inputs and outputs;
- stable `NodeId` values;
- semantic operation IDs and versions;
- named typed input and output ports;
- typed constants and parameter references;
- connections and compound graph references;
- exposed effect parameters;
- coordinate, seed, capability, and domain requirements; and
- explicitly segregated non-computational authoring metadata.

Rust builders, Python builders, R-Candy lowering, CuteCanvas compilation, and
structured tools construct the same schema. Convenience functions may lower to
this model but never form a parallel canonical API.

Graph validation rejects cycles, missing nodes or ports, type mismatches,
unavailable operation versions, invalid values or units, incompatible color or
alpha contracts, unsupported capabilities, unbounded demand without domain
policy, and configured graph limits. Validation preserves unknown records while
distinguishing “retained but unavailable” from “valid and executable.”

`GraphPatch` is a typed transaction containing a base `GraphRevisionId`, exact
preconditions for the nodes or fields it observes, and operations equivalent to:

```text
AddNode           RemoveNode
Connect           Disconnect
SetConstant       BindParameter
ExposeParameter   SetOutput
ReplaceSubgraph   SetAuthoringMetadata
```

A patch validates against one base revision and commits atomically. A stale
base, failed precondition, or invalid outcome returns a structured conflict or
validation result and changes no Ferrastra graph. A host stages the accepted
result, applies admission, and publishes its authored artifact atomically; failed
admission changes no host resource. Unchanged `NodeId` values survive accepted
patches; unaffected computational branches retain equivalent identities and
reusable products. Whole-graph replacement is an explicit import operation, not
the only editing model.

## 6. Typed values, coordinates, and parameters

Graph values use closed typed schemas rather than untyped dictionaries. The
initial vocabulary includes Boolean, integer, float, length, angle, normalized
scalar or percentage, color, enum, transform, seed, resource reference, and
explicitly supported typed lists. Values carry units; parameter names never
imply units.

Persistent procedural computation names its coordinate space explicitly:
document, layer-local, effect-local, normalized canvas, or normalized effect.
Viewport coordinates are forbidden. Randomness requires an explicit persisted
seed. No wall clock, frame count, process state, or implicit global generator
participates in persistent results.

A compound effect exposes a stable intentional parameter surface independent of
its internal nodes. Each exposed parameter declares stable ID, label, type,
unit, default, hard and recommended ranges, linear or logarithmic control
mapping, description, optional group and basic/advanced classification, expected
interaction cost, and bindings to internal parameters. Generated effects expose
meaningful artistic controls rather than every internal constant.

## 7. Operation catalog

Every public Ferrastra operation has one authoritative machine-readable
`OperationDescriptor`. It contains:

- semantic ID, semantic version, exposure class, and stable category;
- typed named ports and typed parameter schemas;
- defaults, hard ranges, recommended authoring ranges, units, and enum values;
- supported formats, color, alpha, edge, coordinate, and quality contracts;
- determinism, locality, demand, support, displacement, and damage behavior;
- capability requirements and approximate request-sensitive cost and memory
  characteristics;
- concise summary and detailed behavior;
- use cases, composition guidance, warnings, and inappropriate uses; and
- stable serialization version.

The computational portion is authoritative for validation, graph identity,
compilation, and conformance. The authoring portion drives R-Candy assistance,
model discovery, CuteCanvas controls, documentation, examples, and effect
search. Authoring metadata changes do not change computational identities.

No operation is public until its descriptor is complete. A numerical-semantic
change requires a new semantic operation version; Rust names, Python names,
crate versions, translated labels, and display names never identify operation
semantics.

Discovery supports structured operations equivalent to:

```text
search_operations(query, input_types, output_type, capabilities)
describe_operation(operation_id)
find_compatible_operations(output_port, input_port)
list_effect_templates(tags, package_lock)
```

Natural-language tags and search indexes are derived authoring data, not
product identity. A language model never needs the entire catalog in its prompt
and never guesses an unavailable operation or parameter schema.

## 8. Diagnostics, analysis, and admission

Graph, compiler, and language failures use stable structured diagnostics with:

- code and severity;
- graph, node, port, parameter, package, and source-span targets as applicable;
- expected and actual types, values, versions, or capabilities;
- concise human-readable text;
- safe machine-readable repairs and candidate names where available; and
- related diagnostics.

Required categories include unknown or unavailable operations, missing inputs,
type mismatch, invalid value, cycle, unresolved package, unbounded demand,
unavailable capability, stale patch, and graph-limit violation. Source spans are
frontend annotations over Ferrastra targets; they do not enter computational
identity.

Analysis is request-aware. Given a graph plus output, region, scale, quality,
format, capability set, execution budget, and host limits, Ferrastra reports:

- validity and required capabilities;
- local, bounded-local, transform, generator, composite, or global behavior;
- maximum source support, displacement, and requested-input expansion;
- likely dominant operations and duplicated expensive branches;
- avoidable conversions and possible fusion;
- retained and intermediate memory estimates; and
- interactive-quality availability and structured cost warnings.

An estimate is not a promise of wall-clock duration. It is a deterministic
admission input with declared assumptions.

Every imported, text-authored, visual, or model-generated graph passes three
independent gates:

1. R-Candy parse, resolution, type, and lowering checks when source is used.
2. Ferrastra graph validation and compilation contracts.
3. Host admission for trust, package availability, capability policy, node and
   depth limits, nesting, support, displacement, input expansion, memory,
   requested cost, and project policy.

Passing an earlier gate never bypasses a later one. Rejected work publishes no
partial graph or product and cannot crash the host.

## 9. Language design

The initial language is declarative and non-Turing-complete. It uses named
arguments, immutable bindings, explicit returns, types, units, versions,
coordinates, and one unambiguous statement structure with one official
formatter. It supports effect inputs and outputs, typed parameters, operation
calls, compound definitions, and bounded compile-time expansion only where the
bound is statically provable.

It excludes mutable general variables, recursion, unbounded loops, overloaded
type-dependent operators, implicit conversions, implicit operation lookup,
context-sensitive grammar, hidden semantic defaults, side effects, arbitrary
calls, and I/O.

Versioned syntax artifacts preserve unknown constructs only when their extent
and raw representation can be delimited safely. They never guess semantics for
unknown syntax or accept it for lowering. Original source always remains
retainable even when the installed compiler cannot parse its language version.

The surface stays close to the graph it describes:

```rcandy
effect FrostedGlass(backdrop: Raster, shape: Coverage) -> Raster {
    param blur_radius: Length = 18px {
        label: "Blur";
        range: 0px..80px;
    }

    blurred = ferrastra.filter.gaussian-blur@1(
        source: backdrop,
        sigma: blur_radius,
        edge_mode: clamp,
    );
    result = ferrastra.coverage.apply@1(
        source: blurred,
        coverage: shape,
    );
    return result;
}
```

The example illustrates shape, not frozen syntax. The versioned grammar and
formatter become authoritative together when implementation begins.

Imports identify packages and compatible requirements in source. The host
resolves them under trust and project policy before compilation, supplies an
exact lock to the compiler, persists that lock with the authored artifact, and
performs any network or filesystem work outside the compiler. Compilation never
silently upgrades an operation or package.

## 10. Human and model authoring

The preferred model interface is strict structured discovery and graph editing,
not unrestricted source generation. The public authoring schemas support actions
equivalent to:

```text
search_operations    inspect_operation
create_effect        add_node
remove_node          connect
set_parameter        expose_parameter
apply_graph_patch    validate_graph
estimate_graph       request_preview
format_as_rcandy
```

The host owns model prompts, credentials, conversation, tool authorization,
preview requests, and document transactions. R-Candy owns source-specific
conversion and formatting. Ferrastra owns catalog truth, graph validity,
analysis, and execution.

A normal model workflow searches and inspects operations, builds or patches a
graph, receives validation and request-aware cost results, asks the host for a
representative preview, revises with targeted patches, and commits an ordinary
deterministic effect resource. The saved effect has no model dependency.

Targeted changes use `GraphPatch`, preserve unchanged authoring identities and
computational branches, and produce meaningful host-owned undo. Canonical
reformatting is acceptable before lossless arbitrary whitespace preservation;
stable semantic identities and explicit source/graph coordination are not
optional.

## 11. Dependency and source structure

The allowed internal direction is:

```text
ferrastra-rcandy  -> ferrastra-core
ferrastra-rcandy  -> ferrastra-graph
ferrastra-python  -> ferrastra-rcandy

ferrastra-core    x  ferrastra-rcandy
ferrastra-graph   x  ferrastra-rcandy
ferrastra-engine  x  ferrastra-rcandy
ferrastra-runtime x  ferrastra-rcandy
```

`ferrastra-python -> ferrastra-rcandy` is optional until the Python language
surface exists. Runtime evaluation of a `GraphDefinition` never requires
R-Candy. The language crate has no CuteCanvas, QPane, Qt, PyO3, Python, runtime,
store, engine, or operation-implementation dependency.

Create `ferrastra-rcandy` only when parser or compiler code has executable
responsibility. Do not create an empty Stage 0 crate. Its implementation remains
split by ownership, such as syntax, parsing, resolution, typing, lowering,
source maps, formatting, and language diagnostics. Parsing never executes a
graph; lowering never owns operation semantics; formatting never validates;
catalog search never performs package acquisition.

## 12. Conformance and enforcement

The architecture and conformance suites enforce:

- forbidden dependency edges and absence of host/runtime back-dependencies;
- a complete stable descriptor for every public operation;
- canonical graph construct/serialize/deserialize/normalize round trips;
- lossless retention of unknown operations and unavailable versions;
- equivalent `GraphDefinition` and `GraphContentId` results from Rust builders,
  Python builders, R-Candy lowering, and structured graph tools;
- source compile/format/reparse stability, source-map identity stability, and
  explicit detachment when a structured graph edit cannot preserve a valid
  source authority;
- computational identity changes only for computational inputs;
- transactional patches, stale-base conflicts, atomic rejection, stable
  unchanged `NodeId` values, and reusable unaffected product keys;
- stable diagnostic codes and precise targets for invalid fixtures;
- explicit units, coordinates, seeds, color, alpha, quality, locality, demand,
  damage, capability, and exposure declarations;
- request-sensitive cost and host-admission limits;
- deterministic source resolution and compilation without I/O;
- parser, serializer, graph, patch, package-lock, and diagnostic fuzzing; and
- responsibility-oriented source structure and structural limits.

Representative invalid fixtures cover unknown operations, unavailable versions,
missing ports, type mismatch, bad units or values, cycles, unbounded demand,
unsupported capabilities, package-lock mismatch, stale patches, and graph
limits. Representative graphs cover raster, coverage, vector, graphic, scalar,
color, transform, generators, composites, bounded and global operations,
compound effects, unknown records, exposed parameters, and authoring metadata.

## 13. Delivery

### Stage 0: architecture baseline

Stage 0 adopts this charter and reconciles root, product, crate, architecture,
and phase guidance. It defines planned ownership and dependencies, operation
entry requirements, identity distinctions, admission boundaries, and
non-production schemas and fixtures needed to test the design. Stage 0 contains
no parser, language crate, production graph API, mock production operation, or
placeholder runtime behavior.

### Ferrastra Phase 1: canonical graph contracts

Phase 1 implements the versioned `GraphDefinition`, identities, typed values and
units, operation descriptors and exposure classes, structured diagnostics,
transactional `GraphPatch`, unknown-record preservation, analysis schema, and
Rust/Python serialization and construction parity. Source and identity/pass-
through operations receive complete descriptors. The runtime still executes the
minimal graph described by `FERRASTRA_DESIGN.md`.

### First real operation slices

Each real operation ships its full computational and authoring descriptor,
catalog discovery, diagnostics, request-aware analysis, conformance, and Python
surface with the operation itself. Lanczos-3 is the first production proof.

### Structured authoring prototype

Before a text parser, prototype catalog search, inspection, graph construction,
patching, validation, estimation, and preview requests against early real
operations and non-production fixtures. Revise the shared contracts instead of
creating tool-specific graph semantics.

### Minimal R-Candy compiler

Create `ferrastra-rcandy` when it can parse, resolve, type-check, lower, map
diagnostics, and canonically format a minimal effect with typed inputs and
output, immutable bindings, named calls, constants, and exposed parameters.
Expose the same capability through `ferrastra.rcandy` with isolated package
proof.

### CuteCanvas integration

Add an effect resource that transactionally stores source, lock, source map,
canonical graph, and identities. Add generated controls, document bindings,
diagnostics, preview, exact refinement, unavailable-operation retention, and
undoable source and patch workflows. QPane continues to receive only generic
products and presentation diagnostics.

### Advanced authoring

Add versioned packages and compound effects, richer repair assistance,
language-server support, reusable templates, visual graph inspection, and
source-aware structured coauthoring. A programmable kernel language remains a
separate future proposal.

## 14. Definition of done

R-Candy graph composition and model authoring are complete when:

- the language has a versioned grammar, exact spans, typed syntax, resolution,
  type checking, explicit units and coordinates, compound effects, locked
  imports, canonical formatting, structured diagnostics, source maps, and
  language-server support;
- every frontend produces the same canonical graph and uses ordinary Ferrastra
  validation, demand, damage, quality, caching, compilation, and execution;
- the full public graph operation surface is discoverable through complete
  descriptors and strict structured tools;
- graph patches preserve stable identities, unaffected products, reviewable
  diffs, and atomic host transactions;
- CuteCanvas supports source and graph persistence, intentional controls,
  resource bindings, previews, exact refinement, undo, packages, inspection,
  and unavailable-operation retention;
- model workflows receive repairable diagnostics and request-aware cost feedback
  without arbitrary code execution or direct pixel access;
- persisted effects are deterministic and independent of the model and compiler
  at evaluation time; and
- architecture and conformance gates prevent semantic duplication or runtime
  dependence on R-Candy.

## 15. Rejected designs

- Executable Python or arbitrary native calls: unsafe, stateful, and not
  analyzable.
- A separate R-Candy runtime: duplicates Ferrastra authority.
- Source as the only executable artifact: prevents structured editing,
  unavailable-operation retention, and compiler-independent evaluation.
- Silent source/graph divergence: creates two incompatible authorities.
- Operation metadata copied into a host: permits catalog and validation drift.
- Free-form model output trusted without validation and host admission: treats
  fallible text as authority.
- Graph-only cost estimates: ignore the request and execution context that
  determine actual work.
- Immediate general shader language: expands the problem into compiler and
  sandbox design before graph composition is proven.
- Giant language modules: combine syntax, semantics, lowering, formatting, and
  diagnostics into mixed ownership.

The final architectural rule is:

> Build Ferrastra so R-Candy is one precise way to author an ordinary graph.
> Build R-Candy so humans and language models can create sophisticated effects
> without bypassing Ferrastra's types, spatial contracts, determinism, safety,
> admission, or performance model.
