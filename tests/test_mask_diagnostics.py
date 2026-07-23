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

import uuid

from cutecanvas.masks.mask_diagnostics import (
    MaskStrokeDiagnostics,
)


def test_tracker_records_submission_and_completion():
    tracker = MaskStrokeDiagnostics()
    mask_id = uuid.uuid4()
    tracker.record_submitted(
        mask_id=mask_id,
        job_token=1,
        generation=2,
        pending_count=0,
        source="paint",
        stride=2,
    )
    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert len(snapshot.outstanding) == 1
    assert snapshot.outstanding[0].source == "paint"
    tracker.record_completed(mask_id=mask_id, job_token=1, status="applied")
    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert not snapshot.outstanding
    assert snapshot.last_result is not None
    assert snapshot.last_result.status == "applied"


def test_tracker_drop_and_generation_events():
    tracker = MaskStrokeDiagnostics()
    mask_id = uuid.uuid4()
    tracker.record_drop(mask_id=mask_id, job_token=5, reason="stale_token")
    tracker.record_generation_event("rebased")
    tracker.record_generation_event("rebased")
    tracker.record_generation_event("clamped")
    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert snapshot.drop_counts.get("stale_token") == 1
    assert snapshot.generation_events.get("rebased") == 2
    assert snapshot.generation_events.get("clamped") == 1
    assert snapshot.last_result is not None
    assert snapshot.last_result.status.startswith("dropped:")
