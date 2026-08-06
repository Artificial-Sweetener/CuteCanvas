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

from qpane.sdk.scene import LayerTransform

from .model import BrushStrokeSegment
from .target_contracts import PaintTargetContext


def segment_with_target_tip_geometry(
    segment: BrushStrokeSegment,
    target: PaintTargetContext,
) -> BrushStrokeSegment:
    """Map a document-space circular tip into the target's local affine space."""

    layer = target.layer
    transform = None if layer is None else layer.transform
    inverse = None if transform is None else transform.inverted()
    if inverse is None:
        return segment
    tip_transform = LayerTransform(
        m11=inverse.m11,
        m12=inverse.m12,
        m21=inverse.m21,
        m22=inverse.m22,
    )
    if tip_transform == segment.tip_transform:
        return segment
    return replace(segment, tip_transform=tip_transform)


__all__ = ["segment_with_target_tip_geometry"]
