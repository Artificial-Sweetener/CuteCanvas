# Host Cookbook

This guide connects CuteCanvas's focused tutorials into the flow of a complete
editor host. It shows which commands belong together and which signals should
drive the surrounding Qt interface.

## Create and Configure the Canvas

Create `CuteCanvas` after `QApplication`. `CuteCanvas.settings` contains the
current detached configuration, and `CuteCanvas.applySettings()` validates and
applies a replacement. `CuteCanvas.installedFeatures` reports the optional
features active in this widget, while `CuteCanvas.maskFeatureAvailable()` and
`CuteCanvas.samFeatureAvailable()` answer the two feature-specific readiness
questions.

`CuteCanvas.editor` returns the focused `EditorFacade`. Its
`DocumentCollection` handles documents, `ToolFacade` handles tool activation,
`SelectionFacade` handles pixel selection, `CoverageFacade` authors coverage,
`EffectsFacade` adds temporary treatments, `HistoryFacade` controls undo and
redo, and `DocumentPersistenceFacade` saves complete editable documents.

`CuteCanvas.setEditorPolicy()` replaces the host's enabled capabilities,
`CuteCanvas.editorPolicy()` returns the current policy, and
`CuteCanvas.editorPolicyChanged` tells toolbars to resolve their enabled state
again. `CuteCanvas.editorOperationState()` explains whether a particular intent
is allowed for the selected document, layer, and pointer position.

## Control the View

`CuteCanvas.setZoomFit()` frames the document, and `CuteCanvas.setZoom1To1()`
shows native physical pixels. `CuteCanvas.applyZoom()` changes scale around an
optional anchor, while `CuteCanvas.currentZoom` and `CuteCanvas.zoomChanged`
keep a status control current. `CuteCanvas.currentViewportRect()` returns the
logical widget area, and `CuteCanvas.viewportRectChanged` reports size or
display-density changes.

`CuteCanvas.panelHitTest()` maps a widget point into image coordinates for
simple image tools. `CuteCanvas.sceneHitTest()` returns the topmost eligible
document layer with panel, document, and source coordinates. Use the latter
when layer identity matters.

`CuteCanvas.placeholderActive()` reports whether no real content is mounted.
The normal viewer navigation behavior remains available through
`CuteCanvas.CONTROL_MODE_PANZOOM`, while `CuteCanvas.CONTROL_MODE_CURSOR`
provides non-navigating pointer inspection.

## Manage Source Images

`CuteCanvas.setImagesByID()` installs an ordered image map. `CuteCanvas.hasImages`
reports whether it contains entries, and `CuteCanvas.imageIDs()` returns their
stable order. `CuteCanvas.allImages` and `CuteCanvas.allImagePaths` provide the
decoded images and paths, while `CuteCanvas.imagePath()` looks up one source.

`CuteCanvas.setCurrentImageID()` opens a catalog image's generated document.
`CuteCanvas.currentImageID`, `CuteCanvas.currentImage`, and
`CuteCanvas.currentImagePath` report the selected source. `CuteCanvas.imageLoaded`
announces completed activation, and `CuteCanvas.currentImageChanged` plus
`CuteCanvas.catalogSelectionChanged` keep host selection UI current.

`CuteCanvas.getCatalogSnapshot()` returns a stable browser snapshot.
`CuteCanvas.catalogChanged` reports structural changes. Use
`CuteCanvas.removeImageByID()` or `CuteCanvas.removeImagesByID()` for selected
sources, and `CuteCanvas.clearImages()` to empty the catalog.

`CuteCanvas.setLinkedGroups()` installs synchronized pan-and-zoom groups, and
`CuteCanvas.linkedGroups()` returns them. `CuteCanvas.setAllImagesLinked()` is
the convenient all-images command. `CuteCanvas.linkGroupsChanged` lets the host
refresh link indicators, and `CuteCanvas.prefetchMaskOverlays()` explicitly
warms masks when a catalog workflow needs them ready before activation.

## Compare Sources

