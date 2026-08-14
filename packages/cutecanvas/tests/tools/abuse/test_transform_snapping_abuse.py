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

"""High-cardinality affine snapping latency and stability proof."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF, QRectF

from cutecanvas.scene.transform_session import LayerTransformBoxState
from cutecanvas.snapping import SnapConfiguration
from cutecanvas.snapping.candidates import SnapTargetSnapshot
from cutecanvas.snapping.model import bounds_candidates
from cutecanvas.snapping.transform_scale import TransformScaleSnapSession
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    average_interaction_latency_ms,
)
from qpane.sdk.scene import (
    LayerTransform,
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

pytestmark = INTERACTIVE_PERFORMANCE


def test_scale_resolution_remains_interactive_with_thousands_of_target_features() -> (
    None
):
    """Frozen indexed targets must keep the pointer hot path below two milliseconds."""
    scene_id = uuid.uuid4()
    box = LayerTransformBoxState(
        scene_id,
        uuid.uuid4(),
        TransformLocalBounds(0.0, 0.0, 100.0, 100.0),
        LayerTransform(),
        False,
    )
    candidates = tuple(
        candidate
        for index in range(1000)
        for candidate in bounds_candidates(
            f"target-{index}",
            QRectF(index * 32.0, index * 11.0, 24.0, 18.0),
        )
    )
    session = TransformScaleSnapSession(
        box,
        TransformOperation(TransformOperationKind.SCALE, TransformHandle.RIGHT),
        QPointF(100.0, 50.0),
        SnapTargetSnapshot(scene_id, candidates, None),
        SnapConfiguration(),
    )
    modifiers = TransformModifiers(proportional=False)
    iteration = 0

    def resolve_next_target() -> None:
        """Resolve a changing target so the benchmark exercises index lookup."""
        nonlocal iteration
        index = iteration % 1000
        iteration += 1
        session.resolve(
            QPointF(index * 32.0 + 2.0, 50.0),
            modifiers,
            scene_units_per_device_pixel=1.0,
        )

    latency_ms = average_interaction_latency_ms(
        resolve_next_target,
        repetitions=2000,
    )

    assert latency_ms < 2.0
