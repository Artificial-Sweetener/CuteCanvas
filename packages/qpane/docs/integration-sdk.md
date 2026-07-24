# Advanced renderer integration

Most applications should stay on `QPane`, `RenderScene`, and the source values
documented in [Declarative rendering](rendering-sdk.md). The `qpane.sdk`
namespaces are for a renderer-backed product that must participate in QPane's
own cache, scheduling, source-capability, diagnostics, and presentation
lifecycle. CuteCanvas is one such host. Import only the concern you actually
integrate:

```python
from qpane.sdk.concurrency import TaskExecutorProtocol
from qpane.sdk.scene import LayerSourceCapabilities, SceneProviderRegistry
```

The namespace is a supported boundary, not a bag of private implementation
modules. Types remain grouped by ownership so an integration can depend on
scene contracts without also depending on widget helpers or catalog policy.

## Scene contributions and source capabilities

`SceneDescriptor` is the renderer's immutable compiled-scene input, while
`SceneKind`, `LayerDescriptor`, and `LayerKind` describe its ordered contents.
`LayerPlacement`, `LayerTransform`, and `RasterBounds` retain exact floating
placement and signed source-local extent; `BlendMode`, `LayerClip`, and
`ClipCoordinateSpace` complete the presentation policy without mutating a
source.

Use `SceneProviderRegistry` to combine independently owned scene producers.
Each producer returns a `SceneContribution`, and `LayerSourceCapabilities`
routes its source values through focused `SourceCapabilityRegistry` instances.
`LayerSourceReference` is the accepted source union. `LayerContentCapabilities`,
`LayerInteractionPolicy`, and `LayerHitTest` carry source-neutral behavior and
input policy rather than editor-specific state.

`SceneRenderItem`, `RasterLayerRenderItem`, and `SceneLayerHitTestResult` are
detached products for presentation and hit testing. `SceneLayerAssetKey`
separates reusable source identity from a placed layer instance, which prevents
one resource used twice from sharing the wrong transient products.

## Damage and transient raster presentation

`RasterPresentation` identifies the renderer's source sampling strategy.
`RasterProductPolicy` controls whether settled derived products may be reused,
and `RasterSourcePatch` communicates bounded revision damage without flushing
unrelated tiles.

Interactive hosts publish a `TransientRasterContribution` while pixels are
being edited. `TransientRasterResolvedContribution` carries already resolved
content, while `TransientRasterTransformContribution` moves an existing
product without resampling it on every pointer event. These values let the
normal compositor preserve clip, ordering, and damage rules during previews.

## Affine editing geometry

`AffineTransformGeometry` projects one immutable transform session.
`TransformOperation` and `TransformOperationKind` describe translation,
rotation, scaling, and pivot work; `TransformHandle` identifies the active
handle, `TransformLocalBounds` retains unrounded local geometry, and
`TransformModifiers` captures constrained or centered gestures. Hosts can
therefore share QPane's exact floating-point transform math without duplicating
renderer geometry.

## Layer effects

`LayerEffectReference` is an immutable effect request attached to a scene
layer. A `LayerEffectRenderRegistry` resolves registered source-neutral effect
owners, keeping effect evaluation in the same compositor and damage pipeline
as ordinary raster, vector, and hybrid content.

## Renderer lifecycle

`View` owns viewport state used by the low-level engine, `Renderer` produces
frames from compiled scenes, and `RenderingPresenter` coordinates publication
without exposing half-finished work. `PyramidManager` owns multiresolution
raster products, while `LayerRasterizationWorker` resolves bounded layer
content away from the GUI thread. `ViewportZoomMode` names the authoritative
fit, native-scale, and explicit zoom policies.

`View.coordinates` and `QPane.coordinateSystem()` expose the same
`SceneCoordinateSystem`. Advanced interactions pass `PanelPoint`,
`ScenePoint`, `LayerLocalPoint`, and `LayerSourcePoint` values through that
owner instead of reconstructing viewport or layer transforms. The coordinate
values retain scene and layer identity so stale or cross-layer projections
fail without producing plausible coordinates.

Advanced hosts should still prefer the `QPane` widget when they do not need to
own this lifecycle. Constructing these collaborators directly means accepting
their cancellation, teardown, and cache contracts as one unit.

