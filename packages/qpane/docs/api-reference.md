# QPane public API

## Viewer

- `QPane` is the focused PySide6 viewer facade.
- `QPane(execution_policy=...)` configures an owned standalone runtime, while
  `QPane(execution_runtime=...)` participates in a host-owned runtime.
- `Config` owns detached viewer and rendering settings.
- `CacheMode`, `ZoomMode`, and `ViewportZoomMode` describe cache and viewport
  behavior.
- `PanelHitTest` carries exact panel, scene, and source coordinates.

### Viewer facade

- `QPane.sceneChanged` publishes each accepted immutable scene replacement.
- `QPane.zoomChanged` publishes the settled viewport scale after navigation.
- `QPane.controlModeChanged` publishes the newly active viewer-tool identifier.
- `QPane.dragOutRequested` publishes completed built-in drag-out intent.
- `QPane.catalogChanged` publishes structural catalog changes for host models.
- `QPane.catalogSelectionChanged` publishes the selected entry or `None`.
- `QPane.comparisonChanged` publishes the current immutable comparison state.
- `QPane.linkGroupsChanged` and `QPane.placeholderChanged` publish catalog-view
  and empty-viewer policy state.
- `QPane.diagnosticsOverlayToggled` publishes live HUD visibility changes.
- `QPane.diagnosticsDomainToggled` publishes a domain identifier and enabled state.
- `QPane.CONTROL_MODE_PANZOOM` and `QPane.CONTROL_MODE_CURSOR` identify the
  built-in tools.
- `QPane.setScene`, `QPane.scene`, `QPane.setImage`, and `QPane.clear` submit
  or inspect ordinary render content. `QPane.currentImage` and
  `QPane.currentImagePath` expose the presented base raster, and
  `QPane.copyCurrentImageToClipboard` performs the standard viewer copy action.
- `QPane.setZoomFit` frames the active scene in the viewport.
- `QPane.setZoom1To1` selects native logical-pixel scale around an optional anchor.
- `QPane.applyZoom` clamps and applies an explicit pointer-anchored scale.
- `QPane.currentZoom` returns the settled viewport scale.
- `QPane.currentPan` returns a detached viewport translation.
- `QPane.setPan` applies an explicit viewport translation.
- `QPane.setPanZoomLocked` and `QPane.panZoomLocked` configure navigation
  policy.
- `QPane.applySettings` atomically applies a detached `Config`.
- `QPane.settings` exposes the viewer's current detached configuration snapshot.
- `QPane.calculateRenderPlan` returns a detached plan for the active presentation.
- `QPane.physicalViewportRect` returns the device-pixel render viewport.
- `QPane.panelHitTest` projects one panel position through authoritative viewport geometry.
- `QPane.coordinateSystem` returns the typed authoritative scene/layer
  projection service.
- `QPane.minimumSizeHint` returns the viewer's useful minimum widget size.

### Catalog and comparison

- `ViewerCatalog` owns ordered reusable image resources and active selection.
- `ViewerCatalogEntry` carries one `RasterSource`, label, path, and stable ID.
- `QPane.catalog` returns the ordered public viewer resource owner.
- `QPane.addImage` creates and optionally selects one reusable raster catalog entry.
- `QPane.selectCatalogImage` restores the one-image presentation for a stable entry ID.
- `QPane.selectNextImage` advances through catalog order with wraparound.
- `QPane.selectPreviousImage` moves backward through catalog order with wraparound.
- `QPane.removeCatalogImage` removes and returns one catalog entry.
- `QPane.clearCatalog` removes all catalog resources and returns to empty presentation.
- `LinkedGroup` describes identities that share normalized viewport state.
- `QPane.linkedImageGroups` returns the current immutable link definitions.
- `QPane.setLinkedImageGroups` replaces validated custom link groups.
- `QPane.setAllImagesLinked` links or unlinks the complete catalog conveniently.
- `ViewerPrefetchSnapshot` and `QPane.catalogPrefetchState` expose bounded
  neighboring pyramid work.
