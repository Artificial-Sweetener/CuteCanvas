**← Previous:** [Catalog and Navigation](catalog-and-navigation.md)

# Scene Composition

Scene composition lets a host build an independent document with its own canvas, ordered layers, comparison state, selection, and edit history. A catalog image is a reusable source resource, not the document root. Images, editable rasters, masks, placed assets, and vectors participate as ordinary layer instances in the same stack.

Use composition documents for editor canvases, contact sheets, review grids, or two-up layouts. Normal catalog navigation remains a convenient viewer workflow: each catalog image receives a generated one-image composition and `setCurrentImageID` opens it.

## Create A Document

Create an empty canvas when the composition should not be anchored to an image:

```python
from PySide6.QtCore import QRectF
from qpane import QPaneCompositionPolicy, QPaneLayerInteractionPolicy

composition_id = viewer.createComposition(
    QRectF(0, 0, 1920, 1080),
    title="Untitled composition",
    policy=QPaneCompositionPolicy(
        removable=True,
        comparison_enabled=True,
    ),
)
```

The canvas bounds remain authoritative even when the document is empty or every layer is moved away from it. Adding, removing, or transforming a layer does not resize the canvas.

`QPaneCompositionPolicy` is the host-owned document policy. `QPaneCompositionPolicy.removable` controls document removal, while `QPaneCompositionPolicy.comparison_enabled` controls whether the document may own an active comparison source. Change both atomically with `QPane.setCompositionPolicy`.

To seed a document from an existing catalog resource, use `QPane.createCompositionFromImage`. Seeding copies the source dimensions into the initial canvas and inserts one ordinary image layer. It does not make that layer structurally special.

```python
editable_image = QPaneLayerInteractionPolicy(
    selectable=True,
    movable=True,
    reorderable=True,
    removable=True,
)
composition_id = viewer.createCompositionFromImage(
    image_id,
    title="Retouch",
    interaction=editable_image,
)
```

Hosts that want a frozen background pass a different policy. Intrinsic source capability and host permission are both required: allowing pixel edits does not make a non-rasterized placed asset paintable, and a technically editable raster remains locked when policy disables the operation.

Add the same catalog source to any active composition with a new independent instance:

```python
layer_id = viewer.addCatalogImageLayer(
    image_id,
    placement=QRectF(240, 120, 960, 540),
    label="Reference",
    interaction=editable_image,
)
```

Multiple instances of the same source share revisions, pyramids, tiles, and other source render products. Their transforms, order, visibility, effects, policy, and damage remain composition-local. Removing an instance never deletes the catalog resource. Removing a catalog resource prunes layers that reference it; independent documents and layers backed by other domains remain intact.

## Compose An Ad-Hoc Scene

Start with catalog image IDs. A `QPaneSceneRequest` is the host's command to store a scene composition, and each `QPaneCatalogImageLayerRequest` inside it points at one catalog image. Build the request the same way you would build a UI layout: choose a scene rectangle, choose a slot for one layer, fit the image into that slot, then add more layers.

```python
import uuid

from PySide6.QtCore import QRectF
from qpane import QPane, QPaneCatalogImageLayerRequest, QPaneSceneRequest

ids = viewer.imageIDs()
catalog = viewer.getCatalogSnapshot()
left_cell = QRectF(0, 0, 320, 320)

left_layer = QPaneCatalogImageLayerRequest(
    layer_id=uuid.uuid4(),
    image_id=ids[0],
    placement=QPane.fitSceneRect(catalog.catalog[ids[0]].image.size(), left_cell),
)

request = QPaneSceneRequest(
    composition_id=None,
    title="Review grid",
    bounds=QRectF(0, 0, 640, 320),
    layers=(left_layer,),
)
```

`QPaneSceneRequest.composition_id` is `None` when QPane should generate a new stored composition ID. Provide an existing host-created scene composition ID when the host wants to replace that scene in place. `QPaneSceneRequest.title` is the browser label, `QPaneSceneRequest.bounds` is the scene-coordinate canvas, and `QPaneSceneRequest.layers` is the draw order.

For the first layer, `QPaneCatalogImageLayerRequest.layer_id` is the stable host ID for the layer, `QPaneCatalogImageLayerRequest.image_id` selects the catalog image, and `QPaneCatalogImageLayerRequest.placement` places it inside the scene. Placement is exact: QPane maps the source pixels into that rectangle. If a host passes a square slot for a portrait image, the image stretches to the square. `QPane.fitSceneRect` avoids that distortion by returning the largest centered rectangle that fits inside the slot while preserving the source aspect ratio.

When a host wants a tight thumbnail grid, it can use the fitted rectangle as the item being packed. Fit each image into a local slot, move the returned rectangle beside the previous fitted rectangle, and use the requested gap between those actual placements. That keeps portrait thumbnails close together without asking QPane to invent layout policy.

Once that shape is clear, add the second layer beside it.

```python
right_cell = QRectF(320, 0, 320, 320)

request = QPaneSceneRequest(
    composition_id=None,
    title="Review grid",
    bounds=QRectF(0, 0, 640, 320),
    layers=(
        left_layer,
        QPaneCatalogImageLayerRequest(
            layer_id=uuid.uuid4(),
            image_id=ids[1],
            placement=QPane.fitSceneRect(
                catalog.catalog[ids[1]].image.size(),
                right_cell,
            ),
            role="thumbnail",
            metadata={"slot": 1},
        ),
    ),
)

composition_id = viewer.composeScene(request)
```

