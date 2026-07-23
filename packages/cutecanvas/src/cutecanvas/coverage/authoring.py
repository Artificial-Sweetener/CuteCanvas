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

"""Host-configurable retained coverage shape authoring policy."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class CoverageShapeOptions:
    """Describe options applied to future retained coverage shapes."""

    feather_radius: float = 0.0

    def __post_init__(self) -> None:
        """Require a finite non-negative scene-space feather radius."""
        radius = float(self.feather_radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("shape feather radius must be finite and non-negative")
        object.__setattr__(self, "feather_radius", radius)


class CoverageShapeConfiguration:
    """Own durable host preferences independently of transient gestures."""

    def __init__(self, changed: Callable[[], None] | None = None) -> None:
        """Initialize exact hard-edged retained shape defaults."""
        self._options = CoverageShapeOptions()
        self._changed = changed

    @property
    def options(self) -> CoverageShapeOptions:
        """Return immutable options for the next shape commit."""
        return self._options

    def configure(self, *, feather_radius: float | None = None) -> bool:
        """Replace supplied options and publish one change notification."""
        options = self._options
        if feather_radius is not None:
            options = replace(options, feather_radius=feather_radius)
        if options == self._options:
            return False
        self._options = options
        if self._changed is not None:
            self._changed()
        return True
