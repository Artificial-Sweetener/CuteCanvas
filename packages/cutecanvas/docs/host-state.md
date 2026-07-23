# Host State

CuteCanvas returns immutable snapshots and enums so a host can build toolbars,
trees, inspectors, and status displays without reaching into editor internals.
This guide explains how those values fit together.

## Configuration and View Choices

`Config` is one validated settings snapshot. `Config.copy()` creates an
independent starting point for another window or profile, so later changes do
not leak between canvases.

`ZoomMode.FIT` continually frames content, `ZoomMode.LOCKED_ZOOM` preserves an
explicit scale, and `ZoomMode.LOCKED_SIZE` preserves the presented logical
size. Empty-canvas images use `PlaceholderScaleMode.AUTO` for automatic choice,
`PlaceholderScaleMode.LOGICAL_FIT` for logical widget fitting,
`PlaceholderScaleMode.PHYSICAL_FIT` for device-pixel fitting, or
`PlaceholderScaleMode.RELATIVE_FIT` for a proportional presentation.

The `DiagnosticsDomain.CACHE` section describes retained products,
`DiagnosticsDomain.SWAP` describes navigation and prefetch,
`DiagnosticsDomain.EXECUTOR` describes workers and queues, and
`DiagnosticsDomain.RETRY` describes retry activity. Editor features add
`DiagnosticsDomain.MASK` for mask work and `DiagnosticsDomain.SAM` for optional
model work.

## Tools and Editor Permission

`ControlMode` is the typed vocabulary for built-in tools.
`ControlMode.PANZOOM` navigates, `ControlMode.CURSOR` inspects, and
`ControlMode.MOVE` moves pixels or layers. `ControlMode.TRANSFORM` performs
affine manipulation, while `ControlMode.DRAW_BRUSH` paints the active target.

Selection gestures use `ControlMode.SELECT_RECTANGLE`,
`ControlMode.SELECT_ELLIPSE`, and `ControlMode.SELECT_LASSO`.
`ControlMode.SMART_SELECT` supplies optional assisted selection. Vector tools
use `ControlMode.VECTOR_SHAPE`, `ControlMode.VECTOR_PATH`,
`ControlMode.VECTOR_NODE`, and `ControlMode.VECTOR_TEXT` for their distinct
direct-manipulation jobs.

`EditorPolicy.capabilities` is the host's enabled set. The individual choices
are `EditorCapability.SELECT_PIXELS`, `EditorCapability.EDIT_PIXELS`,
`EditorCapability.PAINT`, `EditorCapability.MOVE_LAYERS`, and
`EditorCapability.TRANSFORM_LAYERS`. A policy disables complete capabilities;
it does not change source data.

An `EditorOperationState` explains one attempted `EditorIntent`. The
`EditorOperationState.intent` echoes the request,
`EditorOperationState.allowed` reports the decision, and
`EditorOperationState.denial` provides user-facing context. The
`EditorOperationState.alternatives` tuple offers valid next actions, while
`EditorOperationState.scene_id` and `EditorOperationState.layer_id` identify
the resolved target. Common requests use `EditorIntent.SELECT_PIXELS`,
`EditorIntent.PAINT`, `EditorIntent.MOVE`, or `EditorIntent.TRANSFORM`.

## Brush State

`BrushOperation.PAINT` adds color or coverage, while `BrushOperation.ERASE`
removes it. The operation is independent from target type, so the same tool can
edit color, mask, or selection storage.

A `BrushPreset` is the complete deterministic brush description.
`BrushPreset.name` labels it, `BrushPreset.size` sets nominal diameter,
`BrushPreset.hardness` controls edge falloff, `BrushPreset.opacity` limits the
whole stroke, and `BrushPreset.flow` limits each dab. `BrushPreset.spacing`
sets dab distance and `BrushPreset.smoothing` stabilizes the pointer path.
`BrushPreset.angle` rotates the tip. `BrushPreset.texture_strength`,
`BrushPreset.texture_scale`, and `BrushPreset.texture_seed` define repeatable
texture, while `BrushPreset.dynamics` contains device-response rules.

`BrushDynamics.pressure_size` maps pressure to diameter and
`BrushDynamics.pressure_opacity` maps it to opacity.
`BrushDynamics.minimum_pressure_ratio` keeps light contact usable, while
`BrushDynamics.pressure_gamma` shapes the response curve.
`BrushDynamics.position_jitter`, `BrushDynamics.size_jitter`, and
`BrushDynamics.angle_jitter` add deterministic variation.
`BrushDynamics.rotation_angle` and `BrushDynamics.tilt_angle` use pen
orientation, and `BrushDynamics.tangential_opacity` uses barrel pressure when a
device supplies it.

