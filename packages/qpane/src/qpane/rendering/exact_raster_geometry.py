#    QPane - High-performance PySide6 image viewer
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

"""Exact physical-pixel demand geometry for axis-aligned raster products."""

from __future__ import annotations

import math
import uuid
from collections.abc import Hashable

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from ..ferrastra.reconstruction import RasterReconstructionSpace
from ..scene.raster import RasterBounds
from ..scene.raster_sampling import RasterExactSampling
from .projective_visibility import visible_source_rect
from .render_sampling_grid import AffineSamplingGrid, AxisAlignedSamplingGrid
from .render_tile_geometry import RenderTileKey, RenderTileRequest

_TILE_PIXELS = 512
_TILE_BLEED_PIXELS = 2
_MAX_VISIBLE_TILES = 64
_AXIS_TOLERANCE = 1e-12


def exact_axis_sampling_grid(
    transform: QTransform,
    device_pixel_ratio: float,
    bounds: RasterBounds,
) -> AxisAlignedSamplingGrid | None:
    """Return the reusable source grid for an axis-aligned physical mapping."""
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    if (
        not transform.isAffine()
        or abs(transform.m12()) > _AXIS_TOLERANCE
        or abs(transform.m21()) > _AXIS_TOLERANCE
        or abs(transform.m11()) <= _AXIS_TOLERANCE
        or abs(transform.m22()) <= _AXIS_TOLERANCE
    ):
        return None
    scale_x = abs(transform.m11()) * device_pixel_ratio
    scale_y = abs(transform.m22()) * device_pixel_ratio
    step_x = 1.0 / scale_x
    step_y = 1.0 / scale_y
    origin_x = -transform.dx() / transform.m11()
    origin_y = -transform.dy() / transform.m22()
    return AxisAlignedSamplingGrid(
        scale_x=scale_x,
        scale_y=scale_y,
        phase_x=_canonical_phase(origin_x, float(bounds.x), step_x),
        phase_y=_canonical_phase(origin_y, float(bounds.y), step_y),
    )


def exact_visible_tile_requests(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    bounds: RasterBounds,
    source_to_panel: QTransform,
    panel_rect: QRectF,
    device_pixel_ratio: float,
    budget_bytes: int,
    exact_sampling: RasterExactSampling,
    reconstruction_space: RasterReconstructionSpace = (
        RasterReconstructionSpace.SRGB_ENCODED
    ),
) -> tuple[RenderTileRequest, ...] | None:
    """Build exact settled requests without silently reducing sample density."""
    source_bounds = QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )
    visible = visible_source_rect(source_to_panel, panel_rect, source_bounds)
    if visible.isEmpty():
        return ()
    if budget_bytes <= 0 or not source_to_panel.isAffine():
        return None
    grid = exact_axis_sampling_grid(source_to_panel, device_pixel_ratio, bounds)
    if grid is None:
        if exact_sampling is RasterExactSampling.LANCZOS3:
            raise ValueError("Lanczos3 exact sampling requires an axis-aligned mapping")
        return _affine_requests(
            source_kind=source_kind,
            source_id=source_id,
            revision_key=revision_key,
            fallback_key=fallback_key,
            source_to_panel=source_to_panel,
            visible=source_to_panel.mapRect(visible).intersected(panel_rect),
            device_pixel_ratio=device_pixel_ratio,
            budget_bytes=budget_bytes,
            exact_sampling=exact_sampling,
            reconstruction_space=reconstruction_space,
        )
    if exact_sampling is RasterExactSampling.AFFINE_BILINEAR:
        raise ValueError("affine bilinear exact sampling requires axis mixing")
    columns = _tile_indices(visible.left(), visible.right(), grid.phase_x, grid.step_x)
    rows = _tile_indices(visible.top(), visible.bottom(), grid.phase_y, grid.step_y)
    if len(columns) * len(rows) > _MAX_VISIBLE_TILES:
        return None
    tile_bytes = (_TILE_PIXELS + 2 * _TILE_BLEED_PIXELS) ** 2 * 4
    if len(columns) * len(rows) * tile_bytes > budget_bytes:
        return None
    return tuple(
        _request(
            source_kind=source_kind,
            source_id=source_id,
            revision_key=revision_key,
            fallback_key=fallback_key,
            grid=grid,
            exact_sampling=exact_sampling,
            reconstruction_space=reconstruction_space,
            column=column,
            row=row,
        )
        for row in rows
        for column in columns
    )


