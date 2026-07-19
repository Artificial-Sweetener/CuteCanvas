# Pixel selections

QPane keeps pixel selection separate from layer selection. A layer selection identifies which layer direct editing targets; a pixel selection is an 8-bit coverage field in scene coordinates. This keeps soft edges intact and lets one selection constrain masks or color raster layers without belonging to either source type.

`QPane.selectedLayer()` returns a `QPaneLayerSelectionState`; its `QPaneLayerSelectionState.scene_id` and `QPaneLayerSelectionState.layer_id` values identify the edit target. Hosts call `QPane.setSelectedLayer()` or `QPane.clearSelectedLayer()` and observe `QPane.selectedLayerChanged`. A `QPaneLayerInteractionPolicy.pixel_editable` value grants host permission, while the source still determines whether pixels are intrinsically editable.

Use the built-in rectangle, ellipse, and lasso tools for interactive selection:

```python
from qpane import QPane

viewer.setControlMode(QPane.CONTROL_MODE_SELECT_RECTANGLE)
```

Dragging replaces the current selection. Shift adds coverage, Alt subtracts it, and Shift+Alt intersects it. QPane rasterizes the finished vector gesture once; the live preview stays vector-based, and marching-ant geometry is cached until the selection revision changes.

Hosts can also supply grayscale coverage directly. Bounds are expressed in scene coordinates and must match the image dimensions:

```python
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from qpane import PixelSelectionMode

coverage = QImage(320, 180, QImage.Format_Grayscale8)
coverage.fill(255)
viewer.setPixelSelection(
    coverage,
    QRect(40, 60, 320, 180),
    PixelSelectionMode.ADD,
)
```

`pixelSelectionState()` returns detached coverage suitable for host UI or persistence. `selectAllPixels()`, `invertPixelSelection()`, and `clearPixelSelection()` provide the standard whole-selection commands. Selection state is scoped to each composition, so switching compositions restores the corresponding selection rather than moving one global selection between scenes.

Masks expose saved coverage through `QPane.selectLayerCoverage()`. `QPane.deleteSelectedPixels()` applies soft selection coverage to the selected mask or editable RGBA layer and records one patch in chronological scene history. Mask brush previews and durable strokes use the same selection constraint, so pixels outside coverage never appear temporarily.

The Move tool treats active selection coverage as an editing region on the selected editable layer. Start on selected, nontransparent layer content to lift a floating fragment. Transparent RGBA pixels and zero mask coverage are excluded, so the origin reveals lower layers while only meaningful payload pixels and their marching ants follow the pointer. Releasing the pointer leaves that fragment unresolved and available for another drag. Source storage remains unchanged until the fragment is resolved.

Press Enter or call `QPane.anchorFloatingPixels()` to anchor the fragment to its source layer. Supply a compatible scene and layer ID to anchor it to another editable layer, or call `QPane.promoteFloatingPixels()` to create a full composition layer. Hold Alt when beginning a drag to float a copy instead of a cut. Escape or `QPane.cancelFloatingPixels()` restores the pre-lift presentation without recording an edit. A successful resolution records the source, destination or created layer, pixel selection, and selected-layer identity as one chronological history command. Fixed destination rasters clip writes at their bounds, while expand-on-write destinations retain off-canvas content by growing their local storage.

`QPane.floatingPixelEditState()` returns `None` or a detached `QPaneFloatingPixelEditState` containing source identity, cut/copy mode, local offset, and scene bounds. Hosts can observe `QPane.floatingPixelEditChanged` to show contextual Anchor, New Layer, destination-layer, and Cancel controls. Ordinary and temporary tool changes preserve the unresolved fragment, so holding Space for Pan/Zoom and then returning to Move retains its exact displacement. Selection changes anchor first, while composition navigation cancels safely so transient pixels cannot become detached from their owning context. With no active pixel selection, Move returns to whole-layer placement.

- `FloatingPixelMode` identifies lift behavior in a public state snapshot.
- `FloatingPixelMode.CUT` clears the selected source contribution only when resolution succeeds.
- `FloatingPixelMode.COPY` leaves the original source contribution intact after successful resolution.
- `QPaneFloatingPixelEditState.scene_id` identifies the composition scene that owns the unresolved edit.
- `QPaneFloatingPixelEditState.source_layer_id` identifies the editable layer from which pixels were lifted.
- `QPaneFloatingPixelEditState.mode` reports whether successful resolution cuts or copies source content.
- `QPaneFloatingPixelEditState.offset` reports quantized source-local displacement from the original lift position.
- `QPaneFloatingPixelEditState.bounds` reports the current scene-coordinate boundary of floating content.

The demonstration uses `Ctrl+D` to clear a committed selection. Its contextual Floating Pixels toolbar appears after a selected-pixel drag and offers source anchoring, compatible layer targets, new-layer promotion, and cancellation. Escape cancels an unresolved fragment or transient selection geometry without clearing an otherwise committed selection.

Create composition-owned color content with `QPane.addEditableRasterLayer()` and inspect a detached snapshot with `QPane.editableRasterLayerImage()`. Every `QPaneSceneLayer` reports `QPaneSceneLayer.source_kind`, `QPaneSceneLayer.source_id`, and `QPaneSceneLayer.label`; non-image layers have no catalog `image_id`. This lets a host build one layer list without maintaining parallel mask rows. Catalog images remain immutable even if a host accidentally grants pixel-edit policy.
