**← Previous:** [Extensibility](extensibility.md)

# API Reference

## Editor Helpers

`CuteCanvas` is the widget and complete public API. `canvas.editor` groups the
most common application workflows into smaller typed helpers:

The `EditorFacade` collects these helpers without owning a second copy of
document state. `DocumentCollection` creates and resolves typed handles.
`ToolFacade` activates tools, `SelectionFacade` exposes pixel selection,
`CoverageFacade` authors coverage, `HistoryFacade` controls chronological undo
and redo, and `DocumentPersistenceFacade` saves and restores documents.

* `documents` creates and finds documents through `DocumentHandle` values.
* `tools` lists and activates tools.
* `selection` inspects or clears the pixel selection.
* `coverage` adds rectangles, ellipses, polygons, or grayscale coverage to the
  active mask or selection.
* `effects` highlights rendered layer content without editing it.
* `history` provides undo and redo for the open document.
* `persistence` saves and restores editable documents.

Handles keep stable IDs and read current state from the canvas. They do not
cache a second mutable document model.

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
* [Catalog and Navigation](#catalog-and-navigation)
* [Scene Composition](#scene-composition)
* [Compositions](#compositions)
* [Comparison](#comparison)
* [Diagnostics](#diagnostics)
* [Masks and SAM](#masks-and-sam)
* [Extensibility](#extensibility)
* [View State & Geometry](#view-state--geometry)
* [Signals and Events](#signals-and-events)

**Start with the guides:**
* [Getting Started](getting-started.md)
* [Configuration](configuration.md)
* [Configuration Reference](configuration-reference.md)
* [Catalog and Navigation](catalog-and-navigation.md)
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
- CuteCanvas.setControlMode — Switch to a registered mode; unavailable mask/SAM modes are ignored while the placeholder is active, and unknown mode IDs raise `ValueError`.
- CuteCanvas.CONTROL_MODE_CURSOR — Built-in inert cursor mode (no pan/zoom).
- CuteCanvas.CONTROL_MODE_PANZOOM — Built-in pan/zoom mode for navigation.
- CuteCanvas.CONTROL_MODE_MOVE — Built-in selection-aware mode that moves selected editable pixels first, or a selectable movable layer when no pixel selection exists.
- CuteCanvas.CONTROL_MODE_TRANSFORM — Built-in affine transform mode with eight direct-manipulation handles for the selected movable layer.
- CuteCanvas.CONTROL_MODE_MASK_RECTANGLE — Retained rectangle authoring for the active mask target.
- CuteCanvas.CONTROL_MODE_MASK_ELLIPSE — Retained ellipse authoring for the active mask target.
- CuteCanvas.CONTROL_MODE_MASK_LASSO — Retained freeform authoring for the active mask target.
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
	- DiagnosticsDomain.EXECUTOR — Executor identity, queue depth, thread/device limits, wait times.
	- DiagnosticsDomain.RETRY — Retry queues per resource plus compact summaries.
	- DiagnosticsDomain.SAM — SAM cache, readiness, worker counts, and max threads.
- cutecanvas.ControlMode — Built-in control mode identifiers for tool registration.
	- ControlMode.CURSOR — Inert cursor mode (`cursor`).
	- ControlMode.PANZOOM — Pan/zoom mode (`panzoom`).
	- ControlMode.MOVE — Direct layer movement mode (`move`).
	- ControlMode.DRAW_BRUSH — Mask painting mode (`draw-brush`).
	- ControlMode.SMART_SELECT — SAM-based selection mode (`smart-select`).
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
- cutecanvas.CatalogEntry — Structured catalog value containing source image data and an optional path.
	- CatalogEntry.image — Original catalog `QImage` used by CuteCanvas rendering and host snapshots.
	- CatalogEntry.path — Optional source path used for labels, persistence, or host lookup.
- cutecanvas.LinkedGroup — Linked-view group descriptor with a stable UUID and members.
- cutecanvas.ComparisonState — Snapshot returned by `CuteCanvas.comparisonState`.
	- ComparisonState.enabled — Whether comparison rendering is active.
	- ComparisonState.source_id — Catalog image UUID for the comparison source.
	- ComparisonState.source_path — Optional path associated with the comparison image.
	- ComparisonState.source_kind — `"catalog"` when enabled, or None.
	- ComparisonState.split_position — Normalized split position from `0.0` to `1.0`.
	- ComparisonState.orientation — Active `ComparisonOrientation` used for vertical or horizontal split rendering.
- cutecanvas.CompositionPolicy — Host-controlled structural policy for one composition document.
	- CompositionPolicy.removable — Allow the composition to be removed through `CuteCanvas.removeComposition`.
	- CompositionPolicy.comparison_enabled — Allow the composition to own an active comparison source.
- cutecanvas.ComparisonDividerState — Host-facing comparison divider interaction and geometry snapshot.
	- ComparisonDividerState.enabled — Whether authoritative divider geometry is available.
	- ComparisonDividerState.interactive — Whether built-in divider dragging is enabled.
	- ComparisonDividerState.hovered — Whether the pointer is currently over the divider hit target.
	- ComparisonDividerState.dragging — Whether a divider drag is active.
	- ComparisonDividerState.orientation — Current comparison split orientation.
	- ComparisonDividerState.hit_width — Invisible grab tolerance around the rendered boundary.
	- ComparisonDividerState.full_segment — Full projected boundary in widget coordinates, or None.
	- ComparisonDividerState.visible_segment — Portion of the boundary visible inside the widget, or None.
- cutecanvas.CompositionEntry — Snapshot row for one renderable composition.
	- CompositionEntry.composition_id — Stable UUID used with `CuteCanvas.openComposition`.
	- CompositionEntry.kind — Descriptive creation-origin metadata such as `"composition"`, `"default-image"`, `"explicit"`, or `"layered-scene"`; it does not control behavior.
	- CompositionEntry.title — Host-facing browser title.
	- CompositionEntry.source_image_ids — Catalog image UUIDs used by the composition.
	- CompositionEntry.current_image_id — Catalog image ID for a document seeded from one source, or `None` for an independent document.
	- CompositionEntry.comparison — Composition-scoped `ComparisonState` restored when the row reopens.
	- CompositionEntry.scene_layer_count — Number of ordered layer instances in the composition.
	- CompositionEntry.scene_bounds — Authoritative scene-coordinate canvas bounds for the composition.
	- CompositionEntry.layers — Bottom-to-top detached `CompositionLayerEntry` values for building nested layer browsers without activating the composition.
	- CompositionEntry.policy — Current host-controlled `CompositionPolicy` for the document.
- cutecanvas.CompositionLayerEntry — Detached browser metadata for one ordered layer instance.
	- CompositionLayerEntry.layer_id — Stable layer-instance UUID.
	- CompositionLayerEntry.source_kind — Presentation name for the layer source domain.
	- CompositionLayerEntry.source_id — Shared source-resource UUID.
	- CompositionLayerEntry.label — Optional host-facing layer label.
	- CompositionLayerEntry.role — Layer role such as `"base-image"` or `"content"`.
	- CompositionLayerEntry.visible — Current instance visibility.
	- CompositionLayerEntry.opacity — Current instance opacity.
	- CompositionLayerEntry.interaction — Host-controlled layer interaction policy.
	- CompositionLayerEntry.transform — Detached exact local-to-scene affine transform.
- cutecanvas.CompositionSnapshot — Structured composition browser state.
	- CompositionSnapshot.compositions — Mapping of composition UUID to `CompositionEntry`.
	- CompositionSnapshot.order — Composition UUIDs in browser order.
	- CompositionSnapshot.current_composition_id — Active composition UUID, or None.
- cutecanvas.MaskInfo — Mask metadata returned by mask helpers, including stable `scene_id`, `layer_id`, and `interaction` policy for generic scene-layer operations.
- cutecanvas.DiagnosticRecord — Label/value diagnostic entry used in overlays.
- cutecanvas.CatalogMutationEvent — Catalog mutation payload emitted on catalog changes.
- cutecanvas.CatalogSnapshot — Structured catalog state (catalog entries, linked groups, ordering, active IDs).
- cutecanvas.OverlayState — Stable public-overlay snapshot passed to `draw_fn`.
	- OverlayState.zoom — Current zoom factor.
	- OverlayState.qpane_rect — Widget-space bounds of the viewer.
	- OverlayState.physical_viewport_rect — Device-pixel viewport bounds.
	- OverlayState.transform — Image-to-widget transform for coordinate anchoring.
	- OverlayState.current_pan — Current pan offset in widget space.
	- OverlayState.source_image — Base catalog raster resolved for the current overlay pass, not flattened rendered content.
- cutecanvas.CompositionRequest — Host request used to create or replace a stored scene composition.
	- CompositionRequest.composition_id — Optional composition UUID to create or replace; None generates a new UUID.
	- CompositionRequest.title — Optional host-facing composition title.
	- CompositionRequest.bounds — Host-defined scene-coordinate bounds.
	- CompositionRequest.layers — Ordered `CatalogLayerRequest` entries.
- cutecanvas.CatalogLayerRequest — Catalog-backed image layer in a scene composition request.
	- CatalogLayerRequest.layer_id — Stable layer UUID supplied by the host.
	- CatalogLayerRequest.image_id — Catalog image UUID rendered for this layer.
	- CatalogLayerRequest.placement — Scene-coordinate rectangle for this layer.
	- CatalogLayerRequest.visible — Whether the layer renders and hit-tests.
	- CatalogLayerRequest.opacity — Layer opacity from `0.0` to `1.0`.
	- CatalogLayerRequest.clip — Optional `CompositionLayerClip` limiting rendered or hit-tested layer area.
	- CatalogLayerRequest.hit_test — Whether `CuteCanvas.sceneHitTest` can return this layer.
	- CatalogLayerRequest.role — Host label carried into hits and overlays.
	- CatalogLayerRequest.metadata — Opaque host metadata carried into hits and overlays.
	- CatalogLayerRequest.interaction — `LayerPolicy` controlling selection and movement.
- cutecanvas.LayerPolicy — Host policy for direct and structural layer interaction.
	- LayerPolicy.selectable — Allow direct tools to select the layer through covered source pixels.
	- LayerPolicy.movable — Allow generic placement mutation and Move-tool dragging for the layer.
	- LayerPolicy.pixel_editable — Allow pixel tools to mutate a layer when its source also advertises raster editing.
	- LayerPolicy.reorderable — Allow the layer instance to move within its composition stack.
	- LayerPolicy.removable — Allow the layer instance to be removed from its composition.
- cutecanvas.LayerSelectionSnapshot — Selected scene-layer identity, kept separate from pixel-selection coverage.
	- LayerSelectionSnapshot.scene_id — Public identity of the scene containing the selected layer.
	- LayerSelectionSnapshot.layer_id — Stable identity of the selected layer.
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
- cutecanvas.EditorIntent — Public operation identifier accepted by `CuteCanvas.editorOperationState`.
	- EditorIntent.SELECT_PIXELS — Inspect pixel-selection creation and modification.
	- EditorIntent.DELETE_PIXELS — Inspect selection-constrained pixel clearing.
	- EditorIntent.PAINT — Inspect the active paint target.
	- EditorIntent.MOVE — Inspect selected-pixel or complete-layer movement.
	- EditorIntent.TRANSFORM — Inspect selected-pixel or complete-layer transform.
- cutecanvas.EditorPolicy — Immutable set of editor capabilities enabled by the host; the default contains every capability.
	- EditorPolicy.capabilities — Complete immutable `EditorCapability` set.
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
- cutecanvas.CompositionTemplate — Host-owned reusable template for building scene composition requests.
	- CompositionTemplate.template_id — Stable template UUID owned by the host.
	- CompositionTemplate.bounds — Host-defined scene-coordinate bounds.
	- CompositionTemplate.layers — Ordered `TemplateLayer` entries.
	- CompositionTemplate.title — Optional default title used by template composition.
- cutecanvas.TemplateLayer — Template layer bound by source slot at composition time.
	- TemplateLayer.layer_id — Stable layer UUID supplied by the host.
	- TemplateLayer.source_slot — Binding key resolved by `TemplateBindings.catalog_images`.
	- TemplateLayer.placement — Scene-coordinate rectangle for this layer.
	- TemplateLayer.visible — Whether the layer renders and hit-tests.
	- TemplateLayer.opacity — Layer opacity from `0.0` to `1.0`.
	- TemplateLayer.clip — Optional `CompositionLayerClip` applied when the template becomes a stored scene.
	- TemplateLayer.hit_test — Whether `CuteCanvas.sceneHitTest` can return this layer.
	- TemplateLayer.role — Host label carried into hits and overlays.
	- TemplateLayer.metadata — Opaque host metadata merged into composed layers.
	- TemplateLayer.interaction — Direct-interaction policy copied into each composed layer.
- cutecanvas.TemplateBindings — Concrete catalog image bindings for a scene template.
	- TemplateBindings.composition_id — Optional composition UUID to create or replace.
	- TemplateBindings.title — Optional title overriding the template title.
	- TemplateBindings.catalog_images — Mapping of template source slots to catalog image UUIDs.
	- TemplateBindings.metadata — Optional source-slot metadata merged into composed layers.
- cutecanvas.SceneSnapshot — Public scene snapshot for an active generated or host-authored composition.
	- SceneSnapshot.composition_id — Stored composition UUID.
	- SceneSnapshot.scene_id — Render scene UUID; layered scene compositions use the composition UUID.
	- SceneSnapshot.title — Host-facing composition title.
	- SceneSnapshot.bounds — Host-defined scene-coordinate bounds.
	- SceneSnapshot.layers — Ordered `LayerSnapshot` entries.
- cutecanvas.LayerSnapshot — Source-backed layer in a composed scene.
	- LayerSnapshot.layer_id — Stable layer UUID supplied by the host.
	- LayerSnapshot.image_id — Catalog image UUID for image layers, or `None` for masks and editable rasters.
	- LayerSnapshot.placement — Conservative axis-aligned scene bound derived from the exact transform.
	- LayerSnapshot.transform — Detached affine local-to-scene `QTransform` for the layer instance.
	- LayerSnapshot.visible — Whether the layer renders and hit-tests.
	- LayerSnapshot.opacity — Layer opacity from `0.0` to `1.0`.
	- LayerSnapshot.tint — Detached optional presentation tint for layer types such as masks.
	- LayerSnapshot.clip — Optional `CompositionLayerClip` preserved from the normalized request layer.
	- LayerSnapshot.hit_test — Whether `CuteCanvas.sceneHitTest` can return this layer.
	- LayerSnapshot.role — Host label carried into hits and overlays.
	- LayerSnapshot.metadata — Opaque host metadata carried into hits and overlays.
	- LayerSnapshot.interaction — Current selection and movement policy for the layer.
	- LayerSnapshot.source_kind — Source domain: `catalog-image`, `mask`, `raster`, or `placeholder-image`.
	- LayerSnapshot.source_id — Stable source asset UUID independent of the scene-layer UUID.
	- LayerSnapshot.label — Optional host-facing authoring-layer label.
- cutecanvas.CompositionLayerClip — Optional layer clip rectangle.
	- CompositionLayerClip.coordinate_space — Coordinate system for `rect`: `"scene"`, `"normalized-scene"`, `"viewport"`, or `"normalized-viewport"`.
	- CompositionLayerClip.rect — Clip rectangle in the selected coordinate space.
- cutecanvas.LayerHit — Public scene hit result returned by `CuteCanvas.sceneHitTest`.
	- LayerHit.composition_id — Active composition UUID.
	- LayerHit.scene_id — Scene UUID.
	- LayerHit.layer_id — Hit layer UUID.
	- LayerHit.image_id — Catalog image UUID for the hit layer.
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

## Catalog and Navigation

### Catalog Management
- CuteCanvas.imageMapFromLists — Build an ordered catalog mapping from images plus optional paths/IDs; values are `CatalogEntry` objects; length mismatches raise `ValueError`.
- CuteCanvas.setImagesByID — Replace the catalog and set the current image in one call.
- CuteCanvas.clearImages — Drop the entire catalog and show the placeholder/blank view.
- CuteCanvas.removeImageByID — Remove a single catalog entry without rebuilding.
- CuteCanvas.removeImagesByID — Remove multiple entries without rebuilding.

### Navigation & Current State
- CuteCanvas.setCurrentImageID — Navigate to a specific UUID (or `None` to clear); unknown IDs no-op.
- CuteCanvas.currentImageID — Return the current catalog UUID (or None when empty).
- CuteCanvas.currentImage — Return the current `QImage`, or None when no image is selected.
- CuteCanvas.currentImagePath — Return the current image path (or None when missing).
- CuteCanvas.placeholderActive — Return True when the placeholder policy is active.

### Catalog Queries
- CuteCanvas.imageIDs — List all catalog UUIDs in order.
- CuteCanvas.hasImages — Quick guard to see if any images are loaded.
- CuteCanvas.allImages — Return all catalog images in order.
- CuteCanvas.allImagePaths — Return all catalog paths in order.
- CuteCanvas.imagePath — Return the path for a specific ID (or None when missing).
- CuteCanvas.getCatalogSnapshot — Return structured catalog state (entries, order, linked groups, active IDs, mask capability) for host consumption.

### Linked Views
- CuteCanvas.setAllImagesLinked — Link every image into one pan/zoom group (requires 2+ entries).
- CuteCanvas.setLinkedGroups — Define custom linked groups with `LinkedGroup` objects; invalid/overlapping groups are ignored.
- CuteCanvas.linkedGroups — Read current linked groups as `LinkedGroup` instances.

See also: [Catalog and Navigation](catalog-and-navigation.md) and [Interaction Modes](interaction-modes.md) for how linking interacts with tools.

## Scene Composition
- CuteCanvas.composeScene — Store a host-authored `CompositionRequest` whose raster layers reference catalog image IDs and optionally open it.
- CuteCanvas.composeSceneFromTemplate — Expand a host-owned scene template and bindings into a stored scene composition.
- CuteCanvas.fitSceneRect — Return the largest centered aspect-preserving scene rectangle inside a target rectangle.
- CuteCanvas.fillSceneRect — Return the smallest centered aspect-preserving scene rectangle covering a target rectangle; the result may extend outside the target.
- CuteCanvas.currentScene — Return CuteCanvas's normalized public scene snapshot, or None.
- CuteCanvas.sceneHitTest — Return topmost public scene-layer metadata for a widget-space point.
- CuteCanvas.layerTransform — Return a detached exact affine transform for one active scene layer.
- CuteCanvas.layerLocalBounds — Return detached intrinsic source-local bounds for one active scene layer when available.
- CuteCanvas.registerSceneOverlay — Add a named scene overlay; order follows registration.
- CuteCanvas.unregisterSceneOverlay — Remove a scene overlay; no-op if it is absent.
- CuteCanvas.sceneOverlays — Return a read-only snapshot of registered scene overlays; use register/unregister helpers to change it.
- CuteCanvas.setLayerInteractionPolicy — Replace selection and movement permissions for a layer through its scene owner.
- CuteCanvas.setLayerPlacement — Set an absolute scene-space layer rectangle when movement policy permits it.
- CuteCanvas.setLayerTransform — Set an invertible affine local-to-scene transform when movement policy permits it.
- CuteCanvas.setLayerIndex — Move one active layer to a bottom-to-top render index as one undoable composition-stack edit.
- CuteCanvas.selectedLayer — Return selected scene-layer identity independently of pixel coverage.
- CuteCanvas.setSelectedLayer — Select a policy-enabled layer in the active scene.
- CuteCanvas.clearSelectedLayer — Clear layer identity without clearing pixel selection.
- CuteCanvas.rasterSurfaceState — Return local bounds, extent policy, and revisions for a supported active raster layer.
- CuteCanvas.setRasterExtentPolicy — Choose whether writes clip to current local bounds or expand storage.
- CuteCanvas.requestRasterBounds — Asynchronously pad or crop a supported raster layer to exact integer local bounds while preserving its scene transform.
- CuteCanvas.addEditableRasterLayer — Copy a color image into a composition-owned editable RGBA layer.
- CuteCanvas.placeEmbeddedAsset — Copy a `QImage` into a non-destructive embedded source and add an independently transformable layer instance.
- CuteCanvas.placeLinkedAsset — Begin non-blocking file decode and add a linked layer only after decoding succeeds.
- CuteCanvas.duplicatePlacedAsset — Add an independent layer instance that shares the selected placed source and future source refreshes.
- CuteCanvas.placedAssetState — Return detached provenance, status, and generation state for a placed layer.
- CuteCanvas.refreshPlacedAsset — Reload the current linked locator without adding an editor-history command.
- CuteCanvas.relinkPlacedAsset — Decode a replacement locator and record the resulting provenance transition in scene history.
- CuteCanvas.embedPlacedAsset — Detach a linked source from its locator while retaining identical pixels; undo restores the exact link state.
- CuteCanvas.rasterizePlacedAsset — Render a placed source at explicit or natural pixel dimensions and atomically replace it with an editable RGBA source.
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

Layered compositions can combine catalog images, editable rasters, masks, placed assets, and vectors. Each source retains its own editing contract while participating in the same ordered scene, transform, hit-test, and render behavior. Hit testing is passive; calling `CuteCanvas.setCurrentImageID` after a catalog-image scene hit opens that image's generated default composition.

See also: [Scene Composition](scenes.md) and [Extensibility](extensibility.md).

## Compositions
- CuteCanvas.createComposition — Create and open an independent empty document with positive scene-space canvas bounds.
- CuteCanvas.createCompositionFromImage — Create and open an independent document whose canvas is seeded from a catalog image and whose first image is an ordinary layer instance.
- CuteCanvas.addCatalogImageLayer — Place an existing catalog resource as a new independent layer instance in the active composition.
- CuteCanvas.setCompositionPolicy — Replace host-controlled document removal and comparison permissions.
- CuteCanvas.compose — Create and open a persistent composition from one or two catalog image IDs.
- CuteCanvas.openComposition — Open an existing composition UUID.
- CuteCanvas.currentCompositionID — Return the active composition UUID, or None.
- CuteCanvas.compositionIDs — Return composition UUIDs in browser order.
- CuteCanvas.getCompositionSnapshot — Return composition rows for host browsers.
- CuteCanvas.removeComposition — Remove a composition when its document policy permits it.
- CuteCanvas.removeLayer — Remove a layer instance when its layer policy permits it and record the change in composition history.

Every composition owns its canvas and ordered layer stack independently of the catalog. `createCompositionFromImage` uses the source dimensions only to establish the initial canvas and adds a normal catalog-backed instance; placing the same catalog image elsewhere shares source render products while keeping transform, order, effects, and policy independent. Loading catalog images also creates generated one-image compositions so `setCurrentImageID(image_id)` remains supported. `currentImageID`, `currentImage`, `currentImagePath`, and `imageIDs` remain catalog/source APIs.

See also: [Catalog and Navigation](catalog-and-navigation.md).

## Comparison
- CuteCanvas.setComparisonImageID — Use an existing catalog image as the comparison reveal source.
- CuteCanvas.clearComparisonImage — Disable comparison rendering.
- CuteCanvas.setComparisonSplit — Set the normalized split position and optional `ComparisonOrientation`.
- CuteCanvas.comparisonState — Return the active `ComparisonState` snapshot.
- CuteCanvas.comparisonDividerInteractive — Return whether built-in comparison-divider dragging is enabled.
- CuteCanvas.setComparisonDividerInteractive — Enable or disable built-in split-boundary dragging.
- CuteCanvas.comparisonDividerState — Return `ComparisonDividerState` for host-owned divider drawing.

Comparison state belongs to the active composition. Opening another composition reports that composition's comparison state, and returning to a compared composition restores its source, split, and orientation.

While comparison is active, Fit, 1:1 zoom, pan limits, and minimum zoom use the larger compared image as the authority. Comparison is intended for same-shaped or closely matching images.

See also: [Catalog and Navigation](catalog-and-navigation.md).

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
- CuteCanvas.maskIDsForImage — List mask UUIDs for the given/current image.
- CuteCanvas.listMasksForImage — Return mask metadata as a tuple (ID, color, label, opacity, membership, active).
- CuteCanvas.createBlankMask — Create a transparent mask layer for the current image.
- CuteCanvas.loadMaskFromFile — Import a mask file and return its UUID on success.
- CuteCanvas.removeMaskFromImage — Detach a mask from an image and clean up caches.
- CuteCanvas.setActiveMaskID — Select a mask for editing (or clear with None).
- CuteCanvas.getActiveMaskImage — Snapshot the active mask as a grayscale image.
- CuteCanvas.getMaskUndoState — Return a `cutecanvas.MaskUndoState` snapshot with undo/redo depth for a mask ID.
- CuteCanvas.setMaskProperties — Update mask color and/or opacity for an existing mask.
- CuteCanvas.prefetchMaskOverlays — Queue background colorization for a specific image's mask renders.
- CuteCanvas.cycleMasksForward — Rotate the mask stack forward for the current image.
- CuteCanvas.cycleMasksBackward — Rotate the mask stack backward for the current image.
- CuteCanvas.undoMaskEdit — Undo the last mask edit when a mask is active.
- CuteCanvas.redoMaskEdit — Redo the last reverted mask edit when a mask is active.
- CuteCanvas.CONTROL_MODE_DRAW_BRUSH — Built-in brush mode for mask painting.

CuteCanvas receives touch and tablet input automatically. Pan/zoom mode supports direct one-finger pan, centroid-anchored two-finger pan/pinch, double tap, and optional translation inertia. Brush mode supports fixed-size touch painting plus pressure-sensitive active pens and eraser tips. These behaviors are configured through `Config`; see [Touch and Pen Input](touch-and-pen.md).

### SAM
- CuteCanvas.samFeatureAvailable — Check whether the SAM feature is installed.
- CuteCanvas.samCheckpointReady — Check whether the resolved SAM checkpoint exists on disk.
- CuteCanvas.samCheckpointPath — Return the resolved SAM checkpoint path when available.
- CuteCanvas.samCheckpointStatusChanged — Signal that reports SAM checkpoint readiness changes (status, path); `"downloading"` also covers integrity verification when a hash is required.
- CuteCanvas.samCheckpointProgress — Signal that reports checkpoint download progress (downloaded, total or None).
- CuteCanvas.refreshSamFeature — Reinstall SAM tooling using the current configuration snapshot.
- CuteCanvas.CONTROL_MODE_SMART_SELECT — Built-in smart-select mode using SAM predictions.

See also: [Masks and SAM](masks-and-sam.md) and [Interaction Modes](interaction-modes.md).

## Extensibility

### Overlays
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
- CuteCanvas.panelHitTest — Facade helper returning the DPR-aware `PanelHitTest` metadata (raw/clamped coordinates plus inside-image flag) for a panel-space `QPoint`.
- CuteCanvas.sceneHitTest — Return scene-layer hit metadata for a panel-space `QPoint` when a layered scene composition is active.

See also: [Catalog and Navigation](catalog-and-navigation.md) and [Interaction Modes](interaction-modes.md).

## Signals and Events

### Navigation & Catalog
- CuteCanvas.imageLoaded — Path payload (empty when unknown) emitted after a swap applies.
- CuteCanvas.currentImageChanged — Image UUID payload emitted after navigation completes.
- CuteCanvas.catalogChanged — `CatalogMutationEvent` payload emitted after catalog mutations.
- CuteCanvas.catalogSelectionChanged — Image UUID or `None` payload emitted when selection changes.
- CuteCanvas.linkGroupsChanged — Emit with no payload when link definitions change.
- CuteCanvas.comparisonChanged — `ComparisonState` payload emitted after comparison source, split, or orientation changes.
- CuteCanvas.compositionChanged — `CompositionSnapshot` payload emitted after composition records change.
- CuteCanvas.compositionSelectionChanged — Composition UUID or `None` payload emitted when selection changes.
- CuteCanvas.sceneChanged — `SceneSnapshot` or `None` payload emitted when the normalized active render scene changes.
- CuteCanvas.sceneEditHistoryChanged — Two booleans reporting active-scene chronological editor undo and redo availability.
- CuteCanvas.pixelSelectionChanged — `PixelSelectionSnapshot` payload emitted when the active composition selection changes.
- CuteCanvas.floatingPixelEditChanged — `FloatingPixelSnapshot` or `None` emitted when unresolved fragment state changes.
- CuteCanvas.selectedLayerChanged — `LayerSelectionSnapshot` or `None` emitted when selected layer identity changes.
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

See also: [Catalog and Navigation](catalog-and-navigation.md), [Diagnostics](diagnostics.md), and [Masks and SAM](masks-and-sam.md).

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
- `CuteCanvas.setBrushSize` changes only the size field while retaining the rest of the active preset.
- `CuteCanvas.paintColor` and `CuteCanvas.setPaintColor` query and replace the detached color used by RGBA targets. Coverage targets retain coverage semantics.
- `CuteCanvas.paintTargetChanged` emits `PaintTargetSnapshot` or `None` after target changes.
- `CuteCanvas.brushPresetChanged` emits the new `BrushPreset` after preset or size changes.
- `CuteCanvas.paintColorChanged` emits a detached `QColor` after color changes.
- `cutecanvas.CoverageShapeOptions` reports the feather radius applied to future retained mask and selection shapes. `CuteCanvas.coverageShapeOptions` reads it and `CuteCanvas.configureCoverageShapes` replaces supplied values.
- `cutecanvas.CoverageCoordinateSpace.TARGET` interprets authored geometry in the active layer's local coordinates or in scene coordinates for the pixel-selection target. `CoverageCoordinateSpace.NORMALIZED_TARGET` maps normalized fractions through that target's finite bounds, so `QRectF(0, 0, 0.5, 1)` describes its exact left half.
- `CuteCanvas.addCoverageShape`, `CuteCanvas.addCoveragePolygon`, and `CuteCanvas.addCoverageImage` commit retained vector or arbitrary 8-bit raster coverage directly to the active mask or pixel-selection target. They return stable authored-item IDs and do not use or replace the user's current pixel selection. `CuteCanvas.editor.coverage.rectangle`, `.ellipse`, `.polygon`, and `.image` provide the concise focused facade over the same owner.
- `CuteCanvas.fillSelection` projects the active soft selection into the active editable target as one chronological edit.
- `CuteCanvas.paintBucketOptions` and `CuteCanvas.configurePaintBucket` expose tolerance, contiguous fill, and antialiasing. `CuteCanvas.CONTROL_MODE_PAINT_BUCKET` activates the asynchronous tool.
- `CuteCanvas.rasterizeMaskCoverage` explicitly flattens retained mask items without changing the exported result and remains undoable.

## Manipulation geometry and snapping

- `cutecanvas.LayerGeometryMode.CONTENT` is the default and derives bounds from nontransparent RGBA pixels, nonzero hybrid coverage, placed alpha, or exact vector paint geometry.
- `LayerGeometryMode.STORAGE`, `SOURCE`, `CLIP`, `AUTHORED`, and `CUSTOM` preserve explicit host workflows independently of rendering clips and raster write extent.
- `LayerGeometryPolicy` pairs the chosen manipulation mode with validated custom bounds when the host selects `CUSTOM`.
- `CuteCanvas.layerGeometryPolicy` and `CuteCanvas.setLayerGeometryPolicy` query or replace one layer's manipulation geometry. `CuteCanvas.layerLocalBounds` returns the resolved bounds actually used by move, transform, snapping, and editor overlays.
- `CuteCanvas.setLayerVisible` changes composition-local rendering and hit testing as one undoable edit for every layer source. `LayerHandle.set_visible` provides the focused equivalent.
- `CuteCanvas.translateLayer` adds an exact scene-coordinate displacement without changing the affine linear transform. `CuteCanvas.centerLayer` aligns either or both layer-center axes to the composition canvas. `LayerHandle.translate` and `LayerHandle.center` expose the same commands without raw identifier pairs. Movability remains host policy for translation and alignment.
- `cutecanvas.SnapPolicy` selects canvas, visible-layer, selection, guide, and grid candidates plus device-pixel acquire/release thresholds. Its default eight-pixel acquire tolerance is evaluated through QPane's physical viewport zoom, independently of display scaling.
- Bounds snapping admits center-to-center, matching-edge, and opposing-adjacent-edge relationships. Authored guides and grid lines accept the nearest moving feature; layer bounds do not cross-snap edges to centers.
- `CuteCanvas.snapPolicy`, `CuteCanvas.configureSnapping`, `CuteCanvas.setSnapGuides`, and `CuteCanvas.setSnapGrid` configure the one snapping engine used throughout editor movement. Holding Ctrl temporarily suppresses snapping without changing durable policy.

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
- `CuteCanvas.rasterizeVectorLayer` asynchronously renders an explicit pixel size, creates an editable premultiplied RGBA source, and atomically replaces only that vector instance while preserving its displayed affine geometry. Undo restores the semantic vector source.
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
