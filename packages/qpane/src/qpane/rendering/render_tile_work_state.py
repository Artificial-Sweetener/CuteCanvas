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
"""Immutable and pending state for sampled render-tile work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF

from ..execution import ExecutionHandle
from . import render_tile_types as tile_types
from .panel_mapping import PanelLayerMapping, detached_panel_mapping
from .render_tile_geometry import RenderTileKey, RenderTileRequest


class RefinementLane(str, Enum):
    """Separate stable continuity work from replaceable viewport detail."""

    CONTINUITY = "continuity"
    DETAIL = "detail"
    PREFETCH = "prefetch"


@dataclass(slots=True)
class PendingTiles:
    """Retain one latest request in a source refinement lane."""

    signature: tuple[RenderTileKey, ...]
    retained_signature: tuple[RenderTileKey, ...]
    source: tile_types.RenderTileBatchSource
    lane: RefinementLane
    handle: ExecutionHandle[tuple[tile_types.RenderTileProduct, ...], object] | None = (
        None
    )


@dataclass(frozen=True, slots=True)
class DeferredTiles:
    """Retain latest detail work until stable continuity pixels are available."""

    source: tile_types.RenderTileBatchSource
    requests: tuple[RenderTileRequest, ...]
    required_signature: tuple[RenderTileKey, ...]
    retained_signature: tuple[RenderTileKey, ...]


@dataclass(frozen=True, slots=True)
class DeferredPrefetch:
    """Retain the latest settled-view guard request for one source."""

    source: tile_types.RenderTileBatchSource
    source_to_panel: PanelLayerMapping
    panel_rect: QRectF
    visible_requests: tuple[RenderTileRequest, ...]
    overview_signature: tuple[RenderTileKey, ...]

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from the caller's frame."""
        object.__setattr__(
            self,
            "source_to_panel",
            detached_panel_mapping(self.source_to_panel),
        )
        object.__setattr__(self, "panel_rect", QRectF(self.panel_rect))
