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
"""Focused capability contracts for reusable layer sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from .source_references import LayerSourceReference

if TYPE_CHECKING:
    from .raster import RasterBounds


class RasterPresentation(str, Enum):
    """Closed renderer primitive selected by a source presentation owner."""

    IMAGE = "image"
    OVERLAY = "overlay"


class RasterProductPolicy(str, Enum):
    """Describe whether a raster sample is stable enough for derived products."""

    CACHEABLE = "cacheable"
    VOLATILE = "volatile"


class SourceMetadataOwner(Protocol):
    """Supply non-pixel metadata for one source-reference type."""

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return authoritative source dimensions without copying pixels."""
        ...

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return the source path when the domain has one."""
        ...


class RasterPresentationOwner(Protocol):
    """Supply renderer-ready raster products for one source-reference type."""

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return the closed raster primitive produced for ``source``."""
        ...


@dataclass(frozen=True, slots=True)
class RasterSourcePatch:
    """Carry one clipped raster core plus its filterable source-local sample."""

    bounds: RasterBounds
    image: QImage
    sample_bounds: RasterBounds | None = None

    def __post_init__(self) -> None:
        """Detach the Qt image crossing into renderer-owned planning."""
        sample_bounds = (
            self.bounds if self.sample_bounds is None else self.sample_bounds
        )
        image = QImage(self.image)
        if not sample_bounds.contains(self.bounds):
            raise ValueError("raster patch sample must contain its clipped core")
        if image.size() != QSize(sample_bounds.width, sample_bounds.height):
            raise ValueError("raster patch image must match its sample bounds")
        object.__setattr__(self, "image", image)
        object.__setattr__(self, "sample_bounds", sample_bounds)


class RasterPatchPresentationOwner(Protocol):
    """Supply sparse raster patches without materializing transparent gaps."""

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return visible patches, or ``None`` to request dense volatile fallback."""
        ...

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the current derived-product policy for ``source``."""
        ...

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return detached source pixels, sampled when the owner supports it."""
        ...


class SourceHitTestOwner(Protocol):
    """Answer source-local content hit tests for one source-reference type."""

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Return whether source content contains the local point."""
        ...


class VectorPresentationOwner(Protocol):
    """Supply immutable vector document snapshots to the renderer."""

    def vector_document(self, source: LayerSourceReference) -> object | None:
        """Return one immutable vector document revision."""
        ...


class HybridPresentationOwner(Protocol):
    """Supply immutable hybrid document snapshots to the renderer."""

    def hybrid_document(self, source: LayerSourceReference) -> object | None:
        """Return one immutable hybrid presentation revision."""
        ...


class SampledPresentationOwner(Protocol):
    """Supply immutable sampled tile sources for procedural raster content."""

    def sampled_source(self, source: LayerSourceReference) -> object | None:
        """Return one immutable sampled tile source revision."""
        ...


_OwnerT = TypeVar("_OwnerT")


class SourceCapabilityRegistry(Generic[_OwnerT]):
    """Map source-reference types to exactly one focused capability owner."""

    def __init__(self) -> None:
        """Initialize an empty exact-type mapping."""
        self._owners: dict[type[object], _OwnerT] = {}

    def register(
        self,
        source_type: type[object],
        owner: _OwnerT,
    ) -> _OwnerT:
        """Register the sole owner for ``source_type``."""
        existing = self._owners.get(source_type)
        if existing is not None and existing is not owner:
            raise ValueError(f"capability owner already registered for {source_type!r}")
        self._owners[source_type] = owner
        return owner

    def unregister(self, source_type: type[object], owner: _OwnerT) -> None:
        """Remove ``owner`` only when it still owns ``source_type``."""
        if self._owners.get(source_type) is owner:
            self._owners.pop(source_type, None)

    def owner_for(self, source: LayerSourceReference) -> _OwnerT | None:
        """Return the capability owner for the source's concrete type."""
        return self._owners.get(type(source))


class SourceMetadataRegistry(SourceCapabilityRegistry[SourceMetadataOwner]):
    """Route only source metadata queries."""

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return source dimensions through the metadata owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.source_size(source)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return source path metadata through the metadata owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.source_path(source)


class RasterPresentationRegistry(SourceCapabilityRegistry[RasterPresentationOwner]):
    """Route only raster-product queries."""

    def presentation_for(
        self, source: LayerSourceReference
    ) -> RasterPresentation | None:
        """Return the source's closed raster primitive when supported."""
        owner = self.owner_for(source)
        return None if owner is None else owner.presentation_for(source)

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the registered source's current derived-product policy."""
        owner = self.owner_for(source)
        return (
            RasterProductPolicy.CACHEABLE
            if owner is None
            else owner.product_policy(source)
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return source pixels through the raster owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.source_image(source, scale=scale)


class RasterPatchPresentationRegistry(
    SourceCapabilityRegistry[RasterPatchPresentationOwner]
):
    """Route sparse patch sampling independently of ordinary raster metadata."""

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return visible patches when the source domain supplies them."""
        owner = self.owner_for(source)
        return () if owner is None else owner.source_patches(source, visible_bounds)


class SourceHitTestRegistry(SourceCapabilityRegistry[SourceHitTestOwner]):
    """Route only source-local content hit tests."""

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Return whether the registered source content contains ``point``."""
        owner = self.owner_for(source)
        return bool(owner is not None and owner.contains(source, point))


class VectorPresentationRegistry(SourceCapabilityRegistry[VectorPresentationOwner]):
    """Route vector snapshots without pretending they are raster pixels."""

    def vector_document(self, source: LayerSourceReference) -> object | None:
        """Return a vector snapshot through the exact typed owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.vector_document(source)


class HybridPresentationRegistry(SourceCapabilityRegistry[HybridPresentationOwner]):
    """Route hybrid snapshots without flattening them into raster patches."""

    def hybrid_document(self, source: LayerSourceReference) -> object | None:
        """Return a hybrid snapshot through the exact typed owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.hybrid_document(source)


class SampledPresentationRegistry(SourceCapabilityRegistry[SampledPresentationOwner]):
    """Route generic sampled tile sources without flattening them eagerly."""

    def sampled_source(self, source: LayerSourceReference) -> object | None:
        """Return a sampled tile source through the exact typed owner."""
        owner = self.owner_for(source)
        return None if owner is None else owner.sampled_source(source)


@dataclass(frozen=True, slots=True)
class LayerSourceCapabilities:
    """Aggregate focused registries for composition-root wiring only."""

    metadata: SourceMetadataRegistry
    rasters: RasterPresentationRegistry
    raster_patches: RasterPatchPresentationRegistry
    hit_tests: SourceHitTestRegistry
    vectors: VectorPresentationRegistry
    hybrids: HybridPresentationRegistry
    sampled: SampledPresentationRegistry

    @classmethod
    def create(cls) -> LayerSourceCapabilities:
        """Return an empty capability graph."""
        return cls(
            metadata=SourceMetadataRegistry(),
            rasters=RasterPresentationRegistry(),
            raster_patches=RasterPatchPresentationRegistry(),
            hit_tests=SourceHitTestRegistry(),
            vectors=VectorPresentationRegistry(),
            hybrids=HybridPresentationRegistry(),
            sampled=SampledPresentationRegistry(),
        )
