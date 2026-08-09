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

"""Contract tests for transient raster provider admission."""

from __future__ import annotations

from typing import cast

from qpane.rendering.transient_raster_bridge import TransientRasterBridge
from qpane.scene.render_plan import TransientRasterContribution


def test_bridge_acknowledges_only_contributions_reaching_painting() -> None:
    """Plan calculation stays repeatable until painting admits its contribution."""
    contribution = cast(TransientRasterContribution, object())
    admitted: list[TransientRasterContribution] = []
    bridge = TransientRasterBridge()
    bridge.configure(lambda _items: contribution, lambda: None, admitted.append)

    assert bridge.compile(()) is contribution
    assert bridge.compile(()) is contribution
    assert admitted == []

    bridge.admit(contribution)

    assert admitted == [contribution]

    bridge.shutdown()

    assert bridge.compile(()) is None
    bridge.admit(contribution)
    assert admitted == [contribution]
