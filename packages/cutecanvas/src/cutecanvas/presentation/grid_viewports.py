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

"""Own fitted, non-navigable viewport state for responsive grid targets."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from qpane.sdk.layout import ResponsiveGridSnapshot

from .target_mount import CanvasTargetMount


class GridViewportController:
    """Fit every visible grid target after responsive geometry is applied."""

    def __init__(self, mounts: Mapping[uuid.UUID, CanvasTargetMount]) -> None:
        """Retain the grid's target mounts without owning their layout."""

        self._mounts = dict(mounts)

    def unlock_for_reflow(self) -> None:
        """Allow target resize handling to fit against its new geometry."""

        for mount in self._mounts.values():
            mount.canvas.setPanZoomLocked(False)

    def fit_and_lock(self, snapshot: ResponsiveGridSnapshot) -> None:
        """Fit visible targets to their assigned cells, then disable navigation."""

        for frame in snapshot.frames:
            canvas = self._mounts[frame.target_id].canvas
            canvas.setZoomFit()
            canvas.setPanZoomLocked(True)