`CuteCanvas.setComparisonImageID()` chooses a catalog source for split reveal,
while `CuteCanvas.clearComparisonImage()` ends it. `CuteCanvas.setComparisonSplit()`
changes position and orientation, `CuteCanvas.comparisonState()` describes the
result, and `CuteCanvas.comparisonChanged` drives host controls.

`CuteCanvas.setComparisonDividerInteractive()` enables or disables built-in
dragging. `CuteCanvas.comparisonDividerInteractive()` reports that policy, and
`CuteCanvas.comparisonDividerState()` supplies projected divider geometry for
a host-drawn treatment.

## Create and Browse Documents

`CuteCanvas.createComposition()` creates an empty document, and
`CuteCanvas.createCompositionFromImage()` seeds one with an ordinary image
layer. `CuteCanvas.composeScene()` stores a complete catalog-backed layout,
while `CuteCanvas.composeSceneFromTemplate()` binds new images into a reusable
arrangement. `CuteCanvas.compose()` is a concise builder for one- or two-source
review documents.

`CuteCanvas.fitSceneRect()` computes a contained placement and
`CuteCanvas.fillSceneRect()` computes a covering placement. They share the same
scene coordinate rules as document layers.

`CuteCanvas.compositionIDs()` returns browser order,
`CuteCanvas.currentCompositionID()` identifies the open document, and
`CuteCanvas.openComposition()` activates one. `CuteCanvas.removeComposition()`
removes a permitted document, while `CuteCanvas.setCompositionPolicy()` changes
its host-controlled structural policy.

`CuteCanvas.getCompositionSnapshot()` supplies the complete document-and-layer
tree. `CuteCanvas.compositionChanged` reports structural updates, and
`CuteCanvas.compositionSelectionChanged` reports activation. `CuteCanvas.currentScene()`
returns the open document's render snapshot; `CuteCanvas.sceneChanged` reports
when that presentation changes.

## Add and Arrange Layers

`CuteCanvas.addCatalogImageLayer()` adds a shared catalog source to the open
document. `CuteCanvas.addEditableRasterLayer()` adds directly editable pixels,
`CuteCanvas.createPaintLayer()` creates an empty sparse raster, and
`CuteCanvas.createVectorLayer()` creates retained vector content.

`CuteCanvas.setSelectedLayer()` selects one layer and
`CuteCanvas.clearSelectedLayer()` clears the selection.
`CuteCanvas.selectedLayer()` reports the current identity, while
`CuteCanvas.selectedLayerChanged` updates the tree and contextual controls.

`CuteCanvas.translateLayer()` moves a layer by an offset,
`CuteCanvas.centerLayer()` aligns it with the document, and
`CuteCanvas.setLayerPlacement()` sets its scene rectangle. Use
`CuteCanvas.setLayerTransform()` for an exact affine transform,
`CuteCanvas.setLayerIndex()` for stack order, `CuteCanvas.setLayerVisible()`
for visibility, and `CuteCanvas.removeLayer()` for removal.

`CuteCanvas.layerTransform()` returns exact placement geometry,
`CuteCanvas.layerLocalBounds()` returns intrinsic source bounds, and
`CuteCanvas.layerGeometryPolicy()` returns the bounds used for manipulation.
`CuteCanvas.setLayerGeometryPolicy()` changes that choice, while
`CuteCanvas.setLayerInteractionPolicy()` changes selection, movement, pixel
editing, reordering, and removal permission.

## Select and Move Pixels

`CuteCanvas.CONTROL_MODE_SELECT_RECTANGLE`,
`CuteCanvas.CONTROL_MODE_SELECT_ELLIPSE`, and
`CuteCanvas.CONTROL_MODE_SELECT_LASSO` create pixel selections with direct
gestures. `CuteCanvas.pixelSelectionState()` reports current coverage, and
`CuteCanvas.pixelSelectionChanged` keeps selection actions synchronized.

`CuteCanvas.selectAllPixels()` covers the document, while
`CuteCanvas.selectLayerCoverage()` follows nontransparent content.
`CuteCanvas.invertPixelSelection()` reverses coverage, and
`CuteCanvas.clearPixelSelection()` deselects after resolving floating pixels.
`CuteCanvas.setPixelSelection()` lets a host supply an exact grayscale region.