## Catalog and Comparison State

A `CatalogEntry` carries one source. `CatalogEntry.image` is the decoded Qt
image and `CatalogEntry.path` is its optional host path. A `CatalogSnapshot`
combines the ordered entries, selection, and linked groups needed by a browser.
`LinkedGroup` identifies catalog sources that share normalized pan and zoom.

`ComparisonOrientation.VERTICAL` creates a left-and-right reveal, while
`ComparisonOrientation.HORIZONTAL` creates a top-and-bottom reveal. The
`ComparisonState.enabled` flag says whether comparison is active,
`ComparisonState.split_position` gives its normalized position, and
`ComparisonState.orientation` gives its direction. `ComparisonState.source_id`,
`ComparisonState.source_path`, and `ComparisonState.source_kind` describe the
second source for labels and controls.

A `ComparisonDividerState` is projected interaction geometry.
`ComparisonDividerState.enabled` says whether a boundary exists,
`ComparisonDividerState.full_segment` contains the complete projected line,
and `ComparisonDividerState.visible_segment` contains the clipped on-screen
part. `ComparisonDividerState.orientation` matches the reveal direction and
`ComparisonDividerState.hit_width` gives the active pointer target.
`ComparisonDividerState.interactive`, `ComparisonDividerState.hovered`, and
`ComparisonDividerState.dragging` describe the divider's current behavior and
feedback state.

## Document Requests and Browser Rows

A `CompositionPolicy` separates document structure from layer editing.
`CompositionPolicy.removable` controls document removal, while
`CompositionPolicy.comparison_enabled` controls comparison for that document.

A `CompositionRequest` describes a complete catalog-backed document.
`CompositionRequest.composition_id` optionally supplies stable identity,
`CompositionRequest.title` supplies the browser label,
`CompositionRequest.bounds` supplies the canvas, and
`CompositionRequest.layers` supplies bottom-to-top layer requests.

Each request layer uses `CatalogLayerRequest.image_id` for the catalog source
and `CatalogLayerRequest.layer_id` for instance identity.
`CatalogLayerRequest.placement`, `CatalogLayerRequest.opacity`, and
`CatalogLayerRequest.visible` control presentation.
`CatalogLayerRequest.clip` applies an optional clip,
`CatalogLayerRequest.hit_test` controls pointer eligibility, and
`CatalogLayerRequest.interaction` sets edit permission.
`CatalogLayerRequest.role` and `CatalogLayerRequest.metadata` carry host meaning
without changing renderer behavior.

A `CompositionLayerClip` combines `CompositionLayerClip.coordinate_space` with
`CompositionLayerClip.rect`, allowing one rectangle to be interpreted in
source or scene coordinates without ambiguity.

`CompositionTemplate.template_id` identifies a reusable layout,
`CompositionTemplate.title` supplies its optional label,
`CompositionTemplate.bounds` defines its canvas, and
`CompositionTemplate.layers` defines source slots. A `TemplateLayer` gives each
slot `TemplateLayer.layer_id`, `TemplateLayer.source_slot`, and
`TemplateLayer.placement`. Its `TemplateLayer.visible`,
`TemplateLayer.opacity`, and `TemplateLayer.clip` control presentation;
`TemplateLayer.hit_test` and `TemplateLayer.interaction` control interaction;
and `TemplateLayer.role` plus `TemplateLayer.metadata` carry host meaning.

Bindings turn a template into a document. `TemplateBindings.composition_id`
can preserve document identity, `TemplateBindings.title` can replace its title,
`TemplateBindings.catalog_images` maps slots to catalog IDs, and
`TemplateBindings.metadata` carries host data for the resulting composition.

`CompositionSnapshot.order` gives browser order,
`CompositionSnapshot.compositions` maps IDs to rows, and
`CompositionSnapshot.current_composition_id` identifies the open document.

Each `CompositionEntry.composition_id` is stable identity and
`CompositionEntry.title` is display text. `CompositionEntry.kind` describes how
the row was created, `CompositionEntry.source_image_ids` lists catalog
dependencies, and `CompositionEntry.current_image_id` identifies a seeded
source when present. `CompositionEntry.scene_bounds` is the canvas and
`CompositionEntry.scene_layer_count` summarizes its stack.
`CompositionEntry.comparison` and `CompositionEntry.policy` preserve the
document's comparison and structural rules.

