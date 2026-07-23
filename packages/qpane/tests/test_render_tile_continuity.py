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
"""Presentation-settle policy tests for sampled render tiles."""

from __future__ import annotations

import uuid

from qpane.rendering.render_tile_continuity import RenderTileContinuity
from qpane.rendering.render_tile_geometry import RenderTileKey


def test_settle_does_not_redraw_before_exact_products_exist() -> None:
    """A settle timer must not publish the same fallback frame again."""
    ready_calls = 0

    def record_ready() -> None:
        """Record one requested presentation publication."""
        nonlocal ready_calls
        ready_calls += 1

    source_id = uuid.uuid4()
    identity = ("hybrid", source_id)
    signature = (_tile_key(source_id),)
    continuity = RenderTileContinuity(record_ready)
    try:
        assert continuity.prefer_fallback(
            identity,
            signature,
            exact_available=False,
        )
        assert continuity.pending

        continuity._handle_settled()

        assert ready_calls == 0
        continuity.note_exact_available(
            identity,
            exact_available=True,
        )
        assert continuity.pending

        continuity._handle_settled()

        assert ready_calls == 1
    finally:
        continuity.shutdown()


def _tile_key(source_id: uuid.UUID) -> RenderTileKey:
    """Build one stable visible signature for continuity tests."""
    return RenderTileKey("hybrid", source_id, (0, 0, 64, 64), 1, 4.0, 0, 0)
