#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Apply exact active architecture waivers and reject stale exceptions."""

from __future__ import annotations

from datetime import date, datetime, timezone

from .model import Diagnostic, ProductArchitectureState


def apply_architecture_waivers(
    diagnostics: list[Diagnostic],
    states: tuple[ProductArchitectureState, ...],
    *,
    today: date | None = None,
) -> list[Diagnostic]:
    """Suppress exact active findings and reject unused current waivers."""
    current_date = today or datetime.now(timezone.utc).date()
    waivers = tuple(
        waiver
        for state in states
        for waiver in state.waivers
        if waiver.review_by >= current_date
    )
    by_finding = {(waiver.rule, waiver.path): waiver for waiver in waivers}
    used: set[str] = set()
    results: list[Diagnostic] = []
    for diagnostic in diagnostics:
        waiver = by_finding.get((diagnostic.rule, diagnostic.path))
        if waiver is None:
            results.append(diagnostic)
        else:
            used.add(waiver.identifier)
    results.extend(
        Diagnostic(
            "WAIVER006",
            f"packages/{waiver.product}/ARCHITECTURE_WAIVERS.toml",
            f"waiver {waiver.identifier} matches no current {waiver.rule} diagnostic; delete the stale snapshot or correct its exact current facts",
        )
        for waiver in waivers
        if waiver.identifier not in used
    )
    return results
