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
"""Verify a sealed release stack through one clean offline pip transaction."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.release.closure import verify_offline_closure
from tools.release.plan import load_release_plan


def run(arguments: list[str] | None = None) -> None:
    """Load a release plan and prove its full resolver closure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("distributions", type=Path)
    parser.add_argument("workspace", type=Path)
    options = parser.parse_args(arguments)
    plan = load_release_plan(options.plan)
    verify_offline_closure(plan, options.distributions, options.workspace)
    print(f"SUCCESS: release plan {plan.plan_id} resolves offline in one transaction.")


if __name__ == "__main__":
    run()
