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

"""Define detached products published by the native SAM session."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SamPredictorReference:
    """Identify one prepared predictor without exposing its native object."""

    image_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SamSessionSnapshot:
    """Describe the native predictor cache without retaining predictors."""

    entries: tuple[tuple[uuid.UUID, int], ...]

    @property
    def cache_bytes(self) -> int:
        """Return the measured cache footprint."""
        return sum(size for _image_id, size in self.entries)


@dataclass(frozen=True, slots=True)
class SamPreparationProduct:
    """Publish one prepared predictor and the resulting cache snapshot."""

    reference: SamPredictorReference
    cache_hit: bool
    snapshot: SamSessionSnapshot
    evicted_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class SamMaskProduct:
    """Carry one model inference result without its native predictor."""

    image_id: uuid.UUID
    bbox: np.ndarray
    erase_mode: bool
    mask: np.ndarray | None


@dataclass(frozen=True, slots=True)
class SamCacheMutationProduct:
    """Publish the result of one thread-affine cache mutation."""

    removed_ids: tuple[uuid.UUID, ...]
    snapshot: SamSessionSnapshot


__all__ = [
    "SamCacheMutationProduct",
    "SamMaskProduct",
    "SamPredictorReference",
    "SamPreparationProduct",
    "SamSessionSnapshot",
]
