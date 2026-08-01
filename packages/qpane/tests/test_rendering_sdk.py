#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Contract tests for QPane's declarative rendering SDK."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from qpane.rendering.scene_compiler import SceneRenderCompiler
from qpane.rendering.sdk import RasterSource, RenderLayer, RenderScene, VectorSource
from qpane.rendering.sdk_adapter import RenderSceneController
from qpane.scene.affine import LayerTransform
from qpane.scene.model import LayerDescriptor
from qpane.scene.raster import RasterBounds
from qpane.scene.source_capabilities import LayerSourceCapabilities
from qpane.sdk.execution import CancellationToken
from qpane.sdk.raster import (
    qimage_to_numpy_const_view_argb32,
    qimage_to_numpy_const_view_bgra32,
)
from qpane.sdk.rendering import (
    SceneLayerRenderScope,
    SceneRegionRasterizer,
    rasterize_region,
)
from qpane.vector.model import VectorDocument, VectorObject
from qpane.vector.public import (
    VectorObjectKind,
    VectorShapeKind,
    VectorStyle,
)

from qpane import (
    HybridDocument,
    HybridPresentationStyle,
    HybridSource,
    HybridVectorPrimitive,
)


def _image(width: int = 32, height: int = 24) -> QImage:
    """Return one opaque premultiplied test image."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(25, 100, 175, 255))
    return image


def test_const_raster_views_preserve_storage_and_reject_mutation() -> None:
    """Expose compatible Qt pixels without a detached large-image allocation."""
    image = QImage(2, 1, QImage.Format.Format_ARGB32)
    image.fill(QColor(10, 20, 30, 40))
    cache_key = image.cacheKey()

    argb, argb_backing = qimage_to_numpy_const_view_argb32(image)
    bgra, bgra_backing = qimage_to_numpy_const_view_bgra32(image)

    assert image.format() is QImage.Format.Format_ARGB32
    assert image.cacheKey() == cache_key
    assert argb.flags.writeable is False
    assert bgra.flags.writeable is False
    assert argb.shape == (1, 2, 4)
    assert bgra.shape == (1, 2, 4)
    assert argb[0, 0].tolist() == [5, 3, 2, 40]
    assert bgra[0, 0].tolist() == [30, 20, 10, 40]
    assert argb_backing.format() is QImage.Format.Format_ARGB32_Premultiplied
    assert bgra_backing.format() is QImage.Format.Format_ARGB32


def test_const_bgra_view_normalizes_incompatible_formats() -> None:
    """Normalize unsupported storage without mutating the caller's image."""
    image = QImage(1, 1, QImage.Format.Format_RGB888)
    image.fill(QColor(12, 34, 56))

    pixels, backing = qimage_to_numpy_const_view_bgra32(image)

    assert image.format() is QImage.Format.Format_RGB888
    assert backing.format() is QImage.Format.Format_ARGB32_Premultiplied
    assert pixels.flags.writeable is False
    assert pixels[0, 0].tolist() == [56, 34, 12, 255]


class _SolidRegionSource:
    """Return exact solid samples for worker contract testing."""

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return requested dimensions while recording no mutable state."""
        assert source_rect == QRectF(10.0, 20.0, 30.0, 40.0)
        image = QImage(pixel_size, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("magenta"))
        return image


def test_raster_source_detaches_simple_image_and_validates_inputs() -> None:
    """Simple sources retain pixels independently of the caller's QImage handle."""
    original = _image()
    source = RasterSource.from_image(original)

    original.fill(QColor(255, 0, 0, 255))
    retained = source.provider.image()

    assert retained is not None
    assert retained.pixelColor(0, 0) == QColor(25, 100, 175, 255)
    assert source.bounds == RasterBounds(0, 0, 32, 24)
    assert source.size == QSize(32, 24)
    with pytest.raises(ValueError, match="must not be null"):
        RasterSource.from_image(QImage())


def test_region_rasterization_samples_exact_bounded_output() -> None:
    """Advanced sampled sources must rasterize without a full source image."""
    result = rasterize_region(
        _SolidRegionSource(),
        QRectF(10.0, 20.0, 30.0, 40.0),
        QSize(90, 120),
        CancellationToken(),
    )

    assert result.size() == QSize(90, 120)
    assert result.pixelColor(45, 60) == QColor("magenta")


