#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Exact derived layer projections for authoritative scene selections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..coverage import CoverageSnapshot
from ..scene.raster import LayerTransform, RasterBounds


@dataclass(frozen=True, slots=True)
class _ProjectionEntry:
    """Bind one selection revision to its exact layer-local projection."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    selection_revision: int
    transform: LayerTransform
    coverage: CoverageSnapshot


class LayerSelectionProjectionCache:
    """Retain one exact derived projection without duplicating selection authority."""

    def __init__(self) -> None:
        """Initialize an empty revision-keyed projection cache."""
        self._entry: _ProjectionEntry | None = None

    def resolve(
        self,
        *,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        selection_revision: int,
        transform: LayerTransform,
    ) -> CoverageSnapshot | None:
        """Return exact local coverage only while every identity remains current."""
        entry = self._entry
        if entry is None:
            return None
        if (
            entry.scene_id != scene_id
            or entry.layer_id != layer_id
            or entry.selection_revision != selection_revision
            or entry.transform != transform
        ):
            return None
        return entry.coverage

    def remember(
        self,
        *,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        selection_revision: int,
        transform: LayerTransform,
        coverage: CoverageSnapshot,
    ) -> None:
        """Cache exact local coverage derived from the authoritative revision."""
        self._entry = _ProjectionEntry(
            scene_id,
            layer_id,
            selection_revision,
            transform,
            coverage,
        )

    def clear(self) -> None:
        """Discard the derived projection."""
        self._entry = None


def translated_coverage_within(
    coverage: CoverageSnapshot,
    delta_x: int,
    delta_y: int,
    bounds: RasterBounds | None,
) -> CoverageSnapshot:
    """Translate coverage and crop it to finite post-move raster bounds."""
    translated = coverage.translated(delta_x, delta_y)
    translated_bounds = translated.bounds
    if bounds is None or translated_bounds is None:
        return translated
    overlap = translated_bounds.intersection(bounds)
    if overlap is None:
        return CoverageSnapshot(
            None, translated.extent_policy, translated.pixels[:0, :0]
        )
    if overlap == translated_bounds:
        return translated
    source_x = overlap.x - translated_bounds.x
    source_y = overlap.y - translated_bounds.y
    return CoverageSnapshot(
        overlap,
        translated.extent_policy,
        translated.pixels[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ],
    )
