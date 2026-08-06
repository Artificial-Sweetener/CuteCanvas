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
"""Explicit whole-stack cropping to current canvas geometry."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from math import isfinite

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF
from qpane.sdk.scene import (
    LayerEffectReference,
    LayerSourceReference,
    LayerTransform,
    RasterBounds,
)

from ..composition import CompositionService
from .canvas_geometry import (
    CanvasGeometryEdit,
    CanvasGeometryState,
    CanvasGeometryStateOwner,
)


@dataclass(frozen=True, slots=True)
class CanvasCropEffect:
    """Retain one exact crop polygon in the target layer's local space."""

    points: tuple[QPointF, ...]

    def __post_init__(self) -> None:
        """Detach a valid finite crop polygon."""
        points = tuple(QPointF(point) for point in self.points)
        if len(points) < 3:
            raise ValueError("canvas crop effects require at least three points")
        if not all(isfinite(point.x()) and isfinite(point.y()) for point in points):
            raise ValueError("canvas crop points must be finite")
        object.__setattr__(self, "points", points)

    @property
    def kind(self) -> str:
        """Return the stable persistence and diagnostics kind."""
        return "canvas-crop"

    @property
    def retained_sources(self) -> tuple[LayerSourceReference, ...]:
        """Return no resources because crop geometry is stored inline."""
        return ()


class CanvasCropRenderOwner:
    """Render exact target-local canvas crop geometry."""

    def clip_path(
        self,
        effect: LayerEffectReference,
        target_bounds: RasterBounds,
    ) -> QPainterPath:
        """Return the retained crop polygon for a supported effect."""
        if not isinstance(effect, CanvasCropEffect):
            return QPainterPath()
        path = QPainterPath()
        path.addPolygon(QPolygonF(effect.points))
        path.closeSubpath()
        return path


class CanvasCropOwner:
    """Crop every layer through exact target-local effect geometry."""

    def __init__(
        self,
        state: CanvasGeometryStateOwner,
        compositions: CompositionService,
    ) -> None:
        """Bind authoritative geometry and chronological edit ownership."""
        self._state = state
        self._compositions = compositions

    def crop(self, composition_id: uuid.UUID) -> bool:
        """Clip all layers to the current canvas as one exact undoable edit."""
        before = self._state.capture(composition_id)
        layers = []
        for layer in before.layers:
            scene_to_local = layer.transform.inverted()
            if scene_to_local is None:
                raise ValueError("all layer transforms must be invertible to crop")
            effect = CanvasCropEffect(
                tuple(
                    scene_to_local.map_point(point)
                    for point in _canvas_corners(before.bounds)
                )
            )
            layers.append(replace(layer, effects=(*layer.effects, effect)))
        if not layers:
            return False
        after = CanvasGeometryState(
            before.bounds,
            tuple(layers),
            before.selection_document,
            before.selection_coverage,
        )
        if not self._state.restore(composition_id, after):
            return False
        try:
            self._compositions.edit_controller.record_applied(
                CanvasGeometryEdit(composition_id, before, after)
            )
        except Exception:
            self._state.restore(composition_id, before)
            raise
        return True


def scaled_canvas_crop_effect(
    effect: object,
    scale: LayerTransform,
) -> object:
    """Scale crop geometry when target-local raster storage is resized."""
    if not isinstance(effect, CanvasCropEffect):
        return effect
    return replace(
        effect,
        points=tuple(scale.map_point(point) for point in effect.points),
    )


def _canvas_corners(bounds: QRectF) -> tuple[QPointF, ...]:
    """Return the four canvas corners in clockwise scene order."""
    return (
        bounds.topLeft(),
        bounds.topRight(),
        bounds.bottomRight(),
        bounds.bottomLeft(),
    )


__all__ = [
    "CanvasCropEffect",
    "CanvasCropOwner",
    "CanvasCropRenderOwner",
    "scaled_canvas_crop_effect",
]
