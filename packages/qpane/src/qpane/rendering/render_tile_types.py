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
"""Immutable products and source contracts for sampled render tiles."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage

from ..scene.raster import RasterBounds
from .render_tile_geometry import RenderTileKey, RenderTileRequest


@dataclass(frozen=True, slots=True)
class RenderTileProduct:
    """Carry one sampled image and its source-local draw geometry."""

    key: RenderTileKey
    source_rect: QRectF
    image: QImage
    image_source_rect: QRectF

    def __post_init__(self) -> None:
        """Detach mutable Qt values from worker-owned handles."""
        object.__setattr__(self, "source_rect", QRectF(self.source_rect))
        object.__setattr__(self, "image", QImage(self.image))
        object.__setattr__(self, "image_source_rect", QRectF(self.image_source_rect))

    @property
    def retained_bytes(self) -> int:
        """Return the detached image allocation size."""
        return int(self.image.sizeInBytes())


@runtime_checkable
class RenderTileBatchSource(Protocol):
    """Render one immutable source revision into requested sampled tiles."""

    @property
    def source_kind(self) -> str:
        """Return the stable cache namespace."""
        ...

    @property
    def source_id(self) -> uuid.UUID:
        """Return the stable reusable source identity."""
        ...

    @property
    def revision_key(self) -> Hashable:
        """Return the immutable render revision identity."""
        ...

    @property
    def fallback_key(self) -> Hashable:
        """Return identity shared only by visually compatible revisions."""
        ...

    @property
    def bounds(self) -> RasterBounds:
        """Return finite source-local sampling bounds."""
        ...

    def render_tiles(
        self,
        requests: tuple[RenderTileRequest, ...],
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Render one complete request batch away from the GUI thread."""
        ...


@runtime_checkable
class RegionSampleSource(Protocol):
    """Sample arbitrary source-local regions for nested offscreen rendering."""

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return exact premultiplied pixels for one source-local region."""
        ...


@dataclass(frozen=True, slots=True)
class RenderRefinement:
    """Describe exact, pending-with-fallback, or unavailable refinement."""

    products: tuple[RenderTileProduct, ...] | None
    pending: bool
    exact: bool

    @classmethod
    def ready(cls, products: tuple[RenderTileProduct, ...]) -> RenderRefinement:
        """Return an exact complete refinement result."""
        return cls(products, False, True)

    @classmethod
    def waiting(
        cls,
        fallback: tuple[RenderTileProduct, ...] | None,
    ) -> RenderRefinement:
        """Return pending work with a complete covering fallback when available."""
        return cls(fallback, True, False)

    @classmethod
    def unavailable(cls) -> RenderRefinement:
        """Return a result requiring a source-specific immediate fallback."""
        return cls(None, False, False)