- `ViewerPlaceholderState` describes asynchronous and active empty-viewer presentation.
- `QPane.placeholderState` returns the current immutable placeholder lifecycle snapshot.
- `QPane.setPlaceholderImage` installs an already-decoded host placeholder.
- `ComparisonOrientation` identifies vertical and horizontal reveals.
- `ComparisonState` describes the selected comparison source and normalized
  split.
- `ComparisonDividerState` carries projected, detached divider geometry.
- `QPane.compareWithNextImage` reveals the next catalog source over the selection.
- `QPane.setComparisonImage` chooses an explicit catalog comparison source.
- `QPane.clearComparison` disables the active reveal without changing selection.
- `QPane.setComparisonSplit` applies a normalized position and optional orientation.
- `QPane.comparisonState` returns the immutable comparison setup.
- `QPane.setComparisonDividerInteractive` enables or disables built-in divider dragging.
- `QPane.comparisonDividerInteractive` reports the current divider input policy.
- `QPane.comparisonDividerState` returns detached projected divider geometry.

### Diagnostics and overlays

- `Diagnostics` is the live source-neutral diagnostics broker.
- `DiagnosticsSnapshot` is one immutable gathered snapshot.
- `DiagnosticRecord` is one formatted diagnostics row.
- `QPane.diagnostics` returns the live source-neutral diagnostics broker.
- `QPane.gatherDiagnostics` returns one detached diagnostic snapshot.
- `QPane.createStatusOverlay` creates a host-placeable live HUD widget.
- `QPane.setDiagnosticsOverlayEnabled` changes built-in HUD visibility.
- `QPane.diagnosticsOverlayEnabled` reports whether the built-in HUD is visible.
- `QPane.diagnosticsDomains` lists available detail-domain identifiers.
- `QPane.setDiagnosticsDomainEnabled` changes one validated detail domain.
- `QPane.diagnosticsDomainEnabled` reports one detail-domain state.
- `QPane.registerDiagnosticsProvider` adds a host producer.
- `QPane.registerOverlay` adds uniquely named base-content host chrome.
- `QPane.unregisterOverlay` removes named base-content chrome when present.
- `QPane.registerSceneOverlay` adds host chrome with projected layer context.
- `QPane.unregisterSceneOverlay` removes named scene chrome when present.
- `SceneSnapshotOverlayState` describes current scene geometry for a scene
  overlay.
- `SceneSnapshotOverlayLayer` describes one ordered projected scene layer.
- `LayerPresentationEffectKind` identifies content tint, content outline,
  content glow, and rendered-bounds treatments.
- `LayerPresentationStyle` is an immutable effect style; use `tint`, `outline`,
  `glow`, and `bounds` to construct validated values.
- `LayerPresentationEffect` is the ordered, scene-scoped registration snapshot.
- `QPane.addLayerPresentationEffect` adds a transient treatment to one rendered layer.
- `QPane.updateLayerPresentationEffect` replaces a registered treatment style.
- `QPane.removeLayerPresentationEffect` removes one treatment by stable effect ID.
- `QPane.clearLayerPresentationEffects` removes treatments matching optional scene and layer filters.
- `QPane.layerPresentationEffects` returns ordered immutable treatment registrations.

## Tool input SDK

- `PointerDeviceKind`, `PointerPhase`, and `PointerSample` provide immutable,
  device-neutral observations for viewer and editor tools.
- `ToolInputProfile` declares whether a tool accepts navigation, touch, tablet,
  or preview input.
- `TouchGestureArena` and `TouchGestureKind` provide deterministic arbitration
  between direct tools and viewport navigation.
- `TouchNavigationPort` and `TouchNavigationSession` apply device-independent
  pan, pinch, and inertial translation to a compatible viewport.
- `PointerInputPort` supplies source-neutral tool, viewport, and gesture
  collaborators.
- `PointerInputController` normalizes mouse, touch, pen, palm rejection, and
  synthesized-event suppression.
