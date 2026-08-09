# Rendering SDK

The ordinary QPane viewer and custom layered scenes use the same renderer. A
scene is an immutable description of a canvas and the sources placed on it.
QPane decides which parts are visible, chooses suitable raster or vector
products, schedules background work, and presents complete frames.

Most applications need only four values:

* `RasterSource`, `VectorSource`, or `HybridSource` describes reusable content.
* `RenderLayer` places one source in a scene.
* `LayerTransform` maps a source through one affine transform.
* `ProjectiveLayerTransform` maps a source through one homography.
* `PiecewiseLayerTransform` maps a source through one finite deformation cage.
* `BilinearLayerTransform` maps a complete quadrilateral source onto a joined-edge triangle.
* `RenderScene` gives the ordered layers a canvas.

## Build a Two-Image Scene

Start by creating one source for each image:

```python
from PySide6.QtGui import QImage
from qpane import RasterSource

left_source = RasterSource.from_image(QImage("left.png"))
right_source = RasterSource.from_image(QImage("right.png"))
```

Place them side by side on a 1600 × 900 canvas:

```python
from PySide6.QtCore import QSize
from qpane import LayerTransform, RenderLayer, RenderScene

scene = RenderScene.from_size(
    QSize(1600, 900),
    (
        RenderLayer(
            left_source,
            label="Left",
        ),
        RenderLayer(
            right_source,
            transform=LayerTransform(dx=800.0),
            label="Right",
        ),
    ),
)

viewer.setScene(scene)
```

Layers are drawn in tuple order, from bottom to top. Their sources remain
independent of placement, so the same source can appear in several scenes—or
several times in one scene—without copying its pixels or building another
pyramid.

## Place, Scale, and Rotate a Layer

`LayerTransform` stores a complete affine transform. Translation is often all a
layout needs:

```python
placed = RenderLayer(
    left_source,
    transform=LayerTransform(dx=120.0, dy=80.0),
)
```

For scale, rotation, or skew, build a normal Qt transform and detach it into
QPane's immutable value:

```python
from PySide6.QtGui import QTransform

qt_transform = QTransform()
qt_transform.translate(400.0, 220.0)
qt_transform.rotate(12.0)
qt_transform.scale(0.75, 0.75)

placed = RenderLayer(
    left_source,
    transform=LayerTransform.from_qtransform(qt_transform),
)
```

Changing placement means submitting a new scene or layer value. The source ID
and revision stay the same, so cached source products remain reusable.

## Map a Layer to a Quadrilateral

`ProjectiveLayerTransform` maps four ordered source corners onto an arbitrary
convex quadrilateral without resampling or changing the source. QPane applies
the homography consistently to visibility, demand, hit testing, clipping,
damage, and presentation:

```python
from PySide6.QtCore import QPointF
from qpane import ProjectiveLayerTransform, RenderLayer

mapping = ProjectiveLayerTransform.from_quadrilaterals(
    (
        QPointF(0.0, 0.0),
        QPointF(800.0, 0.0),
        QPointF(800.0, 600.0),
        QPointF(0.0, 600.0),
    ),
    (
        QPointF(80.0, 40.0),
        QPointF(760.0, 90.0),
        QPointF(720.0, 560.0),
        QPointF(30.0, 520.0),
    ),
)
placed = RenderLayer(left_source, transform=mapping)
```

The mapping is immutable and retains all nine Qt matrix coefficients. Invalid,
singular, horizon-crossing, and non-finite mappings are rejected at the scene
boundary.

`LayerMapping` is the typed union accepted by scene-layer APIs.
`layer_mapping_from_qtransform()` preserves the narrow `LayerTransform` value
for affine input and returns `ProjectiveLayerTransform` when perspective terms
are present. `compose_layer_mappings()` combines mappings in explicit
application order without flattening projective coefficients.

## Map a Layer through a Finite Deformation Cage

`PiecewiseLayerTransform` maps finite source and target cages through bounded
affine patches. Matching simple boundaries use deterministic triangles for
local deformation. `BilinearLayerTransform` represents the exact limit where
one target edge joins at a point while retaining the complete source domain.
Both forms support clipping, hit testing, damage, sampled demand, and exact
inverse coordinate projection without changing source pixels.

Each immutable `TriangularLayerMappingPatch` exposes one source triangle, its
corresponding target triangle, and the solved affine transform.

