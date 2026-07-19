#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Immutable values describing composition pixel-selection state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..coverage import CoverageSnapshot


@dataclass(frozen=True, slots=True)
class PixelSelectionState:
    """Capture one composition's current pixel-selection coverage."""

    scene_id: uuid.UUID
    revision: int
    coverage: CoverageSnapshot | None

    @property
    def has_selection(self) -> bool:
        """Return whether nonzero selection coverage is active."""
        return self.coverage is not None
