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
"""Seal, inspect, verify, and finalize an immutable release plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.release.artifacts import seal_release_plan, verify_release_artifacts
from tools.release.candidate import finalize_candidate
from tools.release.plan import load_release_plan, save_release_plan
from tools.release.products import format_version

_ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str] | None = None) -> None:
    """Execute one release-plan lifecycle operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    seal = subcommands.add_parser("seal")
    seal.add_argument("plan", type=Path)
    seal.add_argument("distributions", type=Path)
    seal.add_argument("output", type=Path)
    verify = subcommands.add_parser("verify")
    verify.add_argument("plan", type=Path)
    verify.add_argument("distributions", type=Path)
    verify.add_argument("--product")
    finalize = subcommands.add_parser("finalize")
    finalize.add_argument("plan", type=Path)
    describe = subcommands.add_parser("describe")
    describe.add_argument("plan", type=Path)
    options = parser.parse_args(arguments)

    plan = load_release_plan(options.plan)
    if options.command == "seal":
        sealed = seal_release_plan(plan, options.distributions)
        save_release_plan(sealed, options.output)
        print(f"SUCCESS: sealed release plan {sealed.plan_id}.")
    elif options.command == "verify":
        verify_release_artifacts(plan, options.distributions, options.product)
        print(f"SUCCESS: artifacts match sealed release plan {plan.plan_id}.")
    elif options.command == "finalize":
        finalize_candidate(_ROOT, plan)
        print(f"SUCCESS: atomically finalized release plan {plan.plan_id}.")
    else:
        print(
            json.dumps(
                {
                    "plan_id": plan.plan_id,
                    "source_sha": plan.source_sha,
                    "candidate_sha": plan.candidate_sha,
                    "sealed": plan.sealed,
                    "recovery_id": plan.recovery_id if plan.sealed else "",
                    "products": [
                        {
                            "name": product.name,
                            "version": format_version(product.version),
                            "tag": product.tag,
                            "commit_sha": product.commit_sha,
                        }
                        for product in plan.products
                    ],
                },
                separators=(",", ":"),
            )
        )


if __name__ == "__main__":
    run()
