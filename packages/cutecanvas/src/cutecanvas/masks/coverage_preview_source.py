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
"""Render current mask coverage neutrally in dedicated document viewports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage

from qpane import HybridPresentationStyle, HybridSource
from qpane.sdk.raster import present_hybrid_pixels
from qpane.sdk.scene import LayerSourceReference, RasterBounds

from ..coverage import CoverageSnapshot
from ..resources import ProjectResourceReference
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import PixelSampleGeometry
from .source_resolver import MaskSourceCapabilities

_NEUTRAL_MASK_STYLE = HybridPresentationStyle(QColor("white"))


@dataclass(frozen=True, slots=True)
class MaskCoverageSourceReference:
    """Address one mask resource through its neutral coverage presentation."""

    resource_id: uuid.UUID
    kind: str = field(default="mask-coverage", init=False)

    def __post_init__(self) -> None:
        """Validate the stable resource identity."""
        if not isinstance(self.resource_id, uuid.UUID):
            raise TypeError("resource_id must be a UUID")


@dataclass(frozen=True, slots=True)
class MaskCoverageSourceCapabilities:
    """Expose white coverage independently of the mask overlay color."""

    source: MaskSourceCapabilities

    def source_size(self, reference: LayerSourceReference) -> QSize | None:
        """Return the current mask dimensions without copying pixels."""
        return self.source.source_size(_resource(reference))

    def source_path(self, reference: LayerSourceReference) -> Path | None:
        """Return no path because mask coverage remains memory-backed."""
        del reference
        return None

    def contains(self, reference: LayerSourceReference, point: QPointF) -> bool:
        """Hit-test the current mask coverage."""
        return self.source.contains(_resource(reference), point)

    def hybrid_document(
        self,
        reference: LayerSourceReference,
    ) -> HybridSource | None:
        """Return current mask pixels with a neutral white presentation."""
        resource = _resource(reference)
        return self.source.hybrid_document_with_style(
            resource,
            _NEUTRAL_MASK_STYLE,
        )

    def coverage_snapshot(
        self,
        reference: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return authoritative coverage for exact transient presentation."""
        return self.source.coverage_snapshot(_resource(reference), bounds)

    def present_pixels(
        self,
        reference: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Present canonical coverage with the neutral preview style."""
        _resource(reference)
        if pixel_format is not RasterPixelFormat.COVERAGE8:
            return None
        image = present_hybrid_pixels(pixels, _NEUTRAL_MASK_STYLE)
        if target_size is not None and image.size() != target_size:
            image = image.scaled(
                target_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return image

    def present_transition_samples(
        self,
        reference: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Sample a virtual transition through the neutral hybrid evaluator."""
        if pixel_format is not RasterPixelFormat.COVERAGE8:
            return None
        return self.source.present_transition_samples_with_style(
            _resource(reference),
            transition,
            samples,
            _NEUTRAL_MASK_STYLE,
        )


def _resource(reference: LayerSourceReference) -> ProjectResourceReference:
    """Convert a preview reference to its authoritative resource key."""
    if not isinstance(reference, MaskCoverageSourceReference):
        raise TypeError("reference must be a MaskCoverageSourceReference")
    return ProjectResourceReference(reference.resource_id)


__all__ = [
    "MaskCoverageSourceCapabilities",
    "MaskCoverageSourceReference",
]
