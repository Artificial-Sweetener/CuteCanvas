#    QPane - High-performance PySide6 image viewer
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

"""Verify the public runtime's stable native-affinity contract."""

from __future__ import annotations

import threading
import time

from qpane.sdk.execution import (
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    InlineDispatcher,
    create_default_execution_runtime,
)


def test_native_affinity_requests_reuse_one_stable_thread() -> None:
    """Equivalent affinity keys always execute on one persistent thread."""
    runtime = create_default_execution_runtime()
    scope = runtime.open_scope(
        owner_id="sam-affinity-test",
        dispatcher=InlineDispatcher(),
    )
    identities: list[int] = []
    handles = [
        scope.submit(
            ExecutionRequest(
                operation="test.sam.affinity",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.THREAD_AFFINE_NATIVE,
                    affinity_key="sam:cpu",
                    exclusive_key="sam:cpu",
                ),
                work=lambda _context: threading.get_ident(),
            ),
            adopt=identities.append,
        )
        for _index in range(3)
    ]
    deadline = time.monotonic() + 3.0
    while any(handle.outcome is None for handle in handles):
        if time.monotonic() >= deadline:
            raise AssertionError("affinity requests did not settle")
        time.sleep(0.005)
    runtime.shutdown(wait=True)
    assert len(identities) == 3
    assert len(set(identities)) == 1
