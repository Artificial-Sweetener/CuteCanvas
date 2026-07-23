# QPane public API

## Viewer

- `QPane` is the focused PySide6 viewer facade.
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
- `SceneRenderItem`, `RasterLayerRenderItem`, and `SceneLayerHitTestResult` are detached presentation products.
- `SceneLayerAssetKey` separates reusable source identity from placed layer identity.
- `RasterPresentation`, `RasterProductPolicy`, and `RasterSourcePatch` describe sampling, reuse, and bounded damage.
- `TransientRasterContribution`, `TransientRasterResolvedContribution`, and `TransientRasterTransformContribution` preserve renderer rules during interactive previews.
- `AffineTransformGeometry`, `TransformOperation`, and `TransformOperationKind` own exact affine interaction math.
- `TransformHandle`, `TransformLocalBounds`, and `TransformModifiers` describe one transform gesture without rounded coordinates.
- `LayerEffectReference` and `LayerEffectRenderRegistry` connect generic layer effects to the compositor.

### Renderer, cache, and scheduling

- `View`, `Renderer`, `RenderingPresenter`, and `ViewportZoomMode` coordinate viewport state and frame publication.
- `PyramidManager` and `LayerRasterizationWorker` own multiresolution products and worker-side layer resolution.
- `CacheRegistry`, `CacheCoordinator`, and `CachePriority` coordinate byte-bounded product stores.
- `EvictableCacheConsumer`, `KeyedCacheConsumer`, and `cache_detail_provider` connect stores to eviction and diagnostics.
- `BaseWorker`, `TaskExecutorProtocol`, `TaskHandle`, and `TaskRejected` define cancellable bounded background work.
- `QThreadPoolExecutor` and `LiveTunableExecutorProtocol` provide Qt-backed execution and live tuning.
- `ThreadPolicy` and `build_thread_policy` resolve host and configuration concurrency limits.
- `RetryContext`, `RetryEntriesView`, `makeQtRetryController`, and `qt_retry_dispatcher` coordinate bounded Qt-safe retries.
- `retry_diagnostics_provider` and `retry_summary_provider` expose executor retry state consistently.

### Configuration, features, and diagnostics

- `Config`, `CacheSettings`, `FeatureAwareConfig`, and `diff_config_fields` define and compare renderer settings.
- `FeatureConfigDescriptor`, `ConfigFeatureRegistry`, `iter_descriptors`, and `require_feature_slice` support typed configuration extensions.
- `FeatureDefinition`, `FeatureRegistry`, `resolve_feature_order`, and `FeatureInstallError` coordinate optional integration slices.
- `Diagnostics`, `DiagnosticsRegistry`, `DiagnosticsProvider`, and `DiagnosticsSnapshot` own live and gathered diagnostics.
- `DiagnosticRecord` and `DiagnosticsDomain` provide stable diagnostic presentation values.
- `OverlayRegistry`, `OverlayDrawFn`, `SceneOverlayDrawFn`, and `OverlayState` define cheap host paint extensions.
- `DiagnosticsOverlayController` and `create_status_overlay` provide QPane's standard host-placeable diagnostics chrome.

### Catalog, comparison, and viewer values

- `Catalog`, `ImageCatalog`, `ViewerCatalog`, and `CatalogMutationEvent` own ordered resources and structural notifications.
- `CatalogEntry`, `CatalogImageReference`, and `CatalogSourceCapabilities` connect catalog identity to renderer sources.
- `ImageMap`, `LinkManager`, and `NavigationEvent` support stable image association and navigation.
- `CompareService`, `CompareDividerInteraction`, `ComparisonChange`, and `ComparisonChangeKind` own comparison state and input.
- `ComparisonState`, `ComparisonDividerState`, and `ComparisonOrientation` are detached comparison snapshots.
- `LinkedGroup`, `PlaceholderScaleMode`, `ZoomMode`, and `CacheMode` describe stable viewer policies.
- `SceneSnapshotOverlayState` and `SceneSnapshotOverlayLayer` provide prepared scene-aware overlay geometry.

### Raster and vector helpers

- `AffineImageResampler` performs bounded worker-side affine sampling.
- `qimage_to_numpy_argb32`, `qimage_to_numpy_grayscale8`, `qimage_to_numpy_view_argb32`, and `qimage_to_numpy_view_grayscale8` convert QImage pixels with explicit ownership.
- `numpy_to_qimage_argb32`, `numpy_to_qimage_grayscale8`, `numpy_to_qimage_argb32_at_size`, and `numpy_to_qimage_grayscale8_at_size` create validated QImage values.
- `VectorPresentationSnapshot`, `SemanticTextLayoutCache`, `TextFontResolution`, and `text_caret_rect` share immutable vector presentation and text layout.
- `VectorNodeRole`, `object_path`, and `object_contains` provide semantic node and geometry queries.
- `painted_document_path` and `draw_vector_document` share authoritative painted vector geometry.

### Widget and system helpers

- `apply_widget_defaults`, `copyToClipboard`, and `maybeStartDrag` provide standard viewer widget behavior.
- `drag_out_image` and `is_drag_out_allowed` separate drag payload construction from host policy.
- `SwapDelegate` is the supported image-swap boundary for custom shells.
- `SystemHeadroomWorker` samples memory pressure without blocking the GUI thread.