def _affine_requests(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    source_to_panel: QTransform,
    visible: QRectF,
    device_pixel_ratio: float,
    budget_bytes: int,
    exact_sampling: RasterExactSampling,
    reconstruction_space: RasterReconstructionSpace,
) -> tuple[RenderTileRequest, ...] | None:
    """Return panel-space physical tiles for one general affine projection."""
    if visible.isEmpty():
        return ()
    panel_to_source, invertible = source_to_panel.inverted()
    if not invertible:
        return None
    grid = AffineSamplingGrid(
        panel_to_source.m11(),
        panel_to_source.m12(),
        panel_to_source.m21(),
        panel_to_source.m22(),
        panel_to_source.dx(),
        panel_to_source.dy(),
        device_pixel_ratio,
    )
    span = _TILE_PIXELS / device_pixel_ratio
    columns = range(
        math.floor(visible.left() / span), math.ceil(visible.right() / span)
    )
    rows = range(math.floor(visible.top() / span), math.ceil(visible.bottom() / span))
    if len(columns) * len(rows) > _MAX_VISIBLE_TILES:
        return None
    tile_bytes = (_TILE_PIXELS + 2 * _TILE_BLEED_PIXELS) ** 2 * 4
    if len(columns) * len(rows) * tile_bytes > budget_bytes:
        return None
    bleed = _TILE_BLEED_PIXELS / device_pixel_ratio
    return tuple(
        RenderTileRequest(
            RenderTileKey(
                source_kind,
                source_id,
                fallback_key,
                revision_key,
                device_pixel_ratio,
                column,
                row,
                grid,
                exact_sampling,
                reconstruction_space,
            ),
            QRectF(column * span, row * span, span, span),
            QRectF(
                column * span - bleed,
                row * span - bleed,
                span + 2 * bleed,
                span + 2 * bleed,
            ),
        )
        for row in rows
        for column in columns
    )


def _request(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    grid: AxisAlignedSamplingGrid,
    exact_sampling: RasterExactSampling,
    reconstruction_space: RasterReconstructionSpace,
    column: int,
    row: int,
) -> RenderTileRequest:
    """Return one exact tile with a filter-support bleed on the same grid."""
    span_x = _TILE_PIXELS * grid.step_x
    span_y = _TILE_PIXELS * grid.step_y
    core = QRectF(
        grid.phase_x + column * span_x,
        grid.phase_y + row * span_y,
        span_x,
        span_y,
    )
    paint = core.adjusted(
        -_TILE_BLEED_PIXELS * grid.step_x,
        -_TILE_BLEED_PIXELS * grid.step_y,
        _TILE_BLEED_PIXELS * grid.step_x,
        _TILE_BLEED_PIXELS * grid.step_y,
    )
    return RenderTileRequest(
        RenderTileKey(
            source_kind,
            source_id,
            fallback_key,
            revision_key,
            max(grid.scale_x, grid.scale_y),
            column,
            row,
            grid,
            exact_sampling,
            reconstruction_space,
        ),
        core,
        paint,
    )


def _tile_indices(
    visible_start: float,
    visible_end: float,
    phase: float,
    step: float,
) -> range:
    """Return tile indices whose half-open cores intersect a visible interval."""
    tile_span = _TILE_PIXELS * step
    first = math.floor((visible_start - phase) / tile_span)
    end = math.ceil((visible_end - phase) / tile_span)
    return range(first, max(first + 1, end))


def _canonical_phase(origin: float, bounds_origin: float, step: float) -> float:
    """Reduce an equivalent infinite grid to one stable source-local phase."""
    phase = bounds_origin + ((origin - bounds_origin) % step)
    if math.isclose(phase, bounds_origin + step, rel_tol=0.0, abs_tol=1e-12):
        return bounds_origin
    return round(phase, 12)


__all__ = ["exact_axis_sampling_grid", "exact_visible_tile_requests"]
