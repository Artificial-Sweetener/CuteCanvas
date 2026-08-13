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

"""Own bounded visible and continuity demand for sampled refinement."""

from __future__ import annotations

import uuid
from collections.abc import Hashable
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from ..ferrastra.reconstruction import RasterReconstructionSpace
from ..scene.raster import RasterBounds
from ..scene.raster_sampling import RasterExactSampling
from .exact_raster_geometry import exact_visible_tile_requests
from .panel_mapping import PanelLayerMapping
from .render_tile_geometry import (
    RenderTileRequest,
    estimated_request_bytes,
    overview_tile_requests,
    visible_tile_requests,
)
from .render_tile_types import RenderTileBatchSource


@dataclass(frozen=True, slots=True)
class RefinementDemand:
    """Carry exact visible demand plus its source-wide continuity products."""

    overview: tuple[RenderTileRequest, ...]
    visible: tuple[RenderTileRequest, ...]
    exact_available: bool


@dataclass(frozen=True, slots=True)
class _OverviewRequestBatch:
    """Cache source-wide fallback geometry until its render identity changes."""

    revision_key: Hashable
    fallback_key: Hashable
    bounds: RasterBounds
    budget_bytes: int
    exact_sampling: RasterExactSampling | None
    reconstruction_space: RasterReconstructionSpace
    requests: tuple[RenderTileRequest, ...]


class RenderRefinementDemandPlanner:
    """Select bounded exact detail without weakening continuity products."""

    def __init__(self) -> None:
        """Initialize empty source-identity continuity demand."""
        self._overview_requests: dict[tuple[str, uuid.UUID], _OverviewRequestBatch] = {}

    def plan(
        self,
        *,
        source: RenderTileBatchSource,
        source_to_panel: PanelLayerMapping,
        panel_rect: QRectF,
        device_pixel_ratio: float,
        budget_bytes: int,
        maximum_scale: float | None,
        exact_physical_grid: bool,
        exact_sampling: RasterExactSampling | None,
        reconstruction_space: RasterReconstructionSpace,
    ) -> RefinementDemand:
        """Return continuity and requested-density geometry under one budget."""
        if exact_physical_grid:
            if exact_sampling is None:
                raise ValueError(
                    "exact_sampling is required for an exact physical grid"
                )
            overview = self.overview_for(
                source,
                budget_bytes,
                exact_sampling,
                reconstruction_space,
            )
            detail_budget_bytes = max(
                0,
                budget_bytes - estimated_request_bytes(overview),
            )
            exact = self._exact_requests(
                source=source,
                source_to_panel=source_to_panel,
                panel_rect=panel_rect,
                device_pixel_ratio=device_pixel_ratio,
                budget_bytes=detail_budget_bytes,
                exact_sampling=exact_sampling,
                reconstruction_space=reconstruction_space,
            )
            return RefinementDemand(
                overview,
                overview if exact is None else exact,
                exact is not None,
            )
        overview = self.overview_for(
            source,
            budget_bytes,
            None,
            reconstruction_space,
        )
        detail_budget_bytes = max(0, budget_bytes - estimated_request_bytes(overview))
        visible = visible_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=source_to_panel,
            panel_rect=panel_rect,
            device_pixel_ratio=device_pixel_ratio,
            budget_bytes=detail_budget_bytes,
            maximum_scale=maximum_scale,
            reconstruction_space=reconstruction_space,
        )
        return RefinementDemand(
            overview,
            overview if visible is None else visible,
            True,
        )

    def overview_for(
        self,
        source: RenderTileBatchSource,
        budget_bytes: int,
        exact_sampling: RasterExactSampling | None,
        reconstruction_space: RasterReconstructionSpace,
    ) -> tuple[RenderTileRequest, ...]:
        """Return cached whole-source request geometry for one render revision."""
        identity = (source.source_kind, source.source_id)
        current = self._overview_requests.get(identity)
        if (
            current is not None
            and current.revision_key == source.revision_key
            and current.fallback_key == source.fallback_key
            and current.bounds == source.bounds
            and current.budget_bytes == budget_bytes
            and current.exact_sampling is exact_sampling
            and current.reconstruction_space is reconstruction_space
        ):
            return current.requests
        requests = overview_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            budget_bytes=budget_bytes // 2,
            exact_sampling=exact_sampling,
            reconstruction_space=reconstruction_space,
        )
        self._overview_requests[identity] = _OverviewRequestBatch(
            source.revision_key,
            source.fallback_key,
            source.bounds,
            budget_bytes,
            exact_sampling,
            reconstruction_space,
            requests,
        )
        return requests

    def clear(self) -> None:
        """Release every cached continuity-demand description."""
        self._overview_requests.clear()

    @staticmethod
    def _exact_requests(
        *,
        source: RenderTileBatchSource,
        source_to_panel: PanelLayerMapping,
        panel_rect: QRectF,
        device_pixel_ratio: float,
        budget_bytes: int,
        exact_sampling: RasterExactSampling,
        reconstruction_space: RasterReconstructionSpace,
    ) -> tuple[RenderTileRequest, ...] | None:
        """Return exact physical-grid demand for a global affine mapping."""
        if not isinstance(source_to_panel, QTransform):
            return None
        return exact_visible_tile_requests(
            source_kind=source.source_kind,
            source_id=source.source_id,
            revision_key=source.revision_key,
            fallback_key=source.fallback_key,
            bounds=source.bounds,
            source_to_panel=source_to_panel,
            panel_rect=panel_rect,
            device_pixel_ratio=device_pixel_ratio,
            budget_bytes=budget_bytes,
            exact_sampling=exact_sampling,
            reconstruction_space=reconstruction_space,
        )


__all__ = ["RefinementDemand", "RenderRefinementDemandPlanner"]
