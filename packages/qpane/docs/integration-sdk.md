# Advanced renderer integration

Most applications should stay on `QPane`, `RenderScene`, and the source values
documented in [Declarative rendering](rendering-sdk.md). The `qpane.sdk`
namespaces are for a renderer-backed product that must participate in QPane's
own cache, scheduling, source-capability, diagnostics, and presentation
lifecycle. CuteCanvas is one such host. Import only the concern you actually
integrate:

Rounded host surfaces call `QPane.setViewportCornerRadius()` so clipping stays
inside the final renderer presentation boundary.
`QPane.viewportCornerRadius()` returns the configured logical-pixel radius.

```python
from qpane.sdk.execution import ExecutionRuntime
from qpane.sdk.scene import LayerSourceCapabilities, SceneProviderRegistry
```

The namespace is a supported boundary, not a bag of private implementation
modules. Types remain grouped by ownership so an integration can depend on
scene contracts without also depending on widget helpers or catalog policy.

## Scene contributions and source capabilities

`SceneDescriptor` is the renderer's immutable compiled-scene input, while
`SceneKind`, `LayerDescriptor`, and `LayerKind` describe its ordered contents.
`LayerPlacement`, `LayerTransform`, `ProjectiveLayerTransform`,
`PiecewiseLayerTransform`, `BilinearLayerTransform`, and
`RasterBounds` retain exact floating
placement and signed source-local extent; `BlendMode`, `LayerClip`, and
`ClipCoordinateSpace` complete the presentation policy without mutating a
source.

Use `SceneProviderRegistry` to combine independently owned scene producers.
Each producer returns a `SceneContribution`, and `LayerSourceCapabilities`
routes its source values through focused `SourceCapabilityRegistry` instances.
`LayerSourceReference` is the accepted source union. `LayerContentCapabilities`,
`LayerInteractionPolicy`, and `LayerHitTest` carry source-neutral behavior and
input policy rather than editor-specific state.

`SceneRenderItem`, `RasterLayerRenderItem`, and `SampledLayerRenderItem` are
detached products for presentation and hit testing. A sampled layer carries
immutable `SampledTileRenderData` values, so a renderer can reuse refined
regions without granting the frame access to mutable source state. Each tile's
`product_key` combines Qt's constant-time immutable image identity with its
complete draw and clipping geometry. `SampledLayerRenderItem.sample_batch_key`
identifies the exact current product batch, while `sample_geometry_key`
identifies its demand geometry independently of pixel revisions.
Active sampled edits are accepted only for that demand geometry. After commit,
QPane keeps the detached edit pixels for the unchanged view and releases them
when view geometry changes or a later durable asset supersedes the handoff.
`SceneLayerHitTestResult` reports the matching detached item and source-local
point without exposing a live scene owner.
`SceneLayerAssetKey` separates reusable source identity from a placed layer
instance, which prevents one resource used twice from sharing the wrong
transient products.

Raster-grid policy belongs to QPane's rendering lifecycle. The viewport-aware
grid owner selects and debounces automatic sizes; the tile-product owner only
accepts one immutable grid, generates products for that identity, and cancels
or rejects work from retired grids. Host integrations configure the policy
through `Config.tile_size` and must not reproduce grid selection, cache
invalidation, or stale-result rules.

## Damage and transient raster presentation

`RasterPresentation` identifies the renderer's source sampling strategy.
`RasterProductPolicy` controls whether settled derived products may be reused,
and `RasterSourcePatch` communicates bounded revision damage without flushing
unrelated tiles.

