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

"""Delta-reduce deterministic abuse failures while preserving their signature."""

from __future__ import annotations

import math
from collections.abc import Callable

from .abuse_model import AbuseAction, AbuseReport

TraceRunner = Callable[[tuple[AbuseAction, ...]], AbuseReport]


def minimize_failing_actions(
    actions: tuple[AbuseAction, ...],
    reproduce: TraceRunner,
) -> tuple[tuple[AbuseAction, ...], AbuseReport]:
    """Remove irrelevant actions while reproducing the original violation."""
    baseline = reproduce(actions)
    if baseline.violation is None:
        return actions, baseline
    candidate = actions[: baseline.violation.action_index + 1]
    candidate_report = reproduce(candidate)
    if not _same_failure(candidate_report, baseline):
        return actions, baseline

    granularity = 2
    while len(candidate) >= 2:
        chunk_size = math.ceil(len(candidate) / granularity)
        reduced = False
        for start in range(0, len(candidate), chunk_size):
            trial = candidate[:start] + candidate[start + chunk_size :]
            if not trial:
                continue
            trial_report = reproduce(trial)
            if _same_failure(trial_report, baseline):
                candidate = trial
                candidate_report = trial_report
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if reduced:
            continue
        if granularity >= len(candidate):
            break
        granularity = min(len(candidate), granularity * 2)
    return candidate, candidate_report


def _same_failure(candidate: AbuseReport, baseline: AbuseReport) -> bool:
    """Return whether two reports identify the same externally observed defect."""
    if candidate.violation is None or baseline.violation is None:
        return False
    return (
        candidate.violation.phase == baseline.violation.phase
        and candidate.violation.message == baseline.violation.message
    )
