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
"""Mask-domain adapter for the source-neutral painting target contract."""

from __future__ import annotations

import uuid

from PySide6.QtGui import QColor

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageItem,
    CoverageSnapshot,
    RasterCoverageItem,
)

from ..fill.sources import HybridCoverageFillPixelSource
from ..painting import (
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    FloodFillSource,
    PaintTargetContext,
)
from .mask_service import MaskService
from .source_reference import MaskAssetReference


class MaskCoveragePaintTargetOwner:
    """Adapt active mask coverage transactions to generic brush routing."""

    def __init__(self, service: MaskService) -> None:
        """Bind the authoritative mask workflow facade."""
        self._service = service
        self._compiler = BrushStrokeCompiler()
        self._active_mask_id: uuid.UUID | None = None
        self._coordinates: BrushSourceCoordinateSession | None = None

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` references mask coverage."""
        return target.layer is not None and isinstance(
            target.layer.source, MaskAssetReference
        )

    def begin(self, target: PaintTargetContext) -> bool:
        """Activate the exact mask and begin its atomic stroke history."""
        layer = target.layer
        source = None if layer is None else layer.source
        if not isinstance(source, MaskAssetReference):
            return False
        if self._active_mask_id is not None:
            self._service.resetStrokePipeline(self._active_mask_id)
        self._service.activateMask(source.mask_id)
        self._service.pushActiveMaskState()
        self._active_mask_id = source.mask_id
        mask = self._service.assets.get_layer(source.mask_id)
        bounds = None if mask is None else mask.coverage.raster.bounds
        if bounds is None:
            self._active_mask_id = None
            return False
        self._coordinates = BrushSourceCoordinateSession(
            (float(bounds.x), float(bounds.y))
        )
        return True

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply one shared-engine segment through mask-owned preparation."""
        layer = target.layer
        source = None if layer is None else layer.source
        if (
            not isinstance(source, MaskAssetReference)
            or source.mask_id != self._active_mask_id
        ):
            return False
        mask = self._service.assets.get_layer(source.mask_id)
        coordinates = self._coordinates
        if mask is None or coordinates is None:
            return False
        bounds = mask.coverage.raster.bounds
        if bounds is None:
            return False
        configured = self._compiler.compile(
            coordinates.layer_segment(
                segment,
                (float(bounds.x), float(bounds.y)),
            ),
            preset,
        )
        self._service.applyStrokeSegment(configured)
        return True

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit accumulated mask patches through the existing mask owner."""
        source = None if target.layer is None else target.layer.source
        if (
            not isinstance(source, MaskAssetReference)
            or source.mask_id != self._active_mask_id
        ):
            return False
        self._service.commitStroke()
        self._active_mask_id = None
        self._coordinates = None
        return True

    def cancel(self, target: PaintTargetContext) -> bool:
        """Cancel provisional mask work without committing history."""
        mask_id = self._active_mask_id
        if mask_id is None:
            return False
        self._service.resetStrokePipeline(mask_id)
        self._active_mask_id = None
        self._coordinates = None
        return True

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return the mask's configured overlay color for brush feedback."""
        layer = target.layer
        source = None if layer is None else layer.source
        if not isinstance(source, MaskAssetReference):
            return QColor(fallback)
        color = self._service.mask_color(source.mask_id)
        return QColor(fallback) if color is None else QColor(color)

    def idle_preview_color(self, fallback: QColor) -> QColor:
        """Preserve mask-brush feedback before a mask is activated."""
        color = self._service.getActiveMaskColor()
        return QColor(128, 128, 128) if color is None else QColor(color)

    def commit_coverage_item(
        self,
        target: PaintTargetContext,
        item: CoverageItem,
    ) -> bool:
        """Commit target-local retained geometry into one mask asset."""
        source = None if target.layer is None else target.layer.source
        return bool(
            isinstance(source, MaskAssetReference)
            and self._service.applyMaskCoverageItem(source.mask_id, item)
        )

    def flood_fill_source(self, target: PaintTargetContext) -> FloodFillSource | None:
        """Return detached evaluated mask coverage for paint-bucket sampling."""
        source = None if target.layer is None else target.layer.source
        if not isinstance(source, MaskAssetReference):
            return None
        layer = self._service.assets.get_layer(source.mask_id)
        if layer is None:
            return None
        source_pixels = HybridCoverageFillPixelSource(layer.coverage.state_snapshot())
        return FloodFillSource(
            source_pixels,
            source_pixels.bounds,
            layer.coverage.revision,
        )

    def commit_flood_fill(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        expected_revision: object,
        color: QColor,
    ) -> bool:
        """Commit current bucket coverage as retained raster authorship."""
        source = None if target.layer is None else target.layer.source
        if not isinstance(source, MaskAssetReference):
            return False
        layer = self._service.assets.get_layer(source.mask_id)
        return bool(
            layer is not None
            and layer.coverage.revision == expected_revision
            and self._service.applyMaskCoverageItem(
                source.mask_id,
                RasterCoverageItem(uuid.uuid4(), coverage, mode),
            )
        )

    def commit_fill_coverage(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        color: QColor,
    ) -> bool:
        """Commit bounded fill coverage as retained mask authorship."""
        source = None if target.layer is None else target.layer.source
        return bool(
            isinstance(source, MaskAssetReference)
            and self._service.applyMaskCoverageItem(
                source.mask_id,
                RasterCoverageItem(uuid.uuid4(), coverage, mode),
            )
        )
