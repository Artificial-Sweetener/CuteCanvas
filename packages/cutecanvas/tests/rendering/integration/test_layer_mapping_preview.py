#    CuteCanvas - High-performance layered image editor
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

"""Exact transient layer-mapping publication proof."""

from __future__ import annotations

import uuid

from cutecanvas.resources import ProjectResourceReference
from cutecanvas.scene.mapping_preview import (
    LayerMappingPreview,
    SceneLayerMappingPreview,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    LayerDescriptor,
    LayerKind,
    LayerPlacement,
    LayerTransform,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
    RasterBounds,
    SceneDescriptor,
    SceneKind,
)


def test_mapping_preview_publishes_projective_geometry_without_mutating_scene() -> None:
    """A projective override must remain transient, exact, and source-neutral."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    bounds = RasterBounds(0, 0, 100, 80)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=layer_id,
        kind=LayerKind.IMAGE,
        source=ProjectResourceReference(uuid.uuid4()),
        placement=LayerPlacement(0.0, 0.0, 100.0, 80.0),
        raster_bounds=bounds,
        transform=LayerTransform(),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 200.0, 200.0),
        (layer,),
    )
    mapping = ProjectiveLayerTransform.from_quadrilaterals(
        (
            QPointF(0.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 80.0),
            QPointF(0.0, 80.0),
        ),
        (
            QPointF(15.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 80.0),
            QPointF(0.0, 80.0),
        ),
    )
    preview = SceneLayerMappingPreview()

    assert preview.set_many(
        scene,
        (LayerMappingPreview(scene_id, layer_id, mapping),),
    )
    processed = preview.process_scene(scene)

    assert processed is not scene
    assert processed.layers[0].transform == mapping
    assert processed.layers[0].placement == mapping.map_bounds(bounds)
    assert scene.layers[0].transform == LayerTransform()
    assert preview.revision() == 1
    assert preview.clear()
    assert preview.process_scene(scene) is scene


def test_mapping_preview_accepts_inverse_round_trip_boundary_residue() -> None:
    """A finite gesture preview survives harmless source-boundary roundoff."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    bounds = RasterBounds(80, 80, 80, 100)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=layer_id,
        kind=LayerKind.MASK,
        source=ProjectResourceReference(uuid.uuid4()),
        placement=LayerPlacement(80.0, 80.0, 80.0, 100.0),
        raster_bounds=bounds,
        transform=LayerTransform(),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 400.0, 300.0),
        (layer,),
    )
    source = (
        QPointF(79.99999999999999, 80.0),
        QPointF(160.0, 80.0),
        QPointF(160.0, 180.0),
        QPointF(79.99999999999999, 180.0),
    )
    mapping = PiecewiseLayerTransform(source, source)
    preview = SceneLayerMappingPreview()
    assert preview.set(scene, layer_id, mapping)

    processed = preview.process_scene(scene)

    assert processed.layers[0].transform == mapping
    assert scene.layers[0].transform == LayerTransform()


def test_mapping_preview_rejects_source_overflow_without_poisoning_scene() -> None:
    """An invalid transient cage must never enter later scene assembly."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    bounds = RasterBounds(0, 0, 100, 80)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=layer_id,
        kind=LayerKind.MASK,
        source=ProjectResourceReference(uuid.uuid4()),
        placement=LayerPlacement(0.0, 0.0, 100.0, 80.0),
        raster_bounds=bounds,
        transform=LayerTransform(),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 100.0, 80.0),
        (layer,),
    )
    invalid = PiecewiseLayerTransform(
        (
            QPointF(-1.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 80.0),
            QPointF(-1.0, 80.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 80.0),
            QPointF(0.0, 80.0),
        ),
    )
    preview = SceneLayerMappingPreview()

    assert not preview.set(scene, layer_id, invalid)
    assert not preview.previews
    assert preview.process_scene(scene) is scene
