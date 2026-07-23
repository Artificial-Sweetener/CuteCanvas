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
"""Adversarial tests for source-neutral editor snapping."""

from __future__ import annotations

from cutecanvas.snapping import (
    SnapAxis,
    SnapCandidate,
    SnapConfiguration,
    SnapEngine,
    SnapFeatureKind,
    SnapGrid,
    bounds_candidates,
)
from cutecanvas.snapping.scale import scene_units_per_device_pixel
from PySide6.QtCore import QPointF, QRectF

from tests.harness.timing import interaction_clock


def test_snaps_sides_and_centers_independently() -> None:
    candidates = bounds_candidates("target", QRectF(100.0, 200.0, 40.0, 60.0))
    session = SnapEngine().begin(
        "moving",
        QRectF(10.0, 20.0, 20.0, 20.0),
        candidates,
    )

    result = session.resolve(
        QPointF(68.0, 198.0),
        scene_units_per_device_pixel=1.0,
    )

    assert result.delta == QPointF(70.0, 200.0)
    assert result.snapped_x and result.snapped_y
    assert {guide.axis for guide in result.guides} == {SnapAxis.X, SnapAxis.Y}


def test_default_tolerance_matches_eight_device_pixels() -> None:
    """Default snapping should acquire an alignment eight screen pixels away."""
    session = SnapEngine().begin(
        "moving",
        QRectF(0.0, 0.0, 20.0, 20.0),
        bounds_candidates("target", QRectF(100.0, 0.0, 20.0, 20.0)),
    )

    result = session.resolve(QPointF(72.0, 0.0), scene_units_per_device_pixel=1.0)

    assert result.delta.x() == 80.0
    assert result.snapped_x


def test_viewport_scale_does_not_apply_device_ratio_twice() -> None:
    """QPane zoom already expresses physical pixels per scene unit."""
    assert scene_units_per_device_pixel(0.5) == 2.0
    assert scene_units_per_device_pixel(2.0) == 0.5


def test_both_corner_axes_snap_for_overlapping_and_adjacent_bounds() -> None:
    """Corners should align in one result regardless of object overlap."""
    target = bounds_candidates("target", QRectF(200.0, 200.0, 100.0, 100.0))
    source = QRectF(0.0, 0.0, 100.0, 100.0)

    overlapping = (
        SnapEngine()
        .begin("overlap", source, target)
        .resolve(QPointF(199.0, 199.0), scene_units_per_device_pixel=1.0)
    )
    adjacent = (
        SnapEngine()
        .begin("adjacent", source, target)
        .resolve(QPointF(99.0, 199.0), scene_units_per_device_pixel=1.0)
    )

    assert overlapping.delta == QPointF(200.0, 200.0)
    assert adjacent.delta == QPointF(100.0, 200.0)
    assert overlapping.snapped_x and overlapping.snapped_y
    assert adjacent.snapped_x and adjacent.snapped_y


def test_edge_rejects_target_center_and_acquires_target_edge() -> None:
    """An edge crossing a shape center must remain free until an edge is near."""
    target = bounds_candidates("target", QRectF(100.0, 100.0, 300.0, 60.0))
    source = QRectF(100.0, 0.0, 300.0, 200.0)

    center_crossing = (
        SnapEngine()
        .begin("center-crossing", source, target)
        .resolve(QPointF(0.0, 130.0), scene_units_per_device_pixel=1.0)
    )
    adjacent_edge = (
        SnapEngine()
        .begin("adjacent-edge", source, target)
        .resolve(QPointF(0.0, 153.0), scene_units_per_device_pixel=1.0)
    )

    assert center_crossing.delta.y() == 130.0
    assert not center_crossing.snapped_y
    assert adjacent_edge.delta.y() == 160.0
    assert adjacent_edge.snapped_y


def test_bounds_reject_every_edge_center_cross_relationship() -> None:
    """Bounds must never align an edge with a center or a center with an edge."""
    invalid_relationships = (
        (0.0, SnapFeatureKind.CENTER),
        (100.0, SnapFeatureKind.CENTER),
        (50.0, SnapFeatureKind.START),
        (50.0, SnapFeatureKind.END),
    )

    for index, (candidate_position, candidate_kind) in enumerate(invalid_relationships):
        candidate = SnapCandidate(
            f"target-{index}",
            SnapAxis.X,
            candidate_position,
            candidate_kind,
            0.0,
            100.0,
        )
        result = (
            SnapEngine()
            .begin(
                f"moving-{index}",
                QRectF(0.0, 0.0, 100.0, 100.0),
                (candidate,),
            )
            .resolve(QPointF(), scene_units_per_device_pixel=1.0)
        )

        assert not result.snapped_x
        assert result.delta.x() == 0.0


def test_simultaneous_guides_use_the_fully_snapped_corner() -> None:
    """Both guide spans should meet the final two-axis preview geometry."""
    session = SnapEngine().begin(
        "moving",
        QRectF(0.0, 0.0, 100.0, 100.0),
        bounds_candidates("target", QRectF(200.0, 200.0, 100.0, 100.0)),
    )

    result = session.resolve(QPointF(99.0, 199.0), scene_units_per_device_pixel=1.0)
    vertical = next(guide for guide in result.guides if guide.axis is SnapAxis.X)
    horizontal = next(guide for guide in result.guides if guide.axis is SnapAxis.Y)

    assert (vertical.span_start, vertical.span_end) == (200.0, 300.0)
    assert (horizontal.span_start, horizontal.span_end) == (100.0, 300.0)


def test_device_pixel_threshold_is_zoom_invariant() -> None:
    candidates = bounds_candidates("target", QRectF(100.0, 0.0, 10.0, 10.0))
    source = QRectF(0.0, 0.0, 10.0, 10.0)

    zoomed_out = (
        SnapEngine()
        .begin("moving", source, candidates)
        .resolve(
            QPointF(78.0, 40.0),
            scene_units_per_device_pixel=2.0,
        )
    )
    zoomed_in = (
        SnapEngine()
        .begin("moving", source, candidates)
        .resolve(
            QPointF(87.0, 40.0),
            scene_units_per_device_pixel=0.25,
        )
    )

    assert zoomed_out.snapped_x
    assert not zoomed_in.snapped_x


def test_axis_lock_resists_small_reversals_then_breaks_away() -> None:
    candidates = bounds_candidates("target", QRectF(100.0, 0.0, 20.0, 20.0))
    session = SnapEngine().begin("moving", QRectF(0.0, 0.0, 20.0, 20.0), candidates)

    acquired = session.resolve(QPointF(79.0, 0.0), scene_units_per_device_pixel=1.0)
    retained = session.resolve(QPointF(76.0, 0.0), scene_units_per_device_pixel=1.0)
    released = session.resolve(QPointF(62.0, 0.0), scene_units_per_device_pixel=1.0)

    assert acquired.delta.x() == 80.0
    assert retained.delta.x() == 80.0
    assert released.delta.x() == 62.0
    assert not released.snapped_x


def test_suppression_returns_raw_delta_without_destroying_future_snap() -> None:
    candidates = bounds_candidates("target", QRectF(100.0, 0.0, 20.0, 20.0))
    session = SnapEngine().begin("moving", QRectF(0.0, 0.0, 20.0, 20.0), candidates)

    snapped = session.resolve(QPointF(79.0, 0.0), scene_units_per_device_pixel=1.0)
    suppressed = session.resolve(
        QPointF(77.0, 0.0),
        scene_units_per_device_pixel=1.0,
        suppressed=True,
    )
    resumed = session.resolve(QPointF(78.0, 0.0), scene_units_per_device_pixel=1.0)

    assert snapped.delta.x() == 80.0
    assert suppressed.delta.x() == 77.0
    assert resumed.delta.x() == 80.0


def test_ties_are_deterministic_independent_of_candidate_order() -> None:
    first = bounds_candidates("a", QRectF(100.0, 0.0, 20.0, 20.0))
    second = bounds_candidates("b", QRectF(100.0, 0.0, 20.0, 20.0))
    source = QRectF(0.0, 0.0, 20.0, 20.0)
    forward = (
        SnapEngine()
        .begin("moving", source, (*first, *second))
        .resolve(QPointF(79.0, 0.0), scene_units_per_device_pixel=1.0)
    )
    reverse = (
        SnapEngine()
        .begin("moving", source, (*second, *first))
        .resolve(QPointF(79.0, 0.0), scene_units_per_device_pixel=1.0)
    )

    assert forward.guides[0].target_owner_id == "a"
    assert reverse.guides[0].target_owner_id == "a"


def test_thousands_of_layer_candidates_stay_within_interaction_budget() -> None:
    candidates = tuple(
        candidate
        for index in range(3000)
        for candidate in bounds_candidates(
            f"layer-{index:04d}",
            QRectF(float(index * 32), float(index % 17) * 25.0, 20.0, 20.0),
        )
    )
    session = SnapEngine().begin(
        "moving",
        QRectF(0.0, 0.0, 20.0, 20.0),
        candidates,
    )

    started = interaction_clock()
    for offset in range(120):
        session.resolve(
            QPointF(1000.0 + offset * 0.25, 250.0 + offset * 0.125),
            scene_units_per_device_pixel=0.5,
        )
    elapsed_ms = (interaction_clock() - started) * 1000.0

    assert elapsed_ms < 750.0


def test_guides_and_grid_share_deterministic_engine_resolution() -> None:
    """Authored guides and infinite-grid lines should use one axis resolver."""
    configuration = SnapConfiguration()
    configuration.set_guides(vertical=(95.0,), horizontal=(105.0,))
    span = QRectF(0.0, 0.0, 200.0, 200.0)
    session = SnapEngine().begin(
        "moving",
        QRectF(0.0, 0.0, 20.0, 20.0),
        configuration.guide_candidates(span),
        grid=SnapGrid(QPointF(), 50.0, 50.0, span),
    )

    result = session.resolve(QPointF(74.0, 84.0), scene_units_per_device_pixel=1.0)

    assert result.delta == QPointF(75.0, 85.0)
    assert {guide.target_owner_id for guide in result.guides} == {
        "guide:x:0",
        "guide:y:0",
    }


def test_smart_guides_follow_diagonal_movement_span() -> None:
    """Guide endpoints should include the translated source bounds."""
    session = SnapEngine().begin(
        "moving",
        QRectF(0.0, 0.0, 20.0, 20.0),
        bounds_candidates("target", QRectF(100.0, 200.0, 20.0, 20.0)),
    )

    result = session.resolve(QPointF(79.0, 170.0), scene_units_per_device_pixel=1.0)
    vertical = next(guide for guide in result.guides if guide.axis is SnapAxis.X)

    assert vertical.span_start == 170.0
    assert vertical.span_end == 220.0
