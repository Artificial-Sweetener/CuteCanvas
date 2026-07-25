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
"""Evaluate detached paint-bucket requests cooperatively."""

from __future__ import annotations

from qpane.sdk.execution import CancellationToken

from cutecanvas.coverage import CoverageSnapshot

from .flood import FillCancelledError, FloodFillEngine, FloodFillRequest


def evaluate_flood_fill(
    request: FloodFillRequest,
    cancellation: CancellationToken,
) -> CoverageSnapshot:
    """Return one fill result or propagate runtime cancellation."""
    cancellation.raise_if_cancelled()
    try:
        result = FloodFillEngine().fill(
            request,
            cancelled=lambda: cancellation.is_cancelled,
        )
    except FillCancelledError:
        cancellation.raise_if_cancelled()
        raise RuntimeError("paint-bucket evaluation stopped unexpectedly") from None
    cancellation.raise_if_cancelled()
    return result
