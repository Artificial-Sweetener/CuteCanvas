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
"""Visual continuity identities for sampled render-tile batches."""

from __future__ import annotations

from ..scene.render_plan import SampledTileRenderData


def sampled_tile_batch_identity(
    tiles: tuple[SampledTileRenderData, ...],
) -> tuple[tuple[float, float, int, float], ...]:
    """Return sampling properties that must match across scroll repair."""
    identities = {
        (
            _sampling_ratio(tile.image_source_rect.width(), tile.source_rect.width()),
            _sampling_ratio(tile.image_source_rect.height(), tile.source_rect.height()),
            int(tile.image.format().value),
            float(tile.image.devicePixelRatio()),
        )
        for tile in tiles
    }
    return tuple(sorted(identities))


def _sampling_ratio(sampled_extent: float, source_extent: float) -> float:
    """Return one stable sampled-pixels-per-source-unit ratio."""
    if source_extent <= 0.0:
        return 0.0
    return float(sampled_extent) / float(source_extent)
