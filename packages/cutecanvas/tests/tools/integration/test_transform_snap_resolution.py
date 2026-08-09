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
"""Deterministic scale-handle snapping against frozen scene targets."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas.scene.transform_session import LayerTransformBoxState
from cutecanvas.snapping import SnapConfiguration
from cutecanvas.snapping.candidates import SnapTargetSnapshot
from cutecanvas.snapping.edge_candidates import OrientedTargetSnapshot
from cutecanvas.snapping.edge_model import OrientedEdge, OrientedSnapGuide
from cutecanvas.snapping.model import (
    SnapAxis,
    SnapCandidate,
    SnapFeatureKind,
    bounds_candidates,
)
from cutecanvas.snapping.transform_scale import TransformScaleSnapSession
from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerTransform,
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)


def _box(transform: LayerTransform | None = None) -> LayerTransformBoxState:
    """Return one detached 100-by-100 layer transform box."""
    return LayerTransformBoxState(
        uuid.uuid4(),
        uuid.uuid4(),
        TransformLocalBounds(0.0, 0.0, 100.0, 100.0),
        transform or LayerTransform(),
        False,
    )


def _session(
    box: LayerTransformBoxState,
    handle: TransformHandle,
    origin: QPointF,
    candidates: tuple[SnapCandidate, ...],
) -> TransformScaleSnapSession:
    """Build one scale session from explicit immutable candidates."""
    return TransformScaleSnapSession(
        box,
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        SnapTargetSnapshot(box.scene_id, candidates, None),
        SnapConfiguration(),
    )


def test_side_handle_snaps_exactly_to_another_layer_edge() -> None:
    """A right resize handle should land on a nearby target's left edge."""
    box = _box()
    session = _session(
        box,
        TransformHandle.RIGHT,
        QPointF(100.0, 50.0),
        bounds_candidates("target", QRectF(200.0, 0.0, 100.0, 100.0)),
    )

    result = session.resolve(
        QPointF(197.0, 50.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )

    assert result.scene_point == QPointF(200.0, 50.0)
    assert len(result.guides) == 1
    assert result.guides[0].axis is SnapAxis.X
    assert result.guides[0].position == 200.0


def test_rotated_side_handle_snaps_to_parallel_diagonal_edge() -> None:
    """A rotated frame side should align through finite oriented geometry."""
    root = 2**-0.5
    box = _box(LayerTransform(root, root, -root, root, 100.0, 20.0))
    geometry = AffineTransformGeometry(box.bounds, box.transform)
    origin = geometry.scene_point(TransformHandle.RIGHT)
    start = geometry.scene_point(TransformHandle.TOP_RIGHT)
    end = geometry.scene_point(TransformHandle.BOTTOM_RIGHT)
    source = OrientedEdge(
        str(box.layer_id),
        start,
        end,
        geometry.scene_center(),
    )
    target = source.translated(20.0)
    target = OrientedEdge(
        "target",
        target.start,
        target.end,
        target.owner_center,
    )
    session = TransformScaleSnapSession(
        box,
        TransformOperation(TransformOperationKind.SCALE, TransformHandle.RIGHT),
        origin,
        SnapTargetSnapshot(box.scene_id, (), None),
        SnapConfiguration(),
        oriented_targets=OrientedTargetSnapshot(box.scene_id, (target,), None),
    )

    result = session.resolve(
        origin + source.normal * 15.0,
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )

    expected = origin + source.normal * 20.0
    assert result.scene_point.x() == pytest.approx(expected.x())
    assert result.scene_point.y() == pytest.approx(expected.y())
    assert len(result.guides) == 1
    assert isinstance(result.guides[0], OrientedSnapGuide)


def test_corner_snap_preserves_proportional_scaling_about_center() -> None:
    """A constrained center scale should satisfy compatible axis targets."""
    box = _box()
    session = _session(
        box,
        TransformHandle.BOTTOM_RIGHT,
        QPointF(100.0, 100.0),
        (
            SnapCandidate(
                "vertical-guide",
                SnapAxis.X,
                150.0,
                SnapFeatureKind.GUIDE,
                0.0,
                200.0,
            ),
            SnapCandidate(
                "horizontal-guide",
                SnapAxis.Y,
                150.0,
                SnapFeatureKind.GUIDE,
                0.0,
                200.0,
            ),
        ),
    )

    result = session.resolve(
        QPointF(148.0, 151.0),
        TransformModifiers(proportional=True, about_center=True),
        scene_units_per_device_pixel=1.0,
    )

    assert result.scene_point == QPointF(150.0, 150.0)
    assert {guide.axis for guide in result.guides} == {SnapAxis.X, SnapAxis.Y}


def test_proportional_corner_keeps_only_the_satisfiable_nearest_axis() -> None:
    """Conflicting target lines must not advertise an axis the scale misses."""
    box = _box()
    session = _session(
        box,
        TransformHandle.BOTTOM_RIGHT,
        QPointF(100.0, 100.0),
        (
            SnapCandidate(
                "vertical-guide",
                SnapAxis.X,
                200.0,
                SnapFeatureKind.GUIDE,
                0.0,
                240.0,
            ),
            SnapCandidate(
                "horizontal-guide",
                SnapAxis.Y,
                180.0,
                SnapFeatureKind.GUIDE,
                0.0,
                240.0,
            ),
        ),
    )

    result = session.resolve(
        QPointF(197.0, 178.0),
        TransformModifiers(proportional=True),
        scene_units_per_device_pixel=1.0,
    )

    assert result.scene_point == QPointF(180.0, 180.0)
    assert tuple(guide.axis for guide in result.guides) == (SnapAxis.Y,)


def test_rotated_side_handle_snaps_along_its_affine_scale_axis() -> None:
    """A rotated side handle should resolve a reachable target without skewing."""
    box = _box(
        LayerTransform(
            m11=0.8,
            m12=0.6,
            m21=-0.6,
            m22=0.8,
        )
    )
    origin = QPointF(50.0, 100.0)
    session = _session(
        box,
        TransformHandle.RIGHT,
        origin,
        (
            SnapCandidate(
                "vertical-guide",
                SnapAxis.X,
                130.0,
                SnapFeatureKind.GUIDE,
                -100.0,
                300.0,
            ),
        ),
    )

    result = session.resolve(
        QPointF(127.0, 158.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )

    assert result.scene_point.x() == pytest.approx(130.0)
    assert result.scene_point.y() == pytest.approx(160.0)
    assert tuple(guide.axis for guide in result.guides) == (SnapAxis.X,)


def test_suppression_removes_resolution_and_feedback_without_losing_precision() -> None:
    """Suppression preserves exact input and releases prior hysteresis locks."""
    box = _box()
    session = _session(
        box,
        TransformHandle.RIGHT,
        QPointF(100.0, 50.0),
        bounds_candidates("target", QRectF(200.0, 0.0, 100.0, 100.0)),
    )

    acquired = session.resolve(
        QPointF(197.0, 50.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )
    suppressed = session.resolve(
        QPointF(190.5, 50.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
        suppressed=True,
    )
    released = session.resolve(
        QPointF(190.5, 50.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )

    assert acquired.scene_point.x() == 200.0
    assert suppressed.scene_point == QPointF(190.5, 50.0)
    assert suppressed.guides == ()
    assert released.scene_point == QPointF(190.5, 50.0)
    assert released.guides == ()


def test_scale_snap_hysteresis_holds_through_jitter_then_releases() -> None:
    """An acquired edge should remain stable until the configured release distance."""
    box = _box()
    session = _session(
        box,
        TransformHandle.RIGHT,
        QPointF(100.0, 50.0),
        bounds_candidates("target", QRectF(200.0, 0.0, 100.0, 100.0)),
    )
    modifiers = TransformModifiers(proportional=False)

    acquired = session.resolve(
        QPointF(197.0, 50.0),
        modifiers,
        scene_units_per_device_pixel=1.0,
    )
    retained = session.resolve(
        QPointF(211.0, 50.0),
        modifiers,
        scene_units_per_device_pixel=1.0,
    )
    released = session.resolve(
        QPointF(213.0, 50.0),
        modifiers,
        scene_units_per_device_pixel=1.0,
    )

    assert acquired.scene_point.x() == 200.0
    assert retained.scene_point.x() == 200.0
    assert released.scene_point.x() == 213.0
    assert released.guides == ()


def test_scale_handle_uses_the_configured_infinite_grid() -> None:
    """Grid participation should use the same exact scale-handle resolution."""
    box = _box()
    configuration = SnapConfiguration()
    assert configuration.configure(grid=True)
    targets = SnapTargetSnapshot(
        box.scene_id,
        (),
        configuration.grid_model(QRectF(0.0, 0.0, 500.0, 500.0)),
    )
    session = TransformScaleSnapSession(
        box,
        TransformOperation(TransformOperationKind.SCALE, TransformHandle.RIGHT),
        QPointF(100.0, 50.0),
        targets,
        configuration,
    )

    result = session.resolve(
        QPointF(125.0, 50.0),
        TransformModifiers(proportional=False),
        scene_units_per_device_pixel=1.0,
    )

    assert result.scene_point == QPointF(128.0, 50.0)
    assert len(result.guides) == 1
    assert result.guides[0].target_owner_id == "grid:x:4"
