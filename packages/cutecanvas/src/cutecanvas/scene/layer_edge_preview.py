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
"""Store one source-neutral transient layer edge preview."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from qpane.sdk.scene import RasterBounds

from .pixel_transitions import RasterPixelTransition


@dataclass(frozen=True, slots=True)
class LayerEdgePreview:
    """Carry a detached coverage transition for transient presentation."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    generation: int
    coverage: CoverageSnapshot | None
    transition: RasterPixelTransition


class LayerEdgePreviewStore:
    """Own the single current whole-layer coverage preview."""

    def __init__(self) -> None:
        """Create an empty preview owner."""
        self._preview: LayerEdgePreview | None = None

    @property
    def current(self) -> LayerEdgePreview | None:
        """Return the current immutable preview, if any."""
        return self._preview

    def publish(
        self,
        *,
        session_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        generation: int,
        before: CoverageSnapshot,
        after: CoverageSnapshot | None,
    ) -> None:
        """Replace transient presentation with one latest computed product."""
        self._preview = LayerEdgePreview(
            session_id,
            scene_id,
            layer_id,
            generation,
            after,
            _transition(before, after),
        )

    def clear(self, session_id: uuid.UUID | None = None) -> bool:
        """Discard the current preview when it belongs to ``session_id``."""
        current = self._preview
        if current is None or (
            session_id is not None and current.session_id != session_id
        ):
            return False
        self._preview = None
        return True


def _transition(
    before: CoverageSnapshot,
    after: CoverageSnapshot | None,
) -> RasterPixelTransition:
    """Project both sparse states into one exact replacement patch."""
    before_bounds = before.bounds
    if before_bounds is None:
        raise ValueError("layer edge previews require nonempty base coverage")
    after_bounds = None if after is None else after.bounds
    patch_bounds = (
        before_bounds if after_bounds is None else before_bounds.united(after_bounds)
    )
    return RasterPixelTransition._adopt_detached(
        patch_bounds,
        before_bounds,
        after_bounds or before_bounds,
        _project(before, patch_bounds),
        _project(after, patch_bounds),
    )


def _project(
    snapshot: CoverageSnapshot | None,
    bounds: RasterBounds,
) -> np.ndarray:
    """Project optional sparse coverage into a shared preview patch."""
    result = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    source = None if snapshot is None else snapshot.bounds
    if snapshot is None or source is None:
        return result
    overlap = source.intersection(bounds)
    if overlap is None:
        return result
    source_x = overlap.x - source.x
    source_y = overlap.y - source.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    result[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = snapshot.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return np.ascontiguousarray(result)


__all__ = ["LayerEdgePreview", "LayerEdgePreviewStore"]