Add `QPaneCatalogImageLayerRequest.role` and `QPaneCatalogImageLayerRequest.metadata` when the host needs context later in hit tests, overlays, or sidebars. In the example above, a hit or overlay can read the `"thumbnail"` role and the metadata slot to know which catalog cell the user is pointing at.

Use `QPane.fillSceneRect` for cover-style layouts. It returns the smallest centered rectangle that covers the target slot while preserving the source aspect ratio, so the result may extend outside the slot. When the host wants that cover result clipped back to the slot, pass the returned placement on the layer and add a `QPaneSceneClip` for the visible cell.

Use the optional layer controls as refinements instead of rebuilding the scene model. `QPaneCatalogImageLayerRequest.visible` hides a layer while keeping its definition in the stored scene. `QPaneCatalogImageLayerRequest.opacity` lets a host show transparent reference layers. `QPaneCatalogImageLayerRequest.clip` trims a layer to a clip rectangle, and `QPaneCatalogImageLayerRequest.hit_test` decides whether that layer can be returned from `QPane.sceneHitTest`.

## Enable Direct Layer Movement

Layers are locked by default. Set `QPaneCatalogImageLayerRequest.interaction` when composing a scene, or call `QPane.setLayerInteractionPolicy` later, to let the built-in Move tool select and translate a layer. Movement policy belongs to the layer instance, so the tool uses the same path for catalog images and masks.

```python
from qpane import QPaneLayerInteractionPolicy

movable = QPaneLayerInteractionPolicy(selectable=True, movable=True)
layer = QPaneCatalogImageLayerRequest(
    layer_id=uuid.uuid4(),
    image_id=ids[0],
    placement=QRectF(0, 0, 320, 320),
    interaction=movable,
)

viewer.setControlMode(QPane.CONTROL_MODE_MOVE)
```

During a drag, QPane applies a transient affine-transform preview and commits one exact transform on release. Rotation, reflection, scale, and shear remain intact while the layer translates. Source pixels and source revisions do not change. Call `QPane.undoSceneEdit` and `QPane.redoSceneEdit` for scene-scoped transform history, and use `QPane.sceneEditHistoryChanged` to keep Undo and Redo actions enabled correctly.

Use `QPane.sceneEditUndoAvailable` and `QPane.sceneEditRedoAvailable` to seed action state before the first history signal arrives. `QPane.setLayerPlacement` retains its rectangular contract: it maps the layer's local bounds exactly onto the requested scene rectangle. `QPane.setLayerTransform` accepts an invertible affine `QTransform` when the host needs exact rotation, reflection, scale, shear, and translation. `QPane.layerTransform` returns a detached copy of that authoritative value, while `QPane.layerLocalBounds` returns detached intrinsic bounds without requiring raster-storage access. The `QPaneSceneLayer.placement` field is the conservative axis-aligned scene bound derived from `QPaneSceneLayer.transform`; it is not a second geometry authority.

Hosts can change policy at any time:

```python
viewer.setLayerInteractionPolicy(scene_id, layer_id, movable)
viewer.setLayerPlacement(scene_id, layer_id, QRectF(24, 12, 320, 320))

transform = viewer.layerTransform(scene_id, layer_id)
transform.rotate(15)
viewer.setLayerTransform(scene_id, layer_id, transform)
```

Layer order is the composition's render order. Use `QPane.setLayerIndex(scene_id, layer_id, index)` to move an active layer, where index `0` is bottommost. The change is one scene-history command and the demonstration presents the same order topmost-first in its composition tree.

Selection respects actual source coverage. Transparent mask pixels fall through to covered layers, while painted mask pixels select the mask. Moving a mask also moves its brush, SAM selection, and component-adjustment coordinate space.

`QPaneLayerInteractionPolicy` is the host-owned permission set for direct and structural layer editing. `QPaneLayerInteractionPolicy.selectable` controls covered-pixel selection, `QPaneLayerInteractionPolicy.movable` controls transforms, `QPaneLayerInteractionPolicy.pixel_editable` permits raster mutation when the source supports it, `QPaneLayerInteractionPolicy.reorderable` controls stack changes, and `QPaneLayerInteractionPolicy.removable` controls instance removal. Use `QPane.removeLayer` for a policy-enabled layer and `QPane.setLayerIndex` for a reorderable layer. The normalized `QPaneSceneLayer.interaction` value lets an inspector display the effective policy. Reusable layouts carry the same policy in `QPaneTemplateLayer.interaction`, so scenes composed from templates behave like directly authored scenes.

`QPane.composeScene` stores the request as a layered scene composition and returns the composition UUID. With the default `activate=True`, QPane opens the new composition immediately and fits the scene bounds when `fit_view=True`. With `activate=False`, QPane stores the composition without changing selection; if the request replaces the already active scene composition, QPane still emits `QPane.sceneChanged` because the active normalized scene changed.

QPane stores detached scene data. Later changes to the request objects passed to `QPane.composeScene` do not alter stored compositions. To update a stored scene, compose a replacement request with the same `QPaneSceneRequest.composition_id`.

## Store, Open, Replace, And Remove

Scene lifecycle uses one composition browser API. `QPane.compositionIDs` returns browser order, `QPane.currentCompositionID` returns the active composition UUID, and `QPane.openComposition` reopens a document. `QPane.getCompositionSnapshot` provides the canvas, detached layer rows, and document policy. `QPane.setCompositionPolicy` changes removal and comparison permission, and `QPane.removeComposition` removes any document whose current policy permits it. Generated catalog-navigation documents use a non-removable policy and disappear with their catalog resource.

