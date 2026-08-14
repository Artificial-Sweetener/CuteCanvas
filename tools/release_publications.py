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
"""Dispatch and verify independently attested product publications."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.release.orchestration import (
    GitHubActionsGateway,
    PublicationError,
    confirm_verified_orchestrator,
    dispatch_publication_waterfall,
)
from tools.release.plan import load_release_plan


def _required_environment(name: str) -> str:
    """Return one required nonempty environment value."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise PublicationError(f"required environment value {name} is missing")
    return value


def run(arguments: list[str] | None = None) -> None:
    """Run the requested release-publication orchestration command."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    dispatch = subcommands.add_parser(
        "dispatch", help="publish every versioned product in dependency order"
    )
    dispatch.add_argument("plan", type=Path)
    verify = subcommands.add_parser(
        "verify", help="confirm an active release run completed repository verification"
    )
    verify.add_argument("run_id", type=int)
    verify.add_argument("recovery_id")
    options = parser.parse_args(arguments)

    gateway = GitHubActionsGateway(
        repository=_required_environment("GITHUB_REPOSITORY"),
        token=_required_environment("GH_TOKEN"),
    )
    if options.command == "verify":
        confirm_verified_orchestrator(
            gateway,
            run_id=options.run_id,
            repository=_required_environment("GITHUB_REPOSITORY"),
            recovery_id=options.recovery_id,
        )
        print(f"SUCCESS: release workflow run {options.run_id} passed verification.")
        return

    plan = load_release_plan(options.plan)
    tags = tuple(product.tag for product in plan.products)
    dispatch_publication_waterfall(
        gateway,
        tags,
        orchestrator_run_id=_required_environment("GITHUB_RUN_ID"),
        recovery_id=plan.recovery_id,
    )


if __name__ == "__main__":
    try:
        run()
    except PublicationError as error:
        raise SystemExit(f"ERROR: {error}") from error
