# QPane Package Guidance

The root `AGENTS.md` applies. This file adds QPane-specific product ownership.

## Product identity

QPane is a high-performance PySide6 image viewer, rendering viewport, and
public raster/vector rendering SDK. Its ordinary viewer facade and every
advanced consumer use the same renderer boundary.

QPane contains no document-authoring concepts and never imports CuteCanvas.
Masks, selections, edit history, painting, editable layer policy, smart-object
workflow, vector editing, persistence, and SAM are not QPane concerns.

## Ownership

QPane owns:

- immutable render scenes, items, source handles, and revisions;
- stable source-product and independent placed-instance identity;
- raster and vector provider contracts, damage, and invalidation;
- viewport transforms, visibility, hit testing, clipping, compositing, and
  partial redraw;
- pyramids, tiles, refinement, cache budgeting, and render concurrency;
- low-level pointer normalization, navigation, and viewport input;
- catalog-backed viewer navigation, comparison, swap, and prefetch; and
- immutable semantic vector graphics, paths, shapes, styles, text layout,
  vector sampling, product caching, and render hit testing.

Semantic vector values are renderable resources, not editing documents. Stable
object identity may support product reuse, but object selection, node/text edit
sessions, history, tools, carets, handles, conversions, and vector-mask workflow
belong to CuteCanvas.

## Rendering SDK

The public SDK must be clear, typed, declarative, and economical. Ordinary
hosts create a viewport, scene, shared raster/vector sources, and transformed
items without registering domain types or managing tiles, caches, workers, or
invalidation internals. Advanced providers expose live or sparse content,
revisions, and damage through focused contracts.

Renderer optimizations are source-neutral. Never add a mask-, selection-,
editor-layer-, smart-object-, or CuteCanvas-specific render path. New source
kinds participate through the same primitive planners and compositor.

No GUI-thread operation may decode, rasterize large content, build expensive
vector products, query slow operating-system state, or wait for workers. Cache
ownership is explicit, byte-bounded, and coordinated.

## QPane Trinity and proof

Public facade or SDK changes update the QPane contract, implementation, QPane
docs, and the single QPane demo together. The demo remains a polished core
viewer with restrained public SDK teaching, not an editor or renderer lab.

Focused proof includes large-image navigation, raster/vector frame equality,
source reuse, revision invalidation, cache pressure, refinement, teardown, and
isolated installation without CuteCanvas or editor/SAM dependencies.