```python
composition_id = viewer.composeScene(request, activate=False)
viewer.openComposition(composition_id)

snapshot = viewer.getCompositionSnapshot()
for row_id in snapshot.order:
    row = snapshot.compositions[row_id]
    print(row.title, row.kind)
```

Calling `QPane.setCurrentImageID` from an active scene opens that image's generated default composition. `QPane.currentImageID` remains the catalog selection value; `QPane.currentCompositionID` is the authoritative answer for which stored view QPane is rendering.

## Compose From A Template

Templates are host-owned value objects. QPane does not keep a template registry; it stores only the composition produced when the host combines a `QPaneSceneTemplate` with `QPaneSceneTemplateBindings`.

Build the template around reusable slots. `QPaneSceneTemplate.template_id` is the host's reusable template identifier, `QPaneSceneTemplate.bounds` is the scene rectangle every call will fill, `QPaneSceneTemplate.layers` holds the reusable layer layout, and `QPaneSceneTemplate.title` is the default browser label.

Start each `QPaneTemplateLayer` with the fields that make the slot useful:

* `QPaneTemplateLayer.layer_id` is the stable host key for that layer.
* `QPaneTemplateLayer.source_slot` is the binding name the host will fill later.
* `QPaneTemplateLayer.placement` is where the eventual catalog image appears inside the composed scene.

Then add the same refinements you would add to a one-off scene layer. Use `QPaneTemplateLayer.visible` for hidden template layers, `QPaneTemplateLayer.opacity` for transparency, `QPaneTemplateLayer.clip` for clipped layers, and `QPaneTemplateLayer.hit_test` for pointer behavior. Use `QPaneTemplateLayer.role` and `QPaneTemplateLayer.metadata` when hits, overlays, or browser rows need host context from the template.

When the host calls the template, `QPaneSceneTemplateBindings.catalog_images` maps each slot to a catalog image UUID. `QPaneSceneTemplateBindings.composition_id` selects the stored composition ID or lets QPane generate one, `QPaneSceneTemplateBindings.title` overrides the template title for this call, and `QPaneSceneTemplateBindings.metadata` adds slot-level metadata that merges into the resulting scene layers.

```python
from qpane import QPaneSceneTemplate, QPaneSceneTemplateBindings, QPaneTemplateLayer

template = QPaneSceneTemplate(
    template_id=uuid.uuid4(),
    title="Two-up",
    bounds=QRectF(0, 0, 640, 320),
    layers=(
        QPaneTemplateLayer(
            layer_id=uuid.uuid4(),
            source_slot="left",
            placement=QRectF(0, 0, 320, 320),
        ),
        QPaneTemplateLayer(
            layer_id=uuid.uuid4(),
            source_slot="right",
            placement=QRectF(320, 0, 320, 320),
        ),
    ),
)

composition_id = viewer.composeSceneFromTemplate(
    template,
    QPaneSceneTemplateBindings(
        composition_id=None,
        title="Catalog pair",
        catalog_images={"left": ids[0], "right": ids[1]},
    ),
)
```

`QPane.composeSceneFromTemplate` expands the template into the same stored scene composition shape as `QPane.composeScene`. Every template source slot used by a layer must appear in the binding map, extra bindings are ignored, and the stored composition has no dependency on the template object after composition.

## Clip Layers

Use `QPaneSceneClip` when a layer should render or hit-test through a rectangle. `QPaneSceneClip.coordinate_space` selects whether `QPaneSceneClip.rect` is in scene coordinates, normalized scene coordinates, viewport coordinates, or normalized viewport coordinates. Keep clip rectangles simple and deterministic; QPane uses them while deciding which catalog-backed tile work is visible.

## Update UI From The Active Scene

Use `QPane.currentScene` when a sidebar, inspector, or status bar needs to describe the scene QPane is rendering right now. It returns a detached `QPaneScene` snapshot for generated default image compositions and host-authored layered scenes, or `None` when no renderable composition is active. The snapshot is read-only host information; hosts do not pass it back to compose a new scene.

```python
def refresh_scene_panel():
    scene = viewer.currentScene()
    if scene is None:
        scene_title.setText("No scene")
        layer_list.clear()
        return

    scene_title.setText(scene.title)
    scene_size.setText(f"{scene.bounds.width():.0f} x {scene.bounds.height():.0f}")
    layer_list.clear()
    for layer in scene.layers:
        layer_list.addItem(f"{layer.role}: {layer.image_id}")
```

Use the `QPaneScene` fields for different UI jobs:

* `QPaneScene.composition_id` is the stored composition ID your UI can compare with `QPane.currentCompositionID`.
* `QPaneScene.scene_id` is the render-scene identity used by hit testing and overlay state; it helps hosts ignore stale async UI work.
* `QPaneScene.title` is the practical sidebar label for the active scene.
* `QPaneScene.bounds` gives the scene size or canvas rectangle for inspector text.
* `QPaneScene.layers` is the ordered layer list to render in an inspector.

Layer rows usually need three kinds of information from each `QPaneSceneLayer` object.

