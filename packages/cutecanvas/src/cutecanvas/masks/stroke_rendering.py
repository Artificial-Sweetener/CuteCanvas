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
"""Render detached mask stroke products cooperatively."""

from __future__ import annotations

from qpane.sdk.execution import CancellationToken

from ..painting import BrushCompositor, BrushStrokeSegment
from ..painting.rendering import render_coverage_stroke
from .stroke_models import MaskStrokeJobResult, MaskStrokeJobSpec


def render_mask_stroke(
    spec: MaskStrokeJobSpec,
    compositor: BrushCompositor,
    cancellation: CancellationToken,
) -> MaskStrokeJobResult:
    """Replay one immutable stroke specification into a detached result."""
    cancellation.raise_if_cancelled()
    payload = spec.payload
    segments: tuple[BrushStrokeSegment, ...] = (
        () if payload is None else payload.segments
    )
    after_slice, preview_image = render_coverage_stroke(
        before=spec.before,
        dirty_rect=spec.dirty_rect,
        segments=segments,
        preview_stride=1 if payload is None else payload.stride,
        constraint=spec.constraint,
        compositor=compositor,
    )
    cancellation.raise_if_cancelled()
    return MaskStrokeJobResult(
        mask_id=spec.mask_id,
        generation=spec.generation,
        dirty_rect=spec.dirty_rect,
        before=spec.before,
        after=after_slice,
        preview_image=preview_image,
        payload=payload,
        metadata=dict(spec.metadata),
    )