- `ViewerTool` is the supported base for viewer and editor tool extensions.
- `ViewerToolSignals` lets a tool request navigation, repaint, cursor, or
  drag-out work without mutating the host.
- `ToolManager` owns registration, activation, dispatch, and teardown.
- `ToolManagerSignals` publishes active-tool requests to the widget host.
- `PanZoomTool` implements QPane's built-in navigation behavior.
- `CursorTool` implements pointer selection and drag-out behavior.
- `NavigationInteractionPort` and `CursorInteractionPort` are their focused
  activation boundaries.
- `QPane.registerTool` adds one viewer-tool factory under a stable mode ID.
- `QPane.unregisterTool` removes an inactive custom tool registration.
- `QPane.setControlMode` activates one registered viewer tool.
- `QPane.controlMode` returns the active mode identifier.
- `QPane.availableControlModes` returns all registered mode identifiers.

## Scene SDK

- `RenderScene` is an immutable canvas and ordered layer collection.
- `RenderLayer` places one reusable raster, vector, or hybrid source.
- `LayerTransform` is the six-coefficient affine local-to-scene transform.
- `LayerClip` and `ClipCoordinateSpace` define optional clipping.
- `BlendMode` defines layer compositing.
- `RasterBounds` defines signed integer source-local bounds.

## Raster SDK

- `RasterSource` describes one reusable revisioned raster.
- `RasterSourceProvider` supplies immediate source pixels.
- `SparseRasterSourceProvider` supplies visible sparse patches.
- `RasterHitTestProvider` answers source-local content hit tests.
- `RasterProductPolicy` describes settled or volatile product reuse.
- `RasterSourcePatch` carries bounded revision damage.

## Vector SDK

- `VectorSource` presents one immutable semantic document revision.
- `VectorDocument` owns immutable ordered vector objects.
- `VectorObject` is one semantic object with stable identity.
- `VectorObjectKind` distinguishes paths, shapes, and text.
- `VectorShapeKind` identifies parametric rectangle and ellipse shapes.
- `VectorPathCommand` and `VectorPathCommandKind` describe path geometry.
- `VectorStyle` defines fill, stroke, and opacity.
- `VectorFillRule`, `VectorStrokeCap`, and `VectorStrokeJoin` define path style.
- `VectorTextContent` retains Unicode text and semantic style spans.
- `VectorTextStyle` defines character presentation.
- `VectorTextSpan` applies character style to a text range.
- `VectorParagraphStyle` defines paragraph layout.
- `VectorTextAlignment` and `VectorTextDirection` define paragraph policy.

## Hybrid SDK

- `HybridSource` presents one immutable hybrid document and presentation
  revision.
- `HybridDocument` owns ordered raster and semantic-vector coverage
  primitives.
- `HybridRasterPrimitive` references bounded worker-safe raster coverage.
- `HybridRasterSampler` samples exact source regions into detached grayscale coverage.
- `HybridVectorPrimitive` retains one semantic vector contribution with an
  independent transform and feather radius.
- `HybridCombineMode` defines replace, add, subtract, and intersect coverage
  algebra.
- `HybridPresentationStyle` defines late color and optional outline
  presentation.

## Advanced integration SDK

The following values live in focused `qpane.sdk` namespaces for products that
participate directly in QPane's engine lifecycle. Ordinary viewers use the
root facade and declarative SDK above.

### Scene integration

