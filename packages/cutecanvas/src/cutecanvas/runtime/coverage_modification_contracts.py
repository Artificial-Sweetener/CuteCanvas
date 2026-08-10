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

"""Define source-neutral coverage-preview target and result contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from cutecanvas.coverage import CoverageEdgeModificationRequest, CoverageSnapshot
from cutecanvas.coverage.spatial_constraint import CoverageSpatialConstraint
from cutecanvas.types import LayerEdgeOperation


class CoverageModificationPreviewTarget(Protocol):
    """Adapt one authoritative coverage owner to the shared preview lifecycle."""

    @property
    def coverage(self) -> CoverageSnapshot:
        """Return the immutable coverage captured when the session began."""

        ...

    @property
    def spatial_constraint(self) -> CoverageSpatialConstraint:
        """Return the immutable aperture that every product must respect."""

        ...

    def build_request(
        self,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> CoverageEdgeModificationRequest:
        """Build one detached transformation request from captured coverage."""

        ...

    def is_current(self) -> bool:
        """Return whether preview products may still target this owner."""

        ...

    def present(
        self,
        session_id: uuid.UUID,
        generation: int,
        product: CoverageSnapshot | None,
    ) -> bool:
        """Publish one transient product without recording durable history."""

        ...

    def commit(self, product: CoverageSnapshot | None) -> bool:
        """Commit the current product once through authoritative history."""

        ...

    def discard(self, session_id: uuid.UUID) -> None:
        """Discard transient presentation and restore captured state when needed."""

        ...

    def release(self, session_id: uuid.UUID) -> None:
        """Release transient presentation after a successful commit."""

        ...

    def diagnostic_context(self) -> str:
        """Return concise target context for failure logs."""

        ...


@dataclass(frozen=True, slots=True)
class CoverageModificationPreviewResult:
    """Describe one terminal preview request independently of its target family."""

    request_id: uuid.UUID
    session_id: uuid.UUID
    operation: LayerEdgeOperation
    succeeded: bool
    message: str
    target: CoverageModificationPreviewTarget


__all__ = [
    "CoverageModificationPreviewResult",
    "CoverageModificationPreviewTarget",
]
