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

"""Resolve initial viewport behavior independently from document permissions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ViewportActivation:
    """Describe how final content geometry initializes one activated viewport."""

    fit_view: bool
    restore_inspection: bool


def resolve_viewport_activation(
    *,
    fit_requested: bool,
    inspection_available: bool,
) -> ViewportActivation:
    """Give persisted inspection precedence over a default fit request."""
    if inspection_available:
        return ViewportActivation(fit_view=False, restore_inspection=True)
    return ViewportActivation(
        fit_view=bool(fit_requested),
        restore_inspection=not fit_requested,
    )
