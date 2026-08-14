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

"""Resolve document-space brush geometry for one paint target."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF

from qpane.sdk.scene import (
    BilinearLayerTransform,
    PiecewiseLayerTransform,
    inverse_mapping_linearization,
)

from .model import BrushStrokeSegment
from .target_contracts import PaintTargetContext


def segment_with_target_tip_geometry(
    segment: BrushStrokeSegment,
    target: PaintTargetContext,
) -> BrushStrokeSegment:
    """Map a document-space circular tip into the target's local affine space."""

    layer = target.layer
    transform = None if layer is None else layer.transform
    if transform is None:
        return segment
    tip_transform = inverse_mapping_linearization(
        transform,
        QPointF(float(segment.end[0]), float(segment.end[1])),
    )
    if tip_transform is None:
        return segment
    tip_mapping = (
        transform
        if isinstance(transform, (BilinearLayerTransform, PiecewiseLayerTransform))
        else None
    )
    if tip_transform == segment.tip_transform and tip_mapping == segment.tip_mapping:
        return segment
    return replace(segment, tip_transform=tip_transform, tip_mapping=tip_mapping)


__all__ = ["segment_with_target_tip_geometry"]