- `SceneDescriptor`, `SceneKind`, `LayerDescriptor`, and `LayerKind` describe immutable compiled scene structure.
- `LayerPlacement`, `LayerTransform`, and `RasterBounds` retain exact placement and source-local geometry.
- `BlendMode`, `LayerClip`, and `ClipCoordinateSpace` define source-neutral presentation policy.
- `LayerContentCapabilities`, `LayerInteractionPolicy`, and `LayerHitTest` carry generic behavior and hit-test policy.
- `SceneProviderRegistry`, `SceneContribution`, and `SourceCapabilityRegistry` compose independent scene and source owners.
- `LayerSourceCapabilities` routes renderer capabilities for each supported `LayerSourceReference` value.
- `SceneRenderItem`, `RasterLayerRenderItem`, `SampledLayerRenderItem`, `SampledTileRenderData`, and `SceneLayerHitTestResult` are detached presentation products.
- `TransientRasterContribution`, `TransientRasterResolvedContribution`, `TransientSampledResolvedContribution`, and `TransientRasterTransformContribution` carry editor-owned raster edits through normal scene presentation.
- `SceneLayerAssetKey` separates reusable source identity from placed layer identity.
- `RasterPresentation`, `RasterProductPolicy`, and `RasterSourcePatch` describe sampling, reuse, and bounded damage.
- `AffineTransformGeometry`, `TransformOperation`, and `TransformOperationKind` own exact affine interaction math.
- `TransformHandle`, `TransformLocalBounds`, and `TransformModifiers` describe one transform gesture without rounded coordinates.
- `LayerEffectReference` and `LayerEffectRenderRegistry` connect generic layer effects to the compositor.
- `SceneRegionRasterizer` renders a bounded transformed `SceneDescriptor`
  region across raster, vector, and hybrid layers without materializing the
  complete scene.
- `SceneLayerRenderScope` selects an optional layer subset for a bounded scene
  sample while preserving visibility and stack order.
- `RasterLayerRegionOverride` supplies revision-specific pixels for selected
  raster layers during one bounded scene sample.
- `RenderTileRequest` describes one stable-grid source rectangle and its
  antialiasing bleed rectangle.
- `RenderTileProduct` carries one detached sampled tile and exact draw
  geometry.
- `RenderTileBatchSource` lets an immutable source revision render a complete
  request batch away from the GUI thread.
- `RegionSampleSource` lets nested rendering sample an arbitrary source-local
  rectangle at a requested output size.

### Renderer, cache, and scheduling

- `View`, `Renderer`, `RenderingPresenter`, and `ViewportZoomMode` coordinate viewport state and frame publication.
- `PanelPoint`, `ScenePoint`, `LayerLocalPoint`, and `LayerSourcePoint` identify
  non-interchangeable coordinate domains.
- `SceneCoordinateSystem` projects typed points through current viewport,
  scene, layer, and raster-origin geometry.
- `SceneCoordinateProjection` and `LayerCoordinateProjection` are immutable
  per-frame projection values for advanced renderer integrations.
- `PyramidManager` owns multiresolution product scheduling and cache-backed
  source pyramids.
- `rasterize_layer` scales one detached raster source under a caller-provided
  cancellation token.
- `rasterize_region` samples one bounded `RegionSampleSource` under a
  caller-provided cancellation token.
- `CacheRegistry`, `CacheCoordinator`, and `CachePriority` coordinate byte-bounded product stores.
- `EvictableCacheConsumer`, `KeyedCacheConsumer`, and `cache_detail_provider` connect stores to eviction and diagnostics.
- `ExecutionRuntime` admits work once, while `ExecutionScope` binds accepted
  work to the lifetime of the widget, document runtime, or host service that
  requested it. `ExecutionScope.open_finalization_scope()` reserves
  caller-closed cleanup ownership that can outlive its originating scope but
  never the shared runtime. Finalization submissions remain pending through
  temporary backend saturation.
- `ExecutionRequest` carries one detached callable and semantic requirements.
  Its `ExecutionHandle` exposes cancellation, progress observation, lifecycle
  state, timings, and a single terminal outcome.
- `ExecutionRequirements` describes scheduling facts through
  `ExecutionResource`, `ExecutionUrgency`, and `ExecutionLeaseRelease`.
  Affinity, exclusivity, concurrency, and retained-byte fields preserve hard
  constraints without naming host queues.
- `ExecutionBackend` is the physical scheduling protocol.
  `ExecutionBackendCapabilities` reports which hard requirements it honors,
  `ExecutionJob` is the one runtime-owned activation, and `BackendSubmission`
  cancels work that remains physically pending.
- `CancellationToken` gives worker code cooperative cancellation.
  `ExecutionTaskContext` combines that token with one typed
  `ExecutionProgressReporter`, whose updates are coalesced before observer
  delivery.