* Identity: `QPaneSceneLayer.layer_id` is the host layer key, and `QPaneSceneLayer.image_id` is the catalog image behind the layer.
* Layout: `QPaneSceneLayer.placement` is the scene rectangle to show in an inspector.
* Display and interaction: `QPaneSceneLayer.visible`, `QPaneSceneLayer.opacity`, `QPaneSceneLayer.clip`, and `QPaneSceneLayer.hit_test` drive badges and disabled states.
* Host context: `QPaneSceneLayer.role` and `QPaneSceneLayer.metadata` are the values you attached when composing the scene.

`QPane.sceneChanged` emits whenever this normalized active scene snapshot changes. Connect it when a panel should refresh after `QPane.composeScene`, `QPane.composeSceneFromTemplate`, `QPane.openComposition`, `QPane.setCurrentImageID`, or removal of the active composition.

## Navigate From A Scene Hit

`QPane.sceneHitTest` accepts a widget-space point and returns the topmost hit-testable scene layer under that point. The result is passive: QPane does not change catalog selection, composition selection, comparison state, or layer selection. Hosts decide whether a hit opens a catalog image, selects a layer row, shows a detail panel, or does nothing.

```python
def handle_scene_click(event):
    hit = viewer.sceneHitTest(event.position().toPoint())
    if hit is None:
        return

    if hit.composition_id != viewer.currentCompositionID():
        return

    select_layer(hit.layer_id)
    if hit.role == "thumbnail":
        viewer.setCurrentImageID(hit.image_id)
```

The `QPaneSceneHit` object gives the host enough context to make that decision.

* Use `QPaneSceneHit.composition_id` and `QPaneSceneHit.scene_id` to confirm which active view produced the hit.
* Use `QPaneSceneHit.layer_id` when the host selects the matching row in a layer list.
* Use `QPaneSceneHit.image_id` when the host opens the catalog image.
* Use `QPaneSceneHit.role` and `QPaneSceneHit.metadata` when different layer roles trigger different host behavior.
* Use `QPaneSceneHit.panel_point`, `QPaneSceneHit.scene_point`, and `QPaneSceneHit.source_point` when follow-up UI needs widget, scene, or source-image coordinates.

## Draw Labels And Outlines With Scene Overlays

Use scene overlays for host chrome tied to active layered scene compositions, such as labels, badges, hover outlines, and selection rectangles. Register a callback with `QPane.registerSceneOverlay`, remove it with `QPane.unregisterSceneOverlay`, and inspect registered callbacks with the read-only snapshot returned by `QPane.sceneOverlays`.

```python
from PySide6.QtCore import Qt

def draw_labels(painter, state):
    painter.setPen(Qt.white)
    for layer in state.layers:
        if not layer.visible:
            continue
        painter.drawText(layer.panel_bounds.adjusted(6, 6, -6, -6), layer.role)

viewer.registerSceneOverlay("labels", draw_labels)
```

The callback receives `QPaneSceneOverlayState` for the active scene.

* Use `QPaneSceneOverlayState.zoom` when stroke widths or text sizes should scale with zoom.
* Use `QPaneSceneOverlayState.qpane_rect` to anchor widget chrome such as a scene-level badge.
* Use `QPaneSceneOverlayState.physical_viewport_rect` when device-pixel alignment matters.
* Use `QPaneSceneOverlayState.composition_id`, `QPaneSceneOverlayState.scene_id`, and `QPaneSceneOverlayState.scene_bounds` to identify the active scene being annotated.
* Iterate `QPaneSceneOverlayState.layers` when drawing per-layer labels, outlines, badges, or hover chrome.

Each `QPaneSceneOverlayLayer` is already mapped for overlay drawing.

* Use `QPaneSceneOverlayLayer.panel_bounds` for labels or outlines.
* Use `QPaneSceneOverlayLayer.visible` to skip hidden layers so overlays match what QPane rendered.
* Use `QPaneSceneOverlayLayer.transform` when you need to map source-image pixels into widget coordinates.
* Use `QPaneSceneOverlayLayer.source_size` for source-pixel math.
* Use `QPaneSceneOverlayLayer.placement` when overlay text should include scene coordinates.
* Use `QPaneSceneOverlayLayer.layer_id`, `QPaneSceneOverlayLayer.image_id`, `QPaneSceneOverlayLayer.role`, and `QPaneSceneOverlayLayer.metadata` to connect overlay decisions back to host scene data.

Scene overlays draw chrome only. They do not render image pixels and they do not own navigation or selection policy.

## Browser Rows For Scene Compositions

Composition snapshots let hosts show scene compositions next to generated default image compositions and explicit comparison compositions. In a browser, `CompositionSnapshot.order` is the row order, `CompositionSnapshot.compositions` maps each row ID to a `CompositionEntry`, and `CompositionSnapshot.current_composition_id` marks the selected row.

Use the row entry to decide what the browser shows.

* `CompositionEntry.composition_id` is the value to pass to `QPane.openComposition` when the row is clicked.
* `CompositionEntry.title` is the row label.
* `CompositionEntry.kind` tells the browser whether to draw an image row, explicit composition row, or scene row.
* `CompositionEntry.source_image_ids` can drive thumbnails or source-count badges.
* `CompositionEntry.current_image_id` is the base catalog image for image-backed row actions.
* `CompositionEntry.comparison` lets the browser show a comparison badge.
* `CompositionEntry.scene_layer_count` reports the complete stored stack, and `CompositionEntry.layers` exposes detached bottom-to-top `CompositionLayerEntry` values so hosts can render every composition and layer without activating each composition.
* `CompositionEntry.scene_bounds` gives compact scene geometry for layered scenes.

