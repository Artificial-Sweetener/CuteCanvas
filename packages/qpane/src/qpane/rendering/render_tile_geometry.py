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
"""Stable-grid request geometry for resolution-dependent render sources."""

from __future__ import annotations

import math
import uuid
from collections.abc import Hashable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, QSizeF
from PySide6.QtGui import QTransform

from ..scene.raster import RasterBounds
from .panel_mapping import PanelLayerMapping
from .projective_sampling import conservative_transform_scale
from .projective_visibility import visible_source_rect

_TILE_PIXELS = 512
_TILE_BLEED_PIXELS = 2
_MAX_VISIBLE_TILES = 64
_PREFETCH_TILE_RINGS = 2
_OVERVIEW_BUDGET_BYTES = 4 * 1024 * 1024
_OVERVIEW_MAX_DIMENSION = 1024
_MIN_SCALE = 0.125
_MAX_SCALE = 32.0


@dataclass(frozen=True, slots=True)
class RenderTileKey:
    """Identify one source revision, resolution, and origin-aligned tile."""

    source_kind: str
    source_id: uuid.UUID
    fallback_key: Hashable
    revision_key: Hashable
    scale: float
    column: int
    row: int


@dataclass(frozen=True, slots=True)
class RenderTileRequest:
    """Describe one tile's core and antialiasing bleed geometry."""

    key: RenderTileKey
    source_rect: QRectF
    paint_rect: QRectF


def visible_tile_requests(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    bounds: RasterBounds,
    source_to_panel: PanelLayerMapping,
    panel_rect: QRectF,
    device_pixel_ratio: float,
    budget_bytes: int,
    maximum_scale: float | None = None,
) -> tuple[RenderTileRequest, ...] | None:
    """Build a bounded complete request on one stable source-local grid."""
    source_rect = _bounds_rect(bounds)
    visible = visible_source_rect(source_to_panel, panel_rect, source_rect)
    if visible.isEmpty():
        return ()
    if budget_bytes <= 0:
        return None
    scale = scale_bucket(source_to_panel, device_pixel_ratio, source_rect)
    if maximum_scale is not None:
        if maximum_scale <= 0.0:
            raise ValueError("maximum_scale must be positive")
        scale = min(scale, maximum_scale)
    while True:
        requests = _requests_for_scale(
            source_kind,
            source_id,
            revision_key,
            fallback_key,
            bounds,
            visible,
            scale,
        )
        if (
            len(requests) <= _MAX_VISIBLE_TILES
            and _estimated_bytes(requests, scale) <= budget_bytes
        ):
            return requests
        if scale <= _MIN_SCALE:
            return None
        scale = max(_MIN_SCALE, scale / 2.0)


def guarded_tile_requests(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    bounds: RasterBounds,
    source_to_panel: PanelLayerMapping,
    panel_rect: QRectF,
    budget_bytes: int,
    visible_requests: tuple[RenderTileRequest, ...],
) -> tuple[RenderTileRequest, ...]:
    """Return the largest bounded tile guard surrounding the visible request."""
    if not visible_requests or budget_bytes <= 0:
        return visible_requests
    source_rect = _bounds_rect(bounds)
    visible = visible_source_rect(source_to_panel, panel_rect, source_rect)
    if visible.isEmpty():
        return visible_requests
    scale = visible_requests[0].key.scale
    span = _TILE_PIXELS / scale
    for rings in range(_PREFETCH_TILE_RINGS, 0, -1):
        guarded_visible = visible.adjusted(
            -rings * span,
            -rings * span,
            rings * span,
            rings * span,
        ).intersected(source_rect)
        guarded = _requests_for_scale(
            source_kind,
            source_id,
            revision_key,
            fallback_key,
            bounds,
            guarded_visible,
            scale,
        )
        if (
            len(guarded) <= _MAX_VISIBLE_TILES
            and _estimated_bytes(guarded, scale) <= budget_bytes
        ):
            return guarded
    return visible_requests


def overview_tile_requests(
    *,
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    bounds: RasterBounds,
    budget_bytes: int,
) -> tuple[RenderTileRequest, ...]:
    """Return a low-density whole-source fallback within a strict small budget."""
    if budget_bytes <= 0 or bounds.width <= 0 or bounds.height <= 0:
        return ()
    overview_budget = min(budget_bytes, _OVERVIEW_BUDGET_BYTES)
    dimension_scale = min(
        _OVERVIEW_MAX_DIMENSION / bounds.width,
        _OVERVIEW_MAX_DIMENSION / bounds.height,
        1.0,
    )
    byte_scale = math.sqrt(overview_budget / (bounds.width * bounds.height * 4.0))
    exact_scale = min(dimension_scale, byte_scale)
    if exact_scale <= 0.0:
        return ()
    scale = 2.0 ** math.floor(math.log2(exact_scale))
    source_rect = _bounds_rect(bounds)
    while scale > 0.0:
        requests = _requests_for_scale(
            source_kind,
            source_id,
            revision_key,
            fallback_key,
            bounds,
            source_rect,
            scale,
        )
        if (
            len(requests) <= _MAX_VISIBLE_TILES
            and _estimated_bytes(requests, scale) <= overview_budget
        ):
            return requests
        scale /= 2.0
    return ()


