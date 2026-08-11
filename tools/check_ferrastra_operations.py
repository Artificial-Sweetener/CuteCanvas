#!/usr/bin/env python3
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
"""Run the Ferrastra operation contract-entry gate."""

from __future__ import annotations

from pathlib import Path

from architecture.checker import validate_repository


def main() -> None:
    """Reject operation implementations with incomplete contracts."""
    root = Path(__file__).resolve().parent.parent
    diagnostics = [
        diagnostic
        for diagnostic in validate_repository(root)
        if diagnostic.rule == "RUST012"
    ]
    for diagnostic in diagnostics:
        print(diagnostic.render())
    if diagnostics:
        raise SystemExit(
            f"FAILED: Found {len(diagnostics)} operation contract violations."
        )
    print("SUCCESS: Every Ferrastra operation has complete entry metadata.")


if __name__ == "__main__":
    main()