`CuteCanvas.deleteSelectedPixels()` clears selected coverage from an editable
target, and `CuteCanvas.fillSelection()` paints it with the active color.
`CuteCanvas.CONTROL_MODE_MOVE` lifts and moves selected nontransparent pixels;
without a pixel selection, it moves an eligible layer.

`CuteCanvas.floatingPixelEditState()` reports an unresolved lifted fragment,
and `CuteCanvas.floatingPixelEditChanged` drives its contextual controls.
`CuteCanvas.anchorFloatingPixels()` writes the fragment into a compatible
destination, `CuteCanvas.promoteFloatingPixels()` creates a layer from it, and
`CuteCanvas.cancelFloatingPixels()` restores the exact starting state.

## Paint Raster Content

`CuteCanvas.setPaintTarget()` chooses an editable raster or mask layer,
`CuteCanvas.setPixelSelectionPaintTarget()` chooses selection coverage, and
`CuteCanvas.clearPaintTarget()` removes the destination.
`CuteCanvas.paintTargetState()` describes the active target, and
`CuteCanvas.paintTargetChanged` keeps brush controls accurate.

`CuteCanvas.setBrushPreset()` applies a complete preset and
`CuteCanvas.brushPreset()` returns it. `CuteCanvas.setBrushSize()` is the quick
diameter command, while `CuteCanvas.brushPresetChanged` reports every preset
change. `CuteCanvas.setPaintColor()` changes raster color,
`CuteCanvas.paintColor()` returns it, and `CuteCanvas.paintColorChanged` keeps a
host color well synchronized.

`CuteCanvas.CONTROL_MODE_DRAW_BRUSH` paints or erases the active target.
`CuteCanvas.configurePaintBucket()` sets tolerance, connectivity, and edge
behavior; `CuteCanvas.paintBucketOptions()` reports them; and
`CuteCanvas.CONTROL_MODE_PAINT_BUCKET` activates the fill gesture.

`CuteCanvas.rasterSurfaceState()` reports sparse storage and revision state.
`CuteCanvas.editableRasterLayerImage()` returns a detached image snapshot.
`CuteCanvas.setRasterExtentPolicy()` changes write growth, and
`CuteCanvas.requestRasterBounds()` requests a crop or pad without blocking the
window. `CuteCanvas.rasterBoundsRequestCompleted` reports its terminal result.

## Work with Masks

`CuteCanvas.createBlankMask()` creates a mask layer, and
`CuteCanvas.loadMaskFromFile()` imports grayscale coverage.
`CuteCanvas.listMasksForImage()` returns the masks for one catalog source;
`CuteCanvas.maskIDsForImage()` returns only their IDs.
`CuteCanvas.removeMaskFromImage()` removes one permitted mask.

`CuteCanvas.setActiveMaskID()` selects the paint and shape destination,
`CuteCanvas.activeMaskID()` reports it, and `CuteCanvas.cycleMasksForward()` or
`CuteCanvas.cycleMasksBackward()` moves through the source's masks.
`CuteCanvas.setMaskProperties()` changes label, tint, and opacity.

`CuteCanvas.getActiveMaskImage()` evaluates the current coverage for export.
`CuteCanvas.rasterizeMaskCoverage()` converts retained shapes into raster
coverage when requested. `CuteCanvas.maskSaved` reports completed file saves
with a `MaskSavedPayload`.

`CuteCanvas.CONTROL_MODE_MASK_RECTANGLE`,
`CuteCanvas.CONTROL_MODE_MASK_ELLIPSE`, and
`CuteCanvas.CONTROL_MODE_MASK_LASSO` author retained mask coverage.
`CuteCanvas.configureCoverageShapes()` controls feathering, while
`CuteCanvas.coverageShapeOptions()` reports the active choice.

For exact host geometry, `CuteCanvas.addCoverageShape()` adds a rectangle or
ellipse, `CuteCanvas.addCoveragePolygon()` adds a closed polygon, and
`CuteCanvas.addCoverageImage()` adds arbitrary grayscale pixels. These commands
target the active mask or pixel selection without simulating input.