- `ExecutionOutcome` records the terminal `ExecutionState`, optional result,
  and optional `ExecutionFailurePhase`. `ExecutionTimings` separates queue,
  worker, adoption, and settlement time.
- `ExecutionRejected` reports pre-admission failure using a stable
  `ExecutionRejectionReason`. `ExecutionTagValue` is the safe immutable value
  type accepted by diagnostic request tags.
- `CompletionDispatcher` defines owner-context delivery.
  `InlineDispatcher` serves deterministic non-Qt consumers, while
  `QtOwnerDispatcher` posts to a living receiver and acknowledges delivery
  discarded during teardown.
- `DefaultExecutionPolicy` configures the bounded runtime returned by
  `create_default_execution_runtime`. `create_native_execution_runtime`
  returns a disjoint runtime for stable thread-affine native work.
- `ExecutionSnapshot` is a detached utilization sample.
  `ExecutionDiagnosticsProvider` exposes current samples, and
  `DiagnosticsSubscription` disconnects one observer without affecting
  sibling observers.
- `execution_summary_records` and `execution_detail_records` translate runtime
  snapshots into standard diagnostics rows without coupling a host backend to
  QPane's overlay.
- `DelayHandle` cancels one pending delay, and `DelayScheduler` defines delay
  ownership. `QtDelayScheduler` schedules producer retry decisions on the
  receiver's Qt event loop.
- `RetryContext` describes one retained producer retry, `RetryPolicy` computes
  its bounded delay, and `RetryController` coalesces the newest payload after
  structured rejection. `RetrySchedulingError` reports a delay that could not
  be installed.
- `RetryCategorySnapshot` and `RetrySnapshot` expose bounded retry state.
  `retry_summary_records` and `retry_detail_records` translate those snapshots
  into the same diagnostics presentation used by execution state.

### Configuration, features, and diagnostics

- `Config`, `CacheSettings`, `FeatureAwareConfig`, `TileSizeSetting`, and `diff_config_fields` define and compare renderer settings. `TileSizeSetting` is a strict positive integer or the `"auto"` physical-viewport policy.
- `FeatureConfigDescriptor`, `ConfigFeatureRegistry`, `iter_descriptors`, and `require_feature_slice` support typed configuration extensions.
- `FeatureDefinition`, `FeatureRegistry`, `resolve_feature_order`, and `FeatureInstallError` coordinate optional integration slices.
- `Diagnostics`, `DiagnosticsRegistry`, `DiagnosticsProvider`, and `DiagnosticsSnapshot` own live and gathered diagnostics.
- `DiagnosticRecord` and `DiagnosticsDomain` provide stable diagnostic presentation values.
- `OverlayRegistry`, `OverlayDrawFn`, `SceneOverlayDrawFn`, and `OverlayState` define cheap host paint extensions.
- `DiagnosticsOverlayController` and `create_status_overlay` provide QPane's standard host-placeable diagnostics chrome.

### Catalog, comparison, and viewer values

- `ViewerCatalog` owns the ordered raster-source list used by QPane's
  ready-made image-review workflow.
- `ViewerCatalogEntry` carries one reusable `RasterSource` plus its label and
  optional path. It is a viewer row, not a document or editable resource.
- `CompareDividerInteraction` handles source-neutral comparison-divider input for custom viewer hosts.
- `ComparisonChange` carries one immutable comparison interaction observation.
- `ComparisonChangeKind` identifies hover, drag, and split changes.
- `ComparisonState`, `ComparisonDividerState`, and `ComparisonOrientation` are detached comparison snapshots.
- `LinkedGroup`, `PlaceholderScaleMode`, `ZoomMode`, and `CacheMode` describe stable viewer policies.
- `SceneSnapshotOverlayState` and `SceneSnapshotOverlayLayer` provide prepared scene-aware overlay geometry.

### Raster and vector helpers

