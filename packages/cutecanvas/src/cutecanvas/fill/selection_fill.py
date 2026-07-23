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
"""Atomic Fill Selection coordination across source-neutral paint targets."""

from __future__ import annotations

from ..coverage import CoverageCombineMode
from ..painting import PaintingCoordinator
from ..selection import LayerCoverageProjector, PixelSelectionService


class SelectionFillCoordinator:
    """Project the active composition selection into one paint destination."""

    def __init__(
        self,
        *,
        painting: PaintingCoordinator,
        selections: PixelSelectionService,
    ) -> None:
        """Bind authoritative target and selection owners."""
        self._painting = painting
        self._selections = selections
        self._projector = LayerCoverageProjector()

    @property
    def can_fill(self) -> bool:
        """Return whether a nonempty selection and compatible target are active."""
        context = self._painting.current_context()
        return bool(
            context is not None
            and self._painting.can_fill_coverage()
            and self._selections.state(context.scene.scene_id).coverage is not None
        )

    def fill(
        self,
        mode: CoverageCombineMode = CoverageCombineMode.ADD,
    ) -> bool:
        """Commit the current soft selection as one target-local fill edit."""
        context = self._painting.current_context()
        if context is None or not self._painting.can_fill_coverage():
            return False
        coverage = self._selections.state(context.scene.scene_id).coverage
        if coverage is None:
            return False
        layer = context.layer
        if layer is not None:
            transform = layer.transform
            inverse = None if transform is None else transform.inverted()
            if inverse is None:
                return False
            coverage = self._projector.project(coverage, inverse)
        return bool(
            coverage is not None
            and self._painting.commit_fill_coverage(context, coverage, mode)
        )
