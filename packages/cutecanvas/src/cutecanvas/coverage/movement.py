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

"""Retained coverage-item movement through the shared snapping engine."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import LayerTransform

from cutecanvas.snapping.engine import SnapEngine
from cutecanvas.snapping.model import SnapCandidate, SnapGrid, SnapResult

from .document import CoverageDocument
from .evaluation import CoverageDocumentEvaluator


class CoverageItemMoveSession:
    """Preview and commit one retained-item translation without rasterization."""

    def __init__(
        self,
        document: CoverageDocument,
        item_id: uuid.UUID,
        candidates: tuple[SnapCandidate, ...],
        *,
        threshold_device_pixels: float = 6.0,
        release_device_pixels: float = 4.0,
        grid: SnapGrid | None = None,
    ) -> None:
        """Capture immutable authorship and stationary snap geometry."""
        item = document.item(item_id)
        if item is None:
            raise KeyError(item_id)
        bounds = CoverageDocumentEvaluator().item_bounds(item)
        if bounds is None:
            raise ValueError("empty retained coverage items cannot be moved")
        self._document = document
        self._item = item
        self._session = SnapEngine().begin(
            f"coverage:{item_id}",
            QRectF(bounds.x, bounds.y, bounds.width, bounds.height),
            candidates,
            threshold_device_pixels=threshold_device_pixels,
            release_device_pixels=release_device_pixels,
            grid=grid,
        )

    def resolve(
        self,
        delta: QPointF,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
    ) -> tuple[CoverageDocument, SnapResult]:
        """Return a retained preview document and shared snap result."""
        result = self._session.resolve(
            delta,
            scene_units_per_device_pixel=scene_units_per_device_pixel,
            suppressed=suppressed,
        )
        translation = LayerTransform(dx=result.delta.x(), dy=result.delta.y())
        moved = replace(
            self._item,
            transform=self._item.transform.followed_by(translation),
        )
        return self._document.replace_item(moved), result
