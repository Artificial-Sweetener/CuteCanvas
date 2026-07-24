#    CuteCanvas - High-performance layered image editor
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

"""Construct the thread-affine execution lane required by native SAM models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qpane.sdk.concurrency import (
    PersistentWorkerPool,
    QThreadPoolExecutor,
    ThreadPolicy,
    build_thread_policy,
)


def build_sam_executor(
    concurrency: Mapping[str, Any],
    *,
    device: str,
) -> QThreadPoolExecutor:
    """Return a serialized, non-expiring executor for one native model device.

    Args:
        concurrency: Host concurrency settings used for queue limits and priority.
        device: Native model device represented by this execution lane.

    Returns:
        Executor whose tasks always reuse one persistent Python worker thread.
    """
    configured = build_thread_policy(concurrency)
    pending_limit = configured.pending_limits.get("sam")
    pool = PersistentWorkerPool(
        max_workers=1,
        thread_name_prefix=f"cutecanvas-sam-{device}",
    )
    policy = ThreadPolicy(
        max_workers=1,
        max_pending_total=configured.max_pending_total,
        category_priorities={"sam": configured.priority_for("sam")},
        category_limits={"sam": 1},
        pending_limits=({} if pending_limit is None else {"sam": pending_limit}),
        device_limits={device: {"sam": 1}},
    )
    return QThreadPoolExecutor(
        policy=policy,
        pool=pool,
        name=f"cutecanvas-sam-{device}",
    )
