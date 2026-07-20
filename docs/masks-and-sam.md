**← Previous:** [Interaction Modes](interaction-modes.md)

# Masks and SAM

QPane provides a lightweight masking engine designed for AI inpainting, region selection, and image processing workflows. Whether you are preparing masks for inpainting, redacting sensitive data, marking defects for quality control, or refining segmentation datasets, QPane gives you pixel-perfect control. Unlike a dataset labeler, QPane does not store bounding boxes, text labels, or vector shapes. Instead, it produces high-fidelity 8-bit grayscale raster masks for image-processing and generation pipelines.

## Setup and Availability
Mask editing is available in the normal QPane install. Install the SAM extra for AI segmentation:

```bash
pip install "qpane[sam]"
```

Applications can check feature availability at runtime:

* **Check support:** `QPane.maskFeatureAvailable()` and `QPane.samFeatureAvailable()` report whether the requested features loaded successfully.
* **Graceful degradation:** If an optional SAM dependency or model fails to load, QPane initializes safely and reports the feature as unavailable.

## The Mask Lifecycle
QPane treats masks as independent 8-bit grayscale resources placed as ordinary composition layers. A composition may contain multiple masks, but only one mask is active for mask-specific editing at a time. Masks do not require a catalog image: an empty composition can create, paint, move, reorder, and persist them against its own canvas. During painting, QPane renders masks through the same composition and raster-product pipeline as other layers.

### Create and Load
You can start with a blank slate or import existing work.

* **New Layer:** `QPane.createBlankMask(size)` adds a transparent layer to the active composition. Pass the canvas size or another intentional local raster size.
* **Import:** `QPane.loadMaskFromFile(path)` reads an image from disk, converts it to a mask layer, and returns its UUID.

```python
from PySide6.QtCore import QSize

# Create a new layer in the active composition
if viewer.maskFeatureAvailable():
    mask_id = viewer.createBlankMask(QSize(1920, 1080))
    viewer.setActiveMaskID(mask_id)
```

### Manage Layers
* **List:** `QPane.maskIDsForImage(image_id)` gives you the UUIDs. For more detail (like labels and colors), use `QPane.listMasksForImage(image_id)`.

`MaskInfo` objects returned by `QPane.listMasksForImage` describe host-visible mask rows, including label, color, opacity, image membership, and active state.
* **Remove:** `QPane.removeMaskFromImage(image_id, mask_id)` deletes a layer.
* **Active State:** `QPane.activeMaskID()` returns the UUID of the layer currently receiving edits. Use `QPane.setActiveMaskID(uuid)` to switch layers.
* **Content:** `QPane.getActiveMaskImage()` returns the actual `QImage` data of the active mask (useful for custom processing).

### Movement, Local Bounds, and Expanding Layers

A mask has two independent pieces of geometry: a scene placement and integer raster bounds in the mask's own local coordinate space. Moving a mask changes only its scene placement. It does not translate, crop, or rewrite the stored pixels, so painted content can move outside the image canvas and return later.

New masks use `RasterExtentPolicy.FIXED` and image-sized local bounds. Fixed masks clip brush, SAM, and component-adjustment writes at those bounds. Hosts that want a Photoshop-style drawing surface can switch a mask to `RasterExtentPolicy.UNBOUNDED`; arbitrary local coordinates remain durable while storage allocates only touched tiles. The local origin may become negative, while the scene placement continues to be controlled independently by the normal layer movement API. `EXPAND_ON_WRITE` remains supported for hosts preserving that named policy and uses the same sparse storage.

`RasterExtentPolicy` is the host-visible choice between those fixed and expanding write behaviors. `QPane.setRasterExtentPolicy` applies that choice to a supported layer without moving it or modifying its pixels.

```python
from qpane import RasterExtentPolicy

mask = viewer.listMasksForImage()[0]
if mask.scene_id is not None and mask.layer_id is not None:
    viewer.setRasterExtentPolicy(
        mask.scene_id,
        mask.layer_id,
        RasterExtentPolicy.UNBOUNDED,
    )
```

Use `QPane.rasterSurfaceState(scene_id, layer_id)` to inspect the current local `QRect`, policy, revisions, and pending bounds work. `QPane.requestRasterBounds` explicitly pads or crops storage on a worker thread. It returns a request UUID and later emits `QPane.rasterBoundsRequestCompleted`; a newer request for the same layer terminates the earlier request. Bounds changes participate in mask undo and redo without changing the layer's scene transform.

The returned `QPaneRasterSurfaceState` is a detached snapshot that is safe for host UI inspection. `QPaneRasterSurfaceState.scene_id` and `QPaneRasterSurfaceState.layer_id` identify the queried scene instance, while `QPaneRasterSurfaceState.bounds` reports its current layer-local storage rectangle.