def unique_requests(
    requests: tuple[RenderTileRequest, ...],
) -> tuple[RenderTileRequest, ...]:
    """Return requests in order with duplicate stable tile keys removed."""
    unique: dict[RenderTileKey, RenderTileRequest] = {}
    for request in requests:
        unique.setdefault(request.key, request)
    return tuple(unique.values())


def estimated_request_bytes(requests: tuple[RenderTileRequest, ...]) -> int:
    """Return detached-image bytes for requests spanning multiple scales."""
    return sum(
        max(1, math.ceil(request.paint_rect.width() * request.key.scale))
        * max(1, math.ceil(request.paint_rect.height() * request.key.scale))
        * 4
        for request in requests
    )


def scale_bucket(
    transform: QTransform,
    device_pixel_ratio: float,
    source_bounds: QRectF | QSize | QSizeF | None = None,
) -> float:
    """Return a non-undersampling power-of-two physical scale bucket."""
    source_rect = (
        QRectF(0.0, 0.0, source_bounds.width(), source_bounds.height())
        if isinstance(source_bounds, (QSize, QSizeF))
        else source_bounds
    )
    if not transform.isAffine() and source_rect is None:
        raise ValueError("projective scale selection requires finite source bounds")
    exact = (
        conservative_transform_scale(transform, source_rect)
        if source_rect is not None
        else max(
            math.hypot(transform.m11(), transform.m12()),
            math.hypot(transform.m21(), transform.m22()),
        )
    ) * max(0.01, float(device_pixel_ratio))
    if exact <= _MIN_SCALE:
        return _MIN_SCALE
    bucket = 2.0 ** math.ceil(math.log2(exact))
    return min(_MAX_SCALE, max(_MIN_SCALE, bucket))


def source_rect_for_tile_key(
    key: RenderTileKey,
    bounds: RasterBounds,
) -> QRectF:
    """Return one stable tile core clipped to its source-local bounds."""
    span = _TILE_PIXELS / key.scale
    return QRectF(
        bounds.x + key.column * span,
        bounds.y + key.row * span,
        span,
        span,
    ).intersected(_bounds_rect(bounds))


def _estimated_bytes(
    requests: tuple[RenderTileRequest, ...],
    scale: float,
) -> int:
    """Return conservative image bytes for one same-scale request batch."""
    return sum(
        max(1, math.ceil(request.paint_rect.width() * scale))
        * max(1, math.ceil(request.paint_rect.height() * scale))
        * 4
        for request in requests
    )


def _requests_for_scale(
    source_kind: str,
    source_id: uuid.UUID,
    revision_key: Hashable,
    fallback_key: Hashable,
    bounds: RasterBounds,
    visible: QRectF,
    scale: float,
) -> tuple[RenderTileRequest, ...]:
    """Return deterministic requests covering one visible local rectangle."""
    span = _TILE_PIXELS / scale
    source_rect = _bounds_rect(bounds)
    first_column = math.floor((visible.left() - bounds.x) / span)
    last_column = math.floor((visible.right() - bounds.x) / span)
    first_row = math.floor((visible.top() - bounds.y) / span)
    last_row = math.floor((visible.bottom() - bounds.y) / span)
    bleed = _TILE_BLEED_PIXELS / scale
    requests: list[RenderTileRequest] = []
    for row in range(first_row, last_row + 1):
        for column in range(first_column, last_column + 1):
            core = QRectF(
                bounds.x + column * span,
                bounds.y + row * span,
                span,
                span,
            ).intersected(source_rect)
            if core.isEmpty():
                continue
            paint = core.adjusted(-bleed, -bleed, bleed, bleed).intersected(source_rect)
            requests.append(
                RenderTileRequest(
                    RenderTileKey(
                        source_kind,
                        source_id,
                        fallback_key,
                        revision_key,
                        scale,
                        column,
                        row,
                    ),
                    core,
                    paint,
                )
            )
    return tuple(requests)


def _bounds_rect(bounds: RasterBounds) -> QRectF:
    """Return floating geometry for integer source bounds."""
    return QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )
