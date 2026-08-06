# QPane Package Guidance

The root `AGENTS.md` applies. This file defines QPane's local ownership and proof
requirements.

## Product identity

QPane is a high-performance PySide6 image viewer, rendering viewport, and public
raster/vector rendering SDK. Its ordinary viewer facade and advanced consumers
use the same renderer boundary. QPane contains no document-authoring, editing,
history, persistence, selection, mask, painting, or application-policy model.

## Ownership

QPane owns:

- immutable render scenes, items, source handles, revisions, and source-product
  identity distinct from layer-instance identity;
- raster and vector provider contracts, damage, invalidation, visibility, hit
  testing, clipping, compositing, and partial redraw;
- viewport transforms, physical demand, navigation, retained presentation, and
  low-level pointer normalization;
- pyramids, tiles, refinement, source-neutral render planning, coordinated
  byte-bounded caches, and render concurrency;
- catalog-backed viewer navigation, comparison, swap, and prefetch; and
- immutable semantic vector values, paths, shapes, styles, text layout, sampling,
  product caching, presentation, and render hit testing.

Semantic vector values are renderable resources rather than editing documents.
Stable object identity supports product reuse; object selection, node or text
editing, history, tools, carets, handles, conversion workflows, and durable
authoring state are outside QPane.

## Renderer and SDK boundaries

The viewer facade is the obvious starting point for ordinary integration. The
public rendering SDK is typed, declarative, and organized around host workflows.
Hosts create a viewport, scene, shared raster or vector sources, and transformed
items without managing tiles, caches, workers, invalidation internals, or
domain-type registration. Advanced providers expose live or sparse content,
revisions, and damage through focused contracts without bypassing the renderer
boundary.

Renderer optimizations are source-neutral. Do not add operation-, editor-, mask-,
selection-, smart-asset-, or application-specific rendering paths. New source
kinds use the same primitive planners, schedulers, caches, and compositor.

Keep viewport policy, retained-frame ownership, GUI-thread publication, and Qt
presentation in their focused owners. No GUI-thread operation may decode,
rasterize large content, build expensive vector products, query slow external
state, or wait for workers. Cache ownership is explicit, coordinated, and
byte-bounded.

## Public surface

`src/qpane/qpane.pyi` is QPane's authoritative typed contract. Public changes
update it, the implementation, QPane documentation, and `packages/qpane/examples/qpane_demo.py`
together. The demo remains a polished core viewer and focused SDK example rather
than an editor, benchmark dashboard, or renderer laboratory.

## Test organization and proof

Organize QPane tests by the behavior owners for facade and public contracts,
scenes and sources, raster and vector providers, viewport and input, planning and
damage, pyramids and tiles, refinement, caches, concurrency, Qt presentation,
and packaging.

`packages/qpane/TEST_POLICY.toml` maps every QPane production area and public
boundary to its required test areas. Changes to facade, provider, scene, source,
viewport, damage, scheduling, cache, or presentation contracts update that map
in the same work.

Prove transform and demand mathematics with exact deterministic cases and
properties. Prove mounted navigation, input, repaint, publication, retained-
frame, and teardown behavior with real Qt objects. Prove raster and vector frame
equality, source reuse, revision invalidation, partial redraw, refinement,
cancellation, stale-result rejection, and cache accounting at their owning
integration boundaries.

Abuse proof covers navigation and input storms, rapid source and scene changes,
late work, source removal, cache pressure, repeated mount/teardown, and redraw
equality. Performance proof covers frame responsiveness, visible-product latency,
bounded retained memory, invalidation scope, and large raster and vector scenes.
Packaging proof installs QPane with only its declared dependencies and exercises
the supported facade and provider contracts.