`QPaneRasterSurfaceState.extent_policy` reports the active write rule. `QPaneRasterSurfaceState.content_revision` changes with pixels, `QPaneRasterSurfaceState.structure_revision` changes with bounds or policy, and `QPaneRasterSurfaceState.pending_request_id` identifies bounds work still in flight.

```python
from PySide6.QtCore import QRect

state = viewer.rasterSurfaceState(mask.scene_id, mask.layer_id)
if state is not None:
    padded = QRect(
        state.bounds.x() - 32,
        state.bounds.y() - 32,
        state.bounds.width() + 64,
        state.bounds.height() + 64,
    )
    request_id = viewer.requestRasterBounds(
        mask.scene_id,
        mask.layer_id,
        padded,
    )
```

Mask export and autosave always produce an image-sized raster containing the intersection of the transformed mask with the image canvas. Pixels held outside that canvas remain in the authoring layer for later movement, but do not appear in that clipped export.

### Masks In Composition Documents

Mask authoring targets the active composition and its active mask layer. `QPane.activeMaskID`, `QPane.getActiveMaskImage`, mask undo/redo, mask cycling, brush painting, and generated-mask edits therefore work in image-free documents as well as seeded ones. Layer selection, movement, transform, ordering, and removal use the same generic policies and commands as other layer kinds.

Use `QPane.getMaskUndoState` to seed host action availability, then route actions through `QPane.undoMaskEdit` and `QPane.redoMaskEdit`. These compatibility-named methods participate in the active composition's single chronological edit history.

The image-centric helpers remain available for catalog-oriented hosts. Passing an image ID to `QPane.maskIDsForImage`, `QPane.listMasksForImage`, `QPane.removeMaskFromImage`, or `QPane.prefetchMaskOverlays` addresses the generated navigation composition for that catalog resource. Omitting the image ID from list helpers addresses the active composition.

### Appearance
Masks are grayscale internally but rendered with a color overlay in image order. Use `QPane.setMaskProperties` to customize how they look.

```python
viewer.setMaskProperties(
    mask_id,
    color=QColor("magenta"),
    opacity=0.5
)
```

> **Pro Tip:** QPane draws masks in their current image order. Use `QPane.cycleMasksForward()` and `QPane.cycleMasksBackward()` to rotate the active mask to the top, which is great for cycling through overlapping segmentations.

## Tools: Brush and SAM
Once you have an active mask, you can start editing.

### Switching Modes
Use `QPane.setControlMode` to activate the tools.

* **Brush:** `QPane.CONTROL_MODE_DRAW_BRUSH` enables freehand drawing. Perfect for rough defect marking or cleaning up noisy model predictions.
* **Smart Select:** `QPane.CONTROL_MODE_SMART_SELECT` enables the SAM-powered box selector. Ideal for quickly grabbing objects for removal, redaction, or alpha matting.

```python
# Activate the brush tool
viewer.setControlMode(QPane.CONTROL_MODE_DRAW_BRUSH)
```

Brush mode accepts mouse, touch, and active-pen input directly. A finger paints with the configured fixed diameter and receives a visible contact ring. A hover-capable active pen previews the nominal brush or eraser before contact, preserves subpixel coordinates, and uses pressure-sensitive diameter by default while painting. Two contacts that arrive before a finger stroke begins navigate the viewport without creating an undo entry. Recent pen input suppresses palm-like single-touch painting while retaining two-finger navigation. See [Touch and Pen Input](touch-and-pen.md) for the exact arbitration rules and no-hardware simulator.

> **Heads-up:** These modes are disabled when the catalog is empty (placeholder active).

### Smart Select (SAM)
When a user drags a box in Smart Select mode, QPane runs the Segment Anything Model to predict a mask shape.
1. **Predictor Loading:** The first time you use SAM on an image, QPane loads the image embedding. This happens in a background thread.
2. **Caching:** Embeddings are cached per device and checkpoint path to make subsequent edits instant.
3. **Merging:** The prediction is automatically merged into the active mask layer.

## Edits and History
QPane manages a robust undo/redo stack for mask operations.

* **Actions:** `QPane.undoMaskEdit()` and `QPane.redoMaskEdit()` step through history.
* **State:** Listen to `QPane.maskUndoStackChanged` to know when to update your UI.
* **Counts:** Call `QPane.getMaskUndoState(mask_id)` to get the current `undo_depth` and `redo_depth`.

```python
# Update UI buttons when the stack changes
def update_buttons(mask_id):
    state = viewer.getMaskUndoState(mask_id)
    undo_btn.setEnabled(state.undo_depth > 0)
    redo_btn.setEnabled(state.redo_depth > 0)

viewer.maskUndoStackChanged.connect(update_buttons)
```