- `AffineImageResampler` performs bounded worker-side affine sampling.
- `qimage_to_numpy_argb32` and `qimage_to_numpy_grayscale8` return detached arrays.
- `qimage_to_numpy_const_view_argb32` exposes normalized premultiplied BGRA pixels; `qimage_to_numpy_const_view_bgra32` preserves compatible 32-bit storage to avoid needless large-image conversion.
- `qimage_to_numpy_view_argb32` exposes a writable scoped zero-copy view;
  `qimage_to_numpy_view_grayscale8` exposes a read-only scoped zero-copy view.
- `present_hybrid_pixels` applies the same color and optional outline
  presentation used by sampled hybrid layers.
- `present_hybrid_sample` evaluates and presents one hybrid document over an
  explicit source rectangle and output size while preserving its stable
  source-space sampling grid.
- `numpy_to_qimage_argb32`, `numpy_to_qimage_grayscale8`, `numpy_to_qimage_argb32_at_size`, and `numpy_to_qimage_grayscale8_at_size` create validated QImage values.
- `VectorPresentationSnapshot`, `SemanticTextLayoutCache`, `TextFontResolution`, and `text_caret_rect` share immutable vector presentation and text layout.
- `VectorNodeRole`, `object_path`, and `object_contains` provide semantic node and geometry queries.
- `painted_document_path` and `draw_vector_document` share authoritative painted vector geometry.

### Widget and system helpers

- `apply_widget_defaults`, `copyToClipboard`, and `maybeStartDrag` provide standard viewer widget behavior.
- `drag_out_image` and `is_drag_out_allowed` separate drag payload construction from host policy.
- `DragSubject` identifies content selected by a drag gesture.
- `OutboundMimeItem` carries one arbitrary MIME value as detached bytes.
- `OutboundDragPayload` carries URLs, text, custom values, and a preview.
- `OutboundMimeProvider` materializes host payloads synchronously or later.
- `OutboundDragController` owns cancellation, stale-result rejection, GUI
  delivery, and native execution.
- `SystemHeadroomSample` and `sample_system_headroom` provide detached
  memory-pressure measurements.

### Inspection and target layout

- `InspectionTarget` identifies one native coordinate space.
- `InspectionRegion` stores a source-neutral visible rectangle as normalized center and span values.
- `InspectionViewState` retains a normalized visible region and target-local
  zoom interpretation.
- `InspectionZoomMode` preserves whether a target view is fitted, native scale, or custom.
- `InspectionUpdate` carries one generation-guarded linked-view observation to a subscribed target.
- `InspectionObserver` is the callback contract used to receive immutable inspection updates.
- `ProjectedViewport` contains the target-local zoom, pan, and zoom interpretation produced from normalized inspection.
- `InspectionStateStore` owns independent state, explicit link groups, and
  generation-guarded observation.
- `capture_inspection` and `project_inspection` convert between normalized
  inspection and target viewport transforms.
- `ViewTargetSpec` identifies one independently rendered target and its native dimensions.
- `ViewTargetFrame` contains a responsive-grid cell and its aspect-preserving content rectangle.
- `ResponsiveGridPolicy` sets minimum cell width, spacing, and an optional column limit.
- `ResponsiveGridSnapshot` provides stable frames, hit testing, visible-target queries, prefetch order, and bounded layout damage.
- `ResponsiveGridLayout` returns DPR-stable target cells, content frames, hit
  testing, visibility, damage, and prefetch order.
- `TargetComparisonSnapshot` contains exact clips and a physical-pixel-aligned divider for two targets.
- `TargetComparisonLayout` returns two clips and one exact physical divider
  boundary for independent target comparison.

### Native outbound dragging

- `OutboundMimeItem` carries one detached arbitrary MIME value.
- `OutboundDragPayload` combines custom MIME values, URLs, text, and an optional preview for one native drag.
- `DragCompletion` is the one-shot callback used by a host MIME provider.
- `DragCancellation` lets deferred materialization stop without blocking the GUI thread.
- `execute_outbound_drag` turns a fully materialized payload into one Qt native copy drag.
