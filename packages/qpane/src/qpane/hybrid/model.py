#    QPane - High-performance PySide6 image viewer
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
"""Immutable source-neutral values for hybrid raster/vector coverage."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, TypeAlias, runtime_checkable

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage

from ..scene.affine import LayerTransform
from ..scene.raster import RasterBounds
from ..vector.model import VectorObject


class HybridCombineMode(str, Enum):
    """Ordered alpha-coverage operations for hybrid primitives."""

    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


@runtime_checkable
class HybridRasterSampler(Protocol):
    """Sample one immutable, thread-safe raster contribution."""

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return detached grayscale coverage matching ``pixel_size``.

        QPane invokes this method on render workers. Implementations must be
        safe for concurrent reads and must not access GUI-thread-only objects.
        """
        ...


@dataclass(frozen=True, slots=True)
class HybridRasterPrimitive:
    """Reference one bounded raster contribution without materializing gaps."""

    primitive_id: uuid.UUID
    bounds: RasterBounds
    sampler: HybridRasterSampler = field(repr=False, compare=False)
    combine_mode: HybridCombineMode = HybridCombineMode.ADD

    def __post_init__(self) -> None:
        """Validate the sampler contract and normalize the operation."""
        if not isinstance(self.sampler, HybridRasterSampler):
            raise TypeError("sampler must implement HybridRasterSampler")
        object.__setattr__(self, "combine_mode", HybridCombineMode(self.combine_mode))


@dataclass(frozen=True, slots=True)
class HybridVectorPrimitive:
    """Retain semantic vector geometry as one coverage contribution."""

    primitive_id: uuid.UUID
    geometry: VectorObject
    bounds: RasterBounds
    combine_mode: HybridCombineMode = HybridCombineMode.ADD
    transform: LayerTransform = field(default_factory=LayerTransform)
    feather_radius: float = 0.0

    def __post_init__(self) -> None:
        """Validate coverage-specific presentation values."""
        radius = float(self.feather_radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("feather radius must be finite and non-negative")
        object.__setattr__(self, "combine_mode", HybridCombineMode(self.combine_mode))
        object.__setattr__(self, "feather_radius", radius)


HybridPrimitive: TypeAlias = HybridRasterPrimitive | HybridVectorPrimitive


@dataclass(frozen=True, slots=True)
class HybridDocument:
    """Describe one immutable ordered hybrid coverage expression."""

    source_id: uuid.UUID
    bounds: RasterBounds
    primitives: tuple[HybridPrimitive, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        """Validate stable primitive identity and revision state."""
        primitives = tuple(self.primitives)
        identities = tuple(primitive.primitive_id for primitive in primitives)
        if len(set(identities)) != len(identities):
            raise ValueError("hybrid primitive IDs must be unique")
        if self.revision < 0:
            raise ValueError("hybrid document revision must be non-negative")
        object.__setattr__(self, "primitives", primitives)


@dataclass(frozen=True, slots=True)
class HybridPresentationStyle:
    """Describe late color and optional one-pixel outline presentation."""

    color: QColor
    outline_color: QColor | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt color handles."""
        object.__setattr__(self, "color", QColor(self.color))
        if self.outline_color is not None:
            object.__setattr__(self, "outline_color", QColor(self.outline_color))
