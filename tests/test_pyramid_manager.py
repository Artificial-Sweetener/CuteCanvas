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

"""Behavior tests for pyramid execution, adoption, retry, and cancellation."""

from __future__ import annotations

import time
import uuid

import pytest
from PySide6.QtGui import QImage, Qt
from qpane.rendering import PyramidManager, PyramidStatus

from tests.helpers.config import fixed_cache_config
from tests.helpers.execution_backend import ControlledExecution
from tests.helpers.render_plan import make_source_key


@pytest.fixture()
def sample_image() -> QImage:
    """Return a small opaque image for deterministic pyramid generation."""
    image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    return image


def _manager(execution: ControlledExecution) -> PyramidManager:
    """Return a manager bound to one controlled public execution scope."""
    return PyramidManager(
        config=fixed_cache_config(),
        execution_scope=execution.scope,
    )


def test_pyramid_generation_adopts_complete_product(qapp, sample_image: QImage) -> None:
    """One accepted generation should become a complete cached pyramid."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_source_key()

    manager.generate_pyramid_for_asset(key, sample_image)

    assert [job.operation for job in execution.pending_jobs()] == ["render.pyramid"]
    execution.run_operation("render.pyramid")
    qapp.processEvents()
    pyramid = manager.pyramid_for_asset(key)
    assert pyramid is not None
    assert pyramid.status is PyramidStatus.COMPLETE
    assert manager.cache_usage_bytes > 0


def test_duplicate_generation_keeps_one_inflight_product(
    qapp, sample_image: QImage
) -> None:
    """Repeated requests for one asset must not activate parallel generation."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_source_key()

    manager.generate_pyramid_for_asset(key, sample_image)
    manager.generate_pyramid_for_asset(key, sample_image)

    assert len(execution.pending_jobs()) == 1
    execution.run_all()
    qapp.processEvents()
    assert manager.pyramid_for_asset(key).status is PyramidStatus.COMPLETE


def test_shutdown_cancels_pending_generation(qapp, sample_image: QImage) -> None:
    """Closing a manager must settle accepted work without stale adoption."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_source_key()
    manager.generate_pyramid_for_asset(key, sample_image)

    manager.shutdown(wait=False)
    qapp.processEvents()

    assert not execution.pending_jobs()
    assert execution.cancelled
    assert manager.pyramid_for_asset(key).status is not PyramidStatus.COMPLETE


def test_structured_rejection_retries_and_then_adopts(
    qapp, sample_image: QImage
) -> None:
    """Saturation should retain one bounded retry instead of dropping work."""
    execution = ControlledExecution(rejection_counts={"render.pyramid": 1})
    manager = _manager(execution)
    key = make_source_key()
    throttled: list[int] = []
    manager.pyramidThrottled.connect(lambda _key, attempt: throttled.append(attempt))

    manager.generate_pyramid_for_asset(key, sample_image)

    deadline = time.monotonic() + 2.0
    while not execution.pending_jobs() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.002)
    assert throttled == [1]
    execution.run_all()
    qapp.processEvents()
    assert manager.pyramid_for_asset(key).status is PyramidStatus.COMPLETE


def test_revision_keys_never_adopt_into_each_other(qapp, sample_image: QImage) -> None:
    """Distinct source revisions must retain independent pyramid identity."""
    execution = ControlledExecution()
    manager = _manager(execution)
    source_id = uuid.uuid4()
    old_key = make_source_key(source_id, revision=1)
    new_key = make_source_key(source_id, revision=2)
    manager.generate_pyramid_for_asset(old_key, sample_image)
    manager.generate_pyramid_for_asset(new_key, sample_image)

    jobs = execution.pending_jobs()
    execution.run_job(jobs[1])
    execution.run_job(jobs[0])
    qapp.processEvents()

    assert manager.pyramid_for_asset(old_key).status is PyramidStatus.COMPLETE
    assert manager.pyramid_for_asset(new_key).status is PyramidStatus.COMPLETE
    assert old_key != new_key