`CuteCanvas.getMaskUndoState()` reports mask history availability.
`CuteCanvas.undoMaskEdit()` and `CuteCanvas.redoMaskEdit()` traverse the same
chronological document edits exposed by `CuteCanvas.undoSceneEdit()` and
`CuteCanvas.redoSceneEdit()`. `CuteCanvas.maskUndoStackChanged` and
`CuteCanvas.sceneEditHistoryChanged` keep both styles of host action current;
`CuteCanvas.sceneEditUndoAvailable()` and `CuteCanvas.sceneEditRedoAvailable()`
provide direct availability queries.

## Use Assisted Selection

`CuteCanvas.CONTROL_MODE_SMART_SELECT` turns a dragged box into active-mask
coverage when the optional feature is ready. `CuteCanvas.samCheckpointReady()`
reports readiness, `CuteCanvas.samCheckpointPath()` reports the resolved model
file, and `CuteCanvas.refreshSamFeature()` reapplies model settings.

`CuteCanvas.samCheckpointStatusChanged` reports state transitions and messages,
while `CuteCanvas.samCheckpointProgress` reports download progress. Expensive
model and embedding work remains off the GUI thread.

## Place Image Assets

`CuteCanvas.placeEmbeddedAsset()` stores source pixels with the document, while
`CuteCanvas.placeLinkedAsset()` records a path and optional fallback.
`CuteCanvas.placedAssetState()` reports provenance and loading state.

`CuteCanvas.refreshPlacedAsset()` reloads the current path,
`CuteCanvas.relinkPlacedAsset()` chooses another path, and
`CuteCanvas.embedPlacedAsset()` makes a linked source self-contained.
`CuteCanvas.duplicatePlacedAsset()` creates another layer instance without
resampling the immutable asset.

`CuteCanvas.rasterizePlacedAsset()` replaces a placed source with editable
pixels at a chosen resolution. `CuteCanvas.placedAssetRequestCompleted`
reports the terminal result of accepted asynchronous link, refresh, relink, or
rasterization work.

## Author Vector Content

`CuteCanvas.addVectorShape()` adds a rectangle or ellipse,
`CuteCanvas.addVectorPath()` adds path commands, and
`CuteCanvas.addVectorText()` adds Unicode text. `CuteCanvas.vectorDocumentState()`
returns the layer's semantic objects and revision.

`CuteCanvas.updateVectorObject()` changes object transform or style,
`CuteCanvas.removeVectorObject()` removes one, and
`CuteCanvas.reorderVectorObject()` changes object draw order.
`CuteCanvas.setSelectedVectorObjects()` chooses object IDs, while
`CuteCanvas.clearVectorSelection()` clears them.

`CuteCanvas.vectorSelectionState()` reports object selection and
`CuteCanvas.vectorSelectionChanged` reports changes.
`CuteCanvas.vectorNodeSelectionState()` separately reports a path node, and
`CuteCanvas.vectorNodeSelectionChanged` keeps node controls synchronized.

`CuteCanvas.setVectorToolShape()` and `CuteCanvas.vectorToolShape()` write and
read the shape-tool choice. `CuteCanvas.setVectorToolStyle()` and
`CuteCanvas.vectorToolStyle()` do the same for object appearance.
`CuteCanvas.vectorToolOptionsChanged` reports either option changing.

`CuteCanvas.CONTROL_MODE_VECTOR_SHAPE` draws shapes,
`CuteCanvas.CONTROL_MODE_VECTOR_PATH` draws paths,
`CuteCanvas.CONTROL_MODE_VECTOR_NODE` edits nodes, and
`CuteCanvas.CONTROL_MODE_VECTOR_TEXT` creates and edits text.

`CuteCanvas.beginVectorTextEdit()` starts a text session,
`CuteCanvas.vectorTextEditState()` reports its text and cursor, and
`CuteCanvas.vectorTextEditChanged` updates host text controls.
`CuteCanvas.commitVectorTextEdit()` records the result, while
`CuteCanvas.cancelVectorTextEdit()` restores the starting object.

