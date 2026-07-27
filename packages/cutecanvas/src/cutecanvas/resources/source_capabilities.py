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
"""Capability routing from stable resource references to focused payload owners."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.scene import (
    LayerSourceReference,
    RasterBounds,
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)

from ..coverage import CoverageSnapshot
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import PixelSampleGeometry
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


class ProjectResourceCapabilityOwner(Protocol):
    """Describe the shared surface implemented by resource payload adapters."""

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return raster presentation when this payload is raster renderable."""
        ...

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return derived-product caching policy."""
        ...

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return dense or sampled pixels when available."""
        ...

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return intrinsic pixel dimensions."""
        ...

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return source provenance when available."""
        ...

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Return source-local alpha hit testing."""
        ...

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return alpha-tight content bounds."""
        ...

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return storage bounds."""
        ...

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return authored bounds."""
        ...

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Present one virtual edit through the payload's native sampler."""
        ...


class ProjectResourceSourceCapabilities:
    """Route capabilities by authoritative kind while preserving one reference type."""

    def __init__(self, resources: ProjectResourceStore) -> None:
        """Bind the resource graph and initialize focused owner routes."""
        self._resources = resources
        self._owners: dict[ProjectResourceKind, ProjectResourceCapabilityOwner] = {}

    def register(
        self,
        kind: ProjectResourceKind,
        owner: ProjectResourceCapabilityOwner,
    ) -> None:
        """Register the sole capability owner for one resource kind."""
        existing = self._owners.get(kind)
        if existing is not None and existing is not owner:
            raise ValueError(f"capability owner already registered for {kind.value}")
        self._owners[kind] = owner

    def unregister(
        self,
        kind: ProjectResourceKind,
        owner: ProjectResourceCapabilityOwner,
    ) -> None:
        """Remove a matching capability owner."""
        if self._owners.get(kind) is owner:
            self._owners.pop(kind, None)

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return raster presentation through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "presentation_for", None)
        return None if not callable(method) else method(source)

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return derived-product policy through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "product_policy", None)
        return RasterProductPolicy.CACHEABLE if not callable(method) else method(source)

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return pixels through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "source_image", None)
        return None if not callable(method) else method(source, scale=scale)

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return source dimensions through the current payload owner."""
        owner = self._owner(source)
        return None if owner is None else owner.source_size(source)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return source provenance through the current payload owner."""
        owner = self._owner(source)
        return None if owner is None else owner.source_path(source)

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Return alpha hit testing through the current payload owner."""
        owner = self._owner(source)
        return bool(owner is not None and owner.contains(source, point))

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return alpha-tight bounds through the current payload owner."""
        owner = self._owner(source)
        return None if owner is None else owner.content_bounds(source)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return storage bounds through the current payload owner."""
        owner = self._owner(source)
        return None if owner is None else owner.storage_bounds(source)

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return authored bounds through the current payload owner."""
        owner = self._owner(source)
        return None if owner is None else owner.authored_bounds(source)

    def sampled_source(self, source: LayerSourceReference) -> object | None:
        """Return a sampled-render source through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "sampled_source", None)
        return None if not callable(method) else method(source)

    def vector_document(self, source: LayerSourceReference) -> object | None:
        """Return an immutable vector presentation through its payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "vector_document", None)
        return None if not callable(method) else method(source)

    def hybrid_document(self, source: LayerSourceReference) -> object | None:
        """Return a retained hybrid snapshot through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "hybrid_document", None)
        return None if not callable(method) else method(source)

    def coverage_snapshot(
        self,
        source: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return editable coverage through the current payload owner."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "coverage_snapshot", None)
        return None if not callable(method) else method(source, bounds)

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return sparse pixels when the current owner supplies them."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "source_patches", None)
        return None if not callable(method) else method(source, visible_bounds)

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Present canonical pixels when the current owner supports editing."""
        owner = self._owner(source)
        method = None if owner is None else getattr(owner, "present_pixels", None)
        return (
            None
            if not callable(method)
            else method(source, pixel_format, pixels, target_size)
        )

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Present a virtual edit through the current payload owner."""
        owner = self._owner(source)
        method = (
            None
            if owner is None
            else getattr(owner, "present_transition_samples", None)
        )
        return (
            None
            if not callable(method)
            else method(source, pixel_format, transition, samples)
        )

    def _owner(
        self,
        source: LayerSourceReference,
    ) -> ProjectResourceCapabilityOwner | None:
        """Resolve the current kind and its focused payload adapter."""
        if not isinstance(source, ProjectResourceReference):
            return None
        record = self._resources.resolve(source)
        return None if record is None else self._owners.get(record.kind)
