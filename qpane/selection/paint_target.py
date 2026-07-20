#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Composition pixel-selection adapter for the shared paint-target contract."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QColor

from ..coverage import CoverageSnapshot
from ..painting import (
    BrushCompositor,
    BrushDabEngine,
    BrushDabRegionPlanner,
    BrushPreset,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    PaintTargetContext,
)
from ..painting.rendering import render_coverage_stroke
from ..scene.raster import RasterBounds, RasterExtentPolicy
from ..types import PaintTargetKind
from .compositor import trim_selection_coverage
from .service import PixelSelectionService


@dataclass(slots=True)
class _SelectionPaintSession:
    """Retain one unresolved selection-paint transition."""

    scene_id: uuid.UUID
    before: CoverageSnapshot | None


class PixelSelectionPaintTargetOwner:
    """Paint the one authoritative pixel selection with shared brush dabs."""

    def __init__(
        self,
        selections: PixelSelectionService,
        compositor: BrushCompositor | None = None,
    ) -> None:
        """Bind authoritative selection state."""
        self._selections = selections
        self._dabs = BrushDabEngine()
        self._compiler = BrushStrokeCompiler()
        self._regions = BrushDabRegionPlanner()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._session: _SelectionPaintSession | None = None

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` is composition pixel-selection coverage."""
        return target.identity.kind is PaintTargetKind.PIXEL_SELECTION

    def begin(self, target: PaintTargetContext) -> bool:
        """Capture the exact pre-stroke selection state."""
        if self._session is not None:
            self.cancel(target)
        self._session = _SelectionPaintSession(
            target.scene.scene_id,
            self._selections.state(target.scene.scene_id).coverage,
        )
        return True

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Composite one shared segment into live selection coverage."""
        session = self._matching_session(target)
        if session is None:
            return False
        configured = self._compiler.compile(segment, preset)
        dirty = self._regions.bounds(self._dabs.segment_dabs(configured))
        scene_rect = target.scene.bounds
        scene_left = math.floor(scene_rect.x)
        scene_top = math.floor(scene_rect.y)
        scene_right = math.ceil(scene_rect.x + scene_rect.width)
        scene_bottom = math.ceil(scene_rect.y + scene_rect.height)
        scene_bounds = RasterBounds(
            scene_left,
            scene_top,
            scene_right - scene_left,
            scene_bottom - scene_top,
        )
        dirty = None if dirty is None else dirty.intersection(scene_bounds)
        if dirty is None:
            return False
        current = self._selections.state(target.scene.scene_id).coverage
        before = _coverage_region(current, dirty)
        after, _preview = render_coverage_stroke(
            before=before,
            dirty_rect=dirty.to_qrect(),
            segments=(configured,),
            compositor=self._compositor,
        )
        if np.array_equal(before, after):
            return False
        updated = _replace_coverage_region(current, dirty, after, scene_bounds)
        return self._selections.restore(target.scene.scene_id, updated)

    def commit(self, target: PaintTargetContext) -> bool:
        """Record one already-presented selection stroke in chronology."""
        session = self._matching_session(target)
        self._session = None
        return (
            False
            if session is None
            else self._selections.record_preview(
                target.scene.scene_id,
                session.before,
            )
        )

    def cancel(self, target: PaintTargetContext) -> bool:
        """Restore the selection captured before the unresolved stroke."""
        session = self._matching_session(target)
        self._session = None
        return (
            False
            if session is None
            else self._selections.restore(
                target.scene.scene_id,
                session.before,
            )
        )

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return a stable selection-blue brush feedback color."""
        return QColor(75, 145, 255, 255)

    def _matching_session(
        self,
        target: PaintTargetContext,
    ) -> _SelectionPaintSession | None:
        """Return the active session only for its exact composition."""
        session = self._session
        return (
            session
            if session is not None and session.scene_id == target.scene.scene_id
            else None
        )


def _coverage_region(
    coverage: CoverageSnapshot | None,
    bounds: RasterBounds,
) -> np.ndarray:
    """Return zero-padded coverage for one scene-local region."""
    pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    if coverage is None or coverage.bounds is None:
        return pixels
    overlap = coverage.bounds.intersection(bounds)
    if overlap is None:
        return pixels
    source_x = overlap.x - coverage.bounds.x
    source_y = overlap.y - coverage.bounds.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    pixels[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = coverage.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return pixels


def _replace_coverage_region(
    current: CoverageSnapshot | None,
    bounds: RasterBounds,
    replacement: np.ndarray,
    limit: RasterBounds,
) -> CoverageSnapshot | None:
    """Replace one region and trim zero-only selection storage."""
    current_bounds = None if current is None else current.bounds
    combined = bounds if current_bounds is None else current_bounds.united(bounds)
    combined = combined.intersection(limit)
    if combined is None:
        return None
    pixels = _coverage_region(current, combined)
    overlap = combined.intersection(bounds)
    if overlap is not None:
        source_x = overlap.x - bounds.x
        source_y = overlap.y - bounds.y
        target_x = overlap.x - combined.x
        target_y = overlap.y - combined.y
        pixels[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ] = replacement[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ]
    return trim_selection_coverage(
        CoverageSnapshot(combined, RasterExtentPolicy.EXPAND_ON_WRITE, pixels)
    )
