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
"""Optional source capabilities for sampled render-tile work."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from . import render_tile_types as tile_types
from .render_tile_geometry import RenderTileRequest


@runtime_checkable
class ImmediateTileSource(Protocol):
    """Provide products whose bounded result is safe on the GUI thread."""

    def immediate_products(
        self,
        requests: tuple[RenderTileRequest, ...],
    ) -> tuple[tile_types.RenderTileProduct, ...] | None:
        """Return immediate products or decline synchronous derivation."""
        ...


@runtime_checkable
class IdleSettledDetailSource(Protocol):
    """Identify expensive detail that should begin only after GUI idle."""

    @property
    def detail_requires_idle_settle(self) -> bool:
        """Return whether exact detail should cross the idle boundary."""
        ...
