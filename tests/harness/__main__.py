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

"""Command-line entry point for mounted CuteCanvas abuse campaigns."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from .campaign import (
    CI_PROFILE,
    SOAK_PROFILE,
    AbuseProfile,
    load_trace,
    minimize_trace,
    run_campaign,
    run_trace,
    save_trace,
)


def main() -> int:
    """Run the selected profile or replay and emit JSON reports."""
    parser = _argument_parser()
    arguments = parser.parse_args()
    if arguments.minimize and arguments.replay is None:
        parser.error("--minimize requires --replay")
    logging.basicConfig(level=getattr(logging, arguments.log_level.upper()))
    qapp = QApplication.instance() or QApplication([])
    artifact_directory = arguments.artifacts.resolve()
    if arguments.replay is not None:
        seed, actions = load_trace(arguments.replay)
        image_size = arguments.image_size or SOAK_PROFILE.image_size
        if arguments.minimize:
            actions, report = minimize_trace(
                qapp,
                seed=seed,
                actions=actions,
                image_size=image_size,
            )
            save_trace(
                artifact_directory / f"seed-{seed}" / "minimized-trace.json",
                seed,
                actions,
            )
        else:
            report = run_trace(
                qapp,
                seed=seed,
                actions=actions,
                image_size=image_size,
                artifact_directory=artifact_directory,
            )
        reports = (report,)
    else:
        base_profile = CI_PROFILE if arguments.profile == "ci" else SOAK_PROFILE
        profile = AbuseProfile(
            name=base_profile.name,
            image_size=arguments.image_size or base_profile.image_size,
            random_strokes=(
                arguments.random_strokes
                if arguments.random_strokes is not None
                else base_profile.random_strokes
            ),
            seeds=arguments.seeds or base_profile.seeds,
        )
        reports = run_campaign(
            qapp,
            profile=profile,
            first_seed=arguments.seed,
            artifact_directory=artifact_directory,
        )
    print(json.dumps([report.to_dict() for report in reports], indent=2))
    return 0 if all(report.succeeded for report in reports) else 1


def _argument_parser() -> argparse.ArgumentParser:
    """Build the stable assistant-facing command contract."""
    parser = argparse.ArgumentParser(
        description="Abuse a real mounted CuteCanvas with replayable mixed input.",
    )
    parser.add_argument("--profile", choices=("ci", "soak"), default="ci")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seeds", type=int)
    parser.add_argument("--random-strokes", type=int)
    parser.add_argument("--image-size", type=int)
    parser.add_argument(
        "--log-level",
        choices=("debug", "info", "warning", "error"),
        default="warning",
    )
    parser.add_argument("--replay", type=Path)
    parser.add_argument(
        "--minimize",
        action="store_true",
        help="Delta-reduce a failing --replay trace to the same violation.",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("qpane-abuse-artifacts"),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
