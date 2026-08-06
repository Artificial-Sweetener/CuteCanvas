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

"""Transform-tool snapping lifecycle across move and scale gestures."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import (
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

from cutecanvas.scene.transform_session import LayerTransformBoxState

from .candidates import SnapCandidateProvider
from .configuration import SnapConfiguration
from .feedback import SnapGuideFeedback
from .movement import MovementSnapCoordinator
from .transform_scale import TransformScaleSnapSession


class TransformSnapCoordinator:
    """Own snapping lifecycle for Transform-tool move and scale gestures."""

    def __init__(
        self,
        *,
        candidates: SnapCandidateProvider,
        configuration: SnapConfiguration,
        feedback: SnapGuideFeedback,
        movement: MovementSnapCoordinator,
        scene_units_per_device_pixel: Callable[[], float],
        suppressed: Callable[[], bool],
    ) -> None:
        """Bind shared targets, policy, movement behavior, scale, and feedback."""
        self._candidates = candidates
        self._configuration = configuration
        self._feedback = feedback
        self._movement = movement
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._scale_session: TransformScaleSnapSession | None = None
        self._moving = False

    @property
    def active(self) -> bool:
        """Return whether a move or scale snap session owns a gesture."""
        return self._moving or self._scale_session is not None

    def begin(
        self,
        box: LayerTransformBoxState | None,
        operation: TransformOperation,
        origin: QPointF,
        *,
        exclude_selection: bool = False,
    ) -> bool:
        """Capture one transform gesture's stationary target snapshot."""
        self.clear()
        if box is None or not self._configuration.policy.enabled:
            return False
        if operation.kind is TransformOperationKind.MOVE:
            self._moving = self._movement.begin(
                box,
                origin,
                exclude_selection=exclude_selection,
            )
            return self._moving
        if operation.kind is not TransformOperationKind.SCALE:
            return False
        source_bounds = box.transform.map_rect(
            QRectF(box.bounds.x, box.bounds.y, box.bounds.width, box.bounds.height)
        )
        targets = self._candidates.capture(
            excluded_layer_id=box.layer_id,
            excluded_bounds=source_bounds,
            excluded_layer_ids=box.excluded_layer_ids,
            exclude_selection=exclude_selection,
        )
        if targets is None or targets.scene_id != box.scene_id:
            return False
        self._scale_session = TransformScaleSnapSession(
            box,
            operation,
            origin,
            targets,
            self._configuration,
        )
        return True

    def resolve(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
    ) -> QPointF:
        """Return snapped input for the active transform gesture."""
        if self._moving:
            return self._movement.resolve(scene_point)
        session = self._scale_session
        if session is None:
            return QPointF(scene_point)
        result = session.resolve(
            scene_point,
            modifiers,
            scene_units_per_device_pixel=max(
                1e-9, float(self._scene_units_per_device_pixel())
            ),
            suppressed=self._suppressed(),
        )
        self._feedback.publish(result.guides)
        return result.scene_point

    def clear(self) -> bool:
        """End transform snapping and remove all associated feedback."""
        had_scale = self._scale_session is not None
        had_move = self._moving
        self._scale_session = None
        self._moving = False
        movement_changed = self._movement.clear()
        feedback_changed = self._feedback.clear()
        return movement_changed or feedback_changed or had_scale or had_move


__all__ = ["TransformSnapCoordinator"]