def test_render_scene_rejects_invalid_canvas_and_duplicate_layer_ids() -> None:
    """Scenes reject geometry and identity that would poison renderer caches."""
    source = RasterSource.from_image(_image())
    layer_id = uuid.uuid4()

    with pytest.raises(ValueError, match="dimensions must be positive"):
        RenderScene(QRectF(0.0, 0.0, 0.0, 24.0))
    with pytest.raises(ValueError, match="layer IDs must be unique"):
        RenderScene.from_size(
            QSize(64, 48),
            (
                RenderLayer(source, layer_id=layer_id),
                RenderLayer(source, layer_id=layer_id),
            ),
        )


def test_controller_preserves_source_sharing_and_instance_geometry() -> None:
    """Independent placements share products without sharing scene identity."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    source = RasterSource.from_image(_image(), revision=7)
    first = RenderLayer(source, transform=LayerTransform(dx=10.0, dy=20.0))
    second = RenderLayer(
        source,
        transform=LayerTransform(m11=2.0, m22=2.0, dx=80.0, dy=40.0),
    )
    scene = RenderScene.from_size(QSize(256, 192), (first, second))

    assert controller.set_scene(scene)
    assert not controller.set_scene(scene)
    contribution = controller.scene_contribution()

    assert contribution is not None
    assert contribution.scene.scene_id == scene.scene_id
    assert tuple(layer.layer_id for layer in contribution.scene.layers) == (
        first.layer_id,
        second.layer_id,
    )
    assert contribution.scene.layers[0].source is source
    assert contribution.scene.layers[1].source is source
    assert (
        contribution.scene.layers[0].placement != contribution.scene.layers[1].placement
    )

    compiler = SceneRenderCompiler(
        scene_provider=lambda: contribution.scene,
        revision_provider=controller.revision,
        source_metadata=capabilities.metadata,
        raster_sources=capabilities.rasters,
        vector_sources=capabilities.vectors,
        hybrid_sources=capabilities.hybrids,
    )
    compiled = compiler.compiled_scene()

    assert compiled is not None
    assert len(compiled.layers) == 2
    assert compiled.layers[0].asset_key != compiled.layers[1].asset_key
    assert compiled.layers[0].pyramid_asset_key == compiled.layers[1].pyramid_asset_key


def test_simple_raster_source_hit_test_uses_alpha() -> None:
    """The convenient image provider exposes content-aware raster hit testing."""
    capabilities = LayerSourceCapabilities.create()
    RenderSceneController(capabilities)
    image = QImage(3, 2, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    image.setPixelColor(1, 0, QColor(10, 20, 30, 255))
    source = RasterSource.from_image(image)

    assert capabilities.hit_tests.contains(source, QPointF(1.5, 0.5))
    assert not capabilities.hit_tests.contains(source, QPointF(0.5, 0.5))
    assert not capabilities.hit_tests.contains(source, QPointF(3.0, 0.5))
    assert capabilities.raster_patches.source_patches(source, source.bounds) is None


def test_scene_region_rasterizer_preserves_layer_order_and_geometry() -> None:
    """Bounded offscreen samples use the same source and transform contracts."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    background = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    background.fill(QColor(180, 20, 30))
    foreground = QImage(2, 2, QImage.Format.Format_ARGB32_Premultiplied)
    foreground.fill(QColor(20, 180, 30))
    scene = RenderScene.from_size(
        QSize(8, 8),
        (
            RenderLayer(RasterSource.from_image(background)),
            RenderLayer(
                RasterSource.from_image(foreground),
                transform=LayerTransform(dx=2.0, dy=3.0),
            ),
        ),
    )
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(2, 2),
        QTransform.fromTranslate(-2.0, -3.0),
    )

    assert sample.pixelColor(0, 0) == QColor(20, 180, 30)
    assert sample.pixelColor(1, 1) == QColor(20, 180, 30)


def test_scene_region_rasterizer_limits_layers_without_changing_visibility() -> None:
    """A render scope preserves scene order and never includes hidden layers."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    background = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    background.fill(QColor(180, 20, 30))
    middle = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    middle.fill(QColor(20, 180, 30))
    hidden = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    hidden.fill(QColor(20, 30, 180))
    scene = RenderScene.from_size(
        QSize(4, 4),
        (
            RenderLayer(RasterSource.from_image(background)),
            RenderLayer(RasterSource.from_image(middle)),
            RenderLayer(RasterSource.from_image(hidden), visible=False),
        ),
    )
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(4, 4),
        QTransform(),
        layer_scope=SceneLayerRenderScope(
            frozenset(
                {
                    descriptor.layers[1].layer_id,
                    descriptor.layers[2].layer_id,
                }
            )
        ),
    )

    assert sample.pixelColor(2, 2) == QColor(20, 180, 30)


def test_scene_region_rasterizer_accepts_revision_stable_raster_override() -> None:
    """A caller can replace selected source pixels without altering scene state."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    source_image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    source_image.fill(QColor(10, 20, 30))
    scene = RenderScene.from_size(
        QSize(4, 4),
        (RenderLayer(RasterSource.from_image(source_image)),),
    )
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    class Override:
        """Return one fixed revision for every requested source region."""

        def sample(
            self,
            layer: LayerDescriptor,
            local_bounds: RasterBounds,
        ) -> QImage:
            """Return exact opaque replacement pixels."""
            del layer
            image = QImage(
                local_bounds.width,
                local_bounds.height,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(QColor(90, 80, 70))
            return image

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(4, 4),
        QTransform(),
        raster_override=Override(),
    )

    assert sample.pixelColor(2, 2) == QColor(90, 80, 70)