Interactive hosts publish a `TransientRasterContribution` while a bounded
raster product is changing. `TransientRasterResolvedContribution` carries
already resolved content, while `TransientRasterTransformContribution` moves
an existing product without resampling it on every pointer event. Its optional
`destination_attenuation_mask` removes only the destination contribution
authorized by the host; QPane then adds the premultiplied fragment without a
second attenuation. Omitting the mask uses ordinary source-over composition.
These values let the normal compositor preserve clip, ordering, damage, and
transparent no-op behavior during previews.
`TransientSampledResolvedContribution` provides the same preview contract for
tile-backed sampled content, including the layer clip and source geometry
needed for a stable temporary edit. QPane accepts its replacement tiles only
when their sampling geometry matches the current sampled item. A retained
sampled contribution remains valid only for the unchanged view and is released
when view geometry changes or a later durable asset supersedes the handoff.
This validation uses immutable product and geometry identities without reading
image pixels. Resolved contributions retain their last frame until durable
presentation catches up by default.
Set `retain_until_durable=False` for cancellable in-flight feedback whose
disappearance is authoritative and must immediately repair the underlying
durable frame.
When a host must sample immutable hybrid content for a transient product,
`present_hybrid_sample()` evaluates the requested source rectangle at an
explicit output size using the same source-space phase as settled hybrid
presentation.
For an already evaluated coverage array, `present_hybrid_pixels()` applies the
document's color and outline presentation without repeating source evaluation.

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
raster products, while `rasterize_layer()` and `rasterize_region()` produce
detached bounded products inside an execution request. `ViewportZoomMode`
names the authoritative fit, native-scale, and explicit zoom policies.

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

`ExecutionRuntime` owns task lifecycle and routes each accepted
`ExecutionRequest` to exactly one capable `ExecutionBackend`. A request carries
detached work plus `ExecutionRequirements`: resource class, semantic urgency,
optional affinity or exclusion, and a retained-byte estimate. String operation
names are diagnostic identity, not scheduler policy.

Every owner opens an `ExecutionScope`. Closing the scope cancels its handles,
prevents new submissions, and suppresses unsafe late delivery. `ExecutionHandle`
exposes cancellation, state, timings, and one terminal `ExecutionOutcome`.
Worker exceptions and adoption exceptions are identified separately.
`QtOwnerDispatcher` adopts results on a receiver's Qt thread and acknowledges
discarded delivery when that receiver is destroyed.

Worker code receives an `ExecutionTaskContext`. Its `CancellationToken` makes
cooperative cancellation cheap to check, and its typed
`ExecutionProgressReporter` coalesces bursts before delivery. The terminal
`ExecutionOutcome` names its `ExecutionState`, separates worker and adoption
errors with `ExecutionFailurePhase`, and records phase boundaries in
`ExecutionTimings`. Diagnostic request tags accept only safe immutable
`ExecutionTagValue` values.

`CompletionDispatcher` is the delivery protocol used by a scope.
`QtOwnerDispatcher` is the normal widget choice, while `InlineDispatcher`
supports synchronous services and deterministic tests. Dispatchers acknowledge
discarded callbacks so teardown still settles every accepted task.

The standalone runtime uses `DefaultExecutionPolicy` and remains bounded by
accepted-task count and retained bytes. Its default backend applies semantic
urgency with aging, resource limits, immediate structured rejection, and
multi-observer `ExecutionSnapshot` diagnostics. Thread-affine native work is
routed to the affinity backend; an adoption-held exclusive lease can keep a
native resource serialized through GUI-thread adoption.

`create_native_execution_runtime()` creates an owned runtime dedicated to
those hard native-affinity requirements. An integrating product can use it as
a disjoint fallback when its ordinary host backend does not advertise the
capability; ordinary requests continue to use the host backend and each
request is still admitted exactly once.

Applications may inject an `ExecutionRuntime` into `QPane` or `CuteCanvas`.
A custom backend implements only three public responsibilities:

1. report honest `ExecutionBackendCapabilities`;
2. admit one `ExecutionJob` or raise `ExecutionRejected`; and
3. schedule `job.run()` exactly once while returning a `BackendSubmission`
   that can remove pending work with `job.cancel_before_start()`.

`ExecutionBackendCapabilities` tells the runtime which scheduling constraints
the backend can enforce. Each accepted `ExecutionJob` remains owned by the
runtime even though the backend chooses where it runs. The returned
`BackendSubmission` represents only physical pending-work cancellation, so it
does not duplicate the task lifecycle or its terminal outcome.

Each request carries `ExecutionRequirements` instead of a backend-specific
queue name. `ExecutionResource` describes the kind of capacity the work
consumes, while `ExecutionUrgency` expresses how promptly it should begin.
`ExecutionLeaseRelease` determines whether an exclusive resource is released
after worker execution or retained until owner-thread adoption completes.
These scheduling facts let different backends preserve the same observable
contract without copying QPane's standalone policy.

