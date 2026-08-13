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

"""Single-edit publication boundary for completed polygon coverage."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    CoverageItem,
    VectorCoverageItem,
)
from PySide6.QtCore import QPointF


class PolygonCoveragePublication:
    """Constrain and publish one completed polygon as retained coverage."""

    def __init__(
        self,
        *,
        commit: Callable[[CoverageItem], bool],
        constrain: Callable[[CoverageItem], CoverageItem | None],
        feather_radius: Callable[[], float],
    ) -> None:
        """Capture destination policy and the single commit boundary."""
        self._commit = commit
        self._constrain = constrain
        self._feather_radius = feather_radius
        self._geometry = CoverageGeometryFactory()

    def publish(
        self,
        points: tuple[QPointF, ...],
        combine_mode: CoverageCombineMode,
    ) -> bool:
        """Publish one valid closed polygon without retaining transient vertices."""
        item = VectorCoverageItem(
            uuid.uuid4(),
            self._geometry.lasso(points),
            combine_mode,
            feather_radius=self._feather_radius(),
        )
        constrained = self._constrain(item)
        return constrained is not None and self._commit(constrained)


__all__ = ["PolygonCoveragePublication"]