## Constraints

Scene layers include catalog-backed images, masks, and composition-owned editable RGBA rasters. Hosts should not flatten arranged scenes into temporary images just to render them; retaining source identity lets QPane reuse the normal rendering, culling, diagnostics, hit-testing, editing, and history paths.

## Place Non-Destructive Image Sources

Use `QPane.placeEmbeddedAsset` when the host already owns decoded pixels. Use `QPane.placeLinkedAsset` when the composition should retain a filesystem relationship. Linked placement, refresh, relink, and rasterization return request UUIDs and complete through `QPane.placedAssetRequestCompleted`; image decoding and raster output work do not block the GUI thread.

```python
from pathlib import Path

request_id = viewer.placeLinkedAsset(
    Path("artwork/title-card.png"),
    label="Title card",
)

def placed_finished(request_id, scene_id, layer_id, succeeded, message):
    if not succeeded:
        show_non_modal_error(message)
        return
    if layer_id is not None:
        viewer.setSelectedLayer(scene_id, layer_id)

viewer.placedAssetRequestCompleted.connect(placed_finished)
```

`QPane.placedAssetState` returns a detached `QPanePlacedAssetState` that a host can inspect without gaining mutation access to internal source state. `QPanePlacedAssetState.scene_id` and `QPanePlacedAssetState.layer_id` identify the exact layer instance, while `QPanePlacedAssetState.asset_id` identifies the shared source behind independently arranged duplicates.

`QPanePlacedAssetState.mode` uses `PlacedAssetMode` to describe persistence: `PlacedAssetMode.EMBEDDED` means the composition owns the pixels, while `PlacedAssetMode.LINKED` means the source retains a refreshable filesystem relationship. `QPanePlacedAssetState.status` uses `PlacedAssetStatus` to report availability: `PlacedAssetStatus.READY` follows a successful decode, `PlacedAssetStatus.LOADING` marks pending work, `PlacedAssetStatus.MISSING` reports an unavailable file, and `PlacedAssetStatus.ERROR` reports a decode failure.

`QPanePlacedAssetState.source_path` contains the linked locator or `None` for embedded content. `QPanePlacedAssetState.keep_fallback` controls whether private archives retain last-known linked pixels, and `QPanePlacedAssetState.error` carries the latest non-modal failure. `QPanePlacedAssetState.content_revision` advances when decoded pixels change, while `QPanePlacedAssetState.generation` lets QPane reject stale asynchronous work.

Duplicate instances created with `QPane.duplicatePlacedAsset` share that source state while their layer UUIDs and transforms remain independent.

`QPane.refreshPlacedAsset` observes external file changes without entering document history. `QPane.relinkPlacedAsset` and `QPane.embedPlacedAsset` are document edits and undo to the exact prior provenance. Missing or corrupt refreshes keep the last valid display pixels. Private composition archives retain linked fallback pixels only when `QPanePlacedAssetState.keep_fallback` is true.

Call `QPane.rasterizePlacedAsset` when editing should become destructive. QPane produces a premultiplied RGBA raster at the requested `QSize` (or the natural source size), preserves the displayed affine geometry, and swaps the layer source as one undoable edit. Undo restores the placed source; redo restores the same editable raster resource.

While a layered scene composition is active, image-scoped mask and comparison mutation APIs do not operate on a stale catalog selection. Open a generated default image composition or an explicit image composition before editing active image masks or comparison state.

**Continue →** [Interaction Modes](interaction-modes.md)

## Paint Layers, Masks, and Painted Selections

The shared brush operates on an explicit destination. Create an empty authoring
layer with `QPane.createPaintLayer`, or select an existing pixel-editable layer
with `QPane.setPaintTarget`. `QPane.paintTargetState` returns a
`QPanePaintTargetState`; inspect `QPanePaintTargetState.scene_id`,
`QPanePaintTargetState.layer_id`, `QPanePaintTargetState.kind`, and
`QPanePaintTargetState.source_kind` when a host needs to update contextual UI.

```python
from PySide6.QtGui import QColor
from qpane import BrushDynamics, BrushPreset, PaintTargetKind, RasterExtentPolicy

layer_id = viewer.createPaintLayer(
    label="Highlights",
    extent_policy=RasterExtentPolicy.UNBOUNDED,
)
if layer_id is not None:
    viewer.setPaintColor(QColor(255, 120, 40, 210))
    viewer.setBrushPreset(
        BrushPreset(
            name="Soft pressure",
            size=48.0,
            hardness=0.2,
            opacity=0.8,
            flow=0.25,
            dynamics=BrushDynamics(
                pressure_size=1.0,
                pressure_opacity=0.5,
            ),
        )
    )
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)

target = viewer.paintTargetState()
if target is not None and target.kind is PaintTargetKind.LAYER:
    show_layer_target(target.layer_id)
```

`qpane.BrushOperation` defines the shared operations.
`BrushOperation.PAINT` and `BrushOperation.ERASE` describe the two shared
operations. The built-in tool uses paint normally and erase while Alt is held
or an active pen's eraser tip is in contact. `BrushPreset` retains size,
hardness, opacity, flow, spacing, smoothing, angle, and `BrushDynamics`; call
`QPane.brushPreset` to copy the current value, `QPane.setBrushPreset` to replace
it, and `QPane.setBrushSize` for a size-only update. RGBA targets use the color
returned by `QPane.paintColor`; `QPane.setPaintColor` accepts alpha as well as
RGB.