An `ExecutionRejected` value includes an `ExecutionRejectionReason`, so a
producer can distinguish saturation, unsupported requirements, and closed
ownership from worker failure. A rejected request was never accepted and never
has an accepted-task completion lifecycle.

The host remains the only physical admission owner. It does not wrap a QPane
pool, publish domain results, marshal Qt adoption, or duplicate cancellation
state. QPane never configures or shuts down a supplied runtime.

Native resources sometimes require affinity-bound destruction after a widget
or document has already closed. An owner can reserve that lifetime with
`ExecutionScope.open_finalization_scope()`, submit cleanup after the
originating scope closes, and close the finalization scope when its handle
settles. Temporary backend saturation leaves finalization pending until an
accepted task releases capacity. Runtime shutdown remains the outer bound and
closes every outstanding finalization scope.

`RetryPolicy` computes bounded deterministic delays. `RetryController` retains
at most one coalesced payload per producer key and retries only structured
rejection through a `DelayScheduler`. `QtDelayScheduler` keeps those producer
decisions on the owner thread. Retry diagnostics use `RetrySnapshot` and the
same diagnostics system as runtime snapshots.

`RetryContext` carries the operation, producer key, and retained payload size
used to calculate policy. A `DelayHandle` cancels one scheduled attempt, while
`RetrySchedulingError` reports that a `DelayScheduler` could not retain the
delay. `RetryCategorySnapshot` is one operation's immutable counters inside
the complete `RetrySnapshot`.

Runtime diagnostics are read through `ExecutionDiagnosticsProvider`.
`ExecutionSnapshot` contains bounded aggregate and operation state, while a
`DiagnosticsSubscription` releases one listener independently. Use
`execution_summary_records` and `execution_detail_records` to present runtime
state through QPane's diagnostics model. The matching
`retry_summary_records` and `retry_detail_records` functions present producer
backoff without exposing retry internals to host UI code.

`create_default_execution_runtime()` is the convenient bounded runtime for
standalone applications. `create_native_execution_runtime()` is reserved for
hard stable-affinity operations; it does not become a second admission path
for ordinary work.

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

`qpane.sdk.inspection` stores inspection center and display scale independently
of source resolution and viewport size. `InspectionTarget` identifies native
bounds, `capture_inspection()` converts a viewport transform into an
`InspectionViewState`, and `project_inspection()` derives target-local zoom and
pan for another view. `InspectionStateStore` owns explicit link groups,
generation-guards callbacks, and keeps 1:1 interpretation local to the target
that requested it.

An `InspectionRegion` records a normalized center and normalized target span
per physical display pixel. A larger viewport therefore reveals more content
around the same center without changing custom zoom. `InspectionZoomMode`
retains fit, native-scale, or custom interpretation for the target that
authored the state. Projection produces a `ProjectedViewport`, while linked
publication sends an `InspectionUpdate` to each registered
`InspectionObserver` without recursively republishing it.

`qpane.sdk.layout` supplies source-neutral target geometry.
A `ViewTargetSpec` combines a stable target identity with its native size.
`ResponsiveGridLayout` applies `ResponsiveGridPolicy`.
`ResponsiveGridTopology.MAXIMUM_REFERENCE_AREA` chooses the most useful
fixed-aspect arrangement, `IncompleteRowAlignment.CENTER` centers a partial
final row, and policy hysteresis prevents breakpoint flicker. It partitions physical
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
`qimage_to_numpy_view_argb32` provides a writable scoped zero-copy view.
`qimage_to_numpy_view_grayscale8` provides a read-only scoped zero-copy view.
Both require the caller to honor the image lifetime.

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
the same native drag path as QPane's ready-made image workflow.
Deferred providers receive a one-shot `DragCompletion` callback and may return
a `DragCancellation` object for superseded work. Custom native hosts can call
`execute_outbound_drag` after materializing an `OutboundDragPayload`; the
helper builds the Qt MIME data, preview, hotspot, and copy action consistently.

`sample_system_headroom` returns a detached `SystemHeadroomSample` suitable for
runtime submission, so cache policy can react without blocking input.

The advanced SDK deliberately stops at renderer integration. Documents,
editable layers, masks, selections, history, painting, and authoring tools
belong to CuteCanvas.
