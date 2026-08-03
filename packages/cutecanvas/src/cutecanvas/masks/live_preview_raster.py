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
"""Cumulative sampled coverage used while a mask stroke is in flight."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from qpane.sdk.scene import RasterBounds


@dataclass(frozen=True, slots=True)
class LivePreviewRegion:
    """Describe one border-safe update within a sampled preview raster."""

    destination: QRect
    context: QImage
    context_core: QRect


@dataclass(frozen=True, slots=True)
class LivePreviewPatch:
    """Carry one immutable final-coverage patch in layer-local coordinates."""

    bounds: RasterBounds
    pixels: np.ndarray

    def __post_init__(self) -> None:
        """Detach and validate the provisional coverage pixels."""
        expected = (self.bounds.height, self.bounds.width)
        pixels = np.array(self.pixels, copy=True, order="C")
        if pixels.dtype != np.uint8 or pixels.shape != expected:
            raise ValueError(f"live preview patch pixels must match {expected}")
        pixels.flags.writeable = False
        object.__setattr__(self, "pixels", pixels)


class LiveMaskPreviewPatches:
    """Retain native provisional patches without materializing the mask envelope."""

    def __init__(self, source_bounds: RasterBounds) -> None:
        """Anchor storage-coordinate patches to one layer-local source extent."""
        if source_bounds.width <= 0 or source_bounds.height <= 0:
            raise ValueError("source_bounds must be non-empty")
        self._source_bounds = source_bounds
        self._session_id = uuid.uuid4()
        self._patches: list[LivePreviewPatch] = []
        self._content_bounds: RasterBounds | None = None
        self._revision = 0

    @property
    def session_id(self) -> uuid.UUID:
        """Return the stable identity of this in-flight preview session."""
        return self._session_id

    @property
    def source_bounds(self) -> RasterBounds:
        """Return the layer-local source extent represented by this preview."""
        return self._source_bounds

    @property
    def content_bounds(self) -> RasterBounds | None:
        """Return the union of provisional source-local patch bounds."""
        return self._content_bounds

    @property
    def revision(self) -> int:
        """Return the monotonic provisional content generation."""
        return self._revision

    def apply_patch(self, storage_rect: QRect, patch: QImage) -> None:
        """Append one final-coverage patch without reading untouched storage."""
        if storage_rect.isNull() or storage_rect.isEmpty() or patch.isNull():
            raise ValueError("live preview patches must be non-empty")
        if patch.size() != storage_rect.size():
            raise ValueError("native live preview patch must match its storage rect")
        storage = RasterBounds(
            0,
            0,
            self._source_bounds.width,
            self._source_bounds.height,
        )
        requested = RasterBounds.from_qrect(storage_rect)
        if not storage.contains(requested):
            raise ValueError("live preview patch lies outside the source storage")
        local_bounds = RasterBounds(
            self._source_bounds.x + requested.x,
            self._source_bounds.y + requested.y,
            requested.width,
            requested.height,
        )
        provisional = LivePreviewPatch(
            local_bounds,
            qimage_to_numpy_grayscale8(patch),
        )
        self._patches.append(provisional)
        self._content_bounds = (
            local_bounds
            if self._content_bounds is None
            else self._content_bounds.united(local_bounds)
        )
        self._revision += 1

    def apply_to(self, bounds: RasterBounds, pixels: np.ndarray) -> None:
        """Overlay intersecting provisional coverage onto a sampled base region."""
        expected = (bounds.height, bounds.width)
        if pixels.dtype != np.uint8 or pixels.shape != expected:
            raise ValueError(f"sample pixels must match {expected}")
        for patch in self._patches:
            overlap = bounds.intersection(patch.bounds)
            if overlap is None:
                continue
            source_x = overlap.x - patch.bounds.x
            source_y = overlap.y - patch.bounds.y
            target_x = overlap.x - bounds.x
            target_y = overlap.y - bounds.y
            pixels[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = patch.pixels[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]


class LiveMaskPreviewRaster:
    """Accumulate local stroke patches on one source-anchored sample lattice."""

    def __init__(
        self,
        *,
        source_size: QSize,
        stride: int,
        base_pixels: np.ndarray,
    ) -> None:
        """Initialize the sampled raster from durable mask pixels."""
        if not source_size.isValid():
            raise ValueError("source_size must be valid")
        self._stride = max(1, int(stride))
        expected = QSize(
            math.ceil(source_size.width() / self._stride),
            math.ceil(source_size.height() / self._stride),
        )
        grayscale = numpy_to_qimage_grayscale8(base_pixels)
        if grayscale.size() != expected:
            raise ValueError(
                f"base_pixels must produce {expected.width()}x{expected.height()}"
            )
        self._source_size = QSize(source_size)
        self._grayscale = grayscale

    @property
    def stride(self) -> int:
        """Return source pixels represented by one preview pixel."""
        return self._stride

    @property
    def image(self) -> QImage:
        """Return the mutable sampled coverage owned by this preview."""
        return self._grayscale

    @property
    def source_size(self) -> QSize:
        """Return the full source raster dimensions."""
        return QSize(self._source_size)

    def apply_patch(self, source_rect: QRect, patch: QImage) -> LivePreviewRegion:
        """Accumulate one aligned patch and return its border-safe update context."""
        if source_rect.isNull() or source_rect.isEmpty() or patch.isNull():
            raise ValueError("live preview patches must be non-empty")
        if source_rect.left() % self._stride or source_rect.top() % self._stride:
            raise ValueError("live preview patches must align to the sample lattice")
        destination = QRect(
            QPoint(
                source_rect.left() // self._stride,
                source_rect.top() // self._stride,
            ),
            patch.size(),
        ).intersected(self._grayscale.rect())
        if destination.isNull() or destination.isEmpty():
            raise ValueError("live preview patch lies outside the sampled raster")
        source = QRect(QPoint(0, 0), destination.size())
        painter = QPainter(self._grayscale)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(destination, patch, source)
        painter.end()

        affected = destination.adjusted(-1, -1, 1, 1).intersected(
            self._grayscale.rect()
        )
        context_rect = affected.adjusted(-1, -1, 1, 1).intersected(
            self._grayscale.rect()
        )
        context_core = affected.translated(-context_rect.topLeft())
        return LivePreviewRegion(
            destination=affected,
            context=self._grayscale.copy(context_rect),
            context_core=context_core,
        )

    def source_rect(self, sampled_rect: QRect) -> QRect:
        """Map one sampled rectangle back to clipped source coordinates."""
        left = sampled_rect.left() * self._stride
        top = sampled_rect.top() * self._stride
        right = min(
            self._source_size.width(),
            (sampled_rect.right() + 1) * self._stride,
        )
        bottom = min(
            self._source_size.height(),
            (sampled_rect.bottom() + 1) * self._stride,
        )
        return QRect(left, top, right - left, bottom - top)