For host editors, `BrushPreset.name` is the menu label and `BrushPreset.size`
is the target-pixel diameter. `BrushPreset.hardness` controls edge falloff,
`BrushPreset.opacity` caps deposition, `BrushPreset.flow` controls accumulation,
and `BrushPreset.spacing` controls dab frequency. `BrushPreset.smoothing`
stabilizes the sampled path, `BrushPreset.angle` retains tip rotation, and
`BrushPreset.texture_strength`, `BrushPreset.texture_scale`, and
`BrushPreset.texture_seed` define deterministic procedural grain.
`BrushPreset.dynamics` contains the pointer-response mapping.

Within that mapping, `BrushDynamics.pressure_size` and
`BrushDynamics.pressure_opacity` set dynamic strength.
`BrushDynamics.minimum_pressure_ratio` and `BrushDynamics.pressure_gamma`
shape the response curve. `BrushDynamics.position_jitter`,
`BrushDynamics.size_jitter`, and `BrushDynamics.angle_jitter` use the retained
stroke seed so repeated rendering stays deterministic.
`BrushDynamics.rotation_angle`, `BrushDynamics.tilt_angle`, and
`BrushDynamics.tangential_opacity` map rich tablet orientation and barrel
pressure into the same target-neutral dabs.

Masks remain coverage layers. Selecting a mask with `QPane.setPaintTarget`
uses the same samples, pressure dynamics, deterministic spacing, preview, and
stroke transaction while retaining the mask's overlay color and coverage
storage. To paint the composition selection, call
`QPane.setPixelSelectionPaintTarget`; its `QPanePaintTargetState.kind` is
`qpane.PaintTargetKind` supplies the target categories.
`PaintTargetKind.LAYER` identifies a layer destination, while
`PaintTargetKind.PIXEL_SELECTION` identifies selection coverage; its
layer/source fields are `None`, and it
edits the same selection returned by `QPane.pixelSelectionState`. There is no
parallel selection store.

Connect `QPane.paintTargetChanged`, `QPane.brushPresetChanged`, and
`QPane.paintColorChanged` to keep a contextual brush bar synchronized. Call
`QPane.clearPaintTarget` when the host deliberately leaves painting rather
than silently redirecting future strokes.

## Semantic Vector Layers

Vector layers use the same composition order, interaction policy, affine layer
transform, and chronological history as raster and mask layers. Create one with
`QPane.createVectorLayer`, inspect it with `QPane.vectorDocumentState`, and keep
the returned `QPaneVectorDocumentState.scene_id`,
`QPaneVectorDocumentState.layer_id`, `QPaneVectorDocumentState.vector_id`,
`QPaneVectorDocumentState.revision`, and `QPaneVectorDocumentState.objects` as
detached UI state.

`QPaneVectorDocumentState` is the immutable host snapshot of one current
semantic vector document. `QPaneVectorObjectState` is the corresponding
detached snapshot for each ordered object in that document.

`VectorShapeKind` keeps supported shapes parametric instead of quietly turning
them into pixels. `VectorPathCommand` is the durable geometry value for paths,
and `VectorPathCommandKind` identifies how each command consumes its points.

`QPane.addVectorShape` creates one editable parametric object and records one
history transition. `QPane.addVectorPath` does the same for an explicit ordered
command stream, preserving every control point for later editing.

```python
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QTransform
from qpane import (
    VectorFillRule,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
)

scene = viewer.currentScene()
layer_id = viewer.createVectorLayer(label="Annotations")
if scene is not None and layer_id is not None:
    style = VectorStyle(
        fill=QColor(40, 180, 240, 150),
        stroke=QColor(255, 255, 255),
        stroke_width=3.0,
        fill_rule=VectorFillRule.WINDING,
    )
    ellipse_id = viewer.addVectorShape(
        scene.scene_id,
        layer_id,
        VectorShapeKind.ELLIPSE,
        QRectF(40.0, 30.0, 160.0, 100.0),
        style,
    )
    path_id = viewer.addVectorPath(
        scene.scene_id,
        layer_id,
        (
            VectorPathCommand(
                VectorPathCommandKind.MOVE,
                (QPointF(24.0, 24.0),),
            ),
            VectorPathCommand(
                VectorPathCommandKind.LINE,
                (QPointF(180.0, 80.0),),
            ),
        ),
        VectorStyle(fill=None, stroke=QColor(255, 120, 60)),
    )
```

`VectorObjectKind` identifies the semantic category without deciding how the
layer itself is selected or transformed. `VectorObjectKind.PATH` describes a
command path, `VectorObjectKind.SHAPE` describes parametric geometry, and
`VectorObjectKind.TEXT` reserves the semantic text category.

`VectorShapeKind.RECTANGLE` retains editable rectangular parameters, while
`VectorShapeKind.ELLIPSE` retains editable elliptical parameters. Neither uses
raster alpha as authoritative geometry.

Command paths retain `VectorPathCommand.kind` and `VectorPathCommand.points` as
their exact serializable operation and control-point values.
`VectorPathCommandKind.MOVE` starts a subpath and `VectorPathCommandKind.LINE`
adds a straight segment. `VectorPathCommandKind.QUADRATIC` and
`VectorPathCommandKind.CUBIC` add their respective Bézier segments, while
`VectorPathCommandKind.CLOSE` closes the current subpath.

