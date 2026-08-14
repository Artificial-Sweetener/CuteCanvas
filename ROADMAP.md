# CuteCanvas Roadmap

This is where I keep the work on deck after the first CuteCanvas release. It is
not a promise or a release calendar. It is the direction that lets the editor,
viewer, and native engine grow without quietly turning into three copies of the
same infrastructure.

## The Current Foundation

CuteCanvas and QPane are separate products with separate public APIs, versions,
packages, documentation, demos, and test suites. QPane is the PySide6 viewer and
rendering SDK. CuteCanvas builds editable documents, layers, tools, masks,
selections, painting, history, and persistence on that renderer.

Ferrastra has completed its typed spatial graph baseline and the exact
resampling ownership migration. Its Rust and Python surfaces construct and
serialize the same immutable graph, retain canonical raster and Coverage8
sources, and evaluate regional Lanczos3, sampled-view, raster-affine, and
coverage-affine products under explicit cancellation and memory limits. QPane
uses exact native products for pyramids and settled physical-grid refinement
while retaining viewport demand, cache, worker, retained-frame, and Qt
presentation policy. CuteCanvas constructs focused Ferrastra graphs for
coverage, floating fragments, placed images, sparse samples, canvas resize, and
mask import while retaining documents, tools, history, policy, and publication.
The detailed native work belongs to
[FERRASTRA_DESIGN.md](FERRASTRA_DESIGN.md); R-Candy's language and structured-
authoring work belongs to [RCANDY_DESIGN.md](RCANDY_DESIGN.md).

## First Native Slice

The first Ferrastra behavior is deliberately small and complete instead of a
wide collection of placeholder APIs.

Phase 1 established the typed spatial graph, stable identities, validation,
demand, damage, cancellation, memory admission, deterministic products, and
equivalent Rust and Python graph construction. Its first executable graph is:

```text
RasterSource -> Identity -> Output
```

Phase 2 established Lanczos3 resampling as the first production operation and
uses it for QPane pyramid generation. The completed vertical slice includes the
scalar oracle, optimized CPU implementation, tile-seam equivalence, alpha and
color contracts, request-owned memory admission, Python binding, QPane adapter,
controlled performance limits, isolated wheels, and deletion of the exact Qt
pyramid-scaling path it replaced.

Ferrastra now owns exact pyramid resampling. QPane owns source-revision product
reuse, background work, cancellation, caches, level selection, and Qt
presentation around those immutable native products.

## Exact Resampling Ownership

Phase 3 completed QPane affine raster projection and scaling-conversion cleanup,
CuteCanvas coverage and floating-fragment projection, placed-image
rasterization, sparse raster and coverage sampling, and mask import resampling.
Interactive navigation keeps immediate pyramid previews; settled frames publish
complete exact physical-grid products atomically. Coverage uses dedicated
nearest, linear, and area sampling with range-preserving scalar semantics.
QPane defines raster sampling relative to the source-native 1:1 point, where one
source pixel occupies one device pixel. Below 200%, immediate presentation uses
bilinear interpolation while settled axis-aligned products use Lanczos3 and
settled affine products use affine bilinear sampling. At and above 200%, both
immediate and settled products use nearest-neighbor sampling. Display density
does not move this source-native threshold. Sampling operation and physical-grid
phase participate in tile, cache, work, fallback, and adopted-product identity,
so an incompatible reconstruction or stale pan phase cannot replace a nearest
frame.

## Grow the Operation Library

With exact resampling owned in one place, Ferrastra can add the operations that
make a nondestructive editor substantially more useful:

- NoHalo and LoHalo transform sampling;
- color-to-alpha and matte extraction;
- raster and coverage morphology, blur, threshold, and compositing;
- native source stores and bounded edit sessions;
- a per-layer effect graph;
- vector evaluation; and
- the complete composition graph, including adjustment layers and backdrop
  inputs.

Operations are versioned contracts with numerical or visual oracles, explicit
alpha and color behavior, bounded memory, cancellation, and platform parity.
They do not appear first as one-off convenience functions in QPane or
CuteCanvas.

## Bring R-Candy Along with the Graph

R-Candy grows as a first-class Ferrastra authoring surface, not as a second
engine. Phase 1 gives it the same canonical graph definitions, typed values,
identities, diagnostics, patches, and unknown-operation preservation used by
Rust, Python, and host adapters.

The parser, formatter, structured editor, packages, and language tooling arrive
only when their executable responsibilities begin. Source text and structured
authoring both lower to the same graph, and neither one owns execution,
documents, trust, undo, or publication policy.

## Keep Improving QPane

QPane remains useful as a standalone viewer and rendering SDK. Its ongoing work
is focused on the viewer experience and on presenting immutable products well:

- measurable reductions in render latency, memory traffic, and allocation;
- stronger continuity under pan, zoom, resize, refinement, and cache pressure;
- better host-defined input mapping without requiring event-filter workarounds;
- source-neutral scene, hit-test, overlay, diagnostics, and presentation tools;
  and
- clean adoption of Ferrastra products without moving viewport, cache, or Qt
  presentation ownership into the native engine.

Performance work starts with a profile and ends with a benchmark or behavioral
budget. A fast result that flickers, tears, publishes stale work, or changes
pixels is not an optimization.

## Keep Improving CuteCanvas

CuteCanvas remains the owner of editable work and the workflows around it. The
next editor capabilities should build on its existing document, policy, history,
tool, and persistence boundaries rather than adding special paths to the
renderer.

The larger items still on deck are:

- adjustment layers backed by the canonical effect graph;
- broader explicitly selected SAM model support while MobileSAM remains the
  CPU-first default;
- native acceleration for the numerical parts of painting, masks, selections,
  and transforms as Ferrastra reaches the corresponding phases; and
- eventual migration of Shared Edge Resize deformation math while CuteCanvas
  retains snapping, participant selection, preview, policy, and undo ownership.

Existing editor behavior remains supported during those migrations. A native
implementation replaces an authoritative operation only when its complete
vertical slice is tested and ready; it never creates a parallel editor model.

## What Every Roadmap Item Owes the Project

Every public capability updates its typed contract, implementation, API
reference, narrative guide, and polished public demo together. Every structural
migration characterizes behavior first, moves every caller, removes replaced
code and temporary bridges, and activates the ownership check that prevents the
old path from returning.

Correctness, responsiveness, memory bounds, cancellation, teardown, undo and
redo, persistence, packaging, and supported-platform behavior are part of the
feature. They are not cleanup for later.