A `CompositionLayerEntry.layer_id` identifies one layer instance.
`CompositionLayerEntry.source_kind` and `CompositionLayerEntry.source_id`
identify its render source. `CompositionLayerEntry.label` and
`CompositionLayerEntry.role` provide tree text and host meaning.
`CompositionLayerEntry.visible`, `CompositionLayerEntry.opacity`, and
`CompositionLayerEntry.transform` describe presentation, while
`CompositionLayerEntry.interaction` supplies user permission.

## Layer and Scene Snapshots

`LayerPolicy.selectable`, `LayerPolicy.movable`, and
`LayerPolicy.pixel_editable` govern direct selection, movement, and pixel
changes. `LayerPolicy.reorderable` and `LayerPolicy.removable` govern structural
commands. Permission cannot create an operation unsupported by the source.

`LayerGeometryMode` selects the bounds used for manipulation and snapping, while
`SnapPolicy` contains the global snapping choices shared by movement and
transform tools. `LayerHandle` is stable application-facing identity, and
`LayerEffectHandle` is stable identity for one temporary visual treatment.

A `LayerSelectionSnapshot.scene_id` identifies the open scene and
`LayerSelectionSnapshot.layer_id` identifies its selected layer.

`LayerSnapshot.layer_id` identifies the instance, while
`LayerSnapshot.source_kind`, `LayerSnapshot.source_id`, and
`LayerSnapshot.image_id` describe its backing resource.
`LayerSnapshot.label`, `LayerSnapshot.role`, and `LayerSnapshot.metadata` carry
host presentation and meaning. `LayerSnapshot.placement`,
`LayerSnapshot.transform`, and `LayerSnapshot.clip` describe geometry;
`LayerSnapshot.visible`, `LayerSnapshot.opacity`, and `LayerSnapshot.tint`
describe appearance; and `LayerSnapshot.hit_test` plus
`LayerSnapshot.interaction` describe interaction.

`SceneSnapshot.scene_id` identifies the current render scene and
`SceneSnapshot.composition_id` identifies its document.
`SceneSnapshot.title` is host display text, `SceneSnapshot.bounds` is the
document canvas, and `SceneSnapshot.layers` is the bottom-to-top stack.

A `LayerHit.scene_id`, `LayerHit.composition_id`, and `LayerHit.layer_id`
identify what was reached. `LayerHit.image_id` identifies an optional catalog
source. `LayerHit.panel_point`, `LayerHit.scene_point`, and
`LayerHit.source_point` give the same location in three coordinate spaces,
while `LayerHit.role` and `LayerHit.metadata` carry host meaning.

## Overlay Snapshots

Ordinary overlay callbacks receive `OverlayState.qpane_rect` for logical widget
bounds and `OverlayState.physical_viewport_rect` for device-pixel bounds.
`OverlayState.zoom` and `OverlayState.current_pan` describe navigation,
`OverlayState.transform` maps source to widget coordinates, and
`OverlayState.source_image` supplies the available base image.

Scene callbacks receive `SceneSnapshotOverlayState.scene_id` and
`SceneSnapshotOverlayState.scene_bounds` for identity and canvas geometry.
`SceneSnapshotOverlayState.qpane_rect` and
`SceneSnapshotOverlayState.physical_viewport_rect` supply widget bounds, while
`SceneSnapshotOverlayState.zoom` supplies the current scale.

Each `SceneSnapshotOverlayLayer.layer_id` and
`SceneSnapshotOverlayLayer.source_id` identifies a projected layer.
`SceneSnapshotOverlayLayer.label`, `SceneSnapshotOverlayLayer.role`, and
`SceneSnapshotOverlayLayer.metadata` support host chrome.
`SceneSnapshotOverlayLayer.placement`, `SceneSnapshotOverlayLayer.transform`,
and `SceneSnapshotOverlayLayer.panel_bounds` provide geometry;
`SceneSnapshotOverlayLayer.source_size` provides intrinsic dimensions; and
`SceneSnapshotOverlayLayer.visible` prevents stale chrome for hidden layers.

`LayerPresentationEffectKind` selects a renderer treatment,
`LayerPresentationStyle` describes its appearance, and
`LayerPresentationEffect` binds it to stable scene and layer identity. These
values change presentation without entering editable document state.

## Pixel Selection and Floating Content

`PixelSelectionMode.REPLACE` starts new coverage, `PixelSelectionMode.ADD`
unions it, `PixelSelectionMode.SUBTRACT` removes it, and
`PixelSelectionMode.INTERSECT` keeps only overlap.