`QPaneVectorObjectState.object_id`, `QPaneVectorObjectState.kind`,
`QPaneVectorObjectState.bounds`, `QPaneVectorObjectState.transform`,
`QPaneVectorObjectState.style`, `QPaneVectorObjectState.shape_kind`, and
`QPaneVectorObjectState.path` are detached snapshots. `QPane.updateVectorObject`
changes an object's `QTransform` and/or `VectorStyle`; use
`QPane.removeVectorObject` and `QPane.reorderVectorObject` for lifecycle and
object z-order edits.

`VectorStyle` retains semantic appearance independently from the derived render
cache. `VectorStyle.fill` supplies interior color, while `VectorStyle.stroke`
supplies the outline color or disables it with `None`.

`VectorStyle.stroke_width` controls outline thickness and `VectorStyle.opacity`
controls object-level compositing. `VectorStyle.dash_pattern` retains positive
alternating dash lengths instead of flattening them into geometry.

`VectorStyle.join` chooses corner geometry through `VectorStrokeJoin`.
`VectorStrokeJoin.MITER` preserves sharp corners, `VectorStrokeJoin.ROUND`
rounds them, and `VectorStrokeJoin.BEVEL` clips them.

`VectorStyle.cap` chooses open-path endpoint geometry through `VectorStrokeCap`.
`VectorStrokeCap.FLAT` stops at the endpoint, `VectorStrokeCap.ROUND` rounds it,
and `VectorStrokeCap.SQUARE` projects a square cap beyond it.

`VectorStyle.fill_rule` retains the interior rule through `VectorFillRule`.
`VectorFillRule.WINDING` uses nonzero winding, while `VectorFillRule.EVEN_ODD`
supports alternating filled regions and holes.

Object selection is a separate authority. Call `QPane.setSelectedVectorObjects`
and inspect `QPane.vectorSelectionState`; `QPaneVectorSelectionState.scene_id`,
`QPaneVectorSelectionState.layer_id`, and `QPaneVectorSelectionState.object_ids`
identify the exact selection. `QPane.clearVectorSelection` clears it, and
`QPane.vectorSelectionChanged` keeps contextual host UI synchronized without
changing the selected layer or `QPane.pixelSelectionState`.

`QPaneVectorSelectionState` is the immutable host value for this independent
selection authority; it never stores pixel coverage or layer-selection policy.

Control-point selection is narrower and remains independent as well. Activate
`ControlMode.VECTOR_NODE` or `QPane.CONTROL_MODE_VECTOR_NODE`, select an object,
then drag an anchor, Bézier control point, or parametric-shape bounds handle.
`QPane.vectorNodeSelectionState` returns a `QPaneVectorNodeSelectionState` with
the scene, layer, object, stable node index, and `VectorNodeRole`.
`QPane.vectorNodeSelectionChanged` keeps contextual host UI synchronized.
`QPaneVectorNodeSelectionState.scene_id` and
`QPaneVectorNodeSelectionState.layer_id` identify the authoring target,
`QPaneVectorNodeSelectionState.object_id` identifies the semantic object,
`QPaneVectorNodeSelectionState.node_index` identifies its stable handle, and
`QPaneVectorNodeSelectionState.role` is `VectorNodeRole.ANCHOR`,
`VectorNodeRole.CONTROL`, or `VectorNodeRole.BOUNDS`.

Node motion is a transient semantic preview while the pointer is held. Releasing
the pointer records the complete geometry change as one scene-history command;
Escape restores the durable geometry. Holding Space temporarily enters pan/zoom
without discarding or snapping the preview. The same direct-selection tool edits
a visible vector layer or a vector mask attached to another layer.

Activate the parametric creation tool with `ControlMode.VECTOR_SHAPE` or its
widget constant `QPane.CONTROL_MODE_VECTOR_SHAPE`. Activate explicit node-path
construction with `ControlMode.VECTOR_PATH` or
`QPane.CONTROL_MODE_VECTOR_PATH`; Enter commits its current open path, Alt+Enter
closes it, and Escape discards only unresolved nodes.

Use `QPane.vectorToolShape` to read the last-used parametric kind and
`QPane.setVectorToolShape` to switch rectangles and ellipses. Use
`QPane.vectorToolStyle` to read the common creation appearance and
`QPane.setVectorToolStyle` to update it for both tools. The
`QPane.vectorToolOptionsChanged` signal carries both values so a compact
contextual toolbar can stay synchronized without inspecting tool internals.

Vector-to-raster operations are explicit and non-blocking. To derive a pixel
selection from the active object selection, or from the whole document when no
objects are selected, call `QPane.convertVectorToPixelSelection`. Pass an
explicit object-ID iterable to override that choice and a `PixelSelectionMode`
to add, subtract, or intersect through the existing selection authority.

```python
request_id = viewer.convertVectorToPixelSelection(
    scene.scene_id,
    layer_id,
    (ellipse_id,),
)
```

The conversion includes fill and stroke alpha, dashes, fill rule, object
opacity, object transforms, and the layer transform. It produces soft
scene-space coverage and records one normal pixel-selection edit; vector
geometry remains authoritative and unchanged.

Call `QPane.rasterizeVectorLayer` when the user deliberately wants editable
pixels. The optional `QSize` sets the output dimensions. QPane renders away
from the UI thread and atomically replaces only that composition instance with
an editable RGBA source while preserving its displayed affine quadrilateral.
Undo restores the vector instance and redo restores the retained raster source.