## Cache participation

`CacheRegistry` is the inventory of byte-accounted consumers.
`CacheCoordinator` applies shared budgets and pressure decisions, and
`CachePriority` orders eviction importance. Implement `EvictableCacheConsumer`
for a single byte-bounded store or `KeyedCacheConsumer` when distinct product
keys can be retired individually. `cache_detail_provider` turns that shared
state into diagnostics without teaching the diagnostics system about cache
implementations.

## Task execution and retry

Render-adjacent work implements `BaseWorker` and is submitted through
`TaskExecutorProtocol`; `TaskHandle` represents cancellation and completion,
while `TaskRejected` reports a bounded executor refusing more work.
Workers whose GUI-thread result handling owns native-resource teardown can
defer scheduler completion until that handling finishes, keeping category and
device limits authoritative across the complete resource lifecycle.
`QThreadPoolExecutor` owns QPane's bounded scheduler and uses a Qt thread pool
by default.
`LiveTunableExecutorProtocol` is the narrow contract used when concurrency may
change at runtime.
`PersistentWorkerPool` is an optional executor backend for native libraries
that require stable Python worker-thread identity across serialized jobs. It
uses the same QPane queueing, cancellation, limits, completion, and diagnostics
ownership as the default Qt pool.

`ThreadPolicy` is the immutable resolved scheduling policy and
`build_thread_policy` derives it from settings and host limits.
`RetryContext` and `RetryEntriesView` retain bounded retry state;
`makeQtRetryController` and `qt_retry_dispatcher` bridge retry decisions onto
Qt safely. `retry_diagnostics_provider` and `retry_summary_provider` expose the
same state to diagnostics rather than maintaining parallel counters.

## Configuration extensions

`Config` and `CacheSettings` are the concrete renderer settings. Products that
add namespaced settings derive from `FeatureAwareConfig`, describe a slice with
`FeatureConfigDescriptor`, and install it through `ConfigFeatureRegistry`.
`require_feature_slice` validates that an enabled feature has its settings,
`iter_descriptors` returns registered descriptions, and `diff_config_fields`
reports exact changes so owners can apply only relevant updates.

## Optional feature composition

`FeatureDefinition` declares one installable integration slice and its
dependencies. `FeatureRegistry` owns registration and installation order,
`resolve_feature_order` performs deterministic dependency resolution, and
`FeatureInstallError` reports an invalid or failed installation without leaving
a half-installed feature graph.

## Diagnostics, overlays, and host chrome

`Diagnostics` is the live broker, `DiagnosticsRegistry` owns provider
registration, `DiagnosticsProvider` is the producer contract, and
`DiagnosticsSnapshot` is the detached gathered result. `DiagnosticRecord` and
`DiagnosticsDomain` provide stable rows and standard domain names for host
presentation.

`OverlayRegistry` owns named cheap paint callbacks. `OverlayDrawFn` receives
the ordinary `OverlayState`; `SceneOverlayDrawFn` receives prepared scene-aware
geometry. `DiagnosticsOverlayController` and `create_status_overlay` build the
standard viewer diagnostics chrome without transferring diagnostics ownership
to the host.

## Catalog and comparison integration

`ViewerCatalog` is QPane's convenience owner for an ordered image-review list.
Each immutable `ViewerCatalogEntry` retains one reusable `RasterSource`, a
label, and an optional path. Selecting an entry adapts that source into an
ordinary one-layer `RenderScene`; the catalog does not define documents,
editable resources, or layer lifetime.

Custom viewer hosts can use `CompareDividerInteraction` for divider input.
`ComparisonChange` and `ComparisonChangeKind` publish exact interaction changes
rather than forcing consumers to diff mutable state. Comparison presentation
and source selection remain available directly through the `QPane` facade.

`ComparisonState`, `ComparisonDividerState`, and `ComparisonOrientation` are
detached public snapshots. `LinkedGroup` describes synchronized identities,
while `PlaceholderScaleMode`, `ZoomMode`, and `CacheMode` name stable viewer
policies. `OverlayState`, `SceneSnapshotOverlayState`, and
`SceneSnapshotOverlayLayer` contain prepared geometry for paint-only host
extensions.

