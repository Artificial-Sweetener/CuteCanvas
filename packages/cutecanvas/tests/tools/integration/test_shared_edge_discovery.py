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

"""Eligibility and ambiguity proof for shared-edge discovery."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF

from cutecanvas.editor.shared_edge_discovery import SharedEdgeDiscovery
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.edge_model import OrientedEdge
from qpane.sdk.scene import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerKind,
    LayerPlacement,
    LayerTransform,
    SceneDescriptor,
    SceneKind,
)


def test_exactly_two_layers_form_one_hovered_seam() -> None:
    """One unambiguous coincident pair should produce its shared seam."""
    scene, edges = _scene_with_edges(center_xs=(25.0, 75.0))
    discovery = _discovery(scene, edges)

    seam = discovery.seam_at(QPointF(50.0, 50.0))

    assert seam is not None
    assert {item.layer_id for item in seam.participants} == {
        layer.layer_id for layer in scene.layers
    }


def test_three_layers_on_hovered_seam_form_one_group() -> None:
    """Every eligible participant on one coincident span belongs to the group."""
    scene, edges = _scene_with_edges(center_xs=(25.0, 75.0, 90.0))

    seam = _discovery(scene, edges).seam_at(QPointF(50.0, 50.0))

    assert seam is not None
    assert {participant.layer_id for participant in seam.participants} == {
        layer.layer_id for layer in scene.layers
    }


def test_touching_grid_spans_form_one_four_participant_group() -> None:
    """Two adjacent pair spans on one carrier must translate as one seam."""
    scene_id = uuid.uuid4()
    placements = (
        LayerPlacement(0.0, 0.0, 50.0, 50.0),
        LayerPlacement(50.0, 0.0, 50.0, 50.0),
        LayerPlacement(0.0, 50.0, 50.0, 50.0),
        LayerPlacement(50.0, 50.0, 50.0, 50.0),
    )
    layers = tuple(_placed_layer(scene_id, placement) for placement in placements)
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 100.0, 100.0),
        layers,
    )
    edges = (
        _horizontal_edge(layers[0], 0.0, 50.0, 25.0),
        _horizontal_edge(layers[1], 50.0, 100.0, 25.0),
        _horizontal_edge(layers[2], 0.0, 50.0, 75.0),
        _horizontal_edge(layers[3], 50.0, 100.0, 75.0),
    )

    seam = _discovery(scene, edges).seam_at(QPointF(25.0, 50.0))

    assert seam is not None
    assert {participant.layer_id for participant in seam.participants} == {
        layer.layer_id for layer in layers
    }
    assert seam.start == QPointF(0.0, 50.0)
    assert seam.end == QPointF(100.0, 50.0)
    translation = seam.translation_for_distance(5.0, minimum_thickness=1.0)
    assert len(translation.mappings) == 4
    displacement = seam.edge.normal * translation.distance
    for participant in seam.participants:
        mapping = dict(translation.mappings)[participant.layer_id]
        for index, (source, initial) in enumerate(
            zip(
                participant.source_boundary,
                participant.scene_boundary,
                strict=True,
            )
        ):
            expected = (
                initial + displacement
                if index in participant.translation_indexes
                else initial
            )
            assert mapping.map_point(source) == expected


def test_long_top_edge_and_two_bottom_edges_form_one_three_layer_group() -> None:
    """A T layout must couple both adjacent spans of the longer participant."""
    scene, edges = _horizontal_grid(top_spans=((0.0, 100.0),))

    seam = _discovery(scene, edges).seam_at(QPointF(25.0, 50.0))

    assert seam is not None
    assert len(seam.participants) == 3
    assert seam.start == QPointF(0.0, 50.0)
    assert seam.end == QPointF(100.0, 50.0)


def test_locked_touching_span_disables_the_complete_group() -> None:
    """Discovery must not move a subset that would break a locked neighbor."""
    scene, edges = _horizontal_grid(top_spans=((0.0, 100.0),))
    locked = replace(
        scene.layers[-1],
        interaction=LayerInteractionPolicy(selectable=True, movable=False),
    )
    blocked_scene = replace(scene, layers=(*scene.layers[:-1], locked))

    discovery = _discovery(blocked_scene, edges)

    assert discovery.seams() == ()
    assert discovery.seam_at(QPointF(25.0, 50.0)) is None


def test_inventory_returns_every_unambiguous_shared_edge() -> None:
    """Tool presentation should receive every current valid layer-pair seam."""
    scene, _edges = _scene_with_edges(
        center_xs=(25.0, 75.0, 125.0, 175.0),
        edge_xs=(50.0, 50.0, 150.0, 150.0),
    )
    layers = scene.layers
    edges = (
        _vertical_edge(layers[0], 50.0, 25.0),
        _vertical_edge(layers[1], 50.0, 75.0),
        _vertical_edge(layers[2], 150.0, 125.0),
        _vertical_edge(layers[3], 150.0, 175.0),
    )

    seams = _discovery(scene, edges).seams()

    assert len(seams) == 2
    assert {round(seam.start.x()) for seam in seams} == {50, 150}


def test_overlap_away_from_pointer_is_not_reported_as_hovered() -> None:
    """The pointer must be near the shared overlap, not merely one full edge."""
    scene, edges = _scene_with_edges(center_xs=(25.0, 75.0))
    shortened = OrientedEdge(
        edges[1].owner_id,
        QPointF(50.0, 0.0),
        QPointF(50.0, 20.0),
        edges[1].owner_center,
    )

    assert _discovery(scene, (edges[0], shortened)).seam_at(QPointF(50.0, 80.0)) is None


def _scene_with_edges(
    *,
    center_xs: tuple[float, ...],
    edge_xs: tuple[float, ...] | None = None,
) -> tuple[SceneDescriptor, tuple[OrientedEdge, ...]]:
    """Build eligible layer descriptors and coincident vertical edges."""
    scene_id = uuid.uuid4()
    resolved_edge_xs = edge_xs or (50.0,) * len(center_xs)
    layers = tuple(
        _layer(scene_id, center_x, edge_x)
        for center_x, edge_x in zip(center_xs, resolved_edge_xs, strict=True)
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 100.0, 100.0),
        layers,
    )
    edges = tuple(
        _vertical_edge(layer, edge_x, center_x)
        for layer, center_x, edge_x in zip(
            layers,
            center_xs,
            resolved_edge_xs,
            strict=True,
        )
    )
    return scene, edges


def _horizontal_grid(
    *,
    top_spans: tuple[tuple[float, float], ...],
) -> tuple[SceneDescriptor, tuple[OrientedEdge, ...]]:
    """Return top spans over two adjacent bottom rectangles."""
    scene_id = uuid.uuid4()
    spans = (*top_spans, (0.0, 50.0), (50.0, 100.0))
    centers = (25.0,) * len(top_spans) + (75.0, 75.0)
    placements = tuple(
        LayerPlacement(start, 0.0 if center < 50.0 else 50.0, end - start, 50.0)
        for (start, end), center in zip(spans, centers, strict=True)
    )
    layers = tuple(_placed_layer(scene_id, placement) for placement in placements)
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 100.0, 100.0),
        layers,
    )
    edges = tuple(
        _horizontal_edge(layer, start, end, center)
        for layer, (start, end), center in zip(
            layers,
            spans,
            centers,
            strict=True,
        )
    )
    return scene, edges


def _vertical_edge(
    layer: LayerDescriptor,
    edge_x: float,
    center_x: float,
) -> OrientedEdge:
    """Return one vertical edge for a layer centered on either side."""
    return OrientedEdge(
        str(layer.layer_id),
        QPointF(edge_x, 0.0),
        QPointF(edge_x, 100.0),
        QPointF(center_x, 50.0),
    )


def _horizontal_edge(
    layer: LayerDescriptor,
    start_x: float,
    end_x: float,
    center_y: float,
) -> OrientedEdge:
    """Return one horizontal edge with its owner on either side."""
    return OrientedEdge(
        str(layer.layer_id),
        QPointF(start_x, 50.0),
        QPointF(end_x, 50.0),
        QPointF((start_x + end_x) * 0.5, center_y),
    )


def _layer(
    scene_id: uuid.UUID,
    center_x: float,
    edge_x: float,
) -> LayerDescriptor:
    """Return one visible, selectable, movable affine layer."""
    opposite_x = 2.0 * center_x - edge_x
    left = min(edge_x, opposite_x)
    width = abs(edge_x - opposite_x)
    return LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.IMAGE,
        source=ProjectResourceReference(uuid.uuid4()),
        placement=LayerPlacement(left, 0.0, width, 100.0),
        interaction=LayerInteractionPolicy(selectable=True, movable=True),
        transform=LayerTransform(),
    )


def _placed_layer(
    scene_id: uuid.UUID,
    placement: LayerPlacement,
) -> LayerDescriptor:
    """Return one eligible layer with an explicit rectangular placement."""
    return LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.IMAGE,
        source=ProjectResourceReference(uuid.uuid4()),
        placement=placement,
        interaction=LayerInteractionPolicy(selectable=True, movable=True),
        transform=LayerTransform(),
    )


def _discovery(
    scene: SceneDescriptor,
    edges: tuple[OrientedEdge, ...],
) -> SharedEdgeDiscovery:
    """Build discovery with one frozen edge index."""
    return SharedEdgeDiscovery(
        scene,
        OrientedEdgeIndex.build(edges, scene_units_per_device_pixel=1.0),
        scene_units_per_device_pixel=1.0,
    )
