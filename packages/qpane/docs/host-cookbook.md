# Host Cookbook

This guide connects QPane's smaller tutorials into the flow of a complete host
application. It follows the work from mounting a viewer through catalogs,
comparison, diagnostics, extensions, and custom render content.

## Mount and Configure the Viewer

Create `QPane` after `QApplication`. The current `QPane.settings` value is a
detached `Config`, while `QPane.applySettings()` validates and applies a new
snapshot to the running viewer. `QPane.minimumSizeHint()` supplies a useful Qt
layout hint without forcing an application-specific minimum window size.

`QPane.setImage()` presents one decoded image and returns its reusable source.
`QPane.currentImage` and `QPane.currentImagePath` report the ordinary image and
path currently represented by the active view. `QPane.clear()` returns the
viewer to its configured placeholder without destroying host-owned images.

`QPane.setScene()` presents an immutable scene and optionally fits it, while
`QPane.scene()` returns the active scene for inspection. `QPane.sceneChanged`
notifies host chrome after that presentation changes. For planning tools and
performance inspectors, `QPane.calculateRenderPlan()` returns the visible work
chosen for the current scene and viewport.

## Drive the Viewport

`QPane.setZoomFit()` frames the active content, and `QPane.setZoom1To1()` maps
one source pixel to one physical display pixel. `QPane.applyZoom()` changes the
scale around an optional anchor. The matching `QPane.currentZoom()` value and
`QPane.zoomChanged` signal keep a status control synchronized.

`QPane.setPan()` changes the current translation, and `QPane.currentPan()`
returns it as detached geometry. `QPane.physicalViewportRect()` reports the
device-pixel render area. `QPane.panelHitTest()` converts a widget point into
the source coordinates prepared by the active presentation.

`QPane.setPanZoomLocked()` enables or disables navigation as one policy.
`QPane.panZoomLocked()` reports that state, so mouse, touch, host controls, and
custom tools do not invent separate lock rules.

## Build Catalog Navigation

`QPane.addImage()` adds a decoded image and returns its stable catalog entry.
`QPane.selectCatalogImage()` opens a chosen entry, while
`QPane.selectNextImage()` and `QPane.selectPreviousImage()` move through the
ordered review set with wraparound. `QPane.removeCatalogImage()` removes one
entry, and `QPane.clearCatalog()` empties the complete review set.

`QPane.catalogSelectionChanged` carries the selected entry or `None` for title
bars and sidebars. `QPane.catalogChanged` reports structural mutations, and
`QPane.catalogPrefetchState()` gives a host diagnostics panel the current
neighbor-warmup state.

`QPane.setLinkedImageGroups()` installs explicit synchronized groups, and
`QPane.linkedImageGroups()` returns their detached definitions.
`QPane.setAllImagesLinked()` is the convenient all-or-none command.
`QPane.linkGroupsChanged` tells host controls to refresh after any definition
changes.

## Compare Images

`QPane.compareWithNextImage()` starts a comparison from catalog order, while
`QPane.setComparisonImage()` chooses a specific entry and
`QPane.clearComparison()` finishes the comparison. `QPane.setComparisonSplit()`
changes the reveal position and orientation.

`QPane.comparisonState()` describes the selected source and split.
`QPane.comparisonChanged` keeps host actions and sliders current.
`QPane.setComparisonDividerInteractive()` controls built-in divider dragging,
and `QPane.comparisonDividerInteractive()` reports whether it is enabled.
`QPane.comparisonDividerState()` supplies projected line and hover geometry to
a host that draws its own divider.

## Present the Empty Viewer

`QPane.setPlaceholderImage()` supplies an image for the empty state.
`QPane.placeholderState()` returns a `ViewerPlaceholderState` containing its
visibility and navigation presentation, while `QPane.placeholderChanged`
notifies the surrounding interface when that state changes.

`QPane.copyCurrentImageToClipboard()` copies the available base image and
reports success. `QPane.dragOutRequested` lets the application create its own
platform drag payload rather than placing file-system policy in the renderer.

## Select and Extend Tools

`QPane.availableControlModes()` lists registered tools, `QPane.controlMode()`
returns the active mode, and `QPane.setControlMode()` activates another one.
`QPane.controlModeChanged` keeps menus and toolbar buttons synchronized.

