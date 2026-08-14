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

"""Deterministic correctness and performance proof for authoring snapping."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF, QRectF

from cutecanvas.snapping.authoring import (
    AuthoringSnapCoordinator,
    AuthoringSnapSession,
)
from cutecanvas.snapping.candidates import SnapTargetSnapshot
from cutecanvas.snapping.configuration import SnapConfiguration
from cutecanvas.snapping.feedback import SnapGuideFeedback
from cutecanvas.snapping.model import (
    SnapAxis,
    SnapCandidate,
    SnapFeatureKind,
    bounds_candidates,
)
from cutecanvas_test_support.harness.timing import (
    interaction_clock,
    tail_interaction_latency_ms,
)


def _snapshot(*candidates: SnapCandidate) -> SnapTargetSnapshot:
    """Return one target snapshot detached from editor construction concerns."""
    return SnapTargetSnapshot(uuid.uuid4(), tuple(candidates), None)


def _candidate(
    owner: str,
    axis: SnapAxis,
    position: float,
    kind: SnapFeatureKind,
    *,
    priority: int = 0,
) -> SnapCandidate:
    """Return one finite guide candidate for resolver tests."""
    return SnapCandidate(owner, axis, position, kind, 0.0, 1000.0, priority)


def test_endpoint_cross_feature_snap_is_hysteretic_and_releases_deterministically() -> (
    None
):
    """Authored endpoints may use centers and retain a lock through threshold jitter."""
    session = AuthoringSnapSession(
        _snapshot(
            _candidate("layer", SnapAxis.X, 100.0, SnapFeatureKind.CENTER),
        ),
        SnapConfiguration(),
        QPointF(20.0, 20.0),
        scene_units_per_device_pixel=1.0,
    )

    acquired = session.resolve(QPointF(94.0, 40.0), scene_units_per_device_pixel=1.0)
    retained = session.resolve(QPointF(89.0, 40.0), scene_units_per_device_pixel=1.0)
    released = session.resolve(QPointF(87.0, 40.0), scene_units_per_device_pixel=1.0)

    assert acquired.delta.x() == 100.0
    assert acquired.snapped_x
    assert retained.delta.x() == 100.0
    assert retained.snapped_x
    assert released.delta.x() == 87.0
    assert not released.snapped_x


def test_threshold_uses_physical_viewport_zoom_scale() -> None:
    """An eight-device-pixel tolerance scales once into scene coordinates."""
    session = AuthoringSnapSession(
        _snapshot(
            _candidate("guide", SnapAxis.X, 100.0, SnapFeatureKind.GUIDE),
        ),
        SnapConfiguration(),
        QPointF(20.0, 20.0),
        scene_units_per_device_pixel=0.5,
    )

    outside = session.resolve(QPointF(95.5, 40.0), scene_units_per_device_pixel=0.5)
    acquired = session.resolve(QPointF(96.0, 40.0), scene_units_per_device_pixel=0.5)

    assert outside.delta.x() == 95.5
    assert not outside.snapped_x
    assert acquired.delta.x() == 100.0
    assert acquired.snapped_x


def test_priority_then_stable_identity_resolves_ambiguous_candidates() -> None:
    """Candidate priority and identity provide repeatable tie resolution."""
    session = AuthoringSnapSession(
        _snapshot(
            _candidate("lower", SnapAxis.X, 96.0, SnapFeatureKind.START),
            _candidate(
                "preferred",
                SnapAxis.X,
                104.0,
                SnapFeatureKind.END,
                priority=10,
            ),
        ),
        SnapConfiguration(),
        QPointF(20.0, 20.0),
        scene_units_per_device_pixel=1.0,
    )

    result = session.resolve(QPointF(100.0, 40.0), scene_units_per_device_pixel=1.0)

    assert result.delta.x() == 104.0
    assert result.guides[0].target_owner_id == "preferred"


def test_square_constraint_keeps_only_a_geometrically_valid_snap() -> None:
    """Conflicting axis candidates cannot distort a constrained square or its guides."""
    session = AuthoringSnapSession(
        _snapshot(
            _candidate("vertical", SnapAxis.X, 100.0, SnapFeatureKind.GUIDE),
            _candidate("horizontal", SnapAxis.Y, 90.0, SnapFeatureKind.GUIDE),
        ),
        SnapConfiguration(),
        QPointF(),
        scene_units_per_device_pixel=1.0,
    )

    result = session.resolve(
        QPointF(96.0, 87.0),
        scene_units_per_device_pixel=1.0,
        constrain=True,
    )

    assert result.delta == QPointF(100.0, 100.0)
    assert result.snapped_x and not result.snapped_y
    assert tuple(guide.axis for guide in result.guides) == (SnapAxis.X,)


class _CountingCandidates:
    """Expose a fixed target snapshot while counting gesture captures."""

    def __init__(self, snapshot: SnapTargetSnapshot) -> None:
        """Store the immutable target set."""
        self.snapshot = snapshot
        self.capture_count = 0

    def capture(self) -> SnapTargetSnapshot:
        """Return the target set and count the gesture-level query."""
        self.capture_count += 1
        return self.snapshot


def test_coordinator_freezes_candidates_and_bounds_feedback_under_input_storm() -> None:
    """Thousands of updates reuse one snapshot and one unchanged guide presentation."""
    candidates = _CountingCandidates(
        _snapshot(
            _candidate("guide", SnapAxis.X, 100.0, SnapFeatureKind.GUIDE),
        )
    )
    repaints = 0

    def repaint() -> None:
        """Count presentation invalidations."""
        nonlocal repaints
        repaints += 1

    feedback = SnapGuideFeedback(repaint)
    coordinator = AuthoringSnapCoordinator(
        candidates=candidates,  # type: ignore[arg-type]
        configuration=SnapConfiguration(),
        feedback=feedback,
        panel_to_scene=lambda point: QPointF(point),
        scene_to_panel=lambda point: QPointF(point),
        scene_units_per_device_pixel=lambda: 1.0,
        suppressed=lambda: False,
    )

    assert coordinator.begin(QPointF(20.0, 20.0)) == QPointF(20.0, 20.0)
    for _ in range(2_000):
        assert coordinator.update(QPointF(96.0, 40.0)) == QPointF(100.0, 40.0)

    assert candidates.capture_count == 1
    assert repaints == 1
    assert len(feedback.guides) == 1
    assert coordinator.clear()
    assert repaints == 2
    assert not feedback.guides


def test_ctrl_suppression_preserves_raw_anchor_and_endpoint() -> None:
    """Temporary suppression bypasses both authoring points without stale guides."""
    candidates = _CountingCandidates(
        _snapshot(
            _candidate("guide", SnapAxis.X, 100.0, SnapFeatureKind.GUIDE),
        )
    )
    feedback = SnapGuideFeedback(lambda: None)
    coordinator = AuthoringSnapCoordinator(
        candidates=candidates,  # type: ignore[arg-type]
        configuration=SnapConfiguration(),
        feedback=feedback,
        panel_to_scene=lambda point: QPointF(point),
        scene_to_panel=lambda point: QPointF(point),
        scene_units_per_device_pixel=lambda: 1.0,
        suppressed=lambda: False,
    )

    assert coordinator.begin(QPointF(96.0, 20.0), suppressed=True) == QPointF(
        96.0, 20.0
    )
    assert coordinator.update(QPointF(96.0, 40.0), suppressed=True) == QPointF(
        96.0, 40.0
    )
    assert not feedback.guides
    assert coordinator.update(QPointF(96.0, 40.0)) == QPointF(100.0, 40.0)


@pytest.mark.interactive_performance
def test_dense_candidates_keep_construction_and_pointer_latency_bounded() -> None:
    """Large target sets keep capture cost isolated and pointer resolution sub-millisecond."""
    candidates = tuple(
        candidate
        for index in range(500)
        for candidate in bounds_candidates(
            f"layer:{index}",
            QRectF(index * 20.0, index * 13.0, 10.0, 8.0),
        )
    )
    targets = SnapTargetSnapshot(uuid.uuid4(), candidates, None)
    configuration = SnapConfiguration()
    construction_ms: list[float] = []
    for _ in range(50):
        started = interaction_clock()
        session = AuthoringSnapSession(
            targets,
            configuration,
            QPointF(3.0, 7.0),
            scene_units_per_device_pixel=1.0,
        )
        construction_ms.append((interaction_clock() - started) * 1000.0)

    latencies_ms: list[float] = []
    for index in range(2_000):
        if index % 2:
            point = QPointF(
                9_000.0 + (index % 17) * 0.125,
                6_000.0 - (index % 11) * 0.125,
            )
        else:
            point = QPointF(
                1_000.0 + (index % 17) * 0.125,
                650.0 - (index % 11) * 0.125,
            )
        started = interaction_clock()
        result = session.resolve(point, scene_units_per_device_pixel=1.0)
        latencies_ms.append((interaction_clock() - started) * 1000.0)
        assert len(result.guides) <= 2

    assert sum(construction_ms) / len(construction_ms) < 4.0
    assert tail_interaction_latency_ms(latencies_ms) < 0.75