`CuteCanvas.setVectorTextStyle()` and `CuteCanvas.vectorTextStyle()` manage the
active character style. `CuteCanvas.setVectorParagraphStyle()` and
`CuteCanvas.vectorParagraphStyle()` manage paragraph layout.
`CuteCanvas.updateVectorText()` changes an existing object's bounds or content,
and `CuteCanvas.vectorTextFontResolutions()` reports actual font resolution.
`CuteCanvas.convertVectorTextToPaths()` preserves appearance as geometry.

`CuteCanvas.setVectorMask()` attaches vector objects as a non-destructive layer
mask. `CuteCanvas.vectorMaskState()` reports the attachment, and
`CuteCanvas.clearVectorMask()` removes it. `CuteCanvas.convertVectorToPixelSelection()`
samples chosen objects into selection coverage, while
`CuteCanvas.rasterizeVectorLayer()` replaces the vector layer with editable
pixels. `CuteCanvas.vectorRequestCompleted` reports terminal conversion work.

## Move, Transform, and Snap

`CuteCanvas.CONTROL_MODE_TRANSFORM` provides direct affine manipulation of an
eligible layer. Movement and transform share `CuteCanvas.snapPolicy()`.
`CuteCanvas.configureSnapping()` changes global options,
`CuteCanvas.setSnapGuides()` supplies host guides, and
`CuteCanvas.setSnapGrid()` supplies grid spacing and origin.

Snapping follows the geometry chosen by each layer policy. Hosts can therefore
align visible content, intrinsic source bounds, or a fixed application-defined
rectangle without changing the movement tools.

## Add Effects, Overlays, and Tools

`CuteCanvas.addLayerPresentationEffect()` registers a transient renderer
treatment. `CuteCanvas.updateLayerPresentationEffect()` changes it,
`CuteCanvas.removeLayerPresentationEffect()` removes one, and
`CuteCanvas.clearLayerPresentationEffects()` removes a filtered group.
`CuteCanvas.layerPresentationEffects()` returns the current registrations.

`CuteCanvas.registerOverlay()` adds widget-relative drawing, and
`CuteCanvas.unregisterOverlay()` removes it. `CuteCanvas.contentOverlays()`
returns named content callbacks. `CuteCanvas.registerSceneOverlay()` adds
layer-aware drawing, `CuteCanvas.unregisterSceneOverlay()` removes it, and
`CuteCanvas.sceneOverlays()` returns the registered scene callbacks.

During asynchronous content switches, `CuteCanvas.overlaysSuspended()` reports
whether drawing is paused and `CuteCanvas.overlaysResumePending()` reports a
waiting resume. `CuteCanvas.resumeOverlays()` resumes without forcing a paint,
`CuteCanvas.resumeOverlaysAndUpdate()` also schedules one, and
`CuteCanvas.maybeResumeOverlays()` resumes only when activation is ready.

`CuteCanvas.registerTool()` installs a QPane `ViewerTool`, and
`CuteCanvas.unregisterTool()` removes an inactive mode.
`CuteCanvas.availableControlModes()` lists modes,
`CuteCanvas.getControlMode()` returns the active one, and
`CuteCanvas.setControlMode()` activates another.
`CuteCanvas.registerCursorProvider()` supplies contextual cursor behavior, and
`CuteCanvas.unregisterCursorProvider()` removes it.

## Watch Diagnostics

`CuteCanvas.setDiagnosticsOverlayEnabled()` toggles the HUD, and
`CuteCanvas.diagnosticsOverlayEnabled()` reports its state.
`CuteCanvas.diagnosticsOverlayToggled` keeps a menu action synchronized.

`CuteCanvas.diagnosticsDomains()` lists available sections.
`CuteCanvas.setDiagnosticsDomainEnabled()` changes one,
`CuteCanvas.diagnosticsDomainEnabled()` reports it, and
`CuteCanvas.diagnosticsDomainToggled` carries later changes.

## Related Docs

* [Getting Started](getting-started.md): Build a small editor from the beginning.
* [Host State](host-state.md): Read the snapshots and enums used by host UI.
* [Documents and Layers](scenes.md): Work with documents and layer handles.
* [Interaction and Tools](interaction-modes.md): Understand direct gestures and
  temporary editing state.

**Continue →** [Host State](host-state.md)