Connect `QPane.vectorRequestCompleted` to present completion or failure. Its
operation value is `pixel-selection`, `editable-raster`, or `text-paths`;
accepted requests emit exactly one terminal result even when superseded,
rejected, or made stale by an intervening edit.

A semantic vector document can become a layer mask without rasterization. Call
`QPane.setVectorMask` with its visible vector layer and the target layer. QPane
removes that vector instance and attaches the same source document to the
target as one atomic stack transition, preserving source-to-scene alignment.
The optional object IDs limit the mask to selected objects; `inverted=True`
reveals the complement inside the target's local bounds.

```python
viewer.setVectorMask(
    scene.scene_id,
    layer_id,
    target_layer_id,
    (ellipse_id,),
)
```

`QPane.vectorMaskState` returns the detached effect state. The target layer is
also a vector authoring context: pass its layer UUID to
`QPane.vectorDocumentState`, `QPane.updateVectorObject`, the vector tools, or
`QPane.convertVectorToPixelSelection`. Input is mapped through the effect
transform back into document space, so editing remains resolution independent.
`QPane.clearVectorMask` removes the effect as one chronological edit; undo and
redo retain the document through the composition resource-lifetime owner.

`QPaneVectorMaskState` is that immutable host snapshot.
`QPaneVectorMaskState.scene_id` and `QPaneVectorMaskState.layer_id` identify the
target instance, while `QPaneVectorMaskState.vector_id` identifies the retained
semantic document. `QPaneVectorMaskState.object_ids` is empty for the whole
document or contains the exact mask subset. `QPaneVectorMaskState.transform`
maps document coordinates into target-local coordinates, and
`QPaneVectorMaskState.inverted` reports complement masking.
## Editing semantic text

Choose `ControlMode.VECTOR_TEXT` (the same value as
`QPane.CONTROL_MODE_VECTOR_TEXT`) after selecting a vector layer. Clicking text
edits it in place; clicking empty vector space creates a text box. The demo's
contextual bar uses `QPane.vectorTextStyle`, `QPane.setVectorTextStyle`,
`QPane.vectorParagraphStyle`, and `QPane.setVectorParagraphStyle`. It commits
with `QPane.commitVectorTextEdit` and cancels with
`QPane.cancelVectorTextEdit`; hosts may also start an existing object with
`QPane.beginVectorTextEdit` and observe `QPane.vectorTextEditChanged` or
`QPane.vectorTextEditState`.

Hosts use `QPane.addVectorText` when adding a complete semantic object without
simulating typing. `QPane.updateVectorText` changes its content or layout box
as one chronological edit, which makes property inspectors predictable.

`VectorTextContent` is the durable payload rather than a derived glyph image.
Its `VectorTextContent.text` remains Unicode, while `VectorTextContent.style`,
`VectorTextContent.spans`, and `VectorTextContent.paragraph` retain the
authoring choices needed for later edits and reshaping.

`VectorTextStyle` describes a requested font rather than a platform-specific
resolved face. The `VectorTextStyle.families` chain enables fallback;
`VectorTextStyle.font_size`, `VectorTextStyle.weight`, and
`VectorTextStyle.italic` describe ordinary typography; and
`VectorTextStyle.letter_spacing` plus `VectorTextStyle.color` complete the
current character appearance.

`VectorTextSpan` overrides the default style over one codepoint range.
`VectorTextSpan.start` identifies its first Python string index,
`VectorTextSpan.length` gives the range length, and `VectorTextSpan.style`
contains the replacement character style. Ordered, non-overlapping spans keep
archive validation and in-place editing deterministic.

`VectorParagraphStyle` controls layout independently from character styling.
Its `VectorParagraphStyle.alignment`, `VectorParagraphStyle.direction`, and
`VectorParagraphStyle.line_height` apply across every wrapped paragraph in the
text box.

`VectorTextAlignment` offers the familiar `VectorTextAlignment.LEFT`,
`VectorTextAlignment.CENTER`, `VectorTextAlignment.RIGHT`, and
`VectorTextAlignment.JUSTIFY` policies. These choices remain semantic when the
text box or layer is resized and transformed.

`VectorTextDirection` can use `VectorTextDirection.AUTO` for Unicode-driven
bidirectional layout. Hosts may request `VectorTextDirection.LEFT_TO_RIGHT` or
`VectorTextDirection.RIGHT_TO_LEFT` when the document's paragraph policy must
override automatic direction detection.

When a workflow requires literal glyph geometry, call
`QPane.convertVectorTextToPaths`. The method returns immediately with a request
UUID while exact outline construction runs away from the UI thread. Observe
`QPane.vectorRequestCompleted` for the `text-paths` outcome. A successful
operation preserves each painted text color as an editable path object and
lands as one undoable document transition; ordinary scaling and rotation do
not require this destructive conversion.

The current document snapshot exposes text as `QPaneVectorObjectState.text`.
An active `QPaneVectorTextEditState` exposes
`QPaneVectorTextEditState.scene_id`, `QPaneVectorTextEditState.layer_id`,
`QPaneVectorTextEditState.object_id`, `QPaneVectorTextEditState.text`,
`QPaneVectorTextEditState.cursor`, and `QPaneVectorTextEditState.is_new`.
`QPane.vectorTextFontResolutions` returns `QPaneTextFontResolution`; its
`QPaneTextFontResolution.requested_families`,
`QPaneTextFontResolution.resolved_family`, and
`QPaneTextFontResolution.exact_match` fields let a host surface fallback.
