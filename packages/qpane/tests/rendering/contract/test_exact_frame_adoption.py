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

"""Contract proof for atomic exact raster frame adoption."""

from __future__ import annotations

from dataclasses import dataclass

from qpane.rendering.exact_raster_refinement import exact_frame_is_ready


@dataclass(frozen=True, slots=True)
class _AdoptionState:
    """Describe only exact-product eligibility and readiness for the contract."""

    exact_eligible: bool
    exact_ready: bool


def test_exact_frame_waits_for_every_eligible_layer() -> None:
    """Never combine a settled product with another layer's preview product."""
    assert exact_frame_is_ready((_AdoptionState(False, False),))
    assert not exact_frame_is_ready(
        (_AdoptionState(True, True), _AdoptionState(True, False))
    )
    assert exact_frame_is_ready(
        (_AdoptionState(True, True), _AdoptionState(True, True))
    )