`QPane.registerTool()` installs a public `ViewerTool` factory, and
`QPane.unregisterTool()` removes an inactive registration. A
`CursorInteractionPort` gives reusable cursor logic the state it needs without
exposing the viewer implementation. `ToolManagerSignals` carries activation and
cursor changes across the manager boundary.

`QPane.registerOverlay()` adds widget-relative drawing, and
`QPane.unregisterOverlay()` removes it by owner name. For ordered layer
geometry, `QPane.registerSceneOverlay()` supplies prepared scene snapshots and
`QPane.unregisterSceneOverlay()` performs matching cleanup.

## Add Temporary Layer Treatments

`LayerPresentationEffectKind` distinguishes tint, outline, glow, and bounds
treatments. `LayerPresentationEffect` combines one kind and style with stable
scene, layer, and effect identity.

`QPane.addLayerPresentationEffect()` registers a treatment and returns its ID.
`QPane.updateLayerPresentationEffect()` changes its appearance without changing
identity, and `QPane.removeLayerPresentationEffect()` removes one treatment.
`QPane.clearLayerPresentationEffects()` clears a chosen group, while
`QPane.layerPresentationEffects()` returns the active immutable registrations.

## Observe Runtime Work

A standalone `QPane` owns a bounded runtime. A host with several viewers can
create one runtime and pass it to every widget so all rendering participates
in the same admission budget:

```python
from qpane import QPane
from qpane.sdk.execution import create_default_execution_runtime

runtime = create_default_execution_runtime()
left = QPane(execution_runtime=runtime)
right = QPane(execution_runtime=runtime)
```

The host closes that runtime during application teardown. An application with
its own scheduler can construct `ExecutionRuntime` over a custom public
`ExecutionBackend`; see [Advanced Renderer Integration](integration-sdk.md).

`QPane.setDiagnosticsOverlayEnabled()` shows or hides the built-in HUD, and
`QPane.diagnosticsOverlayEnabled()` reports its state.
`QPane.diagnosticsOverlayToggled` keeps a host action synchronized.

`QPane.diagnosticsDomains()` lists the available sections.
`QPane.setDiagnosticsDomainEnabled()` changes one, and
`QPane.diagnosticsDomainEnabled()` reports it. The
`QPane.diagnosticsDomainToggled` signal carries later changes.

`QPane.diagnostics()` returns the live broker for advanced integration.
`QPane.gatherDiagnostics()` returns a detached point-in-time snapshot, and
`QPane.registerDiagnosticsProvider()` contributes fast host records.
`QPane.createStatusOverlay()` builds the standard Qt diagnostics widget for an
application that wants it outside the canvas.

## Author Vector Content

`VectorObjectKind` distinguishes retained shapes, paths, and text inside a
`VectorObject`. A `VectorShapeKind` chooses built-in rectangle or ellipse
geometry, while `VectorPathCommandKind` and `VectorPathCommand` describe the
ordered operations of a custom path.

`VectorStyle` combines fill, stroke, opacity, and path presentation.
`VectorFillRule` determines how overlapping path regions become filled;
`VectorStrokeJoin` and `VectorStrokeCap` determine how connected and terminal
stroke segments are drawn.

`VectorTextStyle` describes font and color, `VectorTextSpan` applies a style to
part of the Unicode string, and `VectorParagraphStyle` controls the block.
`VectorTextAlignment` governs line placement while `VectorTextDirection`
governs logical text flow.

## Combine Vector and Raster Content

`HybridDocument` is an immutable source document containing both semantic and
sampled primitives. `HybridVectorPrimitive` retains vector geometry, while
`HybridRasterPrimitive` requests grayscale or color regions from a worker-safe
sampler. `HybridCombineMode` determines how those primitives combine, and
`HybridPresentationStyle` describes the resulting coverage presentation.

QPane samples both kinds through the normal visible-tile pipeline. A host
publishes source revisions and damage; it does not allocate a second canvas
pyramid or composite the complete document itself.

## Related Docs

* [Getting Started](getting-started.md): Mount the widget and show the first
  image or scene.
* [Viewer Workflows](viewer-workflows.md): Catalog, comparison, placeholder,
  clipboard, and diagnostics examples.
* [Rendering SDK](rendering-sdk.md): Build raster, vector, and hybrid scenes.
* [Advanced Renderer Integration](integration-sdk.md): Implement source and
  scheduling contracts.

**Continue →** [API Reference](api-reference.md)