```python
from PySide6.QtCore import QPointF
from qpane import PiecewiseLayerTransform, RenderLayer

mapping = PiecewiseLayerTransform(
    source_boundary=(
        QPointF(0.0, 0.0),
        QPointF(800.0, 0.0),
        QPointF(800.0, 300.0),
        QPointF(800.0, 600.0),
        QPointF(0.0, 600.0),
    ),
    target_boundary=(
        QPointF(40.0, 30.0),
        QPointF(760.0, 50.0),
        QPointF(700.0, 300.0),
        QPointF(740.0, 570.0),
        QPointF(20.0, 540.0),
    ),
)
placed = RenderLayer(left_source, transform=mapping)
```

Both boundaries contain 4–128 finite vertices, have matching topology and
winding, enclose nonzero area, and do not self-intersect or backtrack.
`inverse_mapping_linearization()` returns the scene-to-source differential at a
source point for spatially varying brush, sampling, or measurement geometry.
Global affine or projective mappings can compose before or after one piecewise
mapping; two independent piecewise cages require an explicit new cage.

## Control Visibility and Clipping

Each layer has independent visibility, opacity, blend mode, hit-test behavior,
role, label, and optional clip:

```python
from qpane import ClipCoordinateSpace, LayerClip

clipped = RenderLayer(
    left_source,
    opacity=0.65,
    clip=LayerClip(
        ClipCoordinateSpace.SCENE,
        100.0,
        100.0,
        600.0,
        400.0,
    ),
    role="preview",
    label="Clipped preview",
)
```

Declare the clip's coordinate space explicitly. Scene clips stay fixed to the
canvas. Normalized scene clips scale with the scene. Viewport clips stay with
the widget, which is useful for presentation chrome that should not move with
the canvas.

## Draw Vector Content

QPane keeps vector shapes, paths, and text as data instead of converting the
whole document into one large image. It samples only the visible regions at the
scale needed for the current frame.

This example creates one rectangle:

```python
import uuid

from PySide6.QtGui import QColor
from qpane import (
    LayerTransform,
    RasterBounds,
    RenderLayer,
    RenderScene,
    VectorDocument,
    VectorObject,
    VectorObjectKind,
    VectorShapeKind,
    VectorSource,
    VectorStyle,
)

rectangle = VectorObject(
    object_id=uuid.uuid4(),
    kind=VectorObjectKind.SHAPE,
    local_bounds=(80.0, 80.0, 480.0, 280.0),
    transform=LayerTransform(),
    style=VectorStyle(
        fill=QColor(85, 180, 240, 180),
        stroke=QColor(20, 90, 140),
        stroke_width=6.0,
    ),
    shape_kind=VectorShapeKind.RECTANGLE,
)

document = VectorDocument(
    vector_id=uuid.uuid4(),
    bounds=RasterBounds(0, 0, 640, 480),
    objects=(rectangle,),
)

scene = RenderScene.from_size(
    QSize(640, 480),
    (RenderLayer(VectorSource(document), label="Vector card"),),
)
viewer.setScene(scene)
```

`VectorDocument` is immutable. Produce a new revision when content changes,
then submit a new `VectorSource` or scene. Stable object and document IDs let
QPane reuse work that still applies.

Text remains Unicode in `VectorTextContent`, with character styles and
paragraph settings kept separately from the sampled pixels. This lets an
authoring application retain meaningful text while QPane concentrates on
drawing it.

## Combine Raster and Vector Coverage

`HybridSource` is useful when one logical source contains both forms of
coverage. A hybrid document may combine:

* retained vector shapes or paths;
* bounded grayscale raster samples from a sparse or live store; and
* ordered add, subtract, intersect, and replace operations.

QPane asks a `HybridRasterSampler` only for the visible source rectangle and
output size. It samples retained vector contributions at the same scale, then
publishes a complete compatible set of tiles. The caller never has to allocate
one canvas-sized intermediate image.

Use a normal `VectorSource` when all content is vector, and a normal
`RasterSource` when all content is pixels. Choose `HybridSource` when both are
part of one source's meaning.

## Supply a Custom Raster Source

`RasterSource.from_image()` is right for an immutable in-memory `QImage`.
Implement `RasterSourceProvider` when pixels come from a file, generator,
remote store, or live producer.

The provider receives a source-local rectangle and an output size. Return only
that detached region. QPane remains responsible for visibility, scale, tiling,
workers, caching, and compositing.

For sparse content, implement `SparseRasterSourceProvider` so QPane can skip
transparent gaps. For exact nontransparent hit testing, implement
`RasterHitTestProvider`. When live pixels change, publish a new source revision
and a `RasterSourcePatch` describing the damaged local region.

See [Advanced Renderer Integration](integration-sdk.md) when your application
also participates in QPane's cache, task, or source-capability lifecycle.

## Highlight Rendered Content

Presentation effects emphasize a layer without changing its source or scene:

```python
from PySide6.QtGui import QColor
from qpane import LayerPresentationStyle

effect_id = viewer.addLayerPresentationEffect(
    scene.scene_id,
    scene.layers[-1].layer_id,
    LayerPresentationStyle.outline(QColor("deepskyblue"), width=2.0),
)
```

Tint, outline, and glow follow the content QPane actually rendered, including
its transform and clip. Remove the effect when the host no longer needs it:

```python
viewer.removeLayerPresentationEffect(effect_id)
```

Effects are temporary presentation. They do not alter source pixels, scene
values, or exported content. Use an overlay instead when the host already knows
exactly what it wants to paint.

## Project Coordinates Through the Viewer

`panelHitTest()` converts a widget position through the active viewport. It
reports scene coordinates and the resolved source hit when available:

```python
hit = viewer.panelHitTest(mouse_position)
if hit is not None:
    print(hit.raw_point, hit.inside_image)
```

Use `coordinateSystem()` when an interaction needs reversible scene or layer
projection. Its point values carry their coordinate domain and scene/layer
identity:

```python
from qpane import PanelPoint

coordinates = viewer.coordinateSystem()
scene_point = coordinates.panel_to_scene(PanelPoint.from_qt(mouse_position))
if scene_point is not None:
    panel_point = coordinates.scene_to_panel(scene_point)
```

`PanelPoint`, `ScenePoint`, `LayerLocalPoint`, and `LayerSourcePoint` are
distinct values. Layer-local coordinates retain authored geometry, while
layer-source coordinates begin at the source's storage origin. The coordinate
system projects between them through the same viewport, scene, layer transform,
and raster bounds used for rendering. Identity mismatches return `None`;
passing a point from the wrong coordinate domain raises `TypeError`.
`SceneCoordinateProjection` and `LayerCoordinateProjection` are immutable
snapshots for consumers that need to retain one resolved frame's geometry.

Do not duplicate device-pixel-ratio, zoom, pan, raster-origin, or layer-transform
math in a tool. Use the coordinate system, the public hit result, and prepared
overlay geometry.

## Keep Interactive Sources Smooth

For a live source:

1. Keep its resource ID stable.
2. Increment its revision when content changes.
3. Report the smallest correct damage region.
4. Return detached images from provider calls.
5. Keep provider reads safe for concurrent workers.

Those rules let QPane preserve unaffected tiles and reject stale work. A broad
or changing identity throws useful cached work away; a reused revision for new
pixels can display stale content.

## Sample a Bounded Scene Region

Renderer-backed products sometimes need exact pixels from a small transformed
scene window without flattening a complete canvas. `SceneRegionRasterizer`
provides that advanced operation through `qpane.sdk.rendering`:

```python
from PySide6.QtCore import QSize
from PySide6.QtGui import QTransform
from qpane.sdk.rendering import SceneLayerRenderScope, SceneRegionRasterizer

rasterizer = SceneRegionRasterizer(source_capabilities)
sample = rasterizer.rasterize(
    scene_descriptor,
    QSize(128, 128),
    scene_to_output_pixels,
    layer_scope=SceneLayerRenderScope(frozenset(layer_ids)),
)
```

The rasterizer preserves layer order, exact layer mapping, visibility, opacity,
clips, and raster, vector, and hybrid presentation while allocating only the
requested output. Omit `layer_scope` to render the complete visible scene.
When supplied, `SceneLayerRenderScope` includes only those layer identities
while retaining their existing stack order and visibility. A
`RasterLayerRegionOverride` may replace selected raster regions for
revision-stable editing or comparison without changing the authoritative
source owner.

This is an advanced integration primitive. Ordinary viewer applications submit
`RenderScene` values to `QPane.setScene()` and let the viewport renderer own
tiling, caching, scheduling, and frame publication.

Sources that produce their own sampled tiles implement `RenderTileBatchSource`.
QPane supplies immutable `RenderTileRequest` values and the source returns a
complete tuple of `RenderTileProduct` values for that revision. Implement
`RegionSampleSource` as well when the source can answer arbitrary bounded
samples for nested scene rendering. These protocols keep expensive sampling on
workers while QPane retains cache keys, scheduling, cancellation, and frame
publication. `rasterize_region()` executes one such bounded sample inside an
execution request and validates the returned dimensions.

## Related Docs

* [Getting Started](getting-started.md): mount the viewer and show its first
  image.
* [Extensibility](extensibility.md): overlays, effects, tools, diagnostics, and
  custom sources.
* [Advanced Renderer Integration](integration-sdk.md): cache, scheduling,
  provider, and lifecycle contracts for renderer-backed products.
* [API Reference](api-reference.md): every public scene, raster, vector, and
  hybrid value.
