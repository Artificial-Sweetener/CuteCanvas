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
"""Admit one product publication from a sealed multi-product release plan."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.release.github_outputs import append_github_outputs
from tools.release.plan import load_release_plan
from tools.release.publication import admit_publication


def run(arguments: list[str] | None = None) -> None:
    """Validate one publication and expose its idempotent PyPI state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("product")
    parser.add_argument("distributions", type=Path)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--recovery-id", required=True)
    parser.add_argument("--release-tag", required=True)
    options = parser.parse_args(arguments)
    plan = load_release_plan(options.plan)
    if plan.recovery_id != options.recovery_id:
        raise RuntimeError(
            f"recovery identity {options.recovery_id} does not match {plan.recovery_id}"
        )
    if plan.product(options.product).tag != options.release_tag:
        raise RuntimeError(
            f"release tag {options.release_tag} is not selected by this plan"
        )
    state = admit_publication(
        plan,
        options.product,
        options.distributions,
        options.commit_sha,
    )
    append_github_outputs(
        {
            "publication_state": state.value,
            "upload_required": str(state.value != "complete").lower(),
        }
    )
    print(
        f"SUCCESS: {options.product} publication is admitted from plan "
        f"{plan.plan_id} with PyPI state {state.value}."
    )


if __name__ == "__main__":
    run()
