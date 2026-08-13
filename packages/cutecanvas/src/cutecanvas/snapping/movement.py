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
"""Movement-session adapter for shared content-tight editor snapping."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas.scene.transform_session import LayerTransformBoxState
from PySide6.QtCore import QPointF, QRectF

from .candidates import SnapCandidateProvider
from .configuration import SnapConfiguration
from .engine import SnapEngine, SnapSession
from .feedback import SnapGuideFeedback
from .model import SnapGuide


class MovementSnapCoordinator:
    """Build and resolve one shared snap session for any movable editor target."""

    def __init__(
        self,
        *,
        candidates: SnapCandidateProvider,
        configuration: SnapConfiguration,
        feedback: SnapGuideFeedback,
        scene_units_per_device_pixel: Callable[[], float],
        suppressed: Callable[[], bool],
    ) -> None:
        """Bind scene geometry, selection, scale, and overlay publication."""
        self._candidates = candidates
        self._configuration = configuration
        self._feedback = feedback
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._engine = SnapEngine()
        self._session: SnapSession | None = None
        self._origin = QPointF()

    @property
    def guides(self) -> tuple[SnapGuide, ...]:
        """Return smart guides for the latest resolved movement update."""
        return self._feedback.guides

    def begin(
        self,
        box: LayerTransformBoxState | None,
        origin: QPointF,
        *,
        exclude_selection: bool = False,
    ) -> bool:
        """Begin snapping for one layer or floating-pixel transform box."""
        policy = self._configuration.policy
        if box is None or not policy.enabled:
            self.clear()
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
            self.clear()
            return False
        self._session = self._engine.begin(
            str(box.layer_id),
            source_bounds,
            targets.candidates,
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            grid=targets.grid,
        )
        self._origin = QPointF(origin)
        self._feedback.clear()
        return True

    def resolve(self, scene_point: QPointF, *, suppressed: bool = False) -> QPointF:
        """Return a corrected scene point for the active movement owner."""
        if self._session is None:
            return QPointF(scene_point)
        result = self._session.resolve(
            scene_point - self._origin,
            scene_units_per_device_pixel=max(
                1e-9, float(self._scene_units_per_device_pixel())
            ),
            suppressed=suppressed or self._suppressed(),
        )
        self._feedback.publish(result.guides)
        return self._origin + result.delta

    def clear(self) -> bool:
        """End snapping and remove any smart-guide presentation."""
        had_state = self._session is not None
        self._session = None
        self._origin = QPointF()
        return self._feedback.clear() or had_state