## Independent inspection and target layout

`qpane.sdk.inspection` stores the visible region independently of source
resolution. `InspectionTarget` identifies native bounds,
`capture_inspection()` converts a viewport transform into an
`InspectionViewState`, and `project_inspection()` derives target-local zoom and
pan for another view. `InspectionStateStore` owns explicit link groups,
generation-guards callbacks, and keeps 1:1 interpretation local to the target
that requested it.

An `InspectionRegion` records normalized center and span values rather than
source pixels. `InspectionZoomMode` retains fit, native-scale, or custom
interpretation for the target that authored the state. Projection produces a
`ProjectedViewport`, while linked publication sends an `InspectionUpdate` to
each registered `InspectionObserver` without recursively republishing it.

`qpane.sdk.layout` supplies source-neutral target geometry.
A `ViewTargetSpec` combines a stable target identity with its native size.
`ResponsiveGridLayout` applies `ResponsiveGridPolicy`, partitions physical
pixels without cumulative rounding drift, and returns a
`ResponsiveGridSnapshot` containing logical `ViewTargetFrame` values for
layout, hit testing, damage, visibility, and prefetch order.
`TargetComparisonLayout` places a two-target reveal divider on one exact
physical-pixel boundary and returns that geometry as a
`TargetComparisonSnapshot`.

## Raster conversion

`AffineImageResampler` performs bounded transform sampling for worker-side
pixel operations. `qimage_to_numpy_argb32` and `qimage_to_numpy_grayscale8`
return detached arrays. `qimage_to_numpy_const_view_argb32` provides a
read-only zero-copy view and its normalized backing image.
`qimage_to_numpy_const_view_bgra32` preserves compatible 32-bit storage when
only channel values, rather than premultiplication, matter.
`qimage_to_numpy_view_argb32` and `qimage_to_numpy_view_grayscale8` provide
writable scoped zero-copy views when the caller can honor the image lifetime.

For the reverse direction, `numpy_to_qimage_argb32` and
`numpy_to_qimage_grayscale8` preserve the array's intrinsic size, while
`numpy_to_qimage_argb32_at_size` and `numpy_to_qimage_grayscale8_at_size`
validate an explicit output extent. Keeping these conversions in QPane gives
all raster consumers the same format, stride, ownership, and detachment rules.

## Semantic vector integration

`VectorPresentationSnapshot` binds an immutable semantic document to one
presentation generation. `SemanticTextLayoutCache` reuses shaped text products,
`TextFontResolution` records the resolved font, and `text_caret_rect` derives
caret geometry from that same layout. `VectorNodeRole` identifies anchors and
control handles without putting an editing session inside QPane.

`object_path` and `object_contains` share authoritative vector geometry for
drawing and hit testing. `painted_document_path` applies document paint rules,
and `draw_vector_document` renders that semantic result into a supplied painter
without creating a second vector model.

## Widget helpers

`apply_widget_defaults` applies QPane's polished viewer attributes to a custom
widget. `copyToClipboard` and `maybeStartDrag` implement familiar image export
gestures, while `drag_out_image` and `is_drag_out_allowed` keep drag payload and
policy decisions separate.

`DragSubject`, `OutboundDragPayload`, and `OutboundMimeItem` describe
host-selected outbound content without assuming it is one image file.
`OutboundMimeProvider` may materialize URLs, text, previews, and custom MIME
values synchronously or later. `OutboundDragController` cancels superseded
work, ignores stale completion, marshals delivery to the GUI thread, and uses
the same native Qt drag executor as QPane's ready-made image workflow.
Deferred providers receive a one-shot `DragCompletion` callback and may return
a `DragCancellation` object for superseded work. Custom native hosts can call
`execute_outbound_drag` after materializing an `OutboundDragPayload`; the
helper builds the Qt MIME data, preview, hotspot, and copy action consistently.

`SystemHeadroomWorker` samples memory pressure away from the GUI thread so
cache policy can react without blocking input.

The advanced SDK deliberately stops at renderer integration. Documents,
editable layers, masks, selections, history, painting, and authoring tools
belong to CuteCanvas.
