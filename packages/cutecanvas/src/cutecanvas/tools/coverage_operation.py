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
"""Resolve modifier precedence for coverage-authoring tools."""

from __future__ import annotations

from cutecanvas.coverage import CoverageCombineMode


def resolve_coverage_operation(
    *,
    default: CoverageCombineMode,
    alt_held: bool,
    shift_held: bool,
) -> CoverageCombineMode:
    """Return one deterministic operation with subtraction taking precedence."""
    if alt_held:
        return CoverageCombineMode.SUBTRACT
    if shift_held:
        return CoverageCombineMode.ADD
    return default


def resolve_coverage_gesture_operation(
    *,
    default: CoverageCombineMode,
    alt_held: bool,
    shift_held: bool,
    has_coverage: bool,
    alt_constrains_empty: bool,
) -> CoverageCombineMode:
    """Resolve one operation while preserving first-selection Alt geometry."""
    if alt_held and alt_constrains_empty and not has_coverage:
        return CoverageCombineMode.REPLACE
    return resolve_coverage_operation(
        default=default,
        alt_held=alt_held,
        shift_held=shift_held,
    )
