**← Previous:** [Extensibility](extensibility.md)

# API Reference (Facade)

Quick index to the QPane facade. Each entry includes a concise explainer; use the guides for tutorialized workflow context.

**Jump within this file:**
* [QPane Setup and Settings](#qpane-setup-and-settings)
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

## QPane Setup and Settings
- QPane.applySettings — Apply a new `Config` to a live QPane, optionally merging keyword overrides for one-off tweaks.
- QPane.settings — Read the current settings snapshot; treat it as read-only and mutate copies instead.
- QPane.installedFeatures — Report which optional features (mask, SAM) are active after initialization.
- QPane.availableControlModes — List all registered control modes, including custom tools.
- QPane.getControlMode — Return the currently active control mode ID.
- QPane.setControlMode — Switch to a registered mode; unavailable mask/SAM modes are ignored while the placeholder is active, and unknown mode IDs raise `ValueError`.
- QPane.CONTROL_MODE_CURSOR — Built-in inert cursor mode (no pan/zoom).
- QPane.CONTROL_MODE_PANZOOM — Built-in pan/zoom mode for navigation.
- QPane.CONTROL_MODE_MOVE — Built-in selection-aware mode that moves selected editable pixels first, or a selectable movable layer when no pixel selection exists.
- QPane.CONTROL_MODE_TRANSFORM — Built-in affine transform mode with eight direct-manipulation handles for the selected movable layer.
- ControlMode.TRANSFORM — Enum value for the built-in affine transform mode.

See also: [Configuration](configuration.md) and [Interaction Modes](interaction-modes.md).

## Config
- Config — Immutable-like settings object handed to QPane; fields are JSON-serializable.
- Config.copy — Deep-clone a config so you can branch without mutating the original.
- Config.as_dict — Return the configuration as a plain dictionary.
- Config.configure — Merge another config/mapping plus keyword overrides; unknown keys raise and enum-backed values (cache mode, placeholder scale/zoom, diagnostics domains) accept enums or canonical strings only.
- Config.feature_descriptors — Expose feature schemas/validators for building UI around optional settings.

See also: [Configuration](configuration.md) and [Configuration Reference](configuration-reference.md).

## Types

### Enums
- qpane.CacheMode — Cache budgeting modes.
	- CacheMode.AUTO — Adapts to OS pressure using headroom settings (`auto`).
	- CacheMode.HARD — Uses a fixed budget (`hard`).
- qpane.PlaceholderScaleMode - Placeholder scaling rules.
	- PlaceholderScaleMode.AUTO — Default scaling (`auto`).
	- PlaceholderScaleMode.LOGICAL_FIT — Fit to logical viewport (`logical_fit`).
	- PlaceholderScaleMode.PHYSICAL_FIT — Fit to physical viewport (`physical_fit`).
	- PlaceholderScaleMode.RELATIVE_FIT — Scale relative to viewport (`relative_fit`).
- qpane.ZoomMode — Placeholder zoom strategies.
	- ZoomMode.FIT — Fit to viewport (`fit`).
	- ZoomMode.LOCKED_ZOOM — Keep zoom level constant (`locked_zoom`).
	- ZoomMode.LOCKED_SIZE — Keep size constant (`locked_size`).
- qpane.DiagnosticsDomain — Diagnostics overlay domains; use enum members (or `.value`) when configuring diagnostics. The base overlay always shows paint/zoom/pyramid rows; the toggles below control additional detail domains.
	- DiagnosticsDomain.CACHE — Cache budgets, usage, and eviction/entitlement detail.
	- DiagnosticsDomain.SWAP — Navigation, renderer queues, and prefetch metrics.
	- DiagnosticsDomain.MASK — Mask status, autosave, job queues, and brush info.
	- DiagnosticsDomain.EXECUTOR — Executor identity, queue depth, thread/device limits, wait times.
	- DiagnosticsDomain.RETRY — Retry queues per resource plus compact summaries.
	- DiagnosticsDomain.SAM — SAM cache, readiness, worker counts, and max threads.
- qpane.ControlMode — Built-in control mode identifiers for tool registration.
	- ControlMode.CURSOR — Inert cursor mode (`cursor`).
	- ControlMode.PANZOOM — Pan/zoom mode (`panzoom`).
	- ControlMode.MOVE — Direct layer movement mode (`move`).
	- ControlMode.DRAW_BRUSH — Mask painting mode (`draw-brush`).
	- ControlMode.SMART_SELECT — SAM-based selection mode (`smart-select`).
	- ControlMode.SELECT_RECTANGLE — Rectangular pixel-selection mode (`select-rectangle`).
	- ControlMode.SELECT_ELLIPSE — Elliptical pixel-selection mode (`select-ellipse`).
	- ControlMode.SELECT_LASSO — Freeform pixel-selection mode (`select-lasso`).
- qpane.PixelSelectionMode — Coverage combination used by pixel-selection edits.
	- PixelSelectionMode.REPLACE — Replace existing selection coverage.
	- PixelSelectionMode.ADD — Add incoming soft coverage.
	- PixelSelectionMode.SUBTRACT — Subtract incoming soft coverage.
	- PixelSelectionMode.INTERSECT — Retain overlapping coverage.
- qpane.FloatingPixelMode — Whether an unresolved pixel fragment will cut or copy its source.
	- FloatingPixelMode.CUT — Clear selected source pixels when the fragment resolves.
	- FloatingPixelMode.COPY — Preserve source pixels when the fragment resolves.
- qpane.ComparisonOrientation — Split direction for comparison rendering.
	- ComparisonOrientation.VERTICAL — Reveal the comparison image to the right of a vertical divider.
	- ComparisonOrientation.HORIZONTAL — Reveal the comparison image below a horizontal divider.

### Data Structures
- qpane.CatalogEntry — Structured catalog value containing source image data and an optional path.
	- CatalogEntry.image — Original catalog `QImage` used by QPane rendering and host snapshots.
	- CatalogEntry.path — Optional source path used for labels, persistence, or host lookup.
- qpane.LinkedGroup — Linked-view group descriptor with a stable UUID and members.
- qpane.ComparisonState — Snapshot returned by `QPane.comparisonState`.
	- ComparisonState.enabled — Whether comparison rendering is active.
	- ComparisonState.source_id — Catalog image UUID for the comparison source.
	- ComparisonState.source_path — Optional path associated with the comparison image.
	- ComparisonState.source_kind — `"catalog"` when enabled, or None.
	- ComparisonState.split_position — Normalized split position from `0.0` to `1.0`.
	- ComparisonState.orientation — Active `ComparisonOrientation` used for vertical or horizontal split rendering.
- qpane.QPaneCompositionPolicy — Host-controlled structural policy for one composition document.
	- QPaneCompositionPolicy.removable — Allow the composition to be removed through `QPane.removeComposition`.
	- QPaneCompositionPolicy.comparison_enabled — Allow the composition to own an active comparison source.
- qpane.ComparisonDividerState — Host-facing comparison divider interaction and geometry snapshot.
	- ComparisonDividerState.enabled — Whether authoritative divider geometry is available.
	- ComparisonDividerState.interactive — Whether built-in divider dragging is enabled.
	- ComparisonDividerState.hovered — Whether the pointer is currently over the divider hit target.
	- ComparisonDividerState.dragging — Whether a divider drag is active.
	- ComparisonDividerState.orientation — Current comparison split orientation.
	- ComparisonDividerState.hit_width — Invisible grab tolerance around the rendered boundary.
	- ComparisonDividerState.full_segment — Full projected boundary in widget coordinates, or None.
	- ComparisonDividerState.visible_segment — Portion of the boundary visible inside the widget, or None.
- qpane.CompositionEntry — Snapshot row for one renderable composition.
	- CompositionEntry.composition_id — Stable UUID used with `QPane.openComposition`.
	- CompositionEntry.kind — Descriptive creation-origin metadata such as `"composition"`, `"default-image"`, `"explicit"`, or `"layered-scene"`; it does not control behavior.
	- CompositionEntry.title — Host-facing browser title.
	- CompositionEntry.source_image_ids — Catalog image UUIDs used by the composition.
	- CompositionEntry.current_image_id — Optional catalog-navigation shortcut retained by seeded compatibility workflows; it is not canvas or layer authority.
	- CompositionEntry.comparison — Composition-scoped `ComparisonState` restored when the row reopens.
	- CompositionEntry.scene_layer_count — Number of ordered layer instances in the composition.
	- CompositionEntry.scene_bounds — Authoritative scene-coordinate canvas bounds for the composition.
	- CompositionEntry.layers — Bottom-to-top detached `CompositionLayerEntry` values for building nested layer browsers without activating the composition.
	- CompositionEntry.policy — Current host-controlled `QPaneCompositionPolicy` for the document.
- qpane.CompositionLayerEntry — Detached browser metadata for one ordered layer instance.
	- CompositionLayerEntry.layer_id — Stable layer-instance UUID.
	- CompositionLayerEntry.source_kind — Presentation name for the layer source domain.
	- CompositionLayerEntry.source_id — Shared source-resource UUID.
	- CompositionLayerEntry.label — Optional host-facing layer label.
	- CompositionLayerEntry.role — Layer role such as `"base-image"` or `"content"`.
	- CompositionLayerEntry.visible — Current instance visibility.
	- CompositionLayerEntry.opacity — Current instance opacity.
	- CompositionLayerEntry.interaction — Host-controlled layer interaction policy.
	- CompositionLayerEntry.transform — Detached exact local-to-scene affine transform.
- qpane.CompositionSnapshot — Structured composition browser state.
	- CompositionSnapshot.compositions — Mapping of composition UUID to `CompositionEntry`.
	- CompositionSnapshot.order — Composition UUIDs in browser order.
	- CompositionSnapshot.current_composition_id — Active composition UUID, or None.
- qpane.MaskInfo — Mask metadata returned by mask helpers, including stable `scene_id`, `layer_id`, and `interaction` policy for generic scene-layer operations.
- qpane.DiagnosticRecord — Label/value diagnostic entry used in overlays.
- qpane.CatalogMutationEvent — Catalog mutation payload emitted on catalog changes.
- qpane.CatalogSnapshot — Structured catalog state (catalog entries, linked groups, ordering, active IDs).
- qpane.OverlayState — Stable public-overlay snapshot passed to `draw_fn`.
	- OverlayState.zoom — Current zoom factor.
	- OverlayState.qpane_rect — Widget-space bounds of the viewer.
	- OverlayState.physical_viewport_rect — Device-pixel viewport bounds.
	- OverlayState.transform — Image-to-widget transform for coordinate anchoring.
	- OverlayState.current_pan — Current pan offset in widget space.
	- OverlayState.source_image — Base catalog raster resolved for the current overlay pass, not flattened rendered content.
- qpane.QPaneSceneRequest — Host request used to create or replace a stored scene composition.
	- QPaneSceneRequest.composition_id — Optional composition UUID to create or replace; None generates a new UUID.
	- QPaneSceneRequest.title — Optional host-facing composition title.
	- QPaneSceneRequest.bounds — Host-defined scene-coordinate bounds.
	- QPaneSceneRequest.layers — Ordered `QPaneCatalogImageLayerRequest` entries.
- qpane.QPaneCatalogImageLayerRequest — Catalog-backed image layer in a scene composition request.
	- QPaneCatalogImageLayerRequest.layer_id — Stable layer UUID supplied by the host.
	- QPaneCatalogImageLayerRequest.image_id — Catalog image UUID rendered for this layer.
	- QPaneCatalogImageLayerRequest.placement — Scene-coordinate rectangle for this layer.
	- QPaneCatalogImageLayerRequest.visible — Whether the layer renders and hit-tests.
	- QPaneCatalogImageLayerRequest.opacity — Layer opacity from `0.0` to `1.0`.
	- QPaneCatalogImageLayerRequest.clip — Optional `QPaneSceneClip` limiting rendered or hit-tested layer area.
	- QPaneCatalogImageLayerRequest.hit_test — Whether `QPane.sceneHitTest` can return this layer.
	- QPaneCatalogImageLayerRequest.role — Host label carried into hits and overlays.
	- QPaneCatalogImageLayerRequest.metadata — Opaque host metadata carried into hits and overlays.
	- QPaneCatalogImageLayerRequest.interaction — `QPaneLayerInteractionPolicy` controlling selection and movement.
- qpane.QPaneLayerInteractionPolicy — Host policy for direct and structural layer interaction.
	- QPaneLayerInteractionPolicy.selectable — Allow direct tools to select the layer through covered source pixels.
	- QPaneLayerInteractionPolicy.movable — Allow generic placement mutation and Move-tool dragging for the layer.
	- QPaneLayerInteractionPolicy.pixel_editable — Allow pixel tools to mutate a layer when its source also advertises raster editing.
	- QPaneLayerInteractionPolicy.reorderable — Allow the layer instance to move within its composition stack.
	- QPaneLayerInteractionPolicy.removable — Allow the layer instance to be removed from its composition.
- qpane.QPaneLayerSelectionState — Selected scene-layer identity, kept separate from pixel-selection coverage.
	- QPaneLayerSelectionState.scene_id — Public identity of the scene containing the selected layer.
	- QPaneLayerSelectionState.layer_id — Stable identity of the selected layer.
- qpane.RasterExtentPolicy — Write-boundary policy for raster layer storage.
	- RasterExtentPolicy.FIXED — Clip edits to the layer's current local bounds.
	- RasterExtentPolicy.EXPAND_ON_WRITE — Preserve the original grow-on-write contract with sparse backing.
	- RasterExtentPolicy.UNBOUNDED — Accept edits at arbitrary local coordinates while allocating only touched tiles.
- qpane.EditorCapability — Independently composable host permission for one editor capability.
	- EditorCapability.SELECT_PIXELS — Create or modify composition pixel selections.
	- EditorCapability.EDIT_PIXELS — Clear or move pixels on intrinsically editable sources.
	- EditorCapability.PAINT — Paint through the active source-owned target.
	- EditorCapability.MOVE_LAYERS — Move complete policy-enabled layers.
	- EditorCapability.TRANSFORM_LAYERS — Apply interactive affine layer transforms.
- qpane.EditorIntent — Public operation identifier accepted by `QPane.editorOperationState`.
	- EditorIntent.SELECT_PIXELS — Inspect pixel-selection creation and modification.
	- EditorIntent.DELETE_PIXELS — Inspect selection-constrained pixel clearing.
	- EditorIntent.PAINT — Inspect the active paint target.
	- EditorIntent.MOVE — Inspect selected-pixel or complete-layer movement.
	- EditorIntent.TRANSFORM — Inspect selected-pixel or complete-layer transform.
- qpane.QPaneEditorPolicy — Immutable set of editor capabilities enabled by the host; the default contains every capability.
	- QPaneEditorPolicy.capabilities — Complete immutable `EditorCapability` set.
- qpane.QPaneEditorOperationState — Detached operation decision containing availability, denial, explicit alternatives, and resolved scene/layer identity.
	- QPaneEditorOperationState.intent — Operation identifier used for this query.
	- QPaneEditorOperationState.allowed — Whether the operation can execute now.
	- QPaneEditorOperationState.denial — Stable denial string, or `None` when allowed.
	- QPaneEditorOperationState.alternatives — Explicit source-owned alternatives such as rasterization.
	- QPaneEditorOperationState.scene_id — Resolved scene identity when available.
	- QPaneEditorOperationState.layer_id — Resolved layer identity when available.
- qpane.QPaneRasterSurfaceState — Detached storage snapshot for one active raster scene layer.
	- QPaneRasterSurfaceState.scene_id — Scene UUID used to query the layer.
	- QPaneRasterSurfaceState.layer_id — Stable raster layer UUID.
	- QPaneRasterSurfaceState.bounds — Integer storage rectangle in layer-local coordinates; its origin may be negative.
	- QPaneRasterSurfaceState.extent_policy — Current `RasterExtentPolicy` applied to edits.
	- QPaneRasterSurfaceState.content_revision — Revision of authoritative raster pixels.
	- QPaneRasterSurfaceState.structure_revision — Revision of bounds or policy state.
	- QPaneRasterSurfaceState.pending_request_id — Active bounds request UUID, or `None`.
- qpane.PlacedAssetMode — Persistence relationship for a non-destructive placed source.
	- PlacedAssetMode.EMBEDDED — Pixels are stored as part of the composition resource.
	- PlacedAssetMode.LINKED — Pixels retain an external filesystem locator and can be refreshed.
- qpane.PlacedAssetStatus — Availability of the latest requested linked content.
	- PlacedAssetStatus.READY — The current source decoded successfully.
	- PlacedAssetStatus.LOADING — A newer linked generation is decoding asynchronously.
	- PlacedAssetStatus.MISSING — The linked locator is unavailable; retained fallback pixels remain visible when configured.
	- PlacedAssetStatus.ERROR — The linked source could not be decoded; retained fallback pixels remain visible.
- qpane.QPanePlacedAssetState — Detached provenance state for one active placed layer.
	- QPanePlacedAssetState.scene_id — Public scene UUID used to query the layer.
	- QPanePlacedAssetState.layer_id — Stable independent layer-instance UUID.
	- QPanePlacedAssetState.asset_id — Shared non-destructive source UUID.
	- QPanePlacedAssetState.mode — Persistence relationship that determines whether pixels are embedded or linked.
	- QPanePlacedAssetState.status — Availability of the latest requested content generation.
	- QPanePlacedAssetState.source_path — Linked filesystem locator, or `None` for embedded sources.
	- QPanePlacedAssetState.error — Latest non-modal link/decode error, or `None`.
	- QPanePlacedAssetState.keep_fallback — Whether private composition archives retain last-known linked pixels.
	- QPanePlacedAssetState.content_revision — Revision of the current decoded source product.
	- QPanePlacedAssetState.generation — Generation used to reject stale asynchronous link work.
- qpane.QPaneSceneTemplate — Host-owned reusable template for building scene composition requests.
	- QPaneSceneTemplate.template_id — Stable template UUID owned by the host.
	- QPaneSceneTemplate.bounds — Host-defined scene-coordinate bounds.
	- QPaneSceneTemplate.layers — Ordered `QPaneTemplateLayer` entries.
	- QPaneSceneTemplate.title — Optional default title used by template composition.
- qpane.QPaneTemplateLayer — Template layer bound by source slot at composition time.
	- QPaneTemplateLayer.layer_id — Stable layer UUID supplied by the host.
	- QPaneTemplateLayer.source_slot — Binding key resolved by `QPaneSceneTemplateBindings.catalog_images`.
	- QPaneTemplateLayer.placement — Scene-coordinate rectangle for this layer.
	- QPaneTemplateLayer.visible — Whether the layer renders and hit-tests.
	- QPaneTemplateLayer.opacity — Layer opacity from `0.0` to `1.0`.
	- QPaneTemplateLayer.clip — Optional `QPaneSceneClip` applied when the template becomes a stored scene.
	- QPaneTemplateLayer.hit_test — Whether `QPane.sceneHitTest` can return this layer.
	- QPaneTemplateLayer.role — Host label carried into hits and overlays.
	- QPaneTemplateLayer.metadata — Opaque host metadata merged into composed layers.
	- QPaneTemplateLayer.interaction — Direct-interaction policy copied into each composed layer.
- qpane.QPaneSceneTemplateBindings — Concrete catalog image bindings for a scene template.
	- QPaneSceneTemplateBindings.composition_id — Optional composition UUID to create or replace.
	- QPaneSceneTemplateBindings.title — Optional title overriding the template title.
	- QPaneSceneTemplateBindings.catalog_images — Mapping of template source slots to catalog image UUIDs.
	- QPaneSceneTemplateBindings.metadata — Optional source-slot metadata merged into composed layers.
- qpane.QPaneScene — Public scene snapshot for an active generated or host-authored composition.
	- QPaneScene.composition_id — Stored composition UUID.
	- QPaneScene.scene_id — Render scene UUID; layered scene compositions use the composition UUID.
	- QPaneScene.title — Host-facing composition title.
	- QPaneScene.bounds — Host-defined scene-coordinate bounds.
	- QPaneScene.layers — Ordered `QPaneSceneLayer` entries.
- qpane.QPaneSceneLayer — Source-backed layer in a composed scene.
	- QPaneSceneLayer.layer_id — Stable layer UUID supplied by the host.
	- QPaneSceneLayer.image_id — Catalog image UUID for image layers, or `None` for masks and editable rasters.
	- QPaneSceneLayer.placement — Conservative axis-aligned scene bound derived from the exact transform.
	- QPaneSceneLayer.transform — Detached affine local-to-scene `QTransform` for the layer instance.
	- QPaneSceneLayer.visible — Whether the layer renders and hit-tests.
	- QPaneSceneLayer.opacity — Layer opacity from `0.0` to `1.0`.
	- QPaneSceneLayer.clip — Optional `QPaneSceneClip` preserved from the normalized request layer.
	- QPaneSceneLayer.hit_test — Whether `QPane.sceneHitTest` can return this layer.
	- QPaneSceneLayer.role — Host label carried into hits and overlays.
	- QPaneSceneLayer.metadata — Opaque host metadata carried into hits and overlays.
	- QPaneSceneLayer.interaction — Current selection and movement policy for the layer.
	- QPaneSceneLayer.source_kind — Source domain: `catalog-image`, `mask`, `raster`, or `placeholder-image`.
	- QPaneSceneLayer.source_id — Stable source asset UUID independent of the scene-layer UUID.
	- QPaneSceneLayer.label — Optional host-facing authoring-layer label.
- qpane.QPaneSceneClip — Optional layer clip rectangle.
	- QPaneSceneClip.coordinate_space — Coordinate system for `rect`: `"scene"`, `"normalized-scene"`, `"viewport"`, or `"normalized-viewport"`.
	- QPaneSceneClip.rect — Clip rectangle in the selected coordinate space.
- qpane.QPaneSceneHit — Public scene hit result returned by `QPane.sceneHitTest`.
	- QPaneSceneHit.composition_id — Active composition UUID.
	- QPaneSceneHit.scene_id — Scene UUID.
	- QPaneSceneHit.layer_id — Hit layer UUID.
	- QPaneSceneHit.image_id — Catalog image UUID for the hit layer.
	- QPaneSceneHit.role — Host role copied from the layer.
	- QPaneSceneHit.metadata — Opaque metadata copied from the layer.
	- QPaneSceneHit.panel_point — Tested widget coordinate.
	- QPaneSceneHit.scene_point — Hit point in scene coordinates.
	- QPaneSceneHit.source_point — Hit point in source image pixel coordinates.
- qpane.QPaneSceneOverlayState — Scene-overlay snapshot passed to `registerSceneOverlay` callbacks.
	- QPaneSceneOverlayState.zoom — Current zoom factor.
	- QPaneSceneOverlayState.qpane_rect — Widget-space bounds.
	- QPaneSceneOverlayState.physical_viewport_rect — Device-pixel viewport bounds.
	- QPaneSceneOverlayState.composition_id — Active composition UUID.
	- QPaneSceneOverlayState.scene_id — Active scene UUID.
	- QPaneSceneOverlayState.scene_bounds — Scene-coordinate bounds.
	- QPaneSceneOverlayState.layers — Rendered public scene layers.
- qpane.QPaneSceneOverlayLayer — Rendered layer geometry for scene overlays.
	- QPaneSceneOverlayLayer.layer_id — Public layer UUID.
	- QPaneSceneOverlayLayer.image_id — Catalog image UUID.
	- QPaneSceneOverlayLayer.role — Host role copied from the layer.
	- QPaneSceneOverlayLayer.metadata — Opaque metadata copied from the layer.
	- QPaneSceneOverlayLayer.placement — Scene-coordinate placement.
	- QPaneSceneOverlayLayer.source_size — Resolved source raster size.
	- QPaneSceneOverlayLayer.transform — Source-pixel to widget-coordinate transform.
	- QPaneSceneOverlayLayer.panel_bounds — Layer bounds in widget coordinates.
	- QPaneSceneOverlayLayer.visible — Whether the rendered layer is visible.
- qpane.PanelHitTest — Hit-test metadata from `QPane.panelHitTest`.
	- PanelHitTest.panel_point — Panel-space position that was tested.
	- PanelHitTest.raw_point — Unclamped image-space coordinate as float.
	- PanelHitTest.clamped_point — Image-space coordinate clamped to image bounds.
	- PanelHitTest.inside_image — True when the raw point lies inside the image.

## Catalog and Navigation

### Catalog Management
- QPane.imageMapFromLists — Build an ordered catalog mapping from images plus optional paths/IDs; values are `CatalogEntry` objects; length mismatches raise `ValueError`.
- QPane.setImagesByID — Replace the catalog and set the current image in one call.
- QPane.clearImages — Drop the entire catalog and show the placeholder/blank view.
- QPane.removeImageByID — Remove a single catalog entry without rebuilding.
- QPane.removeImagesByID — Remove multiple entries without rebuilding.

### Navigation & Current State
- QPane.setCurrentImageID — Navigate to a specific UUID (or `None` to clear); unknown IDs no-op.
- QPane.currentImageID — Return the current catalog UUID (or None when empty).
- QPane.currentImage — Return the current `QImage`, or None when no image is selected.
- QPane.currentImagePath — Return the current image path (or None when missing).
- QPane.placeholderActive — Return True when the placeholder policy is active.

### Catalog Queries
- QPane.imageIDs — List all catalog UUIDs in order.
- QPane.hasImages — Quick guard to see if any images are loaded.
- QPane.allImages — Return all catalog images in order.
- QPane.allImagePaths — Return all catalog paths in order.
- QPane.imagePath — Return the path for a specific ID (or None when missing).
- QPane.getCatalogSnapshot — Return structured catalog state (entries, order, linked groups, active IDs, mask capability) for host consumption.

### Linked Views
- QPane.setAllImagesLinked — Link every image into one pan/zoom group (requires 2+ entries).
- QPane.setLinkedGroups — Define custom linked groups with `LinkedGroup` objects; invalid/overlapping groups are ignored.
- QPane.linkedGroups — Read current linked groups as `LinkedGroup` instances.

See also: [Catalog and Navigation](catalog-and-navigation.md) and [Interaction Modes](interaction-modes.md) for how linking interacts with tools.

## Scene Composition
- QPane.composeScene — Store a host-authored `QPaneSceneRequest` whose raster layers reference catalog image IDs and optionally open it.
- QPane.composeSceneFromTemplate — Expand a host-owned scene template and bindings into a stored scene composition.
- QPane.fitSceneRect — Return the largest centered aspect-preserving scene rectangle inside a target rectangle.
- QPane.fillSceneRect — Return the smallest centered aspect-preserving scene rectangle covering a target rectangle; the result may extend outside the target.
- QPane.currentScene — Return QPane's normalized public scene snapshot, or None.
- QPane.sceneHitTest — Return topmost public scene-layer metadata for a widget-space point.
- QPane.layerTransform — Return a detached exact affine transform for one active scene layer.
- QPane.layerLocalBounds — Return detached intrinsic source-local bounds for one active scene layer when available.
- QPane.registerSceneOverlay — Add a named scene overlay; order follows registration.
- QPane.unregisterSceneOverlay — Remove a scene overlay; no-op if it is absent.
- QPane.sceneOverlays — Return a read-only snapshot of registered scene overlays; use register/unregister helpers to change it.
- QPane.setLayerInteractionPolicy — Replace selection and movement permissions for a layer through its scene owner.
- QPane.setLayerPlacement — Set an absolute scene-space layer rectangle when movement policy permits it.
- QPane.setLayerTransform — Set an invertible affine local-to-scene transform when movement policy permits it.
- QPane.setLayerIndex — Move one active layer to a bottom-to-top render index as one undoable composition-stack edit.
- QPane.selectedLayer — Return selected scene-layer identity independently of pixel coverage.
- QPane.setSelectedLayer — Select a policy-enabled layer in the active scene.
- QPane.clearSelectedLayer — Clear layer identity without clearing pixel selection.
- QPane.rasterSurfaceState — Return local bounds, extent policy, and revisions for a supported active raster layer.
- QPane.setRasterExtentPolicy — Choose whether writes clip to current local bounds or expand storage.
- QPane.requestRasterBounds — Asynchronously pad or crop a supported raster layer to exact integer local bounds while preserving its scene transform.
- QPane.addEditableRasterLayer — Copy a color image into a composition-owned editable RGBA layer.
- QPane.placeEmbeddedAsset — Copy a `QImage` into a non-destructive embedded source and add an independently transformable layer instance.
- QPane.placeLinkedAsset — Begin non-blocking file decode and add a linked layer only after decoding succeeds.
- QPane.duplicatePlacedAsset — Add an independent layer instance that shares the selected placed source and future source refreshes.
- QPane.placedAssetState — Return detached provenance, status, and generation state for a placed layer.
- QPane.refreshPlacedAsset — Reload the current linked locator without adding an editor-history command.
- QPane.relinkPlacedAsset — Decode a replacement locator and record the resulting provenance transition in scene history.
- QPane.embedPlacedAsset — Detach a linked source from its locator while retaining identical pixels; undo restores the exact link state.
- QPane.rasterizePlacedAsset — Render a placed source at explicit or natural pixel dimensions and atomically replace it with an editable RGBA source.
- QPane.editableRasterLayerImage — Return a detached image snapshot for an editable RGBA layer.
- QPane.selectLayerCoverage — Project a mask or other coverage-source layer into pixel selection.
- QPane.deleteSelectedPixels — Clear selected coverage from the selected policy-enabled mask or RGBA layer.
- QPane.floatingPixelEditState — Return detached state for the unresolved floating fragment, or `None`.
- QPane.anchorFloatingPixels — Resolve floating pixels into their source or a compatible destination layer.
- QPane.promoteFloatingPixels — Resolve floating pixels into a newly created composition layer.
- QPane.cancelFloatingPixels — Cancel floating pixels without changing durable source pixels.
- QPane.sceneEditUndoAvailable — Report whether the active scene has a placement change to undo.
- QPane.sceneEditRedoAvailable — Report whether the active scene has a placement change to redo.
- QPane.undoSceneEdit — Undo the active scene's latest committed layer placement.
- QPane.redoSceneEdit — Redo the active scene's latest reverted layer placement.
- QPane.editorPolicy — Return the current immutable host editor policy.
- QPane.setEditorPolicy — Atomically replace independently composable editor capabilities and cancel provisional pointer work losslessly.
- QPane.editorOperationState — Query the same source, state, and policy decision used by built-in tools and editor commands.
- QPane.editorPolicyChanged — Emitted with the complete immutable policy after a real replacement.

Layered compositions can combine catalog images, editable rasters, masks, placed assets, and vectors. Each source retains its own editing contract while participating in the same ordered scene, transform, hit-test, and render behavior. Hit testing is passive; calling `QPane.setCurrentImageID` after a catalog-image scene hit opens that image's generated default composition.

See also: [Scene Composition](scenes.md) and [Extensibility](extensibility.md).

## Compositions
- QPane.createComposition — Create and open an independent empty document with positive scene-space canvas bounds.
- QPane.createCompositionFromImage — Create and open an independent document whose canvas is seeded from a catalog image and whose first image is an ordinary layer instance.
- QPane.addCatalogImageLayer — Place an existing catalog resource as a new independent layer instance in the active composition.
- QPane.setCompositionPolicy — Replace host-controlled document removal and comparison permissions.
- QPane.compose — Create and open a persistent composition from one or two catalog image IDs.
- QPane.openComposition — Open an existing composition UUID.
- QPane.currentCompositionID — Return the active composition UUID, or None.
- QPane.compositionIDs — Return composition UUIDs in browser order.
- QPane.getCompositionSnapshot — Return composition rows for host browsers.
- QPane.removeComposition — Remove a composition when its document policy permits it.
- QPane.removeLayer — Remove a layer instance when its layer policy permits it and record the change in composition history.

Every composition owns its canvas and ordered layer stack independently of the catalog. `createCompositionFromImage` uses the source dimensions only to establish the initial canvas and adds a normal catalog-backed instance; placing the same catalog image elsewhere shares source render products while keeping transform, order, effects, and policy independent. Loading catalog images also creates generated one-image compositions so `setCurrentImageID(image_id)` remains supported. `currentImageID`, `currentImage`, `currentImagePath`, and `imageIDs` remain catalog/source APIs.

See also: [Catalog and Navigation](catalog-and-navigation.md).

## Comparison
- QPane.setComparisonImageID — Use an existing catalog image as the comparison reveal source.
- QPane.clearComparisonImage — Disable comparison rendering.
- QPane.setComparisonSplit — Set the normalized split position and optional `ComparisonOrientation`.
- QPane.comparisonState — Return the active `ComparisonState` snapshot.
- QPane.comparisonDividerInteractive — Return whether built-in comparison-divider dragging is enabled.
- QPane.setComparisonDividerInteractive — Enable or disable built-in split-boundary dragging.
- QPane.comparisonDividerState — Return `ComparisonDividerState` for host-owned divider drawing.

Comparison state belongs to the active composition. Opening another composition reports that composition's comparison state, and returning to a compared composition restores its source, split, and orientation.

While comparison is active, Fit, 1:1 zoom, pan limits, and minimum zoom use the larger compared image as the authority. Comparison is intended for same-shaped or closely matching images.

See also: [Catalog and Navigation](catalog-and-navigation.md).

## Diagnostics
- QPane.diagnosticsOverlayEnabled — Read whether the diagnostics HUD is visible.
- QPane.setDiagnosticsOverlayEnabled — Enable or disable the diagnostics HUD.
- QPane.diagnosticsDomains — List available diagnostics domains.
- QPane.diagnosticsDomainEnabled — Read whether a given domain is enabled; raises when the domain is unavailable.
- QPane.setDiagnosticsDomainEnabled — Enable or disable a domain; raises when the domain is unavailable.

See also: [Diagnostics](diagnostics.md).

## Masks and SAM
### Masks
- QPane.maskFeatureAvailable — Check whether the mask feature is installed.
- QPane.activeMaskID — Read the active mask UUID (or None).
- QPane.maskIDsForImage — List mask UUIDs for the given/current image.
- QPane.listMasksForImage — Return mask metadata as a tuple (ID, color, label, opacity, membership, active).
- QPane.createBlankMask — Create a transparent mask layer for the current image.
- QPane.loadMaskFromFile — Import a mask file and return its UUID on success.
- QPane.removeMaskFromImage — Detach a mask from an image and clean up caches.
- QPane.setActiveMaskID — Select a mask for editing (or clear with None).
- QPane.getActiveMaskImage — Snapshot the active mask as a grayscale image.
- QPane.getMaskUndoState — Return a `qpane.MaskUndoState` snapshot with undo/redo depth for a mask ID.
- QPane.setMaskProperties — Update mask color and/or opacity for an existing mask.
- QPane.prefetchMaskOverlays — Queue background colorization for a specific image's mask renders.
- QPane.cycleMasksForward — Rotate the mask stack forward for the current image.
- QPane.cycleMasksBackward — Rotate the mask stack backward for the current image.
- QPane.undoMaskEdit — Undo the last mask edit when a mask is active.
- QPane.redoMaskEdit — Redo the last reverted mask edit when a mask is active.
- QPane.CONTROL_MODE_DRAW_BRUSH — Built-in brush mode for mask painting.

QPane receives touch and tablet input automatically. Pan/zoom mode supports direct one-finger pan, centroid-anchored two-finger pan/pinch, double tap, and optional translation inertia. Brush mode supports fixed-size touch painting plus pressure-sensitive active pens and eraser tips. These behaviors are configured through `Config`; see [Touch and Pen Input](touch-and-pen.md).

### SAM
- QPane.samFeatureAvailable — Check whether the SAM feature is installed.
- QPane.samCheckpointReady — Check whether the resolved SAM checkpoint exists on disk.
- QPane.samCheckpointPath — Return the resolved SAM checkpoint path when available.
- QPane.samCheckpointStatusChanged — Signal that reports SAM checkpoint readiness changes (status, path); `"downloading"` also covers integrity verification when a hash is required.
- QPane.samCheckpointProgress — Signal that reports checkpoint download progress (downloaded, total or None).
- QPane.refreshSamFeature — Reinstall SAM tooling using the current configuration snapshot.
- QPane.CONTROL_MODE_SMART_SELECT — Built-in smart-select mode using SAM predictions.

See also: [Masks and SAM](masks-and-sam.md) and [Interaction Modes](interaction-modes.md).

## Extensibility

### Overlays
- QPane.registerOverlay — Add a named overlay; order follows registration.
- QPane.unregisterOverlay — Remove an overlay; no-op if it is absent.
- QPane.contentOverlays — Return a read-only snapshot of registered content overlays; use register/unregister helpers to change it.
- QPane.registerSceneOverlay — Add a named scene overlay for active layered scene composition layers.
- QPane.unregisterSceneOverlay — Remove a scene overlay; no-op if it is absent.
- QPane.sceneOverlays — Return a read-only snapshot of registered scene overlays.
- QPane.overlaysSuspended — Report whether overlays are temporarily suppressed.
- QPane.overlaysResumePending — Indicate overlays should resume after activation work.
- QPane.resumeOverlays — Resume overlays without forcing a repaint.
- QPane.resumeOverlaysAndUpdate — Resume overlays and schedule a repaint.
- QPane.maybeResumeOverlays — Resume overlays when pending activation work completes.

### Tool Registration
- QPane.registerTool — Register a custom tool/control mode (unique ID required).
- QPane.unregisterTool — Remove a custom tool; cannot remove the active mode or built-ins.
- QPane.registerCursorProvider — Attach a cursor provider to a control mode.
- QPane.unregisterCursorProvider — Remove a cursor provider and refresh if active.

### ExtensionTool API
- qpane.ExtensionTool — Base class for custom tools; emit `self.signals` requests to pan, zoom, or repaint.
- ExtensionTool.activate — Called when the tool becomes active; receives dependency hooks.
- ExtensionTool.deactivate — Called when the tool is deactivated so it can clean up.
- ExtensionTool.mousePressEvent — Handle pointer press events forwarded by QPane.
- ExtensionTool.mouseMoveEvent — Handle pointer move events forwarded by QPane.
- ExtensionTool.mouseReleaseEvent — Handle pointer release events forwarded by QPane.
- ExtensionTool.mouseDoubleClickEvent — Optional double-click handling.
- ExtensionTool.wheelEvent — Handle wheel or trackpad gestures forwarded by QPane.
- ExtensionTool.enterEvent — Optional cursor-enter handling.
- ExtensionTool.leaveEvent — Optional cursor-leave handling.
- ExtensionTool.keyPressEvent — Optional key press handling.
- ExtensionTool.keyReleaseEvent — Optional key release handling.
- ExtensionTool.draw_overlay — Optional overlay paint hook for the active tool.
- ExtensionTool.getCursor — Return a custom cursor or None to defer to cursor providers.

### Tool Signals
- qpane.ExtensionToolSignals — Signal hub exposed on `ExtensionTool` for requesting QPane actions.
- ExtensionTool.signals — ExtensionToolSignals instance used to emit tool requests.
- ExtensionToolSignals.pan_requested — Ask QPane to pan to a new QPointF.
- ExtensionToolSignals.zoom_requested — Ask QPane to zoom around a QPointF anchor.
- ExtensionToolSignals.repaint_overlay_requested — Ask QPane to repaint overlays.
- ExtensionToolSignals.cursor_update_requested — Ask QPane to refresh the cursor.

These helpers delegate through the same hook layer QPane uses internally, keeping the public surface stable while feature installers share signatures.

See also: [Extensibility](extensibility.md) and [Interaction Modes](interaction-modes.md).

## View State & Geometry
- QPane.currentZoom — Read the current zoom factor (float) as a device-pixel normalized value. Matches the payload emitted via `QPane.zoomChanged`.
- QPane.setZoomFit — Fit the current image to the viewport and recenter pan.
- QPane.setZoom1To1 — Snap zoom to native scale while keeping `anchor` steady when provided.
- QPane.applyZoom — Clamp zoom requests and remap unity to the device-native scale.
- QPane.viewportRectChanged — `QRectF` signal fired whenever the physical viewport changes size (resizes or monitor/DPR changes). Emits once after initialization so status bars and overlays can seed layout state before user interaction.
- QPane.currentViewportRect — Returns the most recent physical viewport rect snapshot, falling back to the live `physicalViewportRect()` when no emission occurred yet.
- QPane.panelHitTest — Facade helper returning the DPR-aware `PanelHitTest` metadata (raw/clamped coordinates plus inside-image flag) for a panel-space `QPoint`.
- QPane.sceneHitTest — Return scene-layer hit metadata for a panel-space `QPoint` when a layered scene composition is active.

See also: [Catalog and Navigation](catalog-and-navigation.md) and [Interaction Modes](interaction-modes.md).

## Signals and Events

### Navigation & Catalog
- QPane.imageLoaded — Path payload (empty when unknown) emitted after a swap applies.
- QPane.currentImageChanged — Image UUID payload emitted after navigation completes.
- QPane.catalogChanged — `CatalogMutationEvent` payload emitted after catalog mutations.
- QPane.catalogSelectionChanged — Image UUID or `None` payload emitted when selection changes.
- QPane.linkGroupsChanged — Emit with no payload when link definitions change.
- QPane.comparisonChanged — `ComparisonState` payload emitted after comparison source, split, or orientation changes.
- QPane.compositionChanged — `CompositionSnapshot` payload emitted after composition records change.
- QPane.compositionSelectionChanged — Composition UUID or `None` payload emitted when selection changes.
- QPane.sceneChanged — `QPaneScene` or `None` payload emitted when the normalized active render scene changes.
- QPane.sceneEditHistoryChanged — Two booleans reporting active-scene chronological editor undo and redo availability.
- QPane.pixelSelectionChanged — `QPanePixelSelectionState` payload emitted when the active composition selection changes.
- QPane.floatingPixelEditChanged — `QPaneFloatingPixelEditState` or `None` emitted when unresolved fragment state changes.
- QPane.selectedLayerChanged — `QPaneLayerSelectionState` or `None` emitted when selected layer identity changes.
- QPane.CONTROL_MODE_SELECT_RECTANGLE — Built-in rectangular pixel-selection tool ID.
- QPane.CONTROL_MODE_SELECT_ELLIPSE — Built-in elliptical pixel-selection tool ID.
- QPane.CONTROL_MODE_SELECT_LASSO — Built-in freeform pixel-selection tool ID.
- QPane.pixelSelectionState — Return the active composition's detached selection snapshot.
- QPane.setPixelSelection — Combine caller-provided grayscale coverage at explicit scene-coordinate bounds.
- QPane.clearPixelSelection — Clear selection coverage in the active composition.
- QPane.selectAllPixels — Select the active scene's finite canvas bounds.
- QPane.invertPixelSelection — Invert coverage inside the active scene's finite canvas bounds.
- qpane.QPanePixelSelectionState — Detached scene ID, revision, optional bounds, and grayscale coverage for one composition selection.
	- QPanePixelSelectionState.scene_id — Public active-scene identity.
	- QPanePixelSelectionState.revision — Monotonic selection revision for that scene.
	- QPanePixelSelectionState.bounds — Optional scene-coordinate coverage bounds.
	- QPanePixelSelectionState.coverage — Optional detached grayscale coverage image.
	- QPanePixelSelectionState.has_selection — Whether nonzero selection coverage is active.
- qpane.QPaneFloatingPixelEditState — Detached unresolved-fragment source identity, cut/copy mode, local offset, and scene bounds.
	- QPaneFloatingPixelEditState.scene_id — Public scene owning the floating edit.
	- QPaneFloatingPixelEditState.source_layer_id — Layer from which pixels were lifted.
	- QPaneFloatingPixelEditState.mode — Whether resolution cuts or copies source pixels.
	- QPaneFloatingPixelEditState.offset — Integer source-local movement from the lift origin.
	- QPaneFloatingPixelEditState.bounds — Current scene-coordinate content-selection bounds.

### View State
- QPane.zoomChanged — Float payload emitted when viewport zoom changes; seeds once during initialization so listeners can prime UI without peeking at the viewport.
- QPane.viewportRectChanged — `QRectF` payload emitted when the physical viewport size or device pixel ratio changes (resize/show/screen hop) so overlays and tiles stay aligned.

### Masks
- QPane.maskSaved — `qpane.MaskSavedPayload` (`mask_id`, `path`) emitted after a mask autosave completes.
- QPane.maskUndoStackChanged — Mask UUID (`uuid.UUID`) payload emitted when a mask undo stack mutates.
- QPane.rasterBoundsRequestCompleted — `(request_id, scene_id, layer_id, succeeded, message)` emitted exactly once when a raster bounds request succeeds, is replaced, becomes stale, or fails.
- QPane.placedAssetRequestCompleted — `(request_id, scene_id, layer_id, succeeded, message)` emitted exactly once for accepted link, relink, refresh, and rasterization work.

### Diagnostics
- QPane.diagnosticsOverlayToggled — Bool payload emitted when the diagnostics HUD visibility changes.
- QPane.diagnosticsDomainToggled — `(domain: str, enabled: bool)` payload emitted when a diagnostics domain toggles.

### SAM
- QPane.samCheckpointStatusChanged — `(status: str, path: Path)` payload emitted during SAM checkpoint readiness changes (`downloading`, `ready`, `failed`, `missing`); `"downloading"` also covers integrity verification when a hash is required.
- QPane.samCheckpointProgress — `(downloaded: int, total: int | None)` payload emitted during SAM checkpoint downloads.

See also: [Catalog and Navigation](catalog-and-navigation.md), [Diagnostics](diagnostics.md), and [Masks and SAM](masks-and-sam.md).

## Painting

- `qpane.BrushOperation` describes paint or erase semantics. `BrushOperation.PAINT` deposits target-appropriate color or coverage; `BrushOperation.ERASE` removes alpha or coverage.
- `qpane.BrushDynamics` is the immutable pointer-response and jitter configuration retained by a preset. It includes pressure size/opacity response, pressure floor and gamma, deterministic position, size, and angle jitter, plus rotation, tilt, and tangential-pressure mappings.
  - `BrushDynamics.pressure_size` and `BrushDynamics.pressure_opacity` control how strongly pressure affects diameter and opacity.
  - `BrushDynamics.minimum_pressure_ratio` and `BrushDynamics.pressure_gamma` define the normalized pressure curve.
  - `BrushDynamics.position_jitter`, `BrushDynamics.size_jitter`, and `BrushDynamics.angle_jitter` are deterministic seeded variations.
  - `BrushDynamics.rotation_angle` and `BrushDynamics.tilt_angle` blend tablet orientation into tip angle; `BrushDynamics.tangential_opacity` maps barrel pressure into deposited opacity.
- `qpane.BrushPreset` is the immutable active brush configuration: name, size, hardness, opacity, flow, spacing, smoothing, angle, procedural texture, and `BrushDynamics`.
  - `BrushPreset.name` identifies the preset in host UI.
  - `BrushPreset.size` is the nominal target-pixel diameter.
  - `BrushPreset.hardness` controls edge falloff.
  - `BrushPreset.opacity` caps deposited opacity and `BrushPreset.flow` controls per-dab accumulation.
  - `BrushPreset.spacing` controls dab frequency along motion.
  - `BrushPreset.smoothing` controls source-neutral pointer-path stabilization.
  - `BrushPreset.angle` is the nominal tip rotation.
  - `BrushPreset.texture_strength`, `BrushPreset.texture_scale`, and `BrushPreset.texture_seed` define deterministic procedural grain whose generated tips are byte-bounded by QPane's shared cache budget.
  - `BrushPreset.dynamics` contains the immutable `BrushDynamics` mapping.
- `qpane.PaintTargetKind` identifies the destination category. `PaintTargetKind.LAYER` addresses a paint-capable layer; `PaintTargetKind.PIXEL_SELECTION` addresses the active composition's selection coverage.
- `qpane.QPanePaintTargetState` is the detached active-target snapshot.
  - `QPanePaintTargetState.scene_id` is the public active-scene identity.
  - `QPanePaintTargetState.kind` is the target category.
  - `QPanePaintTargetState.layer_id` is the layer instance for a layer target, otherwise `None`.
  - `QPanePaintTargetState.source_kind` reports `"raster"`, `"mask"`, or `None` for composition selection coverage.
- `QPane.createPaintLayer` creates a transparent editable RGBA layer, selects it, and makes it the paint target. Its initial dimensions default to the active scene and its extent policy defaults to unbounded sparse storage.
- `QPane.paintTargetState` returns the active detached target or `None`.
- `QPane.setPaintTarget` selects a pixel-editable mask or RGBA layer in the active scene.
- `QPane.setPixelSelectionPaintTarget` routes brush coverage to the one authoritative composition selection.
- `QPane.clearPaintTarget` cancels unresolved brush work and clears its destination.
- `QPane.brushPreset` and `QPane.setBrushPreset` query and replace the complete immutable brush configuration.
- `QPane.setBrushSize` changes only the size field while retaining the rest of the active preset.
- `QPane.paintColor` and `QPane.setPaintColor` query and replace the detached color used by RGBA targets. Coverage targets retain coverage semantics.
- `QPane.paintTargetChanged` emits `QPanePaintTargetState` or `None` after target changes.
- `QPane.brushPresetChanged` emits the new `BrushPreset` after preset or size changes.
- `QPane.paintColorChanged` emits a detached `QColor` after color changes.

## Vector Documents

- `qpane.VectorObjectKind` identifies semantic objects: `VectorObjectKind.PATH`, `VectorObjectKind.SHAPE`, and the text-ready `VectorObjectKind.TEXT` category.
- `qpane.VectorShapeKind` retains parametric geometry as `VectorShapeKind.RECTANGLE` or `VectorShapeKind.ELLIPSE` until an explicit future conversion.
- `qpane.VectorPathCommandKind` defines durable path operations: `VectorPathCommandKind.MOVE`, `VectorPathCommandKind.LINE`, `VectorPathCommandKind.QUADRATIC`, `VectorPathCommandKind.CUBIC`, and `VectorPathCommandKind.CLOSE`.
- `qpane.VectorPathCommand` stores one operation in `VectorPathCommand.kind` and its detached ordered control points in `VectorPathCommand.points`.
- `qpane.VectorFillRule` selects `VectorFillRule.WINDING` or `VectorFillRule.EVEN_ODD` fill behavior.
- `qpane.VectorStrokeJoin` selects `VectorStrokeJoin.MITER`, `VectorStrokeJoin.ROUND`, or `VectorStrokeJoin.BEVEL`; `qpane.VectorStrokeCap` selects `VectorStrokeCap.FLAT`, `VectorStrokeCap.ROUND`, or `VectorStrokeCap.SQUARE`.
- `qpane.VectorNodeRole` identifies an editable anchor as `VectorNodeRole.ANCHOR`, a Bézier control point as `VectorNodeRole.CONTROL`, or a parametric-shape bounds handle as `VectorNodeRole.BOUNDS`.
- `qpane.VectorStyle` is the immutable object style. `VectorStyle.fill` and `VectorStyle.stroke` are detached colors or `None`; `VectorStyle.stroke_width`, `VectorStyle.opacity`, `VectorStyle.join`, `VectorStyle.cap`, `VectorStyle.dash_pattern`, and `VectorStyle.fill_rule` retain the remaining render semantics.
- `qpane.QPaneVectorObjectState` exposes `QPaneVectorObjectState.object_id`, `QPaneVectorObjectState.kind`, `QPaneVectorObjectState.bounds`, `QPaneVectorObjectState.transform`, `QPaneVectorObjectState.style`, `QPaneVectorObjectState.shape_kind`, and `QPaneVectorObjectState.path` without exposing mutable document authority.
- `qpane.QPaneVectorDocumentState` exposes `QPaneVectorDocumentState.scene_id`, `QPaneVectorDocumentState.layer_id`, `QPaneVectorDocumentState.vector_id`, `QPaneVectorDocumentState.revision`, and ordered `QPaneVectorDocumentState.objects`.
- `qpane.QPaneVectorSelectionState` exposes independent object selection through `QPaneVectorSelectionState.scene_id`, `QPaneVectorSelectionState.layer_id`, and ordered `QPaneVectorSelectionState.object_ids`.
- `qpane.QPaneVectorMaskState` exposes a target layer's semantic mask through `QPaneVectorMaskState.scene_id`, `QPaneVectorMaskState.layer_id`, `QPaneVectorMaskState.vector_id`, optional `QPaneVectorMaskState.object_ids`, target-local `QPaneVectorMaskState.transform`, and `QPaneVectorMaskState.inverted`.
- `qpane.QPaneVectorNodeSelectionState` exposes the selected control point through `QPaneVectorNodeSelectionState.scene_id`, `QPaneVectorNodeSelectionState.layer_id`, `QPaneVectorNodeSelectionState.object_id`, stable `QPaneVectorNodeSelectionState.node_index`, and `QPaneVectorNodeSelectionState.role`.
- `QPane.createVectorLayer` creates an empty movable vector document at the active scene origin. `QPane.vectorDocumentState` returns its detached semantic revision.
- `QPane.addVectorShape` adds a parametric shape and `QPane.addVectorPath` adds explicit commands. Both produce one stable object UUID and one chronological edit.
- `QPane.updateVectorObject` changes style and/or affine object transform atomically. `QPane.removeVectorObject` and `QPane.reorderVectorObject` retain exact undo/redo behavior.
- `QPane.setSelectedVectorObjects`, `QPane.vectorSelectionState`, and `QPane.clearVectorSelection` operate independently of layer and pixel selection. `QPane.vectorSelectionChanged` emits the detached state or `None`.
- `QPane.vectorNodeSelectionState` reports the direct-selection tool's control point independently of object, layer, and pixel selection. `QPane.vectorNodeSelectionChanged` emits the detached state or `None`.
- `ControlMode.VECTOR_SHAPE` and `QPane.CONTROL_MODE_VECTOR_SHAPE` identify the built-in parametric shape tool. `ControlMode.VECTOR_PATH` and `QPane.CONTROL_MODE_VECTOR_PATH` identify the explicit path-construction tool. `ControlMode.VECTOR_NODE` and `QPane.CONTROL_MODE_VECTOR_NODE` identify direct node editing.
- `QPane.vectorToolShape` and `QPane.setVectorToolShape` query and change the last-used parametric shape kind. `QPane.vectorToolStyle` and `QPane.setVectorToolStyle` query and change the shared immutable creation style.
- `QPane.vectorToolOptionsChanged` emits the active `VectorShapeKind` and `VectorStyle` so contextual controls remain synchronized.
- `QPane.convertVectorToPixelSelection` asynchronously derives soft scene-space coverage from exact vector fill, stroke, object opacity, object transforms, and the layer transform. Passing object IDs chooses them explicitly; otherwise an object selection on the layer takes precedence over the whole document. The resulting edit uses `PixelSelectionMode` and the existing pixel-selection history.
- `QPane.rasterizeVectorLayer` asynchronously renders an explicit pixel size, creates an editable premultiplied RGBA source, and atomically replaces only that vector instance while preserving its displayed affine geometry. Undo restores the semantic vector source.
- `QPane.vectorRequestCompleted` emits request UUID, public scene UUID, layer UUID, the `pixel-selection`, `editable-raster`, or `text-paths` operation string, success, and a terminal message exactly once for accepted work.
- `QPane.setVectorMask` atomically removes a visible vector layer instance and retains its semantic document as a target layer effect. It can use every object or an explicit object subset and can invert reveal geometry. `QPane.vectorMaskState` inspects the effect, while `QPane.clearVectorMask` removes it chronologically. `QPane.vectorDocumentState` and vector object edits accept the masked target layer so the same paths remain editable without a parallel mask document.
## Semantic vector text

`ControlMode.VECTOR_TEXT` and `QPane.CONTROL_MODE_VECTOR_TEXT` activate in-place
semantic text creation and editing on the selected vector layer. The public
text values preserve Unicode and authoring intent through
`qpane.VectorTextContent`: `VectorTextContent.text`,
`VectorTextContent.style`, `VectorTextContent.spans`, and
`VectorTextContent.paragraph`; `qpane.VectorTextStyle` supplies
`VectorTextStyle.families`,
`VectorTextStyle.font_size`, `VectorTextStyle.weight`,
`VectorTextStyle.italic`, `VectorTextStyle.letter_spacing`, and
`VectorTextStyle.color`; `qpane.VectorTextSpan` supplies `VectorTextSpan.start`, `VectorTextSpan.length`, and
`VectorTextSpan.style`; and `qpane.VectorParagraphStyle` supplies `VectorParagraphStyle.alignment`,
`VectorParagraphStyle.direction`, and `VectorParagraphStyle.line_height`.

Paragraph policy uses `qpane.VectorTextAlignment` through `VectorTextAlignment.LEFT`,
`VectorTextAlignment.CENTER`, `VectorTextAlignment.RIGHT`, and
`VectorTextAlignment.JUSTIFY`, with `qpane.VectorTextDirection` through `VectorTextDirection.AUTO`,
`VectorTextDirection.LEFT_TO_RIGHT`, or
`VectorTextDirection.RIGHT_TO_LEFT`. `QPane.addVectorText` creates text,
`QPane.updateVectorText` atomically changes its content or box, and
`QPaneVectorObjectState.text` exposes the retained semantic value.

`QPane.beginVectorTextEdit`, `QPane.vectorTextEditState`,
`QPane.commitVectorTextEdit`, and `QPane.cancelVectorTextEdit` control one
in-place session. `qpane.QPaneVectorTextEditState` exposes `QPaneVectorTextEditState.scene_id`,
`QPaneVectorTextEditState.layer_id`, `QPaneVectorTextEditState.object_id`,
`QPaneVectorTextEditState.text`, `QPaneVectorTextEditState.cursor`, and
`QPaneVectorTextEditState.is_new` describe it; `QPane.vectorTextEditChanged`
publishes changes. `QPane.vectorTextStyle`, `QPane.setVectorTextStyle`,
`QPane.vectorParagraphStyle`, and `QPane.setVectorParagraphStyle` control the
contextual options.

`QPane.vectorTextFontResolutions` returns `QPaneTextFontResolution` entries.
Each exposes `QPaneTextFontResolution.requested_families`,
`QPaneTextFontResolution.resolved_family`, and
`QPaneTextFontResolution.exact_match`, so hosts can explain font fallback
without treating the resolved platform font as document authority.
`QPane.convertVectorTextToPaths` begins non-blocking conversion of one semantic
text object into color-preserving editable glyph outlines. It returns a request
UUID; `QPane.vectorRequestCompleted` reports the `text-paths` terminal outcome,
and a successful conversion lands as one undoable edit.
