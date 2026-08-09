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
"""Editor-only source capabilities kept outside QPane's renderer graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.scene import LayerSourceReference, RasterBounds, SourceCapabilityRegistry

from ..coverage import CoverageSnapshot
from .pixel_fragments import RasterPixelFormat
from .pixel_transitions import RasterPixelTransition


@dataclass(frozen=True, slots=True)
class PixelSampleGeometry:
    """Describe one source-local raster sample and its exact output density."""

    source_rect: QRectF
    pixel_size: QSize

    def __post_init__(self) -> None:
        """Detach mutable Qt values and reject empty sample geometry."""
        if self.source_rect.isEmpty() or self.pixel_size.isEmpty():
            raise ValueError("pixel sample geometry must be positive")
        object.__setattr__(self, "source_rect", QRectF(self.source_rect))
        object.__setattr__(self, "pixel_size", QSize(self.pixel_size))


class SourceCoverageOwner(Protocol):
    """Expose authoritative editable coverage for one source type."""

    def coverage_snapshot(
        self,
        source: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return detached coverage, optionally clipped in source coordinates."""
        ...


class SourceContentBoundsOwner(Protocol):
    """Expose content-tight local bounds independently of storage geometry."""

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return minimal meaningful source-local bounds without dense scanning."""
        ...


class SourceContentBoundaryOwner(Protocol):
    """Expose a content-tight polygon independently of storage geometry."""

    def content_boundary(
        self,
        source: LayerSourceReference,
    ) -> tuple[QPointF, ...]:
        """Return an ordered source-local manipulation boundary."""
        ...


class SourceStorageBoundsOwner(Protocol):
    """Expose finite allocated storage independently of visible content."""

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the source's allocated local storage bounds."""
        ...


class SourceAuthoredBoundsOwner(Protocol):
    """Expose retained authorship geometry independently of storage."""

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return finite local bounds encompassing authored source content."""
        ...


class PixelPresentationOwner(Protocol):
    """Present canonical editor pixels through their source domain."""

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Return detached display pixels at the requested derived size."""
        ...

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Present one virtual raster transition on exact sampling grids."""
        ...


class SourceCoverageRegistry(SourceCapabilityRegistry[SourceCoverageOwner]):
    """Route editor coverage queries to one exact-type owner."""

    def coverage_snapshot(
        self,
        source: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return source coverage through its registered owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.coverage_snapshot(source, bounds)


class SourceContentBoundsRegistry(SourceCapabilityRegistry[SourceContentBoundsOwner]):
    """Route content geometry to the exact source-domain owner."""

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return source-owned meaningful bounds."""
        owner = self.owner_for(source)
        bounds = None if owner is None else owner.content_bounds(source)
        return None if bounds is None else QRectF(bounds)


class SourceContentBoundaryRegistry(
    SourceCapabilityRegistry[SourceContentBoundaryOwner]
):
    """Route polygon geometry to the exact source-domain owner."""

    def content_boundary(
        self,
        source: LayerSourceReference,
    ) -> tuple[QPointF, ...]:
        """Return detached source-owned boundary points."""
        owner = self.owner_for(source)
        boundary = () if owner is None else owner.content_boundary(source)
        return tuple(QPointF(point) for point in boundary)


class SourceStorageBoundsRegistry(SourceCapabilityRegistry[SourceStorageBoundsOwner]):
    """Route storage-geometry queries to exact source-domain owners."""

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return source storage geometry through its registered owner."""
        owner = self.owner_for(source)
        bounds = None if owner is None else owner.storage_bounds(source)
        return None if bounds is None else QRectF(bounds)


class SourceAuthoredBoundsRegistry(SourceCapabilityRegistry[SourceAuthoredBoundsOwner]):
    """Route authored-geometry queries to exact source-domain owners."""

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return source authorship geometry through its registered owner."""
        owner = self.owner_for(source)
        bounds = None if owner is None else owner.authored_bounds(source)
        return None if bounds is None else QRectF(bounds)


class PixelPresentationRegistry(SourceCapabilityRegistry[PixelPresentationOwner]):
    """Route transient editor-pixel presentation to one exact-type owner."""

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Present canonical pixels through their registered source owner."""
        owner = self.owner_for(source)
        if owner is None:
            return None
        return owner.present_pixels(source, pixel_format, pixels, target_size)

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Present a virtual transition through its source-domain sampler."""
        owner = self.owner_for(source)
        if owner is None:
            return None
        return owner.present_transition_samples(
            source,
            pixel_format,
            transition,
            samples,
        )


@dataclass(frozen=True, slots=True)
class EditorSourceCapabilities:
    """Collect capabilities used only by CuteCanvas editing workflows."""

    coverage: SourceCoverageRegistry
    content_bounds: SourceContentBoundsRegistry
    content_boundary: SourceContentBoundaryRegistry
    storage_bounds: SourceStorageBoundsRegistry
    authored_bounds: SourceAuthoredBoundsRegistry
    pixel_presentation: PixelPresentationRegistry

    @classmethod
    def create(cls) -> EditorSourceCapabilities:
        """Return an empty editor capability graph."""
        return cls(
            SourceCoverageRegistry(),
            SourceContentBoundsRegistry(),
            SourceContentBoundaryRegistry(),
            SourceStorageBoundsRegistry(),
            SourceAuthoredBoundsRegistry(),
            PixelPresentationRegistry(),
        )
