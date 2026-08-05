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
"""Run migration-stage canonical numerical ownership enforcement."""

from __future__ import annotations

from pathlib import Path

from ferrastra_ownership import validate_ownership


def main() -> None:
    """Validate canonical operation ownership from the repository root."""
    root = Path(__file__).resolve().parent.parent
    diagnostics = validate_ownership(root)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    if diagnostics:
        raise SystemExit(f"FAILED: Found {len(diagnostics)} ownership violations.")
    print("SUCCESS: Canonical Ferrastra ownership policy is valid.")


if __name__ == "__main__":
    main()
