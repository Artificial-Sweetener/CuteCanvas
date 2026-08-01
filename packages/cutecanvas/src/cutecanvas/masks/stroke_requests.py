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

"""Own queued mask-stroke request identity and successor relationships."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qpane.sdk.execution import ExecutionHandle

from .stroke_models import MaskStrokeJobResult


@dataclass(slots=True)
class PendingStrokeRequest:
    """Retain one queued stroke request and its adoption policy."""

    mask_id: UUID
    job_token: int
    commit: bool
    handle: ExecutionHandle[MaskStrokeJobResult, object] | None = None


class StrokeRequestRegistry:
    """Own pending request membership, handles, and commit succession."""

    def __init__(self) -> None:
        """Initialize an empty request registry."""

        self._ids_by_mask: dict[UUID, set[UUID]] = {}
        self._requests: dict[UUID, PendingStrokeRequest] = {}

    def register(
        self,
        request_id: UUID,
        *,
        mask_id: UUID,
        job_token: int,
        commit: bool,
    ) -> None:
        """Register one request before backend admission."""

        if request_id in self._requests:
            raise ValueError("stroke request identity must be unique")
        self._requests[request_id] = PendingStrokeRequest(
            mask_id=mask_id,
            job_token=job_token,
            commit=commit,
        )
        self._ids_by_mask.setdefault(mask_id, set()).add(request_id)

    def bind_handle(
        self,
        request_id: UUID,
        handle: ExecutionHandle[MaskStrokeJobResult, object],
    ) -> bool:
        """Attach an admitted handle if the request remains pending."""

        request = self._requests.get(request_id)
        if request is None:
            return False
        request.handle = handle
        return True

    def request(self, request_id: UUID) -> PendingStrokeRequest | None:
        """Return one pending request without changing membership."""

        return self._requests.get(request_id)

    def remove(self, request_id: UUID) -> PendingStrokeRequest | None:
        """Remove one request from both identity indexes."""

        request = self._requests.pop(request_id, None)
        if request is None:
            return None
        request_ids = self._ids_by_mask.get(request.mask_id)
        if request_ids is not None:
            request_ids.discard(request_id)
            if not request_ids:
                self._ids_by_mask.pop(request.mask_id, None)
        return request

    def request_ids(self, mask_id: UUID) -> tuple[UUID, ...]:
        """Return stable pending identities for one mask."""

        return tuple(self._ids_by_mask.get(mask_id, ()))

    def mask_ids(self) -> tuple[UUID, ...]:
        """Return masks with pending requests."""

        return tuple(self._ids_by_mask)

    def pending_count(self, mask_id: UUID) -> int:
        """Return the number of pending requests for one mask."""

        return len(self._ids_by_mask.get(mask_id, ()))

    def has_pending(self, mask_id: UUID) -> bool:
        """Return whether one mask retains queued or running requests."""

        return bool(self._ids_by_mask.get(mask_id))

    def has_committed_successor(self, mask_id: UUID) -> bool:
        """Return whether a pending request will durably settle the mask."""

        return any(
            (request := self._requests.get(request_id)) is not None and request.commit
            for request_id in self._ids_by_mask.get(mask_id, ())
        )

    def debug_handles(
        self,
    ) -> dict[UUID, tuple[ExecutionHandle[MaskStrokeJobResult, object], ...]]:
        """Return detached pending handles grouped by mask."""

        return {
            mask_id: tuple(
                request.handle
                for request_id in request_ids
                if (request := self._requests.get(request_id)) is not None
                and request.handle is not None
            )
            for mask_id, request_ids in self._ids_by_mask.items()
            if request_ids
        }

    def clear(self) -> None:
        """Forget every pending request after its lifecycle was cancelled."""

        self._ids_by_mask.clear()
        self._requests.clear()


__all__ = ["PendingStrokeRequest", "StrokeRequestRegistry"]
