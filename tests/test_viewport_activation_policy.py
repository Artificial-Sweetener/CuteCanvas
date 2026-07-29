#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Exercise every initial viewport activation-policy input combination."""

from __future__ import annotations

import pytest
from cutecanvas.runtime.viewport_activation import (
    ViewportActivation,
    resolve_viewport_activation,
)


@pytest.mark.parametrize(
    ("fit_requested", "inspection_available", "expected"),
    (
        (False, False, ViewportActivation(False, True)),
        (True, False, ViewportActivation(True, False)),
        (False, True, ViewportActivation(False, True)),
        (True, True, ViewportActivation(False, True)),
    ),
)
def test_persisted_inspection_always_wins_over_default_fit(
    fit_requested: bool,
    inspection_available: bool,
    expected: ViewportActivation,
) -> None:
    """Resolve all hostile combinations without structural-policy inputs."""

    assert (
        resolve_viewport_activation(
            fit_requested=fit_requested,
            inspection_available=inspection_available,
        )
        == expected
    )
