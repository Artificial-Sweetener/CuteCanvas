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
"""Own one bounded asynchronous coverage product prepared for mask painting."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)

from cutecanvas.coverage import CoverageAsset, CoverageSnapshot

from .mask import MaskAssetStore


class MaskPaintPreparationCache:
    """Retain at most one current worker projection and one completed product."""

    def __init__(self, execution_scope: ExecutionScope, *, owner: str) -> None:
        """Open a mask-owned child scope for cancellable preparation work."""
        self._scope = execution_scope.open_child(f"{execution_scope.owner_id}:{owner}")
        self._pending_key: object | None = None
        self._pending: ExecutionHandle[CoverageSnapshot | None, object] | None = None
        self._ready_key: object | None = None
        self._ready: CoverageSnapshot | None = None

    def warm(
        self,
        key: object,
        project: Callable[[], CoverageSnapshot | None],
    ) -> bool:
        """Submit one exact product unless it is already ready or pending."""
        if key == self._ready_key or key == self._pending_key:
            return True
        self.discard()
        request = ExecutionRequest(
            operation="editor.mask.paint.prepare",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.INTERACTIVE,
            ),
            work=lambda _context: project(),
        )
        self._pending_key = key
        try:
            handle = self._scope.submit(
                request,
                adopt=lambda product: self._adopt(key, product),
            )
        except ExecutionRejected:
            self._pending_key = None
            return False
        self._pending = handle
        handle.add_done_callback(lambda outcome: self._settle(key, handle, outcome))
        return True

    def product(self, key: object) -> CoverageSnapshot | None:
        """Return the completed product only when every authority input matches."""
        return self._ready if key == self._ready_key else None

    def is_ready(self, key: object) -> bool:
        """Return whether the exact requested product has completed."""
        return key == self._ready_key

    def discard(self) -> None:
        """Cancel pending work and release the completed bounded product."""
        pending = self._pending
        self._pending = None
        self._pending_key = None
        self._ready_key = None
        self._ready = None
        if pending is not None:
            pending.cancel(reason="mask paint preparation superseded")

    def shutdown(self) -> None:
        """Cancel preparation and close its execution scope."""
        self.discard()
        self._scope.close(reason="mask_paint_preparation_shutdown")

    def _adopt(
        self,
        key: object,
        product: CoverageSnapshot | None,
    ) -> None:
        """Publish a worker product only while its request remains current."""
        if self._pending_key != key:
            return
        self._ready_key = key
        self._ready = product

    def _settle(
        self,
        key: object,
        handle: ExecutionHandle[CoverageSnapshot | None, object],
        outcome: ExecutionOutcome[CoverageSnapshot | None],
    ) -> None:
        """Clear terminal request identity without disturbing newer work."""
        if self._pending_key != key or self._pending is not handle:
            return
        self._pending = None
        self._pending_key = None
        if outcome.state != ExecutionState.SUCCEEDED:
            self._ready_key = None
            self._ready = None


class RetainedMaskPaintPreparation:
    """Prepare exact retained coverage for the first direct raster stroke."""

    def __init__(
        self,
        assets: MaskAssetStore,
        execution_scope: ExecutionScope,
    ) -> None:
        """Bind immutable coverage inputs to one bounded worker product."""
        self._assets = assets
        self._products = MaskPaintPreparationCache(
            execution_scope,
            owner="mask-retained-paint",
        )

    def warm(self, mask_id: uuid.UUID) -> bool:
        """Prepare current retained coverage before pointer input begins."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return False
        if not layer.coverage.has_retained_items:
            self._products.discard()
            return True
        key = (mask_id, layer.coverage.revision)
        state = layer.coverage.state_snapshot()
        return self._products.warm(
            key,
            lambda: CoverageAsset.from_snapshot(mask_id, state).snapshot(),
        )

    def ready(self, mask_id: uuid.UUID) -> bool:
        """Return whether current retained coverage is ready for painting."""
        layer = self._assets.get_layer(mask_id)
        if layer is None or not layer.coverage.has_retained_items:
            return True
        return self._products.is_ready((mask_id, layer.coverage.revision))

    def take(self, mask_id: uuid.UUID) -> CoverageSnapshot | None:
        """Consume the exact current prepared product when one is available."""
        layer = self._assets.get_layer(mask_id)
        key = None if layer is None else (mask_id, layer.coverage.revision)
        product = None if key is None else self._products.product(key)
        self._products.discard()
        return product

    def shutdown(self) -> None:
        """Cancel preparation and release its view-local execution scope."""
        self._products.shutdown()


__all__ = ["MaskPaintPreparationCache", "RetainedMaskPaintPreparation"]