def test_scene_region_rasterizer_samples_vector_content_at_output_scale() -> None:
    """Bounded scene samples should preserve semantic vector paint and opacity."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    vector = VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.SHAPE,
        local_bounds=(100.0, 80.0, 200.0, 120.0),
        transform=LayerTransform(),
        style=VectorStyle(fill=QColor(50, 160, 230, 255)),
        shape_kind=VectorShapeKind.RECTANGLE,
    )
    document = VectorDocument(
        vector_id=uuid.uuid4(),
        bounds=RasterBounds(0, 0, 1000, 800),
        objects=(vector,),
    )
    scene = RenderScene.from_size(
        QSize(1000, 800),
        (
            RenderLayer(
                VectorSource(document),
                opacity=0.5,
            ),
        ),
    )
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(100, 60),
        QTransform(0.5, 0.0, 0.0, 0.5, -50.0, -40.0),
    )

    center = sample.pixelColor(50, 30)
    assert abs(center.red() - 50) <= 1
    assert abs(center.green() - 160) <= 1
    assert abs(center.blue() - 230) <= 1
    assert 126 <= center.alpha() <= 129


def test_scene_region_rasterizer_samples_hybrid_content_at_output_scale() -> None:
    """Bounded scene samples should evaluate hybrid coverage at target density."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    bounds = RasterBounds(0, 0, 200, 120)
    geometry = VectorObject(
        object_id=uuid.uuid4(),
        kind=VectorObjectKind.SHAPE,
        local_bounds=(0.0, 0.0, 200.0, 120.0),
        transform=LayerTransform(),
        style=VectorStyle(fill=QColor("white")),
        shape_kind=VectorShapeKind.RECTANGLE,
    )
    source = HybridSource(
        HybridDocument(
            source_id=uuid.uuid4(),
            bounds=bounds,
            primitives=(
                HybridVectorPrimitive(
                    primitive_id=uuid.uuid4(),
                    geometry=geometry,
                    bounds=bounds,
                ),
            ),
        ),
        HybridPresentationStyle(QColor(35, 190, 145, 255)),
    )
    scene = RenderScene.from_size(
        QSize(200, 120),
        (RenderLayer(source, opacity=0.75),),
    )
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(100, 60),
        QTransform.fromScale(0.5, 0.5),
    )

    center = sample.pixelColor(50, 30)
    assert abs(center.red() - 35) <= 1
    assert abs(center.green() - 190) <= 1
    assert abs(center.blue() - 145) <= 1
    assert 190 <= center.alpha() <= 192


def test_vector_source_uses_the_same_scene_and_compiler_boundary() -> None:
    """Semantic vectors compile beside rasters without a parallel scene model."""
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    document = VectorDocument(
        vector_id=uuid.uuid4(),
        bounds=RasterBounds(-10, 5, 120, 80),
        revision=3,
    )
    source = VectorSource(document, presentation_revision=2)
    layer = RenderLayer(source, transform=LayerTransform(dx=15.0, dy=-5.0))
    scene = RenderScene.from_size(QSize(200, 160), (layer,))
    controller.set_scene(scene)
    contribution = controller.scene_contribution()

    assert contribution is not None
    compiler = SceneRenderCompiler(
        scene_provider=lambda: contribution.scene,
        revision_provider=controller.revision,
        source_metadata=capabilities.metadata,
        raster_sources=capabilities.rasters,
        vector_sources=capabilities.vectors,
        hybrid_sources=capabilities.hybrids,
    )
    compiled = compiler.compiled_scene()
    snapshot = capabilities.vectors.vector_document(source)

    assert compiled is not None
    assert compiled.layers == ()
    assert tuple(layer.descriptor for layer in compiled.vector_layers) == (
        contribution.scene.layers
    )
    assert compiled.vector_layers[0].snapshot == snapshot
    assert snapshot is not None
    assert snapshot.document is document
    assert snapshot.preview_object_id is None
