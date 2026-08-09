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

"""Panel projection for discoverable shared-edge resize handles."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_pivot import SharedEdgeHandle, SharedEdgePivot


@dataclass(frozen=True, slots=True)
class SharedEdgeHandlePresentation:
    """Describe one finite shared edge and its three panel handles."""

    layer_ids: tuple[uuid.UUID, ...]
    start: QPointF
    end: QPointF
    start_enabled: bool = True
    middle_enabled: bool = True
    end_enabled: bool = True
    focused_handle: SharedEdgeHandle | None = None
    focused_axis: QPointF | None = None
    hovered: bool = False
    active: bool = False

    def __post_init__(self) -> None:
        """Detach mutable Qt point storage."""
        object.__setattr__(self, "start", QPointF(self.start))
        object.__setattr__(self, "end", QPointF(self.end))
        if self.focused_axis is not None:
            object.__setattr__(self, "focused_axis", QPointF(self.focused_axis))

    @property
    def handles(self) -> tuple[QPointF, QPointF, QPointF]:
        """Return endpoint, midpoint, and endpoint handle centers."""
        return self.start, (self.start + self.end) * 0.5, self.end

    @property
    def focused_enabled(self) -> bool:
        """Return whether the focused handle can begin its advertised gesture."""
        if self.focused_handle is SharedEdgeHandle.START:
            return self.start_enabled
        if self.focused_handle is SharedEdgeHandle.END:
            return self.end_enabled
        return self.focused_handle is SharedEdgeHandle.MIDDLE and self.middle_enabled


@dataclass(frozen=True, slots=True)
class SharedEdgePresentation:
    """Describe all current shared edges and their manipulation state."""

    edges: tuple[SharedEdgeHandlePresentation, ...]

    @property
    def focused_edge(self) -> SharedEdgeHandlePresentation | None:
        """Return the active or hovered edge used for cursor feedback."""
        return next(
            (edge for edge in self.edges if edge.active or edge.hovered),
            None,
        )


class SharedEdgePresentationProjector:
    """Project immutable seam inventory and current focus into panel space."""

    def __init__(
        self,
        *,
        scene_to_panel: Callable[[QPointF], QPointF | None],
    ) -> None:
        """Bind the authoritative viewport projection owner."""
        self._scene_to_panel = scene_to_panel

    def project(
        self,
        seams: tuple[SharedEdgeSeam, ...],
        *,
        focused: SharedEdgeSeam | None,
        focused_points: tuple[QPointF, QPointF] | None,
        focused_handle: SharedEdgeHandle | None,
        pivot_for: Callable[
            [SharedEdgeSeam],
            tuple[SharedEdgePivot | None, SharedEdgePivot | None],
        ],
        active: bool,
    ) -> SharedEdgePresentation:
        """Return every valid shared-edge handle in panel coordinates."""
        focused_identity = None if focused is None else _seam_identity(focused)
        edges: list[SharedEdgeHandlePresentation] = []
        focused_added = False
        for seam in seams:
            is_focused = focused_identity == _seam_identity(seam)
            source = focused if is_focused and focused is not None else seam
            points = focused_points if is_focused else None
            edge = self._project_edge(
                source,
                points=points,
                pivots=pivot_for(source),
                focused_handle=focused_handle if is_focused else None,
                hovered=is_focused and not active,
                active=is_focused and active,
            )
            if edge is not None:
                edges.append(edge)
                focused_added = focused_added or is_focused
        if focused is not None and not focused_added:
            edge = self._project_edge(
                focused,
                points=focused_points,
                pivots=pivot_for(focused),
                focused_handle=focused_handle,
                hovered=not active,
                active=active,
            )
            if edge is not None:
                edges.append(edge)
        return SharedEdgePresentation(tuple(edges))

    def _project_edge(
        self,
        seam: SharedEdgeSeam,
        *,
        points: tuple[QPointF, QPointF] | None,
        pivots: tuple[SharedEdgePivot | None, SharedEdgePivot | None],
        focused_handle: SharedEdgeHandle | None,
        hovered: bool,
        active: bool,
    ) -> SharedEdgeHandlePresentation | None:
        """Project one displaced seam into panel coordinates."""
        scene_start, scene_end = (seam.start, seam.end) if points is None else points
        start = self._scene_to_panel(scene_start)
        end = self._scene_to_panel(scene_end)
        if start is None or end is None:
            return None
        focused_pivot = (
            pivots[0]
            if focused_handle is SharedEdgeHandle.START
            else pivots[1] if focused_handle is SharedEdgeHandle.END else None
        )
        axis = self._project_pivot_axis(focused_pivot)
        return SharedEdgeHandlePresentation(
            layer_ids=_participant_ids(seam),
            start=start,
            end=end,
            start_enabled=pivots[0] is not None,
            middle_enabled=seam.parallel_translation_enabled,
            end_enabled=pivots[1] is not None,
            focused_handle=focused_handle,
            focused_axis=axis,
            hovered=hovered,
            active=active,
        )

    def _project_pivot_axis(self, pivot: SharedEdgePivot | None) -> QPointF | None:
        """Project one common rail direction for operation cursor feedback."""
        if pivot is None:
            return None
        start = self._scene_to_panel(pivot.rail_start)
        end = self._scene_to_panel(pivot.rail_end)
        return None if start is None or end is None else end - start


def _participant_ids(seam: SharedEdgeSeam) -> tuple[uuid.UUID, ...]:
    """Return every deterministic seam participant identity."""
    return tuple(participant.layer_id for participant in seam.participants)


def _seam_identity(seam: SharedEdgeSeam) -> tuple[object, ...]:
    """Distinguish separate carriers that involve the same participant set."""
    endpoints = sorted(
        (
            (round(seam.start.x(), 9), round(seam.start.y(), 9)),
            (round(seam.end.x(), 9), round(seam.end.y(), 9)),
        )
    )
    return _participant_ids(seam), endpoints[0], endpoints[1]


__all__ = [
    "SharedEdgeHandlePresentation",
    "SharedEdgePresentation",
    "SharedEdgePresentationProjector",
]
