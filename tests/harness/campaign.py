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

"""Run bounded or soaking mounted-CuteCanvas abuse campaigns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from .abuse_model import (
    AbuseAction,
    AbuseReport,
    action_from_dict,
    action_to_dict,
)
from .abuse_runner import MaskAbuseRunner
from .minimizer import minimize_failing_actions
from .mounted_qpane import MountedQPaneHarness
from .scenarios import seeded_abuse_actions


@dataclass(frozen=True, slots=True)
class AbuseProfile:
    """Define resource bounds for one repeatable campaign profile."""

    name: str
    image_size: int
    random_strokes: int
    seeds: int


CI_PROFILE = AbuseProfile("ci", image_size=2048, random_strokes=4, seeds=1)
SOAK_PROFILE = AbuseProfile("soak", image_size=4096, random_strokes=30, seeds=10)


def run_campaign(
    qapp: QApplication,
    *,
    profile: AbuseProfile,
    first_seed: int,
    artifact_directory: Path,
) -> tuple[AbuseReport, ...]:
    """Run ``profile`` against fresh mounted panes and return every report."""
    reports: list[AbuseReport] = []
    for seed in range(first_seed, first_seed + profile.seeds):
        actions = seeded_abuse_actions(seed, random_strokes=profile.random_strokes)
        reports.append(
            run_trace(
                qapp,
                seed=seed,
                actions=actions,
                image_size=profile.image_size,
                artifact_directory=artifact_directory,
            )
        )
        if not reports[-1].succeeded:
            break
    return tuple(reports)


def run_trace(
    qapp: QApplication,
    *,
    seed: int,
    actions: tuple[AbuseAction, ...],
    image_size: int,
    artifact_directory: Path | None,
) -> AbuseReport:
    """Execute one action trace against a fresh production CuteCanvas."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(image_size, image_size),
        widget_size=QSize(500, 500),
        mask_count=2,
    )
    try:
        return MaskAbuseRunner(
            harness,
            seed=seed,
            artifact_directory=artifact_directory,
        ).run(actions)
    finally:
        harness.close()


def load_trace(path: Path) -> tuple[int, tuple[AbuseAction, ...]]:
    """Load a seed and exact action sequence from a failure artifact."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return int(payload["seed"]), tuple(
        action_from_dict(action) for action in payload["actions"]
    )


def save_trace(path: Path, seed: int, actions: tuple[AbuseAction, ...]) -> None:
    """Persist an exact replay trace for later assistant or CI execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "seed": seed,
                "actions": [action_to_dict(action) for action in actions],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def minimize_trace(
    qapp: QApplication,
    *,
    seed: int,
    actions: tuple[AbuseAction, ...],
    image_size: int,
) -> tuple[tuple[AbuseAction, ...], AbuseReport]:
    """Reduce one mounted failure without emitting artifacts for every trial."""

    def reproduce(candidate: tuple[AbuseAction, ...]) -> AbuseReport:
        return run_trace(
            qapp,
            seed=seed,
            actions=candidate,
            image_size=image_size,
            artifact_directory=None,
        )

    return minimize_failing_actions(actions, reproduce)
