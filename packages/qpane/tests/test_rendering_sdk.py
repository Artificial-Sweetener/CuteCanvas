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
from PySide6.QtGui import QColor, QImage
from qpane.rendering.scene_compiler import SceneRenderCompiler
from qpane.rendering.sdk import RasterSource, RenderLayer, RenderScene, VectorSource
from qpane.rendering.sdk_adapter import RenderSceneController
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.scene.source_capabilities import LayerSourceCapabilities
from qpane.vector.model import VectorDocument


def _image(width: int = 32, height: int = 24) -> QImage:
    """Return one opaque premultiplied test image."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(25, 100, 175, 255))
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
