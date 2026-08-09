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
"""Source-anchored geometry for phase-stable sampled presentation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import isclose

from PySide6.QtCore import QRectF, QSize

from ..scene.model import LayerDescriptor
from ..scene.raster import RasterBounds
from .panel_mapping import PanelLayerMapping, PiecewisePanelMapping
from .projective_visibility import visible_source_rect

_SOURCE_LATTICE_SPAN = 512


@dataclass(frozen=True, slots=True)
class SampledSourceLattice:
    """Bind one aligned local raster region to render-source coordinates."""

    local_bounds: RasterBounds
    source_rect: QRectF

    def __post_init__(self) -> None:
        """Detach mutable source geometry from the planning frame."""
        object.__setattr__(self, "source_rect", QRectF(self.source_rect))


def sampled_source_lattice(
    *,
    descriptor: LayerDescriptor,
    source_size: QSize,
    source_to_panel: PanelLayerMapping,
    panel_rect: QRectF,
) -> SampledSourceLattice | None:
    """Return the visible source region aligned to one global raster lattice."""
    if source_size.isEmpty() or panel_rect.isEmpty():
        return None
    source_bounds = QRectF(
        0.0,
        0.0,
        float(source_size.width()),
        float(source_size.height()),
    )
    visible_source = visible_source_rect(
        source_to_panel,
        panel_rect,
        source_bounds,
    )
    if visible_source.isEmpty():
        return None
    local_bounds = descriptor.raster_bounds or RasterBounds(
        0,
        0,
        source_size.width(),
        source_size.height(),
    )
    source_to_local_x = local_bounds.width / source_size.width()
    source_to_local_y = local_bounds.height / source_size.height()
    visible_local = QRectF(
        local_bounds.x + visible_source.x() * source_to_local_x,
        local_bounds.y + visible_source.y() * source_to_local_y,
        visible_source.width() * source_to_local_x,
        visible_source.height() * source_to_local_y,
    )
    aligned_left = math.floor(visible_local.left() / _SOURCE_LATTICE_SPAN)
    aligned_top = math.floor(visible_local.top() / _SOURCE_LATTICE_SPAN)
    aligned_right = math.ceil(
        (visible_local.x() + visible_local.width()) / _SOURCE_LATTICE_SPAN
    )
    aligned_bottom = math.ceil(
        (visible_local.y() + visible_local.height()) / _SOURCE_LATTICE_SPAN
    )
    aligned_local = RasterBounds(
        aligned_left * _SOURCE_LATTICE_SPAN,
        aligned_top * _SOURCE_LATTICE_SPAN,
        max(1, (aligned_right - aligned_left) * _SOURCE_LATTICE_SPAN),
        max(1, (aligned_bottom - aligned_top) * _SOURCE_LATTICE_SPAN),
    ).intersection(local_bounds)
    if aligned_local is None:
        return None
    local_to_source_x = source_size.width() / local_bounds.width
    local_to_source_y = source_size.height() / local_bounds.height
    return SampledSourceLattice(
        aligned_local,
        QRectF(
            (aligned_local.x - local_bounds.x) * local_to_source_x,
            (aligned_local.y - local_bounds.y) * local_to_source_y,
            aligned_local.width * local_to_source_x,
            aligned_local.height * local_to_source_y,
        ),
    )


def source_sampling_phase_is_fractional(
    source_to_panel: PanelLayerMapping,
    device_pixel_ratio: float,
) -> bool:
    """Return whether source axes do not map to integral physical-pixel steps."""
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    transforms = (
        tuple(patch.transform for patch in source_to_panel.patches)
        if isinstance(source_to_panel, PiecewisePanelMapping)
        else (source_to_panel,)
    )
    return any(
        not isclose(value, round(value), rel_tol=0.0, abs_tol=1e-9)
        for transform in transforms
        for value in (
            transform.m11() * device_pixel_ratio,
            transform.m12() * device_pixel_ratio,
            transform.m21() * device_pixel_ratio,
            transform.m22() * device_pixel_ratio,
        )
    )
