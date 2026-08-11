**← Previous:** [Extensibility](extensibility.md)

# API Reference

## Document and presentation ownership

### `CanvasDocument`

Headless owner of reusable resources, compositions, selections, and
chronological history. Use `create_composition()`,
`create_composition_from_image()`, `replace_composition_image()`,
`composition_ids()`, `snapshot()`,
`content_reference()`, `resource_reference()`, `resolve_content()`, and
`close()`.

`replace_composition_image(composition_id, image)` updates the embedded content
and intrinsic bounds of an imported image composition while retaining its
composition, layer, resource, masks, history, and mounted view state. It is a
headless document mutation and does not activate the composition in any view.

### `CanvasViewSession`

Detachable owner of active composition, presentation, host-owned linked
inspection groups, and view-local revision. `CanvasPresentation` selects `SINGLE`, `TABBED`, `GRID`,
`COMPARISON`, or `CUSTOM` arrangement without entering document history.
`CanvasSessionSnapshot` is the immutable revisioned observation published to
session subscribers. `CanvasComparison` records the two target identities,
split position, and orientation used by a comparison presentation.
`CanvasPresentationKind` names every built-in and host-provided arrangement.
`CanvasInspectionGroup` gives a host one stable group identity and ordered
composition membership for linked inspection that survives presentation changes.

### Independent document viewports

`CanvasViewportSource` selects a composition, one layer, a same-composition
layer subset, or a mounted resource through stable content references.
`CanvasViewportSpec` combines that source with a stable viewport identity,
`CanvasViewportInteraction`, and `CanvasRenderVariant`.
`CuteCanvas.setViewportSpec()` mounts selected live content without changing
document structure, and `CuteCanvas.viewportSpec()` returns the view-local
policy. `CanvasViewportInteraction.FIT_ONLY` refits after size changes and
locks direct navigation; `INTERACTIVE` retains pan and zoom.
`CuteCanvas.setViewportCornerRadius()` clips the final presented frame with
QPane's antialiased border compositor, while
`CuteCanvas.viewportCornerRadius()` reports the configured logical-pixel
radius.
`CanvasRenderVariant.MASK_COVERAGE` presents selected masks as neutral
grayscale coverage, while `COMPOSITE` and `MASK_OVERLAY` retain ordinary
presentation.

### `CanvasWorkspace`

QWidget for one document across independent target views.
`retained_target_capacity` bounds the least-recently-used hidden target
renderers retained between presentation switches; visible targets do not
consume this budget.
`setSinglePresentation()`, `setTabbedPresentation()`,
`setGridPresentation()`, and `setComparisonPresentation()` install built-in
arrangements. `registerPresentationProvider()` and `setCustomPresentation()`
host an application-defined arrangement through
`CanvasPresentationProvider`.
`CanvasPresentationContext` gives a provider validated target identities and
the supported function for creating each target view.

`registerComparisonOverlay()` and `unregisterComparisonOverlay()` own
host-specific comparison chrome without exposing the native renderer.
`CanvasComparisonOverlayState` contains the current `CanvasComparison`, a
physical `CanvasComparisonDivider`, the native viewport, and a physical scale
for each source for one paint. `comparisonZoomGesture` reports only
pointer-originated comparison zoom as a `CanvasComparisonZoomGesture`;
`comparisonPointerMoved` reports the current comparison pointer. Hosts call
`refreshComparisonOverlays()` after changing transient overlay state.

`document_runtime` supplies one shared `CanvasDocumentRuntime` for every
target. `execution_runtime` supplies a host-owned physical runtime when the
workspace creates that document binding. `execution_policy` configures the
bounded runtime owned by a standalone workspace. A supplied document runtime
is mutually exclusive with both execution arguments.

`CanvasInteractionMode` supplies `READ_ONLY`, `MASK_AUTHORING`, and
`FULL_EDITOR` profiles through the ordinary capability policy.
`CuteCanvas.interactionMode` reports the current profile and
`CuteCanvas.setInteractionMode` replaces it. `CuteCanvas.document` returns the
mounted headless owner, while `CuteCanvas.viewSession` returns the detachable
view-local state.

`CuteCanvas.setOutboundMimeProvider` applies a host MIME provider to one view.
`CuteCanvas.clearOutboundMimeProvider` cancels pending materialization and
disables drag-out for that view.

`ExecutionRuntime` is the host-owned execution boundary accepted by
`CanvasDocumentRuntime`, `CuteCanvas`, and `CanvasWorkspace`.
`ExecutionRequirements`, `ExecutionResource`, `ExecutionUrgency`, and
`ExecutionLeaseRelease` let a host backend honor the full CuteCanvas
scheduling contract without importing QPane. `DragSubject`,
`OutboundMimeProvider`, `OutboundDragPayload`, and `OutboundMimeItem` are the
CuteCanvas drag-out boundary: a provider receives the captured subject and
returns the selected URLs, MIME bytes, and preview without importing renderer
UI modules. `ResponsiveGridPolicy`, `ResponsiveGridTopology`,
`ResponsiveGridPacking`, and `IncompleteRowAlignment` are the public
CuteCanvas layout contract used by `setGridPresentation()`; `gridSnapshot()`
returns the matching `ResponsiveGridSnapshot`.

`ExecutionBackend`, `BackendSubmission`, `ExecutionBackendCapabilities`,
`ExecutionHandle`, `ExecutionJob`, `ExecutionRejected`,
`ExecutionRejectionReason`, `ExecutionRequest`, and `InlineDispatcher` form
the typed host-backend lifecycle used by `ExecutionRuntime`. A host can publish
`ExecutionSnapshot` values and return `DiagnosticsSubscription` handles without
importing QPane. These contracts let an application advertise supported
resources, accept or reject bounded work, cancel pending submissions, observe
capacity, and deliver adoption on the owner-selected dispatcher.

`OverlayDrawFn` and `CanvasOverlayDrawFn` describe renderer and CuteCanvas
detail-overlay callbacks. `CanvasComparisonOverlayDrawFn` receives a
`CanvasComparisonScale` for each reveal source, while
`CanvasComparisonDivider` and `CanvasComparisonZoomGesture` carry divider and
pointer-zoom state without exposing the native renderer.

`OverlayState.zoom`, `OverlayState.qpane_rect`, `OverlayState.source_image`,
`OverlayState.transform`, `OverlayState.current_pan`, and
`OverlayState.physical_viewport_rect` are the detached native render values
available to low-level overlay integrations.

`CuteCanvas.contentSubject()` captures the stable drag/content subject for the
active composition. `CuteCanvas.setPanZoomLocked()` enables or disables direct
viewport navigation while preserving programmatic fit and presentation
reflow.

### Content references

`CanvasContentReference` identifies a composition, layer, or resource and
records the observed instance and resource revisions.
`CanvasDocument.resolve_content()` returns `ResolvedCanvasContent`; its
`stale` property reports whether the content changed while preserving stable
identity.
`CanvasContentKind` distinguishes composition, placed layer, and reusable
resource references.

`EmbeddedImageExportSnapshot` carries detached pixels and an exact resource
revision. `CuteCanvas.captureEmbeddedImageExport()` captures it without view
activation. `MaskExportSnapshot` carries a detached canvas-bounded grayscale
mask and exact resource revision; `CuteCanvas.captureMaskExport()` captures it
without changing mask or view activation.

### Projection

`CanvasProjectionRequest` records stable content identity, source bounds, and
output resolution. `CuteCanvas.requestProjection` begins cancellable rendering,
and `CuteCanvas.projectionCompleted` publishes exactly one
`CanvasProjectionResult`. `CanvasProjectionStatus` distinguishes completed,
cancelled, rejected, stale, and failed terminal outcomes.

## Editor Helpers

`CuteCanvas` is the widget and complete public API. `canvas.editor` groups the
most common application workflows into smaller typed helpers:

`CuteCanvas(execution_policy=...)` configures its owned standalone runtime.
`CuteCanvas(execution_runtime=...)` uses a host-owned runtime without
configuring or closing it.
`CuteCanvas(document_runtime=...)` shares document-scoped mutation work and
freshness with other views and leaves that binding host-owned.
`CuteCanvas.documentRuntime` returns that exact binding so a host can mount
another editor or presentation workspace without creating a competing
document scope.

`CanvasDocumentRuntime(document, execution_runtime=...)` binds durable document
state to ephemeral execution. `execution_scope` is the document-lifetime
scope, `open_view_scope()` creates receiver-safe view scopes, and
`native_execution_scope()` uses the supplied runtime when it supports stable
native affinity or creates a disjoint document-owned fallback for that work.

The `EditorFacade` collects these helpers without owning a second copy of
document state. `CompositionCollection` creates and resolves typed handles.
`ToolFacade` activates tools, `SelectionFacade` exposes pixel selection,
`CoverageFacade` authors coverage, `HistoryFacade` controls chronological undo
and redo, `CloneStampFacade` configures retouching, and
`CompositionPersistenceFacade` saves and restores composition archives.

* `compositions` creates and finds compositions through `CompositionHandle` values.
* `tools` lists and activates tools.
* `clone_stamp` activates Clone Stamp and manages its source and sampling.
* `selection` inspects or clears the pixel selection.
* `coverage` adds rectangles, ellipses, polygons, or grayscale coverage to the
  active mask or selection.
* `effects` highlights rendered layer content without editing it.
* `history` provides undo and redo for the open composition.
* `persistence` saves and restores editable composition archives.

Handles keep stable IDs and read current state from the canvas. They do not
cache a second mutable document model.

### Detached document persistence

`CompositionPersistenceFacade.capture_document()` captures every independent
composition and its transitive resources into an immutable
`DocumentPersistenceSnapshot`. Capture runs against live document authority
and performs no filesystem access. A host may pass the snapshot to a worker
and call `CompositionPersistenceFacade.write_document()` there; the write
never consults the live canvas or document. `save_document()` performs both
steps synchronously for hosts that do not need split scheduling.

- `DocumentPersistenceSnapshot.composition_ids` records the ordered root
  compositions represented by the capture.
- `CompositionPersistenceFacade.capture_document()` returns a detached
  document snapshot.
- `CompositionPersistenceFacade.write_document()` atomically writes a
  previously captured snapshot.
- `CompositionPersistenceFacade.load_document()` restores every root from one
  document archive.
- `prepare_document_restore()` decodes and validates an archive without touching
  a live editor, so hosts can perform that expensive work on a worker thread.
- `CompositionPersistenceFacade.restore_document()` transactionally installs a
  `PreparedDocumentRestore` on the editor-owning thread.

The sections below list the complete public surface. Use the narrative guides
for step-by-step workflows.

### Transient layer effects

- `LayerPresentationEffectKind` identifies QPane's supported transient treatments.
- `LayerPresentationStyle` validates one immutable renderer-owned treatment style.
- `LayerPresentationEffect` describes one stable scene-and-layer effect registration.
- `EditorFacade.effects` returns the focused `EffectsFacade`.
- `EffectsFacade.highlight` adds the standard visible-content emphasis treatment.
- `EffectsFacade.tint` adds a color treatment constrained to rendered coverage.
- `EffectsFacade.glow` adds a soft halo around rendered coverage.
- `EffectsFacade.bounds` adds a cosmetic rendered-product rectangle.
- `EffectsFacade.add` accepts any QPane `LayerPresentationStyle`.
- `EffectsFacade.clear` removes all active effects or only those for one layer.
- `LayerHandle.add_effect` is the direct handle-oriented equivalent.
- `LayerEffectHandle.state` returns the immutable current registration.
- `LayerEffectHandle.update` replaces the style without changing effect identity.
- `LayerEffectHandle.remove` retires the transient registration safely.
- `CuteCanvas.addLayerPresentationEffect` adds one effect through lower-level UUID identity.
- `CuteCanvas.updateLayerPresentationEffect` replaces a lower-level registration style.
- `CuteCanvas.removeLayerPresentationEffect` removes one lower-level registration.
- `CuteCanvas.clearLayerPresentationEffects` removes effects matching optional filters.
- `CuteCanvas.layerPresentationEffects` returns all active ordered registrations.

Effects are renderer-owned presentation state. They do not create history,
change composition archives, alter exports, or copy layer pixels.

**Jump within this file:**
* [CuteCanvas Setup and Settings](#qpane-setup-and-settings)
* [Config](#config)
* [Types](#types)
* [Project Resources](#project-resources)
* [Scene Composition](#scene-composition)
* [Compositions](#compositions)
* [Presentations and Projection](#presentations-and-projection)
* [Diagnostics](#diagnostics)
* [Masks and SAM](#masks-and-sam)
* [Extensibility](#extensibility)
* [View State & Geometry](#view-state--geometry)
* [Signals and Events](#signals-and-events)

**Start with the guides:**
* [Getting Started](getting-started.md)
* [Configuration](configuration.md)
* [Configuration Reference](configuration-reference.md)
* [Project Resources](project-resources.md)
* [Scene Composition](scenes.md)
* [Interaction Modes](interaction-modes.md)
* [Masks and SAM](masks-and-sam.md)
* [Diagnostics](diagnostics.md)
* [Extensibility](extensibility.md)

## CuteCanvas Setup and Settings
- CuteCanvas.applySettings — Apply a new `Config` to a live CuteCanvas, optionally merging keyword overrides for one-off tweaks.
- CuteCanvas.settings — Read the current settings snapshot; treat it as read-only and mutate copies instead.
- CuteCanvas.installedFeatures — Report which optional features (mask, SAM) are active after initialization.
- CuteCanvas.availableControlModes — List all registered control modes, including custom tools.
- CuteCanvas.getControlMode — Return the currently active control mode ID.
- CuteCanvas.setControlMode — Select a registered mode and return whether it was accepted. While Space is held, Pan/Zoom remains effective until release; unavailable mask/SAM modes return `False`, and unknown mode IDs raise `ValueError`.
- CuteCanvas.CONTROL_MODE_CURSOR — Built-in inert cursor mode (no pan/zoom).
- CuteCanvas.CONTROL_MODE_PANZOOM — Built-in pan/zoom mode for navigation.
- CuteCanvas.CONTROL_MODE_MOVE — Built-in selection-aware mode that moves selected editable pixels first, or a selectable movable layer when no pixel selection exists.
- CuteCanvas.CONTROL_MODE_TRANSFORM — Built-in affine transform mode with eight direct-manipulation handles for the selected movable layer.
- CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE — Built-in atomic resize mode for every movable layer in a continuous coincident-edge group. Horizontal and vertical midpoints move the complete group; eligible endpoint points remain adjustable at any angle.
- CuteCanvas.CONTROL_MODE_CLONE_STAMP — Built-in revision-stable Clone Stamp mode for editable RGBA layers.
- CuteCanvas.CONTROL_MODE_SELECT_POLYGON — Point-by-point retained polygon authoring for the active pixel selection.
- CuteCanvas.CONTROL_MODE_MASK_RECTANGLE — Retained rectangle authoring for the active mask target.
- CuteCanvas.CONTROL_MODE_MASK_ELLIPSE — Retained ellipse authoring for the active mask target.
- CuteCanvas.CONTROL_MODE_MASK_LASSO — Retained freeform authoring for the active mask target.
- CuteCanvas.CONTROL_MODE_MASK_POLYGON — Point-by-point retained polygon authoring for the active mask target.
- ControlMode.TRANSFORM — Enum value for the built-in affine transform mode.

See also: [Configuration](configuration.md) and [Interaction Modes](interaction-modes.md).

## Config
- Config — Immutable-like settings object handed to CuteCanvas; fields are JSON-serializable.
- Config.copy — Deep-clone a config so you can branch without mutating the original.
- Config.as_dict — Return the configuration as a plain dictionary.
- Config.configure — Merge another config/mapping plus keyword overrides; unknown keys raise and enum-backed values (cache mode, placeholder scale/zoom, diagnostics domains) accept enums or canonical strings only.
- Config.feature_descriptors — Expose feature schemas/validators for building UI around optional settings.

See also: [Configuration](configuration.md) and [Configuration Reference](configuration-reference.md).

## Types

### Enums
- cutecanvas.CacheMode — Cache budgeting modes.
	- CacheMode.AUTO — Adapts to OS pressure using headroom settings (`auto`).
	- CacheMode.HARD — Uses a fixed budget (`hard`).
- cutecanvas.PlaceholderScaleMode - Placeholder scaling rules.
	- PlaceholderScaleMode.AUTO — Default scaling (`auto`).
	- PlaceholderScaleMode.LOGICAL_FIT — Fit to logical viewport (`logical_fit`).
	- PlaceholderScaleMode.PHYSICAL_FIT — Fit to physical viewport (`physical_fit`).
	- PlaceholderScaleMode.RELATIVE_FIT — Scale relative to viewport (`relative_fit`).
- cutecanvas.ZoomMode — Placeholder zoom strategies.
	- ZoomMode.FIT — Fit to viewport (`fit`).
	- ZoomMode.LOCKED_ZOOM — Keep zoom level constant (`locked_zoom`).
	- ZoomMode.LOCKED_SIZE — Keep size constant (`locked_size`).
- cutecanvas.DiagnosticsDomain — Diagnostics overlay domains; use enum members (or `.value`) when configuring diagnostics. The base overlay always shows paint/zoom/pyramid rows; the toggles below control additional detail domains.
	- DiagnosticsDomain.CACHE — Cache budgets, usage, and eviction/entitlement detail.
	- DiagnosticsDomain.SWAP — Navigation, renderer queues, and prefetch metrics.
	- DiagnosticsDomain.MASK — Mask status, autosave, job queues, and brush info.
	- DiagnosticsDomain.EXECUTOR — Accepted, pending, running, retained, rejected, and completed execution work.
	- DiagnosticsDomain.RETRY — Retry queues per resource plus compact summaries.
	- DiagnosticsDomain.SAM — SAM cache, readiness, preparation, and inference activity.
- cutecanvas.ControlMode — Built-in control mode identifiers for tool registration.
	- ControlMode.CURSOR — Inert cursor mode (`cursor`).
	- ControlMode.PANZOOM — Pan/zoom mode (`panzoom`).
	- ControlMode.MOVE — Direct layer movement mode (`move`).
	- ControlMode.DRAW_BRUSH — Mask painting mode (`draw-brush`).
	- ControlMode.ERASER — Explicit transparent-paint mode (`eraser`).
	- ControlMode.CLONE_STAMP — Clone Stamp retouching mode (`clone-stamp`).
	- ControlMode.SMART_SELECT — SAM-based selection mode (`smart-select`).
	- ControlMode.SMART_MASK — SAM-based mask-authoring mode (`smart-mask`).
	- ControlMode.SELECT_RECTANGLE — Rectangular pixel-selection mode (`select-rectangle`).
	- ControlMode.SELECT_ELLIPSE — Elliptical pixel-selection mode (`select-ellipse`).
	- ControlMode.SELECT_LASSO — Freeform pixel-selection mode (`select-lasso`).
- cutecanvas.PixelSelectionMode — Coverage combination used by pixel-selection edits.
	- PixelSelectionMode.REPLACE — Replace existing selection coverage.
	- PixelSelectionMode.ADD — Add incoming soft coverage.
	- PixelSelectionMode.SUBTRACT — Subtract incoming soft coverage.
	- PixelSelectionMode.INTERSECT — Retain overlapping coverage.
- cutecanvas.CoverageCoordinateSpace — Coordinate interpretation for direct retained-coverage authoring.
	- CoverageCoordinateSpace.TARGET — Use layer-local coordinates for layer targets or scene coordinates for the pixel-selection target.
	- CoverageCoordinateSpace.NORMALIZED_TARGET — Use normalized fractions of the active target's finite bounds.
- cutecanvas.FloatingPixelMode — Whether an unresolved pixel fragment will cut or copy its source.
	- FloatingPixelMode.CUT — Clear selected source pixels when the fragment resolves.
	- FloatingPixelMode.COPY — Preserve source pixels when the fragment resolves.
- cutecanvas.ComparisonOrientation — Split direction for comparison rendering.
	- ComparisonOrientation.VERTICAL — Reveal the comparison image to the right of a vertical divider.
	- ComparisonOrientation.HORIZONTAL — Reveal the comparison image below a horizontal divider.

### Data Structures
- cutecanvas.CompositionPolicy — Host-controlled structural policy for one composition document.
	- CompositionPolicy.removable — Allow the composition to be removed through `CuteCanvas.removeComposition`.
- cutecanvas.CompositionEntry — Snapshot row for one renderable composition.
	- CompositionEntry.composition_id — Stable UUID used with `CuteCanvas.openComposition`.
	- CompositionEntry.kind — Descriptive document-kind metadata; it does not control behavior.
	- CompositionEntry.title — Host-facing browser title.
	- CompositionEntry.scene_layer_count — Number of ordered layer instances in the composition.
	- CompositionEntry.scene_bounds — Authoritative scene-coordinate canvas bounds for the composition.
	- CompositionEntry.layers — Bottom-to-top detached `CompositionLayerEntry` values for building nested layer browsers without activating the composition.
	- CompositionEntry.policy — Current host-controlled `CompositionPolicy`.
- cutecanvas.CompositionLayerEntry — Detached browser metadata for one ordered layer instance.
	- CompositionLayerEntry.layer_id — Stable layer-instance UUID.
	- CompositionLayerEntry.source_kind — Presentation name for the layer source domain.
	- CompositionLayerEntry.source_id — Shared source-resource UUID.
	- CompositionLayerEntry.label — Optional host-facing layer label.
	- CompositionLayerEntry.role — Layer role such as `"base-image"` or `"content"`.
	- CompositionLayerEntry.visible — Current instance visibility.
	- CompositionLayerEntry.opacity — Current instance opacity.
	- CompositionLayerEntry.interaction — Host-controlled layer interaction policy.
	- CompositionLayerEntry.transform — Detached exact local-to-scene affine, projective, or piecewise mapping.
- cutecanvas.CompositionSnapshot — Structured composition browser state.
	- CompositionSnapshot.compositions — Mapping of composition UUID to `CompositionEntry`.
	- CompositionSnapshot.order — Composition UUIDs in browser order.
	- CompositionSnapshot.current_composition_id — Active composition UUID, or None.
- cutecanvas.MaskInfo — Mask metadata returned by mask helpers, including stable `scene_id`, `layer_id`, and `interaction` policy for generic scene-layer operations.
- cutecanvas.DiagnosticRecord — Label/value diagnostic entry used in overlays.
- cutecanvas.CanvasOverlayState — Renderer-neutral detail-overlay snapshot passed to `registerCanvasOverlay` callbacks.
	- CanvasOverlayState.display_scale — Actual horizontal and vertical physical display pixels occupied by one source pixel.
	- CanvasOverlayState.zoom — Current zoom factor.
	- CanvasOverlayState.viewport — Widget-space bounds of the canvas.
	- CanvasOverlayState.physical_viewport — Device-pixel viewport bounds.
	- CanvasOverlayState.transform — Image-to-widget transform for coordinate anchoring.
	- CanvasOverlayState.pan — Current pan offset in widget space.
	- CanvasOverlayState.source_image — Available source raster for image-oriented overlay helpers.
- cutecanvas.CanvasDisplayScale — Horizontal and vertical physical source-pixel scale for detail-overlay indicators.
- cutecanvas.LayerPolicy — Host policy for direct and structural layer interaction.
	- LayerPolicy.selectable — Allow direct tools to select the layer through covered source pixels.
	- LayerPolicy.movable — Allow generic placement mutation and Move-tool dragging for the layer.
	- LayerPolicy.pixel_editable — Allow pixel tools to mutate a layer when its source also advertises raster editing.
	- LayerPolicy.reorderable — Allow the layer instance to move within its composition stack.
	- LayerPolicy.removable — Allow the layer instance to be removed from its composition.
- cutecanvas.LayerSelectionSnapshot — Selected scene-layer identity, kept separate from pixel-selection coverage.
	- LayerSelectionSnapshot.scene_id — Public identity of the scene containing the selected layer.
	- LayerSelectionSnapshot.layer_id — Stable identity of the selected layer.
- cutecanvas.MoveToolOptions — Immutable direct-layer movement configuration.
	- MoveToolOptions.auto_select_layers — Select topmost visible content at gesture start instead of preserving the existing layer set.
- cutecanvas.RasterExtentPolicy — Write-boundary policy for raster layer storage.
	- RasterExtentPolicy.FIXED — Clip edits to the layer's current local bounds.
	- RasterExtentPolicy.EXPAND_ON_WRITE — Preserve the original grow-on-write contract with sparse backing.
	- RasterExtentPolicy.UNBOUNDED — Accept edits at arbitrary local coordinates while allocating only touched tiles.
- cutecanvas.EditorCapability — Independently composable host permission for one editor capability.
	- EditorCapability.SELECT_PIXELS — Create or modify composition pixel selections.
	- EditorCapability.EDIT_PIXELS — Clear or move pixels on intrinsically editable sources.
	- EditorCapability.PAINT — Paint through the active source-owned target.
	- EditorCapability.MOVE_LAYERS — Move complete policy-enabled layers.
	- EditorCapability.TRANSFORM_LAYERS — Apply interactive affine layer transforms.
	- EditorCapability.EDIT_VECTORS — Modify semantic vector objects and their retained geometry.
	- EditorCapability.MANAGE_LAYERS — Create, remove, reorder, and configure composition layers.
	- EditorCapability.EDIT_RESOURCES — Perform explicit destructive edits on reusable resources.
- cutecanvas.EditorIntent — Public operation identifier accepted by `CuteCanvas.editorOperationState`.
	- EditorIntent.SELECT_PIXELS — Inspect pixel-selection creation and modification.
	- EditorIntent.DELETE_PIXELS — Inspect selection-constrained pixel clearing.
	- EditorIntent.PAINT — Inspect the active paint target.
	- EditorIntent.MOVE — Inspect selected-pixel or complete-layer movement.
	- EditorIntent.TRANSFORM — Inspect selected-pixel or complete-layer transform.
- cutecanvas.EditorPolicy — Immutable set of editor capabilities enabled by the host; the default contains every capability.
	- EditorPolicy.capabilities — Complete immutable `EditorCapability` set.
	- EditorPolicy.noneditable_paint — Interactive brush behavior for a selected layer that cannot store pixels.
- cutecanvas.NonEditablePaintPolicy — Paint-destination provisioning behavior.
	- NonEditablePaintPolicy.CREATE_RASTER_LAYER — Create and select a real unbounded raster layer above the selection.
	- NonEditablePaintPolicy.REJECT — Reject the stroke without changing selection or content.
- cutecanvas.EditorOperationState — Detached operation decision containing availability, denial, explicit alternatives, and resolved scene/layer identity.
	- EditorOperationState.intent — Operation identifier used for this query.
	- EditorOperationState.allowed — Whether the operation can execute now.
	- EditorOperationState.denial — Stable denial string, or `None` when allowed.
	- EditorOperationState.alternatives — Explicit source-owned alternatives such as rasterization.
	- EditorOperationState.scene_id — Resolved scene identity when available.
	- EditorOperationState.layer_id — Resolved layer identity when available.
- cutecanvas.RasterSurfaceSnapshot — Detached storage snapshot for one active raster scene layer.
	- RasterSurfaceSnapshot.scene_id — Scene UUID used to query the layer.
	- RasterSurfaceSnapshot.layer_id — Stable raster layer UUID.
	- RasterSurfaceSnapshot.bounds — Integer storage rectangle in layer-local coordinates; its origin may be negative.
	- RasterSurfaceSnapshot.extent_policy — Current `RasterExtentPolicy` applied to edits.
	- RasterSurfaceSnapshot.content_revision — Revision of authoritative raster pixels.
	- RasterSurfaceSnapshot.structure_revision — Revision of bounds or policy state.
	- RasterSurfaceSnapshot.pending_request_id — Active bounds request UUID, or `None`.
- cutecanvas.PlacedAssetMode — Persistence relationship for a non-destructive placed source.
	- PlacedAssetMode.EMBEDDED — Pixels are stored as part of the composition resource.
	- PlacedAssetMode.LINKED — Pixels retain an external filesystem locator and can be refreshed.
- cutecanvas.PlacedAssetStatus — Availability of the latest requested linked content.
	- PlacedAssetStatus.READY — The current source decoded successfully.
	- PlacedAssetStatus.LOADING — A newer linked generation is decoding asynchronously.
	- PlacedAssetStatus.MISSING — The linked locator is unavailable; retained fallback pixels remain visible when configured.
	- PlacedAssetStatus.ERROR — The linked source could not be decoded; retained fallback pixels remain visible.
- cutecanvas.PlacedAssetSnapshot — Detached provenance state for one active placed layer.
	- PlacedAssetSnapshot.scene_id — Public scene UUID used to query the layer.
	- PlacedAssetSnapshot.layer_id — Stable independent layer-instance UUID.
	- PlacedAssetSnapshot.asset_id — Shared non-destructive source UUID.
	- PlacedAssetSnapshot.mode — Persistence relationship that determines whether pixels are embedded or linked.
	- PlacedAssetSnapshot.status — Availability of the latest requested content generation.
	- PlacedAssetSnapshot.source_path — Linked filesystem locator, or `None` for embedded sources.
	- PlacedAssetSnapshot.error — Latest non-modal link/decode error, or `None`.
	- PlacedAssetSnapshot.keep_fallback — Whether private composition archives retain last-known linked pixels.
	- PlacedAssetSnapshot.content_revision — Revision of the current decoded source product.
	- PlacedAssetSnapshot.generation — Generation used to reject stale asynchronous link work.
- cutecanvas.SceneSnapshot — Public scene snapshot for an active generated or host-authored composition.
	- SceneSnapshot.composition_id — Stored composition UUID.
	- SceneSnapshot.scene_id — Render scene UUID; layered scene compositions use the composition UUID.
	- SceneSnapshot.title — Host-facing composition title.
	- SceneSnapshot.bounds — Host-defined scene-coordinate bounds.
	- SceneSnapshot.layers — Ordered `LayerSnapshot` entries.
- cutecanvas.LayerSnapshot — Source-backed layer in a composed scene.
	- LayerSnapshot.layer_id — Stable layer UUID supplied by the host.
	- LayerSnapshot.source_kind — Project resource domain such as `imported-raster`, `linked-raster`, `raster`, `coverage`, `vector`, or `composition`.
	- LayerSnapshot.source_id — Stable project resource UUID independent of the layer UUID.
	- LayerSnapshot.placement — Conservative axis-aligned scene bound derived from the exact transform.
	- LayerSnapshot.transform — Detached affine/projective `QTransform` or immutable piecewise mapping for the layer instance.
	- LayerSnapshot.visible — Whether the layer renders and hit-tests.
	- LayerSnapshot.opacity — Layer opacity from `0.0` to `1.0`.
	- LayerSnapshot.tint — Detached optional presentation tint for layer types such as masks.
	- LayerSnapshot.clip — Optional `CompositionLayerClip` preserved from the normalized request layer.
	- LayerSnapshot.hit_test — Whether `CuteCanvas.sceneHitTest` can return this layer.
	- LayerSnapshot.role — Host label carried into hits and overlays.
	- LayerSnapshot.metadata — Opaque host metadata carried into hits and overlays.
	- LayerSnapshot.interaction — Current selection and movement policy for the layer.
	- LayerSnapshot.label — Optional host-facing authoring-layer label.
- cutecanvas.CompositionLayerClip — Optional layer clip rectangle.
	- CompositionLayerClip.coordinate_space — Coordinate system for `rect`: `"scene"`, `"normalized-scene"`, `"viewport"`, or `"normalized-viewport"`.
	- CompositionLayerClip.rect — Clip rectangle in the selected coordinate space.
- cutecanvas.LayerHit — Public scene hit result returned by `CuteCanvas.sceneHitTest`.
	- LayerHit.composition_id — Active composition UUID.
	- LayerHit.scene_id — Scene UUID.
	- LayerHit.layer_id — Hit layer UUID.
	- LayerHit.source_id — Project resource UUID backing the hit layer.
	- LayerHit.role — Host role copied from the layer.
	- LayerHit.metadata — Opaque metadata copied from the layer.
	- LayerHit.panel_point — Tested widget coordinate.
	- LayerHit.scene_point — Hit point in scene coordinates.
	- LayerHit.source_point — Hit point in source image pixel coordinates.
- cutecanvas.SceneSnapshotOverlayState — Scene-overlay snapshot passed to `registerSceneOverlay` callbacks.
	- SceneSnapshotOverlayState.zoom — Current zoom factor.
	- SceneSnapshotOverlayState.qpane_rect — Widget-space bounds.
	- SceneSnapshotOverlayState.physical_viewport_rect — Device-pixel viewport bounds.
	- SceneSnapshotOverlayState.scene_id — Active scene UUID.
	- SceneSnapshotOverlayState.scene_bounds — Scene-coordinate bounds.
	- SceneSnapshotOverlayState.layers — Rendered public scene layers.
- cutecanvas.SceneSnapshotOverlayLayer — Rendered layer geometry for scene overlays.
	- SceneSnapshotOverlayLayer.layer_id — Public layer UUID.
	- SceneSnapshotOverlayLayer.source_id — Reusable source UUID when available.
	- SceneSnapshotOverlayLayer.label — Optional host-facing layer label.
	- SceneSnapshotOverlayLayer.role — Host role copied from the layer.
	- SceneSnapshotOverlayLayer.metadata — Opaque metadata copied from the layer.
	- SceneSnapshotOverlayLayer.placement — Scene-coordinate placement.
	- SceneSnapshotOverlayLayer.source_size — Resolved source raster size.
	- SceneSnapshotOverlayLayer.transform — Source-pixel to widget-coordinate transform.
	- SceneSnapshotOverlayLayer.panel_bounds — Layer bounds in widget coordinates.
	- SceneSnapshotOverlayLayer.visible — Whether the rendered layer is visible.
- cutecanvas.PanelHitTest — Hit-test metadata from `CuteCanvas.panelHitTest`.
	- PanelHitTest.panel_point — Panel-space position that was tested.
	- PanelHitTest.raw_point — Unclamped image-space coordinate as float.
	- PanelHitTest.clamped_point — Image-space coordinate clamped to image bounds.
	- PanelHitTest.inside_image — True when the raw point lies inside the image.

## Project Resources

- CuteCanvas.createCompositionFromImage — Import detached pixels as a project
  resource and create a composition containing one ordinary layer instance.
- CuteCanvas.duplicateLayer — Duplicate an instance while sharing its resource.
- CuteCanvas.forkLayerResource — Clone a resource and redirect only the selected
  instance.
- CuteCanvas.placeComposition — Place another composition as a live nested resource;
  dependency cycles are rejected atomically.

Project resources own shared content identity, kind, revision, editability, and
dependencies. Layer instances own presentation and host interaction policy.
Saving a root composition follows its transitive resource graph and writes every
nested composition and payload exactly once.

See also: [Project Resources](project-resources.md).

## Scene Composition
- CuteCanvas.fitSceneRect — Return the largest centered aspect-preserving scene rectangle inside a target rectangle.
- CuteCanvas.fillSceneRect — Return the smallest centered aspect-preserving scene rectangle covering a target rectangle; the result may extend outside the target.
- CuteCanvas.currentScene — Return CuteCanvas's normalized public scene snapshot, or None.
- CuteCanvas.sceneHitTest — Return topmost public scene-layer metadata for a widget-space point.
- CuteCanvas.layerTransform — Return a detached exact affine/projective transform or immutable piecewise mapping for one active scene layer.
- CuteCanvas.layerLocalBounds — Return detached intrinsic source-local bounds for one active scene layer when available.
- CuteCanvas.registerSceneOverlay — Add a named scene overlay; order follows registration.
- CuteCanvas.unregisterSceneOverlay — Remove a scene overlay; no-op if it is absent.
- CuteCanvas.sceneOverlays — Return a read-only snapshot of registered scene overlays; use register/unregister helpers to change it.
- CuteCanvas.setLayerInteractionPolicy — Replace selection and movement permissions for a layer through its scene owner.
- CuteCanvas.setLayerPlacement — Set an absolute scene-space layer rectangle when movement policy permits it.
- CuteCanvas.setLayerTransform — Set an invertible affine, projective, or piecewise local-to-scene mapping when movement policy permits it.
- CuteCanvas.setLayerIndex — Move one active layer to a bottom-to-top render index as one undoable composition-stack edit.
- CuteCanvas.selectedLayer — Return selected scene-layer identity independently of pixel coverage.
- CuteCanvas.selectedLayers — Return the complete ordered layer selection with its active member last.
- CuteCanvas.setSelectedLayer — Select a policy-enabled layer in the active scene.
- CuteCanvas.setSelectedLayers — Replace selection with policy-enabled layers and an optional active member.
- CuteCanvas.clearSelectedLayer — Clear layer identity without clearing pixel selection.
- CuteCanvas.moveToolOptions — Return immutable direct-layer movement options.
- CuteCanvas.setMoveToolOptions — Replace direct-layer movement options.
- CuteCanvas.rasterSurfaceState — Return local bounds, extent policy, and revisions for a supported active raster layer.
- CuteCanvas.setRasterExtentPolicy — Choose whether writes clip to current local bounds or expand storage.
- CuteCanvas.requestRasterBounds — Asynchronously pad or crop a supported raster layer to exact integer local bounds while preserving its scene transform.
- CuteCanvas.addEditableRasterLayer — Copy a color image into a composition-owned editable RGBA layer.
- CuteCanvas.placeEmbeddedAsset — Copy a `QImage` into a non-destructive embedded source and add an independently transformable layer instance.
- CuteCanvas.placeLinkedAsset — Begin non-blocking file decode and add a linked layer only after decoding succeeds.
- CuteCanvas.duplicateLayer — Add an independent layer instance that shares the selected project resource and future resource edits.
- CuteCanvas.placedAssetState — Return detached provenance, status, and generation state for a placed layer.
- CuteCanvas.refreshPlacedAsset — Reload the current linked locator without adding an editor-history command.
- CuteCanvas.relinkPlacedAsset — Decode a replacement locator and record the resulting provenance transition in scene history.
- CuteCanvas.embedPlacedAsset — Detach a linked source from its locator while retaining identical pixels; undo restores the exact link state.
- CuteCanvas.rasterizeLayer — Render an imported, linked, vector, or nested-document resource at explicit or natural pixel dimensions and atomically replace that layer instance with an editable RGBA resource.
- CuteCanvas.editableRasterLayerImage — Return a detached image snapshot for an editable RGBA layer.
- CuteCanvas.selectLayerCoverage — Project a mask or other coverage-source layer into pixel selection.
- CuteCanvas.deleteSelectedPixels — Clear selected coverage from the selected policy-enabled mask or RGBA layer.
- CuteCanvas.floatingPixelEditState — Return detached state for the unresolved floating fragment, or `None`.
- CuteCanvas.anchorFloatingPixels — Resolve floating pixels into their source or a compatible destination layer.
- CuteCanvas.promoteFloatingPixels — Resolve floating pixels into a newly created composition layer.
- CuteCanvas.cancelFloatingPixels — Cancel floating pixels without changing durable source pixels.
- CuteCanvas.sceneEditUndoAvailable — Report whether the active scene has a placement change to undo.
- CuteCanvas.sceneEditRedoAvailable — Report whether the active scene has a placement change to redo.
- CuteCanvas.undoSceneEdit — Undo the active scene's latest committed layer placement.
- CuteCanvas.redoSceneEdit — Redo the active scene's latest reverted layer placement.
- CuteCanvas.editorPolicy — Return the current immutable host editor policy.
- CuteCanvas.setEditorPolicy — Atomically replace independently composable editor capabilities and cancel provisional pointer work losslessly.
- CuteCanvas.editorOperationState — Query the same source, state, and policy decision used by built-in tools and editor commands.
- CuteCanvas.editorPolicyChanged — Emitted with the complete immutable policy after a real replacement.

Layered compositions combine imported and editable rasters, coverage, vectors,
and nested compositions. Each layer references one project resource while keeping
its own transform, visibility, opacity, effects, and interaction policy.

See also: [Scene Composition](scenes.md) and [Extensibility](extensibility.md).

## Compositions
- CuteCanvas.createComposition — Create and open an independent empty composition with positive scene-space canvas bounds.
- CuteCanvas.createCompositionFromImage — Import detached pixels and create an independent composition whose first image is an ordinary resource-backed layer.
- CuteCanvas.duplicateLayer — Duplicate one layer instance while sharing its project resource.
- CuteCanvas.forkLayerResource — Redirect one layer to an independent copy of its current resource.
- CuteCanvas.rasterizeLayer — Convert one imported, linked, vector, or nested-document resource into editable pixels while preserving the layer instance.
- CuteCanvas.layerRasterizationCompleted — Report the terminal result of each accepted generic rasterization request.
- CuteCanvas.placeComposition — Place another composition as a live nested resource.
- CuteCanvas.setCompositionPolicy — Replace host-controlled composition-removal permission.
- CuteCanvas.resizeCanvasBounds — Resize canvas bounds and align all content to one of nine anchor points without resampling or cropping.
- CuteCanvas.requestCanvasResampling — Begin source-aware whole-canvas resampling with `CanvasResamplingMode.FAST` or `CanvasResamplingMode.SMOOTH`.
- CuteCanvas.cancelCanvasResampling — Cancel a pending whole-canvas resampling request by UUID.
- CuteCanvas.canvasResamplingCompleted — Emit one terminal `CanvasResamplingResult` with completed, cancelled, rejected, stale, or failed status.
- CuteCanvas.cropLayersToCanvas — Apply an exact semantic canvas clip to every layer as one undoable edit.
- CanvasAnchor — Select the top, center, bottom, left, right, or corner point held fixed by a bounds resize.
- CanvasResamplingMode — Choose Qt-backed fast nearest or smooth pixel filtering for whole-canvas resampling.
- CanvasResamplingResult — Report one request identity, composition, target size, quality mode, terminal status, whether document state changed, and an actionable message.
- CanvasResamplingStatus — Distinguish completed, cancelled, rejected, stale, and failed canvas resampling outcomes.
- CuteCanvas.openComposition — Open an existing composition UUID.
- CuteCanvas.currentCompositionID — Return the active composition UUID, or None.
- CuteCanvas.compositionIDs — Return composition UUIDs in browser order.
- CuteCanvas.getCompositionSnapshot — Return composition rows for host browsers.
- CuteCanvas.removeComposition — Remove a composition when its policy permits it.
- CuteCanvas.removeLayer — Remove a layer instance when its layer policy permits it and record the change in composition history.

Every composition owns an independent canvas and ordered layer stack.
`createCompositionFromImage` copies the supplied pixels into one imported
resource and uses its dimensions for the initial canvas. Shared resources reuse
QPane render products while layer instances retain independent presentation.

See also: [Project Resources](project-resources.md).

`LayerHandle.duplicate()` returns another handle sharing the same project
resource. `LayerHandle.fork_resource()` redirects one instance to an
independent resource. `LayerHandle.rasterize()` converts any supported
renderable resource into editable pixels, and `LayerHandle.resource_id`
reports its current resource identity. `CompositionHandle.place_composition()`
places another composition as a live nested layer in the open destination.
`CompositionHandle.resize_bounds()`, `resample()`, and `crop_to_canvas()` expose
the canvas geometry workflows without raw composition identifiers.

## Presentations and Projection

- CanvasWorkspace.setSinglePresentation — Mount one composition target.
- CanvasWorkspace.setTabbedPresentation — Mount switchable targets while the host retains inspection groups.
- CanvasWorkspace.setGridPresentation — Arrange targets with a host-selected CuteCanvas responsive-grid policy.
- CanvasWorkspace.gridSnapshot — Return the current immutable CuteCanvas grid snapshot.
- CanvasWorkspace.targetActivated — Emit the composition selected through a presentation target.
- CanvasWorkspace.setInspectionGroups — Preserve host-owned linked inspection groups across presentation changes.
- CuteCanvas.outboundDragFailed — Emit a stable drag subject and host materialization error from one target.
- CuteCanvas.contentContextRequested — Emit a stable content subject and global position without activating its target.
- CanvasWorkspace.setComparisonPresentation — Reveal two independent targets across a draggable divider.
- CanvasWorkspace.registerComparisonOverlay — Draw host comparison chrome without native renderer access.
- CanvasWorkspace.comparisonZoomGesture — Report a pointer-originated comparison zoom without native renderer access.
- CanvasWorkspace.refreshComparisonOverlays — Request a comparison overlay repaint without native renderer access.
- CanvasWorkspace.setCustomPresentation — Build a registered host arrangement over validated targets.
- CanvasWorkspace.setInteractionMode — Apply read-only, mask-authoring, or full-editor policy to current and future views.
- CanvasWorkspace.setOutboundMimeProvider — Apply host MIME materialization to every presentation target.
- CuteCanvas.requestProjection — Render a stable composition or layer reference at explicit source bounds and output resolution.
- CuteCanvas.projectionCompleted — Emit one terminal `CanvasProjectionResult`.
- CanvasProjectionHandle.cancel — Cancel pending work and suppress late publication.
- CanvasProjectionResult.status — Report `COMPLETED`, `CANCELLED`, `REJECTED`, `STALE`, or `FAILED`.

Presentations belong to `CanvasViewSession`, not document history. Projection
uses the mounted QPane scene renderer and publishes pixels only while the
captured `CanvasContentReference` revision remains current.

## Diagnostics
- CuteCanvas.diagnosticsOverlayEnabled — Read whether the diagnostics HUD is visible.
- CuteCanvas.setDiagnosticsOverlayEnabled — Enable or disable the diagnostics HUD.
- CuteCanvas.diagnosticsDomains — List available diagnostics domains.
- CuteCanvas.diagnosticsDomainEnabled — Read whether a given domain is enabled; raises when the domain is unavailable.
- CuteCanvas.setDiagnosticsDomainEnabled — Enable or disable a domain; raises when the domain is unavailable.

See also: [Diagnostics](diagnostics.md).

## Masks and SAM
### Masks
- CuteCanvas.maskFeatureAvailable — Check whether the mask feature is installed.
- CuteCanvas.activeMaskID — Read the active mask UUID (or None).
- CuteCanvas.maskIDsForComposition — List mask UUIDs for the given or active document.
- CuteCanvas.listMasksForComposition — Return document mask metadata.
- CuteCanvas.createBlankMask — Create a transparent mask layer, optionally outside user undo history.
- CuteCanvas.loadMaskFromFile — Import a mask file with optional document-admission history.
- CuteCanvas.removeMaskFromComposition — Remove a mask instance from a document.
- CuteCanvas.setActiveMaskID — Select a mask for editing (or clear with None).
- CuteCanvas.getActiveMaskImage — Snapshot the active mask as a grayscale image.
- CuteCanvas.exportMaskImage — Snapshot an addressed mask without changing active editor state.
- CuteCanvas.replaceMaskFromFile — Replace an addressed mask's pixels from a file while retaining its UUID.
- CuteCanvas.replaceMaskImage — Replace an addressed mask's pixels from a `QImage` while retaining its UUID.
- CuteCanvas.getMaskUndoState — Return a `cutecanvas.MaskUndoState` snapshot with undo/redo depth for a mask ID.
- CuteCanvas.setMaskProperties — Update mask color and/or opacity for an existing mask.
- CuteCanvas.prefetchMaskOverlays — Queue background presentation work for one document's masks.
- CuteCanvas.cycleMasksForward — Rotate the active document's mask stack forward.
- CuteCanvas.cycleMasksBackward — Rotate the active document's mask stack backward.
- CuteCanvas.undoMaskEdit — Undo the last mask edit when a mask is active.
- CuteCanvas.redoMaskEdit — Redo the last reverted mask edit when a mask is active.
- CuteCanvas.CONTROL_MODE_DRAW_BRUSH — Built-in brush mode for mask painting.
- CuteCanvas.CONTROL_MODE_ERASER — Built-in eraser mode using the active brush preset without Alt inversion.

CuteCanvas receives touch and tablet input automatically. Pan/zoom mode supports direct one-finger pan, centroid-anchored two-finger pan/pinch, double tap, and optional translation inertia. Brush mode supports fixed-size touch painting plus pressure-sensitive active pens and eraser tips. These behaviors are configured through `Config`; see [Touch and Pen Input](touch-and-pen.md).

### SAM
- `warmSamDependencies` imports the optional SAM runtime eagerly through the
  package's public API.
- CuteCanvas.samFeatureAvailable — Check whether the SAM feature is installed.
- CuteCanvas.samCheckpointReady — Check whether the resolved SAM checkpoint exists on disk.
- CuteCanvas.samCheckpointPath — Return the resolved SAM checkpoint path when available.
- CuteCanvas.samCheckpointStatusChanged — Signal that reports SAM checkpoint readiness changes (status, path); `"downloading"` also covers integrity verification when a hash is required.
- CuteCanvas.samCheckpointProgress — Signal that reports checkpoint download progress (downloaded, total or None).
- CuteCanvas.refreshSamFeature — Reinstall SAM tooling using the current configuration snapshot.
- CuteCanvas.CONTROL_MODE_SMART_SELECT — Built-in smart-select mode using SAM predictions.
- CuteCanvas.CONTROL_MODE_SMART_MASK — Built-in smart-mask mode using SAM predictions.

See also: [Masks and SAM](masks-and-sam.md) and [Interaction Modes](interaction-modes.md).

## Extensibility

### Overlays
- CuteCanvas.registerCanvasOverlay — Add renderer-neutral detail chrome; callbacks receive `CanvasOverlayState`.
- CuteCanvas.unregisterCanvasOverlay — Remove one renderer-neutral detail overlay; no-op if absent.
- CuteCanvas.registerOverlay — Add a named overlay; order follows registration.
- CuteCanvas.unregisterOverlay — Remove an overlay; no-op if it is absent.
- CuteCanvas.contentOverlays — Return a read-only snapshot of registered content overlays; use register/unregister helpers to change it.
- CuteCanvas.registerSceneOverlay — Add a named scene overlay for active layered scene composition layers.
- CuteCanvas.unregisterSceneOverlay — Remove a scene overlay; no-op if it is absent.
- CuteCanvas.sceneOverlays — Return a read-only snapshot of registered scene overlays.
- CuteCanvas.overlaysSuspended — Report whether overlays are temporarily suppressed.
- CuteCanvas.overlaysResumePending — Indicate overlays should resume after activation work.
- CuteCanvas.resumeOverlays — Resume overlays without forcing a repaint.
- CuteCanvas.resumeOverlaysAndUpdate — Resume overlays and schedule a repaint.
- CuteCanvas.maybeResumeOverlays — Resume overlays when pending activation work completes.

### Tool Registration
- CuteCanvas.registerTool — Register a custom tool/control mode (unique ID required).
- CuteCanvas.unregisterTool — Remove a custom tool; cannot remove the active mode or built-ins.
- CuteCanvas.registerCursorProvider — Attach a cursor provider to a control mode.
- CuteCanvas.unregisterCursorProvider — Remove a cursor provider and refresh if active.
- CuteCanvas.setEditorCursorTheme — Install optional host artwork for built-in semantic editor cursor feedback; pass `None` to restore all portable defaults.
- EditorCursorIntent — Stable semantic intents for default, forbidden, precise, additive, subtractive, and selection-boundary translation feedback.
- EditorCursorTheme — Host protocol that resolves an intent and device-pixel ratio to a `QCursor`, or returns `None` to defer to CuteCanvas.

Custom editor tools use QPane's public `ViewerTool` and `ViewerToolSignals`
contract. `CuteCanvas.registerTool` installs those tools into the same generic
input lifecycle used by QPane's built-in viewer tools.

See also: [Extensibility](extensibility.md) and [Interaction Modes](interaction-modes.md).

## View State & Geometry
- CuteCanvas.currentZoom — Read the current zoom factor (float) as a device-pixel normalized value. Matches the payload emitted via `CuteCanvas.zoomChanged`.
- CuteCanvas.setZoomFit — Fit the current image to the viewport and recenter pan.
- CuteCanvas.setZoom1To1 — Snap zoom to native scale while keeping `anchor` steady when provided.
- CuteCanvas.applyZoom — Clamp zoom requests and remap unity to the device-native scale.
- CuteCanvas.viewportRectChanged — `QRectF` signal fired whenever the physical viewport changes size (resizes or monitor/DPR changes). Emits once after initialization so status bars and overlays can seed layout state before user interaction.
- CuteCanvas.currentViewportRect — Returns the most recent physical viewport rect snapshot, falling back to the live `physicalViewportRect()` when no emission occurred yet.
- CuteCanvas.sceneToPanelRect — Map a valid absolute scene rectangle into detached logical widget coordinates, or return `None` when no scene is active.
- CuteCanvas.panelHitTest — Facade helper returning the DPR-aware `PanelHitTest` metadata (raw/clamped coordinates plus inside-image flag) for a panel-space `QPoint`.
- CuteCanvas.sceneHitTest — Return scene-layer hit metadata for a panel-space `QPoint` when a layered scene composition is active.

See also: [Documents and Layers](scenes.md) and [Interaction Modes](interaction-modes.md).

## Signals and Events

### Documents and Interaction
- CuteCanvas.controlModeChanged — Control-mode ID emitted after every successful tool activation, including internal fallbacks and host-initiated changes.
- CuteCanvas.compositionChanged — `CompositionSnapshot` payload emitted after composition records change.
- CuteCanvas.compositionSelectionChanged — Composition UUID or `None` payload emitted when selection changes.
- CuteCanvas.sceneChanged — `SceneSnapshot` or `None` payload emitted when the normalized active render scene changes.
- CuteCanvas.layerPixelsChanged — Scene, layer, and resource UUIDs emitted once after a durable generic layer-pixel mutation, including chronological undo and redo replay.
- CuteCanvas.sceneEditHistoryChanged — Two booleans reporting active-scene chronological editor undo and redo availability.
- CuteCanvas.pixelSelectionChanged — `PixelSelectionSnapshot` payload emitted when the active composition selection changes.
- CuteCanvas.floatingPixelEditChanged — `FloatingPixelSnapshot` or `None` emitted when unresolved fragment state changes.
- CuteCanvas.editorTransformChanged — `EditorTransformSnapshot` emitted when the explicit target, live frame, or unresolved affine preview changes.
- CuteCanvas.selectedLayerChanged — `LayerSelectionSnapshot` or `None` emitted when selected layer identity changes.
- CuteCanvas.selectedLayersChanged — Ordered `LayerSelectionSnapshot` tuple emitted when layer selection changes.
- CuteCanvas.moveToolOptionsChanged — `MoveToolOptions` emitted after direct-layer movement configuration changes.
- CuteCanvas.CONTROL_MODE_SELECT_RECTANGLE — Built-in rectangular pixel-selection tool ID.
- CuteCanvas.CONTROL_MODE_SELECT_ELLIPSE — Built-in elliptical pixel-selection tool ID.
- CuteCanvas.CONTROL_MODE_SELECT_LASSO — Built-in freeform pixel-selection tool ID.
- CuteCanvas.pixelSelectionState — Return the active composition's detached selection snapshot.
- CuteCanvas.setPixelSelection — Combine caller-provided grayscale coverage at explicit scene-coordinate bounds.
- CuteCanvas.clearPixelSelection — Clear selection coverage in the active composition.
- CuteCanvas.selectAllPixels — Select the active scene's finite canvas bounds.
- CuteCanvas.invertPixelSelection — Invert coverage inside the active scene's finite canvas bounds.
- cutecanvas.PixelSelectionSnapshot — Detached scene ID, revision, optional bounds, and grayscale coverage for one composition selection.
	- PixelSelectionSnapshot.scene_id — Public active-scene identity.
	- PixelSelectionSnapshot.revision — Monotonic selection revision for that scene.
	- PixelSelectionSnapshot.bounds — Optional scene-coordinate coverage bounds.
	- PixelSelectionSnapshot.coverage — Optional detached grayscale coverage image.
	- PixelSelectionSnapshot.has_selection — Whether nonzero selection coverage is active.
- cutecanvas.FloatingPixelSnapshot — Detached unresolved-fragment source identity, cut/copy mode, local offset, and scene bounds.
	- FloatingPixelSnapshot.scene_id — Public scene owning the floating edit.
	- FloatingPixelSnapshot.source_layer_id — Layer from which pixels were lifted.
	- FloatingPixelSnapshot.mode — Whether resolution cuts or copies source pixels.
	- FloatingPixelSnapshot.offset — Integer source-local movement from the lift origin.
	- FloatingPixelSnapshot.bounds — Current scene-coordinate content-selection bounds.
	- FloatingPixelSnapshot.dragging — Whether a direct selected-pixel pointer drag currently owns the floating edit.
- cutecanvas.EditorTransformTarget — Select either complete selection bounds with selected-layer pixel payload or tight nontransparent layer-content bounds.
	- EditorTransformTarget.SELECTION_CONTENT — Use the complete pixel-selection bounds as the frame and selected-layer pixels as the payload.
	- EditorTransformTarget.LAYER_CONTENT — Use the selected layer's tight nontransparent content bounds as both frame and payload source.
- cutecanvas.EditorTransformCommand — Apply a frame-relative command to the current cumulative preview.
	- EditorTransformCommand.ROTATE_LEFT_90 — Rotate the preview 90 degrees counterclockwise around its current center.
	- EditorTransformCommand.ROTATE_RIGHT_90 — Rotate the preview 90 degrees clockwise around its current center.
	- EditorTransformCommand.FLIP_HORIZONTAL — Mirror the preview across its current vertical center axis.
	- EditorTransformCommand.FLIP_VERTICAL — Mirror the preview across its current horizontal center axis.
- cutecanvas.EditorTransformSnapshot — Detached state for one explicit transform target.
	- EditorTransformSnapshot.target — Target whose availability and geometry were resolved.
	- EditorTransformSnapshot.allowed — Whether the target can enter the shared transform session.
	- EditorTransformSnapshot.denial — Stable denial reason when activation is unavailable, including `nothing-to-transform` for empty layer content.
	- EditorTransformSnapshot.scene_id — Scene that owns the target, when resolved.
	- EditorTransformSnapshot.layer_id — Layer that supplies the transformed pixels, when resolved.
	- EditorTransformSnapshot.corners — Four scene-space frame corners in stable order, when resolved.
	- EditorTransformSnapshot.center — Scene-space center of the live frame, when resolved.
	- EditorTransformSnapshot.unresolved — Whether the active session contains an unapplied preview.
	- EditorTransformSnapshot.gesture_active — Whether a direct pointer gesture currently owns the affine session.
- CuteCanvas.editorTransformState — Inspect one explicit target without changing editor state.
- CuteCanvas.activateEditorTransform — Activate the built-in transform tool against one explicit target.
- CuteCanvas.applyEditorTransformCommand — Replace the current cumulative preview with one frame-relative discrete command.
- CuteCanvas.applyEditorTransform — Commit the complete preview as one chronological edit.
- CuteCanvas.cancelEditorTransform — Restore the exact original target state without history.

### View State
- CuteCanvas.zoomChanged — Float payload emitted when viewport zoom changes; seeds once during initialization so listeners can prime UI without peeking at the viewport.
- CuteCanvas.viewportRectChanged — `QRectF` payload emitted when the physical viewport size or device pixel ratio changes (resize/show/screen hop) so overlays and tiles stay aligned.

### Masks
- CuteCanvas.maskSaved — `cutecanvas.MaskSavedPayload` (`mask_id`, `path`) emitted after a mask autosave completes.
- CuteCanvas.maskUndoStackChanged — Mask UUID (`uuid.UUID`) payload emitted when a mask undo stack mutates.
- CuteCanvas.rasterBoundsRequestCompleted — `(request_id, scene_id, layer_id, succeeded, message)` emitted exactly once when a raster bounds request succeeds, is replaced, becomes stale, or fails.
- CuteCanvas.placedAssetRequestCompleted — `(request_id, scene_id, layer_id, succeeded, message)` emitted exactly once for accepted link, relink, refresh, and rasterization work.

### Diagnostics
- CuteCanvas.diagnosticsOverlayToggled — Bool payload emitted when the diagnostics HUD visibility changes.
- CuteCanvas.diagnosticsDomainToggled — `(domain: str, enabled: bool)` payload emitted when a diagnostics domain toggles.

### SAM
- CuteCanvas.samCheckpointStatusChanged — `(status: str, path: Path)` payload emitted during SAM checkpoint readiness changes (`downloading`, `ready`, `failed`, `missing`); `"downloading"` also covers integrity verification when a hash is required.
- CuteCanvas.samCheckpointProgress — `(downloaded: int, total: int | None)` payload emitted during SAM checkpoint downloads.

See also: [Documents and Layers](scenes.md), [Diagnostics](diagnostics.md), and [Masks and SAM](masks-and-sam.md).

## Painting

- `cutecanvas.BrushOperation` describes paint or erase semantics. `BrushOperation.PAINT` deposits target-appropriate color or coverage; `BrushOperation.ERASE` removes alpha or coverage.
- `cutecanvas.BrushDynamics` is the immutable pointer-response and jitter configuration retained by a preset. It includes pressure size/opacity response, pressure floor and gamma, deterministic position, size, and angle jitter, plus rotation, tilt, and tangential-pressure mappings.
  - `BrushDynamics.pressure_size` and `BrushDynamics.pressure_opacity` control how strongly pressure affects diameter and opacity.
  - `BrushDynamics.minimum_pressure_ratio` and `BrushDynamics.pressure_gamma` define the normalized pressure curve.
  - `BrushDynamics.position_jitter`, `BrushDynamics.size_jitter`, and `BrushDynamics.angle_jitter` are deterministic seeded variations.
  - `BrushDynamics.rotation_angle` and `BrushDynamics.tilt_angle` blend tablet orientation into tip angle; `BrushDynamics.tangential_opacity` maps barrel pressure into deposited opacity.
- `cutecanvas.BrushPreset` is the immutable active brush configuration: name, size, hardness, opacity, flow, spacing, smoothing, angle, procedural texture, and `BrushDynamics`.
  - `BrushPreset.name` identifies the preset in host UI.
  - `BrushPreset.size` is the nominal target-pixel diameter.
  - `BrushPreset.hardness` controls edge falloff.
  - `BrushPreset.opacity` caps deposited opacity and `BrushPreset.flow` controls per-dab accumulation.
  - `BrushPreset.spacing` controls dab frequency along motion.
  - `BrushPreset.smoothing` controls source-neutral pointer-path stabilization.
  - `BrushPreset.angle` is the nominal tip rotation.
  - `BrushPreset.texture_strength`, `BrushPreset.texture_scale`, and `BrushPreset.texture_seed` define deterministic procedural grain whose generated tips are byte-bounded by CuteCanvas's shared cache budget.
  - `BrushPreset.dynamics` contains the immutable `BrushDynamics` mapping.
- `cutecanvas.PaintTargetKind` identifies the destination category. `PaintTargetKind.LAYER` addresses a paint-capable layer; `PaintTargetKind.PIXEL_SELECTION` addresses the active composition's selection coverage.
- `cutecanvas.PaintTargetSnapshot` is the detached active-target snapshot.
  - `PaintTargetSnapshot.scene_id` is the public active-scene identity.
  - `PaintTargetSnapshot.kind` is the target category.
  - `PaintTargetSnapshot.layer_id` is the layer instance for a layer target, otherwise `None`.
  - `PaintTargetSnapshot.source_kind` reports `"raster"`, `"mask"`, or `None` for composition selection coverage.
- `CuteCanvas.createPaintLayer` creates a transparent editable RGBA layer, selects it, and makes it the paint target. Its initial dimensions default to the active scene and its extent policy defaults to unbounded sparse storage.
- `CuteCanvas.paintTargetState` returns the active detached target or `None`.
- `CuteCanvas.setPaintTarget` selects a pixel-editable mask or RGBA layer in the active scene.
- `CuteCanvas.setPixelSelectionPaintTarget` routes brush coverage to the one authoritative composition selection.
- `CuteCanvas.clearPaintTarget` cancels unresolved brush work and clears its destination.
- `CuteCanvas.brushPreset` and `CuteCanvas.setBrushPreset` query and replace the complete immutable brush configuration.
- `CuteCanvas.renderBrushTipPreview` renders the active preset into a detached,
  DPR-aware image using the production brush-tip cache.
- `CuteCanvas.setBrushSize` changes only the size field while retaining the rest of the active preset.
- `CuteCanvas.paintColor` and `CuteCanvas.setPaintColor` query and replace the detached color used by RGBA targets. Coverage targets retain coverage semantics.
- `CuteCanvas.paintTargetChanged` emits `PaintTargetSnapshot` or `None` after target changes.
- `CuteCanvas.brushPresetChanged` emits the new `BrushPreset` after preset or size changes.
- `CuteCanvas.paintColorChanged` emits a detached `QColor` after color changes.
- `cutecanvas.CloneStampAlignment` selects source-offset behavior.
  - `CloneStampAlignment.ALIGNED` retains the source-to-destination offset
    across separate strokes.
  - `CloneStampAlignment.UNALIGNED` begins every stroke from the chosen source.
- `cutecanvas.CloneStampSampleMode` selects the source product.
  - `CloneStampSampleMode.ANCHORED_LAYER` samples only the layer on which the
    source was chosen.
  - `CloneStampSampleMode.ANCHORED_LAYER_AND_BELOW` samples that layer and
    visible layers below it.
  - `CloneStampSampleMode.VISIBLE_COMPOSITE` samples every visible layer.
- `cutecanvas.CloneStampTransform` describes the sampled content's affine
  result around its source anchor.
  - `CloneStampTransform.rotation_degrees` rotates the visible result.
  - `CloneStampTransform.scale_x` scales the visible horizontal result and
    must be finite and positive.
  - `CloneStampTransform.scale_y` scales the visible vertical result and must
    be finite and positive.
  - `CloneStampTransform.mirror_horizontal` reflects the horizontal source
    axis.
  - `CloneStampTransform.mirror_vertical` reflects the vertical source axis.
- `cutecanvas.CloneStampSource` retains one source anchor.
  - `CloneStampSource.scene_id` identifies the source composition.
  - `CloneStampSource.scene_position` stores the scene-space coordinate pair.
  - `CloneStampSource.scene_point` returns a detached scene `QPointF`.
  - `CloneStampSource.layer_id` identifies an anchored source layer when
    applicable.
  - `CloneStampSource.layer_position` stores the zero-origin layer-source
    coordinate pair.
  - `CloneStampSource.layer_point` returns a detached layer-source `QPointF`
    or `None`.
- `cutecanvas.CloneStampState` is the complete immutable Clone Stamp snapshot.
  - `CloneStampState.alignment` is the current `CloneStampAlignment`.
  - `CloneStampState.sample_mode` is the current `CloneStampSampleMode`.
  - `CloneStampState.transform` is the current `CloneStampTransform`.
  - `CloneStampState.source` is the current `CloneStampSource` or `None`.
  - `CloneStampState.source_set` reports whether a source is configured.
- `CuteCanvas.cloneStampState` returns the complete immutable Clone Stamp
  snapshot.
- `CuteCanvas.setCloneStampSource` sets a source in active-composition scene
  coordinates.
- `CuteCanvas.clearCloneStampSource` clears the source and retained aligned
  offset.
- `CuteCanvas.setCloneStampAlignment` changes source-offset behavior.
- `CuteCanvas.setCloneStampSampleMode` changes the source product.
- `CuteCanvas.setCloneStampTransform` changes rotation, output scale, and
  reflection for subsequent strokes.
- `CuteCanvas.cloneStampChanged` publishes the complete state after any source
  or configuration change.
- `cutecanvas.CloneStampFacade` provides focused activation and configuration.
- `EditorFacade.clone_stamp` is the focused `CloneStampFacade` configuration
  entry point on every editor facade.
- `CloneStampFacade.state` returns the current immutable state.
- `CloneStampFacade.activate` activates Clone Stamp.
- `CloneStampFacade.set_source` sets a scene-space source.
- `CloneStampFacade.clear_source` clears the current source.
- `CloneStampFacade.set_alignment` changes source-offset behavior.
- `CloneStampFacade.set_sample_mode` changes the source product.
- `CloneStampFacade.set_transform` changes the sampled-content transform.
- `cutecanvas.NonEditablePaintPolicy.CREATE_RASTER_LAYER` creates and visibly
  selects an unbounded raster layer above a non-editable selection before an
  interactive brush stroke.
- `NonEditablePaintPolicy.REJECT` rejects that stroke without changing the
  selected layer.
- `EditorPolicy.noneditable_paint` selects this behavior. Automatic creation
  also requires `EditorCapability.MANAGE_LAYERS`.
- `cutecanvas.CoverageShapeOptions` reports the feather radius applied to future retained mask and selection shapes. `CuteCanvas.coverageShapeOptions` reads it and `CuteCanvas.configureCoverageShapes` replaces supplied values.
- `cutecanvas.CoverageCoordinateSpace.TARGET` interprets authored geometry in the active layer's local coordinates or in scene coordinates for the pixel-selection target. `CoverageCoordinateSpace.NORMALIZED_TARGET` maps normalized fractions through that target's finite bounds, so `QRectF(0, 0, 0.5, 1)` describes its exact left half.
- `CuteCanvas.addCoverageShape`, `CuteCanvas.addCoveragePolygon`, and `CuteCanvas.addCoverageImage` commit retained vector or arbitrary 8-bit raster coverage directly to the active mask or pixel-selection target. They return stable authored-item IDs and do not use or replace the user's current pixel selection. `CuteCanvas.editor.coverage.rectangle`, `.ellipse`, `.polygon`, and `.image` provide the concise focused facade over the same owner.
- `CuteCanvas.fillSelection` projects the active soft selection into the active editable target as one chronological edit.
- `CuteCanvas.paintBucketOptions` and `CuteCanvas.configurePaintBucket` expose tolerance, contiguous fill, and antialiasing. `CuteCanvas.CONTROL_MODE_PAINT_BUCKET` activates the asynchronous tool.
- `CuteCanvas.rasterizeMaskCoverage` explicitly flattens retained mask items without changing the exported result and remains undoable.
- `cutecanvas.LayerEdgeOperation` identifies source-neutral asynchronous edge operations.
  - `LayerEdgeOperation.EXPAND` grows the coverage edge.
  - `LayerEdgeOperation.CONTRACT` shrinks the coverage edge.
  - `LayerEdgeOperation.FEATHER` softens the coverage edge.
- `cutecanvas.PixelSelectionModificationResult` reports each request's terminal state.
  - `PixelSelectionModificationResult.request_id` is the accepted request UUID.
  - `PixelSelectionModificationResult.scene_id` is the public composition UUID.
  - `PixelSelectionModificationResult.operation` identifies the requested operation.
  - `PixelSelectionModificationResult.succeeded` reports whether the detached result was adopted.
  - `PixelSelectionModificationResult.message` provides the terminal explanation.
- `CuteCanvas.pixelSelectionModificationCompleted` emits one `PixelSelectionModificationResult` for each accepted request.
- `CuteCanvas.expandPixelSelection`, `CuteCanvas.contractPixelSelection`, and `CuteCanvas.featherPixelSelection` transform only the active composition selection and return a request ID when work is accepted. `CuteCanvas.editor.selection.expand`, `.contract`, and `.feather` provide the focused equivalents. Successful adoption creates one chronological selection edit; stale results never replace newer selection state.
- `CuteCanvas.beginPixelSelectionModificationPreview`, `CuteCanvas.updatePixelSelectionModificationPreview`, `CuteCanvas.settlePixelSelectionModificationPreview`, and `CuteCanvas.cancelPixelSelectionModificationPreview` expose one reversible interactive selection transaction. Updates always derive from the selection captured at begin time; settlement records only the latest product, while cancellation restores the original without history. `CuteCanvas.editor.selection.begin_modification`, `.preview_modification`, `.apply_modification`, and `.cancel_modification` provide the focused equivalents.

## Manipulation geometry and snapping

- `cutecanvas.LayerGeometryMode.CONTENT` is the default and derives bounds from nontransparent RGBA pixels, nonzero hybrid coverage, placed alpha, or exact vector paint geometry.
- `LayerGeometryMode.STORAGE`, `SOURCE`, `CLIP`, `AUTHORED`, and `CUSTOM` preserve explicit host workflows independently of rendering clips and raster write extent. `BOUNDARY` retains an exact polygonal manipulation topology when raster painting adopts the result of a finite deformation.
- `LayerGeometryPolicy` pairs the chosen manipulation mode with validated custom bounds for `CUSTOM` or finite polygon vertices for `BOUNDARY`.
- `CuteCanvas.layerGeometryPolicy` and `CuteCanvas.setLayerGeometryPolicy` query or replace one layer's manipulation geometry. `CuteCanvas.layerLocalBounds` returns the resolved bounds actually used by move, transform, snapping, and editor overlays.
- `CuteCanvas.setLayerVisible` changes composition-local rendering and hit testing as one undoable edit for every layer source. `LayerHandle.set_visible` provides the focused equivalent.
- `CuteCanvas.setLayerOpacity` changes the final visual-only layer multiplier without rewriting authored pixels, scalar coverage, brush hardness, or paint opacity. `LayerHandle.set_opacity` provides the focused equivalent. Coverage sources keep their full scalar curve and apply this multiplier at composition.
- `CuteCanvas.expandLayerEdges`, `CuteCanvas.contractLayerEdges`, and `CuteCanvas.featherLayerEdges` route source-neutral requests through the adapter registered for the addressed layer kind. Coverage/mask layers are supported directly and settle as one reversible baked edit. Changes are admitted only inside the composition canvas aperture in layer-source space; pre-existing hidden coverage outside it remains unchanged.
- `CuteCanvas.beginLayerEdgePreview`, `CuteCanvas.updateLayerEdgePreview`, `CuteCanvas.settleLayerEdgePreview`, and `CuteCanvas.cancelLayerEdgePreview` expose a nonmodal latest-value session. Every update derives from one immutable base revision, its transient product remains inside the canvas aperture even for expandable storage, settlement commits the latest product once, and cancellation leaves durable content unchanged.
- `CuteCanvas.beginMaskEdgePreview`, `CuteCanvas.expandMaskEdges`, `CuteCanvas.contractMaskEdges`, and `CuteCanvas.featherMaskEdges` are mask-identity conveniences over the generic layer route.
- `CuteCanvas.layerEdgeModificationCompleted` emits `LayerEdgeModificationResult` when a settled or one-shot whole-layer request terminates.
- `cutecanvas.LayerEdgeModificationResult` reports one terminal whole-layer request.
  - `LayerEdgeModificationResult.request_id` is the accepted update or one-shot request UUID.
  - `LayerEdgeModificationResult.session_id` identifies the preview transaction.
  - `LayerEdgeModificationResult.scene_id` and `LayerEdgeModificationResult.layer_id` identify the addressed layer instance.
  - `LayerEdgeModificationResult.operation` identifies the requested edge operation.
  - `LayerEdgeModificationResult.succeeded` reports whether the product was committed.
  - `LayerEdgeModificationResult.message` provides the terminal explanation.
- `CuteCanvas.translateLayer` adds an exact scene-coordinate displacement without changing the affine linear transform. `CuteCanvas.centerLayer` aligns either or both layer-center axes to the composition canvas. `LayerHandle.translate` and `LayerHandle.center` expose the same commands without raw identifier pairs. Movability remains host policy for translation and alignment.
- Move auto-selects the topmost eligible visible content by default. Shift-click adds to the layer set; dragging any selected member and keyboard nudging move all movable members through one preview, one durable publication, and one history edit. `MoveToolOptions.auto_select_layers=False` preserves the existing set, and Ctrl at gesture start temporarily inverts that option.
- `cutecanvas.SnapPolicy` selects canvas, visible-layer, selection, guide, and grid candidates plus device-pixel acquire/release thresholds. Its default eight-pixel acquire tolerance is evaluated through QPane's physical viewport zoom, independently of display scaling.
- Movement snapping admits center-to-center, matching-edge, opposing-adjacent-edge, and edge-to-center relationships. Authored guides and grid lines accept the nearest moving feature.
- Transform-frame movement uses the same relationships as Move. Scale handles snap their actual scene-space point to configured target lines while preserving proportional and about-center constraints. Rotated side handles and constrained corners remain on their affine scale axis, and Smart Guides report only lines reached exactly.
- Rectangle and ellipse mask tools, rectangle and ellipse pixel-selection tools, vector rectangle and ellipse tools, and explicit vector-path anchors snap both their anchor and active endpoint. An authored endpoint may align to any configured target edge or center. Preview and commit use the same resolved geometry.
- `CuteCanvas.snapPolicy`, `CuteCanvas.configureSnapping`, `CuteCanvas.setSnapGuides`, and `CuteCanvas.setSnapGrid` configure the shared policy for movement, affine transforms, and geometric authoring. Holding Ctrl temporarily suppresses snapping without changing durable policy. Freehand lasso, painting, fill, and SAM region gestures remain unsnapped.

## Vector Documents

- `cutecanvas.VectorObjectKind` identifies semantic objects: `VectorObjectKind.PATH`, `VectorObjectKind.SHAPE`, and the text-ready `VectorObjectKind.TEXT` category.
- `cutecanvas.VectorShapeKind` retains parametric geometry as `VectorShapeKind.RECTANGLE` or `VectorShapeKind.ELLIPSE` until an explicit future conversion.
- `cutecanvas.VectorPathCommandKind` defines durable path operations: `VectorPathCommandKind.MOVE`, `VectorPathCommandKind.LINE`, `VectorPathCommandKind.QUADRATIC`, `VectorPathCommandKind.CUBIC`, and `VectorPathCommandKind.CLOSE`.
- `cutecanvas.VectorPathCommand` stores one operation in `VectorPathCommand.kind` and its detached ordered control points in `VectorPathCommand.points`.
- `cutecanvas.VectorFillRule` selects `VectorFillRule.WINDING` or `VectorFillRule.EVEN_ODD` fill behavior.
- `cutecanvas.VectorStrokeJoin` selects `VectorStrokeJoin.MITER`, `VectorStrokeJoin.ROUND`, or `VectorStrokeJoin.BEVEL`; `cutecanvas.VectorStrokeCap` selects `VectorStrokeCap.FLAT`, `VectorStrokeCap.ROUND`, or `VectorStrokeCap.SQUARE`.
- `cutecanvas.VectorNodeRole` identifies an editable anchor as `VectorNodeRole.ANCHOR`, a Bézier control point as `VectorNodeRole.CONTROL`, or a parametric-shape bounds handle as `VectorNodeRole.BOUNDS`.
- `cutecanvas.VectorStyle` is the immutable object style. `VectorStyle.fill` and `VectorStyle.stroke` are detached colors or `None`; `VectorStyle.stroke_width`, `VectorStyle.opacity`, `VectorStyle.join`, `VectorStyle.cap`, `VectorStyle.dash_pattern`, and `VectorStyle.fill_rule` retain the remaining render semantics.
- `cutecanvas.VectorObjectSnapshot` exposes `VectorObjectSnapshot.object_id`, `VectorObjectSnapshot.kind`, `VectorObjectSnapshot.bounds`, `VectorObjectSnapshot.transform`, `VectorObjectSnapshot.style`, `VectorObjectSnapshot.shape_kind`, and `VectorObjectSnapshot.path` without exposing mutable document authority.
- `cutecanvas.VectorDocumentSnapshot` exposes `VectorDocumentSnapshot.scene_id`, `VectorDocumentSnapshot.layer_id`, `VectorDocumentSnapshot.vector_id`, `VectorDocumentSnapshot.revision`, and ordered `VectorDocumentSnapshot.objects`.
- `cutecanvas.VectorSelectionSnapshot` exposes independent object selection through `VectorSelectionSnapshot.scene_id`, `VectorSelectionSnapshot.layer_id`, and ordered `VectorSelectionSnapshot.object_ids`.
- `cutecanvas.VectorMaskSnapshot` exposes a target layer's semantic mask through `VectorMaskSnapshot.scene_id`, `VectorMaskSnapshot.layer_id`, `VectorMaskSnapshot.vector_id`, optional `VectorMaskSnapshot.object_ids`, target-local `VectorMaskSnapshot.transform`, and `VectorMaskSnapshot.inverted`.
- `cutecanvas.VectorNodeSelectionSnapshot` exposes the selected control point through `VectorNodeSelectionSnapshot.scene_id`, `VectorNodeSelectionSnapshot.layer_id`, `VectorNodeSelectionSnapshot.object_id`, stable `VectorNodeSelectionSnapshot.node_index`, and `VectorNodeSelectionSnapshot.role`.
- `CuteCanvas.createVectorLayer` creates an empty movable vector document at the active scene origin. `CuteCanvas.vectorDocumentState` returns its detached semantic revision.
- `CuteCanvas.addVectorShape` adds a parametric shape and `CuteCanvas.addVectorPath` adds explicit commands. Both produce one stable object UUID and one chronological edit.
- `CuteCanvas.updateVectorObject` changes style and/or affine object transform atomically. `CuteCanvas.removeVectorObject` and `CuteCanvas.reorderVectorObject` retain exact undo/redo behavior.
- `CuteCanvas.setSelectedVectorObjects`, `CuteCanvas.vectorSelectionState`, and `CuteCanvas.clearVectorSelection` operate independently of layer and pixel selection. `CuteCanvas.vectorSelectionChanged` emits the detached state or `None`.
- `CuteCanvas.vectorNodeSelectionState` reports the direct-selection tool's control point independently of object, layer, and pixel selection. `CuteCanvas.vectorNodeSelectionChanged` emits the detached state or `None`.
- `ControlMode.VECTOR_SHAPE` and `CuteCanvas.CONTROL_MODE_VECTOR_SHAPE` identify the built-in parametric shape tool. `ControlMode.VECTOR_PATH` and `CuteCanvas.CONTROL_MODE_VECTOR_PATH` identify the explicit path-construction tool. `ControlMode.VECTOR_NODE` and `CuteCanvas.CONTROL_MODE_VECTOR_NODE` identify direct node editing.
- `CuteCanvas.vectorToolShape` and `CuteCanvas.setVectorToolShape` query and change the last-used parametric shape kind. `CuteCanvas.vectorToolStyle` and `CuteCanvas.setVectorToolStyle` query and change the shared immutable creation style.
- `CuteCanvas.vectorToolOptionsChanged` emits the active `VectorShapeKind` and `VectorStyle` so contextual controls remain synchronized.
- `CuteCanvas.convertVectorToPixelSelection` asynchronously derives soft scene-space coverage from exact vector fill, stroke, object opacity, object transforms, and the layer transform. Passing object IDs chooses them explicitly; otherwise an object selection on the layer takes precedence over the whole document. The resulting edit uses `PixelSelectionMode` and the existing pixel-selection history.
- `CuteCanvas.rasterizeLayer` asynchronously renders an explicit pixel size, creates an editable premultiplied RGBA resource, and atomically replaces only that layer instance while preserving its displayed affine geometry. Undo restores the original resource.
- `CuteCanvas.vectorRequestCompleted` emits request UUID, public scene UUID, layer UUID, the `pixel-selection`, `editable-raster`, or `text-paths` operation string, success, and a terminal message exactly once for accepted work.
- `CuteCanvas.setVectorMask` atomically removes a visible vector layer instance and retains its semantic document as a target layer effect. It can use every object or an explicit object subset and can invert reveal geometry. `CuteCanvas.vectorMaskState` inspects the effect, while `CuteCanvas.clearVectorMask` removes it chronologically. `CuteCanvas.vectorDocumentState` and vector object edits accept the masked target layer so the same paths remain editable without a parallel mask document.
## Semantic vector text

`ControlMode.VECTOR_TEXT` and `CuteCanvas.CONTROL_MODE_VECTOR_TEXT` activate in-place
semantic text creation and editing on the selected vector layer. The public
text values preserve Unicode and authoring intent through
`cutecanvas.VectorTextContent`: `VectorTextContent.text`,
`VectorTextContent.style`, `VectorTextContent.spans`, and
`VectorTextContent.paragraph`; `cutecanvas.VectorTextStyle` supplies
`VectorTextStyle.families`,
`VectorTextStyle.font_size`, `VectorTextStyle.weight`,
`VectorTextStyle.italic`, `VectorTextStyle.letter_spacing`, and
`VectorTextStyle.color`; `cutecanvas.VectorTextSpan` supplies `VectorTextSpan.start`, `VectorTextSpan.length`, and
`VectorTextSpan.style`; and `cutecanvas.VectorParagraphStyle` supplies `VectorParagraphStyle.alignment`,
`VectorParagraphStyle.direction`, and `VectorParagraphStyle.line_height`.

Paragraph policy uses `cutecanvas.VectorTextAlignment` through `VectorTextAlignment.LEFT`,
`VectorTextAlignment.CENTER`, `VectorTextAlignment.RIGHT`, and
`VectorTextAlignment.JUSTIFY`, with `cutecanvas.VectorTextDirection` through `VectorTextDirection.AUTO`,
`VectorTextDirection.LEFT_TO_RIGHT`, or
`VectorTextDirection.RIGHT_TO_LEFT`. `CuteCanvas.addVectorText` creates text,
`CuteCanvas.updateVectorText` atomically changes its content or box, and
`VectorObjectSnapshot.text` exposes the retained semantic value.

`CuteCanvas.beginVectorTextEdit`, `CuteCanvas.vectorTextEditState`,
`CuteCanvas.commitVectorTextEdit`, and `CuteCanvas.cancelVectorTextEdit` control one
in-place session. `cutecanvas.VectorTextEditSnapshot` exposes `VectorTextEditSnapshot.scene_id`,
`VectorTextEditSnapshot.layer_id`, `VectorTextEditSnapshot.object_id`,
`VectorTextEditSnapshot.text`, `VectorTextEditSnapshot.cursor`, and
`VectorTextEditSnapshot.is_new` describe it; `CuteCanvas.vectorTextEditChanged`
publishes changes. `CuteCanvas.vectorTextStyle`, `CuteCanvas.setVectorTextStyle`,
`CuteCanvas.vectorParagraphStyle`, and `CuteCanvas.setVectorParagraphStyle` control the
contextual options.

`CuteCanvas.vectorTextFontResolutions` returns `TextFontResolution` entries.
Each exposes `TextFontResolution.requested_families`,
`TextFontResolution.resolved_family`, and
`TextFontResolution.exact_match`, so hosts can explain font fallback
without treating the resolved platform font as document authority.
`CuteCanvas.convertVectorTextToPaths` begins non-blocking conversion of one semantic
text object into color-preserving editable glyph outlines. It returns a request
UUID; `CuteCanvas.vectorRequestCompleted` reports the `text-paths` terminal outcome,
and a successful conversion lands as one undoable edit.
