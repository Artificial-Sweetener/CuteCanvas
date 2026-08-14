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
"""Prepare an immutable multi-product release candidate without publishing it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tools.release.candidate import prepare_candidate, write_github_outputs

_ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str] | None = None) -> None:
    """Prepare a release plan and expose its candidate outputs to CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(arguments)
    plan = prepare_candidate(_ROOT, options.source_sha, options.output)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        write_github_outputs(plan, Path(github_output))
    if plan.products:
        print(
            f"SUCCESS: prepared release plan {plan.plan_id} at "
            f"{plan.candidate_sha} for {', '.join(p.tag for p in plan.products)}."
        )
    else:
        print(f"SUCCESS: source {plan.source_sha} requires no product release.")


if __name__ == "__main__":
    run()
