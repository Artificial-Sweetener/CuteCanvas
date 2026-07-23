# CuteCanvas Package Guidance

The root `AGENTS.md` applies. This file adds CuteCanvas-specific ownership.

## Product identity

CuteCanvas is a performant embeddable raster/vector document editor built on
QPane's public rendering SDK. Its facade should make document, layer, and tool
workflows delightful without accumulating all behavior in one widget.

## Ownership

CuteCanvas owns:

- independent document identity, canvas, metadata, and persistence;
- ordered generic editable layer instances and resource lifetimes;
- host capability policy, durable user locks, and one operation resolver;
- unified chronological undo/redo and atomic edit transactions;
- editable raster and coverage storage, masks, selections, and painting;
- placed/smart-asset provenance, conversion, and rasterization workflows;
- vector revision authoring around QPane's immutable vector values;
- layer/pixel movement, floating edits, free transform, tools, and overlays;
- document export/autosave and SAM integration.

Tools translate input and UI presents state. Neither owns durable document,
selection, geometry, pixel, history, permission, or rendering state. Every
durable edit uses the one document history. Host policy and user locks remain
separate inputs to the one operation resolver.

## Cross-package performance work

CuteCanvas changes may and should modify QPane when profiling or ownership
analysis shows that the correct owner is the shared renderer, viewport, cache,
input system, vector representation, or public SDK. Do not build CuteCanvas-
local render workarounds, duplicate product caches, parallel damage logic, or
operation-specific fast paths when a source-neutral QPane improvement solves
the problem for every consumer.

QPane improvements must remain editor-agnostic, preserve the one-way dependency,
update QPane's own Trinity when public, and pass QPane-focused plus cross-package
tests. Truly document- or operation-specific optimizations remain CuteCanvas.

## Facade and demo

Expose typed document and layer handles plus focused document, layer, tool,
selection, history, and export subfacades. Avoid routine raw identifier pairs,
private QPane access, service-locator APIs, and a god widget. Programmer errors
fail clearly; unavailable operations return stable reasons and alternatives.

Public changes update the CuteCanvas contract, implementation, docs, and its
single demo together. The demo is a coherent layered image editor with an
intentional canvas, tools/options, layer tree, selections, transforms, painting,
masks, raster/vector/placed layers, undo/redo, and persistence. It must not look
or behave like a collection of test panels.

Focused proof uses mounted workflows and the abuse harness for rapid document
switching, edit/undo chains, input suspension, stale work, source removal,
cache pressure, 4K/8K and sparse content, redraw equality, persistence failure
atomicity, teardown, and responsive interaction.