`CoverageCoordinateSpace.TARGET` interprets authored geometry in target-local
coordinates. `CoverageCoordinateSpace.NORMALIZED_TARGET` interprets each axis
from zero to one, which is useful for proportional host layouts. A
`CoverageShapeOptions` snapshot reports the active feathering behavior.

A `PixelSelectionSnapshot.scene_id` identifies the document and
`PixelSelectionSnapshot.revision` changes with coverage.
`PixelSelectionSnapshot.has_selection` distinguishes no selection from valid
coverage, `PixelSelectionSnapshot.bounds` encloses stored pixels, and
`PixelSelectionSnapshot.coverage` carries their detached grayscale image.

`FloatingPixelMode.CUT` lifts pixels out of their source, while
`FloatingPixelMode.COPY` leaves the source unchanged. A
`FloatingPixelSnapshot.scene_id` and `FloatingPixelSnapshot.source_layer_id`
identify origin; `FloatingPixelSnapshot.mode` records cut or copy;
`FloatingPixelSnapshot.offset` records live displacement; and
`FloatingPixelSnapshot.bounds` encloses the fragment in scene coordinates.

## Paint and Raster State

`PaintTargetKind.LAYER` means the brush edits a raster or mask layer, while
`PaintTargetKind.PIXEL_SELECTION` means it edits selection coverage. A
`PaintTargetSnapshot.scene_id` identifies the document,
`PaintTargetSnapshot.layer_id` identifies an optional layer,
`PaintTargetSnapshot.kind` identifies the destination category, and
`PaintTargetSnapshot.source_kind` tells host controls what the target stores.

`RasterExtentPolicy.FIXED` clips writes to current storage,
`RasterExtentPolicy.EXPAND_ON_WRITE` grows storage when a write crosses an edge,
and `RasterExtentPolicy.UNBOUNDED` keeps sparse regions without treating the
canvas as a storage limit.

A `RasterSurfaceSnapshot.scene_id` and `RasterSurfaceSnapshot.layer_id`
identify the surface. `RasterSurfaceSnapshot.bounds` describes current storage
and `RasterSurfaceSnapshot.extent_policy` describes growth.
`RasterSurfaceSnapshot.content_revision` changes for pixel edits,
`RasterSurfaceSnapshot.structure_revision` changes for storage structure, and
`RasterSurfaceSnapshot.pending_request_id` identifies an asynchronous bounds
request still in flight.

## Placed Image State

`PlacedAssetMode.EMBEDDED` stores source data in the document, while
`PlacedAssetMode.LINKED` retains a source path. `PlacedAssetStatus.READY` means
content is available, `PlacedAssetStatus.LOADING` means work is pending,
`PlacedAssetStatus.MISSING` means a linked path is absent, and
`PlacedAssetStatus.ERROR` records another loading failure.

A `PlacedAssetSnapshot.scene_id` and `PlacedAssetSnapshot.layer_id` identify
the layer, while `PlacedAssetSnapshot.asset_id` identifies its shared immutable
resource. `PlacedAssetSnapshot.mode`, `PlacedAssetSnapshot.status`, and
`PlacedAssetSnapshot.source_path` describe provenance.
`PlacedAssetSnapshot.keep_fallback` reports whether embedded fallback pixels
are retained, `PlacedAssetSnapshot.generation` distinguishes stale worker
results, `PlacedAssetSnapshot.content_revision` changes with loaded content,
and `PlacedAssetSnapshot.error` carries a terminal message.

## Vector Documents and Objects

A `VectorDocumentSnapshot.scene_id` and `VectorDocumentSnapshot.layer_id`
identify the layer, `VectorDocumentSnapshot.vector_id` identifies its semantic
document, `VectorDocumentSnapshot.revision` changes with edits, and
`VectorDocumentSnapshot.objects` contains its ordered objects.

`VectorObjectKind.SHAPE`, `VectorObjectKind.PATH`, and `VectorObjectKind.TEXT`
distinguish the three object forms. A `VectorObjectSnapshot.object_id` provides
stable identity and `VectorObjectSnapshot.kind` gives its form.
`VectorObjectSnapshot.bounds` and `VectorObjectSnapshot.transform` describe
geometry, `VectorObjectSnapshot.style` describes appearance,
`VectorObjectSnapshot.shape_kind` identifies built-in shape geometry,
`VectorObjectSnapshot.path` stores commands, and `VectorObjectSnapshot.text`
stores optional semantic text.

