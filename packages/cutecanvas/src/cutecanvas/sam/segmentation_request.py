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
"""Describe target-stable Smart segmentation requests."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import Enum

from cutecanvas.coverage import CoverageCombineMode


class SmartSegmentationProduct(str, Enum):
    """Name the durable artifact produced from segmented coverage."""

    PIXEL_SELECTION = "pixel-selection"
    MASK_COVERAGE = "mask-coverage"


@dataclass(frozen=True, slots=True)
class SmartSegmentationRequest:
    """Carry one prompt plus its exact raster and destination identities."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    resource_id: uuid.UUID
    bounds: tuple[float, float, float, float]
    product: SmartSegmentationProduct
    combine_mode: CoverageCombineMode
    mask_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous targets and invalid rectangular bounds."""
        identities = (self.scene_id, self.layer_id, self.resource_id)
        if any(not isinstance(identity, uuid.UUID) for identity in identities):
            raise TypeError("scene, layer, and resource IDs must be UUID values")
        if len(self.bounds) != 4 or not all(
            math.isfinite(value) for value in self.bounds
        ):
            raise ValueError("bounds must contain four finite coordinates")
        x1, y1, x2, y2 = self.bounds
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bounds must describe a positive rectangle")
        if self.product is SmartSegmentationProduct.MASK_COVERAGE:
            if not isinstance(self.mask_id, uuid.UUID):
                raise ValueError("mask coverage requests require a mask target")
        elif self.mask_id is not None:
            raise ValueError("pixel-selection requests cannot target a mask")

    @property
    def erase(self) -> bool:
        """Return whether the destination algebra subtracts generated coverage."""
        return self.combine_mode is CoverageCombineMode.SUBTRACT


__all__ = ["SmartSegmentationProduct", "SmartSegmentationRequest"]
