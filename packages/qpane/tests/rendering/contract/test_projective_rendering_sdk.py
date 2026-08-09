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

"""Public contract proof for projectively mapped render layers."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from qpane import ProjectiveLayerTransform, RasterSource, RenderLayer, RenderScene
from qpane.rendering.sdk_adapter import RenderSceneController
from qpane.scene.source_capabilities import LayerSourceCapabilities
from qpane.sdk.rendering import SceneRegionRasterizer


def test_render_layer_preserves_projective_mapping_in_scene_contract() -> None:
    """The supported SDK carries one validated homography into its descriptor."""
    source = RasterSource.from_image(_solid_image())
    mapping = _trapezoid_mapping()
    layer = RenderLayer(source, transform=mapping)
    scene = RenderScene.from_size(QSize(8, 8), (layer,))
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)

    assert controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    assert descriptor.layers[0].transform == mapping


def test_render_layer_rejects_horizon_crossing_its_source() -> None:
    """Invalid projective content fails at the public layer boundary."""
    source = RasterSource.from_image(_solid_image())
    mapping = ProjectiveLayerTransform(m13=1.0, dx=1.0, m33=-2.0)

    with pytest.raises(ValueError, match="horizon crosses"):
        RenderLayer(source, transform=mapping)


def test_scene_region_rasterizes_projective_layer_without_baking_source() -> None:
    """Bounded rendering samples through the mapping and preserves source pixels."""
    source_image = _solid_image()
    source_key = source_image.cacheKey()
    source = RasterSource.from_image(source_image)
    scene = RenderScene.from_size(
        QSize(8, 8),
        (RenderLayer(source, transform=_trapezoid_mapping()),),
    )
    capabilities = LayerSourceCapabilities.create()
    controller = RenderSceneController(capabilities)
    controller.set_scene(scene)
    descriptor = controller.scene_descriptor()

    assert descriptor is not None
    sample = SceneRegionRasterizer(capabilities).rasterize(
        descriptor,
        QSize(8, 8),
        QTransform(),
    )

    assert sample.pixelColor(2, 3) == QColor("magenta")
    assert sample.pixelColor(7, 0).alpha() == 0
    assert source_image.cacheKey() == source_key


def _solid_image() -> QImage:
    """Return one reusable opaque source fixture."""
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("magenta"))
    return image


def _trapezoid_mapping() -> ProjectiveLayerTransform:
    """Map the source square onto a stable non-affine trapezoid."""
    return ProjectiveLayerTransform.from_quadrilaterals(
        (
            QPointF(0.0, 0.0),
            QPointF(4.0, 0.0),
            QPointF(4.0, 4.0),
            QPointF(0.0, 4.0),
        ),
        (
            QPointF(1.0, 1.0),
            QPointF(6.0, 2.0),
            QPointF(5.0, 6.0),
            QPointF(1.0, 6.0),
        ),
    )
