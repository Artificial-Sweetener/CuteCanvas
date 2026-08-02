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

"""Endpoint snapping for geometric selection, mask, and vector authoring."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF

from .axis_resolution import AxisSnapLock, AxisSnapResolver
from .candidates import SnapCandidateProvider, SnapTargetSnapshot
from .configuration import SnapConfiguration, SnapPolicy
from .feedback import SnapGuideFeedback
from .model import SnapAxis, SnapCandidate, SnapFeatureKind, SnapGuide, SnapResult

_AUTHORING_OWNER_ID = "geometry-authoring"


class AuthoringSnapSession:
    """Resolve authored anchors and endpoints against one frozen target set."""

    def __init__(
        self,
        targets: SnapTargetSnapshot,
        configuration: SnapConfiguration,
        anchor: QPointF,
        *,
        scene_units_per_device_pixel: float,
        snap_anchor: bool = True,
    ) -> None:
        """Snap the anchor once and prepare independent endpoint locks."""
        policy = configuration.policy
        x_candidates, y_candidates = _axis_candidates(targets)
        self._x = self._axis(SnapAxis.X, policy, targets, x_candidates)
        self._y = self._axis(SnapAxis.Y, policy, targets, y_candidates)
        anchor_result = (
            self._resolve(
                QPointF(anchor),
                scene_units_per_device_pixel=scene_units_per_device_pixel,
            )
            if snap_anchor
            else SnapResult(QPointF(anchor))
        )
        self._anchor = QPointF(anchor_result.delta)
        self._anchor_guides = anchor_result.guides
        self._x.clear()
        self._y.clear()

    @property
    def anchor(self) -> QPointF:
        """Return the resolved immutable authoring anchor."""
        return QPointF(self._anchor)

    @property
    def anchor_guides(self) -> tuple[SnapGuide, ...]:
        """Return guides acquired while placing the authoring anchor."""
        return self._anchor_guides

    def resolve(
        self,
        proposed_point: QPointF,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
        constrain: bool = False,
    ) -> SnapResult:
        """Return an independently snapped authored endpoint."""
        point = QPointF(proposed_point)
        if suppressed:
            return SnapResult(point)
        constrained_point = (
            _square_endpoint(self._anchor, point) if constrain else point
        )
        result = self._resolve(
            constrained_point,
            scene_units_per_device_pixel=scene_units_per_device_pixel,
        )
        return (
            self._constrained_result(constrained_point, result) if constrain else result
        )

    def _constrained_result(
        self,
        proposed: QPointF,
        result: SnapResult,
    ) -> SnapResult:
        """Preserve equal extents while retaining only geometrically valid guides."""
        if not result.snapped_x and not result.snapped_y:
            return result
        x = result.delta.x()
        y = result.delta.y()
        delta_x = x - self._anchor.x()
        delta_y = y - self._anchor.y()
        equal_extents = abs(abs(delta_x) - abs(delta_y)) <= 1e-9
        keep_x = result.snapped_x
        keep_y = result.snapped_y
        if not equal_extents:
            x_correction = abs(x - proposed.x()) if keep_x else float("inf")
            y_correction = abs(y - proposed.y()) if keep_y else float("inf")
            keep_x = x_correction <= y_correction
            keep_y = not keep_x
            if keep_x:
                y = self._anchor.y() + _direction(delta_y) * abs(delta_x)
                self._y.clear()
            else:
                x = self._anchor.x() + _direction(delta_x) * abs(delta_y)
                self._x.clear()
        resolved = QPointF(x, y)
        guides = tuple(
            self._guide(axis, lock, self._anchor, resolved)
            for axis, lock, keep in (
                (SnapAxis.X, self._x.lock, keep_x),
                (SnapAxis.Y, self._y.lock, keep_y),
            )
            if keep and lock is not None
        )
        return SnapResult(resolved, guides, keep_x, keep_y)

    def _resolve(
        self,
        point: QPointF,
        *,
        scene_units_per_device_pixel: float,
    ) -> SnapResult:
        """Resolve one point and build guides spanning its authored rectangle."""
        x = self._x.resolve(
            point.x(),
            ((SnapFeatureKind.END, point.x()),),
            scene_units_per_device_pixel=scene_units_per_device_pixel,
        )
        y = self._y.resolve(
            point.y(),
            ((SnapFeatureKind.END, point.y()),),
            scene_units_per_device_pixel=scene_units_per_device_pixel,
        )
        resolved = QPointF(x.value, y.value)
        anchor = getattr(self, "_anchor", point)
        guides = tuple(
            self._guide(axis, lock, anchor, resolved)
            for axis, lock in ((SnapAxis.X, x.lock), (SnapAxis.Y, y.lock))
            if lock is not None
        )
        return SnapResult(
            resolved,
            guides,
            snapped_x=x.lock is not None,
            snapped_y=y.lock is not None,
        )

    @staticmethod
    def _axis(
        axis: SnapAxis,
        policy: SnapPolicy,
        targets: SnapTargetSnapshot,
        candidates: tuple[SnapCandidate, ...],
    ) -> AxisSnapResolver:
        """Create one authoring endpoint axis from captured policy values."""
        return AxisSnapResolver(
            axis,
            candidates,
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            grid=targets.grid,
            relationship_rank=_authoring_relationship_rank,
            moving_kinds=(SnapFeatureKind.END,),
        )

    @staticmethod
    def _guide(
        axis: SnapAxis,
        lock: AxisSnapLock,
        anchor: QPointF,
        endpoint: QPointF,
    ) -> SnapGuide:
        """Build one guide spanning the authored rectangle and snap target."""
        candidate = lock.candidate
        authored_start, authored_end = (
            (anchor.y(), endpoint.y())
            if axis is SnapAxis.X
            else (anchor.x(), endpoint.x())
        )
        return SnapGuide(
            axis,
            candidate.position,
            min(authored_start, authored_end, candidate.span_start),
            max(authored_start, authored_end, candidate.span_end),
            _AUTHORING_OWNER_ID,
            candidate.owner_id,
        )


class AuthoringSnapCoordinator:
    """Adapt panel-space authoring input to one source-neutral snap session."""

    def __init__(
        self,
        *,
        candidates: SnapCandidateProvider,
        configuration: SnapConfiguration,
        feedback: SnapGuideFeedback,
        panel_to_scene: Callable[[QPointF], QPointF | None],
        scene_to_panel: Callable[[QPointF], QPointF | None],
        scene_units_per_device_pixel: Callable[[], float],
        suppressed: Callable[[], bool],
    ) -> None:
        """Bind shared targets, feedback, coordinates, scale, and suppression."""
        self._candidates = candidates
        self._configuration = configuration
        self._feedback = feedback
        self._panel_to_scene = panel_to_scene
        self._scene_to_panel = scene_to_panel
        self._scene_units_per_device_pixel = scene_units_per_device_pixel
        self._suppressed = suppressed
        self._session: AuthoringSnapSession | None = None

    def begin(
        self,
        panel_point: QPointF,
        suppressed: bool = False,
    ) -> QPointF:
        """Capture targets and return the resolved panel-space anchor."""
        self.clear()
        raw_panel = QPointF(panel_point)
        scene_point = self._panel_to_scene(raw_panel)
        targets = self._candidates.capture()
        if scene_point is None or targets is None:
            return raw_panel
        snap_anchor = not (suppressed or self._suppressed())
        self._session = AuthoringSnapSession(
            targets,
            self._configuration,
            scene_point,
            scene_units_per_device_pixel=self._scale(),
            snap_anchor=snap_anchor,
        )
        if not snap_anchor:
            self._feedback.clear()
            return raw_panel
        self._feedback.publish(self._session.anchor_guides)
        return self._project(self._session.anchor, raw_panel)

    def update(
        self,
        panel_point: QPointF,
        suppressed: bool = False,
        constrain: bool = False,
    ) -> QPointF:
        """Return the current resolved panel-space authored endpoint."""
        raw_panel = QPointF(panel_point)
        session = self._session
        scene_point = self._panel_to_scene(raw_panel)
        if session is None or scene_point is None:
            return raw_panel
        result = session.resolve(
            scene_point,
            scene_units_per_device_pixel=self._scale(),
            suppressed=suppressed or self._suppressed(),
            constrain=constrain,
        )
        self._feedback.publish(result.guides)
        return self._project(result.delta, raw_panel)

    def clear(self) -> bool:
        """End the authoring session and remove shared guide feedback."""
        had_session = self._session is not None
        self._session = None
        return self._feedback.clear() or had_session

    def _scale(self) -> float:
        """Return one validated scene-unit threshold scale."""
        return max(1e-9, float(self._scene_units_per_device_pixel()))

    def _project(self, scene_point: QPointF, fallback: QPointF) -> QPointF:
        """Project one resolved scene point or preserve the raw panel point."""
        panel_point = self._scene_to_panel(scene_point)
        return QPointF(fallback) if panel_point is None else QPointF(panel_point)


def _authoring_relationship_rank(
    _moving: SnapFeatureKind,
    _target: SnapFeatureKind,
    _accepts_cross_feature: bool,
) -> int:
    """Allow an authored endpoint to align with every configured target line."""
    return 0


def _axis_candidates(
    targets: SnapTargetSnapshot,
) -> tuple[tuple[SnapCandidate, ...], tuple[SnapCandidate, ...]]:
    """Partition captured candidates once for the two axis resolvers."""
    x_candidates: list[SnapCandidate] = []
    y_candidates: list[SnapCandidate] = []
    for candidate in targets.candidates:
        (x_candidates if candidate.axis is SnapAxis.X else y_candidates).append(
            candidate
        )
    return tuple(x_candidates), tuple(y_candidates)


def _square_endpoint(anchor: QPointF, endpoint: QPointF) -> QPointF:
    """Return an endpoint whose absolute axis extents are equal."""
    delta = endpoint - anchor
    extent = max(abs(delta.x()), abs(delta.y()))
    return QPointF(
        anchor.x() + _direction(delta.x()) * extent,
        anchor.y() + _direction(delta.y()) * extent,
    )


def _direction(value: float) -> float:
    """Return a stable nonzero sign for one authored extent."""
    return -1.0 if value < 0.0 else 1.0