`VectorShapeKind.RECTANGLE` and `VectorShapeKind.ELLIPSE` provide built-in
shapes. Custom paths use `VectorPathCommand.kind` to select an operation and
`VectorPathCommand.points` for its ordered coordinates.
`VectorPathCommandKind.MOVE` starts a contour,
`VectorPathCommandKind.LINE` adds a straight segment,
`VectorPathCommandKind.QUADRATIC` adds one control point,
`VectorPathCommandKind.CUBIC` adds two, and `VectorPathCommandKind.CLOSE` closes
the contour.

`VectorFillRule.WINDING` and `VectorFillRule.EVEN_ODD` choose how overlapping
contours fill. `VectorStrokeJoin.MITER`, `VectorStrokeJoin.ROUND`, and
`VectorStrokeJoin.BEVEL` choose corner treatment.
`VectorStrokeCap.FLAT`, `VectorStrokeCap.ROUND`, and `VectorStrokeCap.SQUARE`
choose open-end treatment.

`VectorStyle.fill` and `VectorStyle.stroke` are optional colors.
`VectorStyle.stroke_width` and `VectorStyle.opacity` control weight and
transparency, while `VectorStyle.join`, `VectorStyle.cap`, and
`VectorStyle.dash_pattern` control stroke presentation.
`VectorStyle.fill_rule` controls contour filling.

`VectorSelectionSnapshot.scene_id` and `VectorSelectionSnapshot.layer_id`
identify the layer, while `VectorSelectionSnapshot.object_ids` contains selected
object identities.

`VectorNodeRole.ANCHOR` identifies a path anchor,
`VectorNodeRole.CONTROL` identifies a curve handle, and
`VectorNodeRole.BOUNDS` identifies object-bounds manipulation. A
`VectorNodeSelectionSnapshot.scene_id`,
`VectorNodeSelectionSnapshot.layer_id`, and
`VectorNodeSelectionSnapshot.object_id` locate the object, while
`VectorNodeSelectionSnapshot.role` and `VectorNodeSelectionSnapshot.node_index`
locate the selected point.

## Vector Text State

`VectorTextStyle.families` lists requested font families,
`VectorTextStyle.font_size` sets logical size, and `VectorTextStyle.weight` plus
`VectorTextStyle.italic` set emphasis. `VectorTextStyle.letter_spacing` changes
tracking and `VectorTextStyle.color` supplies character color.

A `VectorTextSpan.start` and `VectorTextSpan.length` select a character range,
while `VectorTextSpan.style` supplies that range's override.

`VectorTextAlignment.LEFT`, `VectorTextAlignment.CENTER`,
`VectorTextAlignment.RIGHT`, and `VectorTextAlignment.JUSTIFY` choose line
placement. `VectorTextDirection.AUTO` follows detected script direction,
`VectorTextDirection.LEFT_TO_RIGHT` forces forward flow, and
`VectorTextDirection.RIGHT_TO_LEFT` forces reverse flow.

`VectorParagraphStyle.alignment`, `VectorParagraphStyle.direction`, and
`VectorParagraphStyle.line_height` combine line placement, logical direction,
and spacing. `VectorTextContent.text` contains Unicode content,
`VectorTextContent.style` supplies its base style,
`VectorTextContent.spans` supplies range overrides, and
`VectorTextContent.paragraph` supplies block layout.

A `VectorTextEditSnapshot.scene_id`, `VectorTextEditSnapshot.layer_id`, and
`VectorTextEditSnapshot.object_id` identify the edit target.
`VectorTextEditSnapshot.text` contains working content,
`VectorTextEditSnapshot.cursor` contains the insertion index, and
`VectorTextEditSnapshot.is_new` distinguishes creation from editing.

`TextFontResolution.requested_families` records the requested fallback list,
`TextFontResolution.resolved_family` reports the family Qt chose, and
`TextFontResolution.exact_match` says whether the first choice was available.

## Vector Masks

A `VectorMaskSnapshot.scene_id` and `VectorMaskSnapshot.layer_id` identify the
masked target. `VectorMaskSnapshot.vector_id` identifies the source vector
document, `VectorMaskSnapshot.object_ids` selects its objects,
`VectorMaskSnapshot.transform` maps their coordinates to the target, and
`VectorMaskSnapshot.inverted` reports whether coverage is reversed.

## Related Docs

* [Host Cookbook](host-cookbook.md): Commands and signals that produce these
  values.
* [Documents and Layers](scenes.md): Build the document tree and apply policy.
* [Painting](painting.md): Configure brushes and raster targets.
* [Vector Layers](vector-layers.md): Create and edit retained content.

**Continue →** [API Reference](api-reference.md)