## Configuration and Autosave
You can tune performance and persistence via the `Config` object.

### Autosave
Autosave writes masks to disk as PNGs, ensuring you don't lose work. It's disabled by default.

```python
config = qpane.Config().configure(
    mask_autosave_enabled=True,
    mask_autosave_debounce_ms=500,  # Wait 500ms after last stroke
    mask_autosave_path_template="masks/{image_id}_{mask_id}.png"
)
```

* **Debounce:** The save timer resets on every stroke, so we don't spam the disk while drawing.
* **Creation:** Set `mask_autosave_on_creation=True` if you want empty files created immediately.
* **Signal:** Connect to `QPane.maskSaved` to get the `(mask_id, path)` payload when a file is written. This tuple is formally known as `MaskSavedPayload`.

### Performance Tuning
* **SAM Device:** Set `sam_device="cuda"` if you have a GPU; otherwise defaults to `"cpu"`.
* **Caching:** `sam_cache_limit` controls how many heavy image embeddings we keep in RAM.
* **Prefetch:** `mask_prefetch_enabled` and `sam_prefetch_depth` allow background workers to prepare data before the user navigates.
* **Manual Prefetch:** Call `QPane.prefetchMaskOverlays(image_id)` to manually warm mask renders for the next image in your sequence.

### Checkpoint Management
Checkpoint controls let you decide *when* the SAM model is fetched and *where* it lives. This matters in real apps: you might want to avoid startup stalls, ship a pre-bundled model in a managed environment, or route downloads through your own hosting or caching layer.

* **Download Modes:** `sam_download_mode` chooses how QPane acquires the checkpoint. By default, QPane will download the MobileSAM weights in the background the first time it needs them (`"background"` mode).
    * `"background"` downloads missing weights after startup so the UI stays responsive.
    * `"blocking"` blocks app startup until the checkpoint is ready; pair it with a splash screen when you need SAM fully ready the moment the UI appears.
    * `"disabled"` never downloads; your app must provide the file up front.
* **Path vs URL:** `sam_model_path` points at a local checkpoint (for pre-provisioned models or shared caches). `sam_model_url` overrides the download source; when unset, QPane uses the MobileSAM GitHub weights and stores them under `QStandardPaths.AppDataLocation/mobile_sam.pt` unless you set a custom path.
* **Hash Verification:** `sam_model_hash` lets you supply a SHA-256 checksum for the checkpoint; set it to `"default"` to use the built-in MobileSAM hash. When the default URL is used and `sam_model_path` is unset, the built-in hash is enforced after downloads. Custom URLs without a hash log a warning and are downloaded without integrity verification.
* **Preflight Behavior:** When downloads are enabled, QPane checks for the file at startup and fetches it if missing; disabled mode requires the file to exist already.
* **Readiness + Progress:** Connect to `QPane.samCheckpointStatusChanged` (`"downloading"`, `"ready"`, `"failed"`, `"missing"`) and `QPane.samCheckpointProgress` (`downloaded`, `total`) to drive UI state or show progress; `"downloading"` also covers integrity verification when a hash is required.
* **Runtime Helpers:** `QPane.samCheckpointReady()` and `QPane.samCheckpointPath()` let you gate predictor work. Use `QPane.refreshSamFeature()` when checkpoint-related configuration changes need to reinitialize SAM.

For the complete SAM setting list and defaults, see [Configuration Reference](configuration-reference.md).

## Quick Start Recipe
Here is how to wire up a fully functional editor.

```python
import qpane

# 1. Configure
config = qpane.Config().configure(
    mask_autosave_enabled=True,
    mask_autosave_path_template="masks/{image_id}.png",
    sam_device="cpu",
    sam_download_mode="background"
)

# 2. Initialize
viewer = qpane.QPane(config=config, features=("mask", "sam"))

# 3. Wire UI
viewer.maskUndoStackChanged.connect(lambda mid: print(f"Undo stack changed for {mid}"))
viewer.maskSaved.connect(lambda mid, path: print(f"Saved {path}"))

# 4. Activate Tool (ensure image is loaded first!)
# Note: In a real app, do this after loading an image
image = viewer.currentImage
if viewer.maskFeatureAvailable() and image is not None:
    mask_id = viewer.createBlankMask(image.size())
    viewer.setActiveMaskID(mask_id)
    viewer.setControlMode(qpane.QPane.CONTROL_MODE_SMART_SELECT)
```

## Related Docs
* [Diagnostics](diagnostics.md): Monitor SAM worker health and cache usage.
* [Configuration Reference](configuration-reference.md): Full list of mask and SAM settings.

**Continue →** [Diagnostics](diagnostics.md)
