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
"""Resolve layer-type-specific edge edits behind a source-neutral contract."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.spatial_constraint import CoverageSpatialConstraint
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor


@dataclass(frozen=True, slots=True, kw_only=True)
class LayerEdgeTargetSnapshot:
    """Capture immutable coverage and adoption guards for one layer target."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source_id: uuid.UUID
    source_revision: object
    coverage: CoverageSnapshot
    spatial_constraint: CoverageSpatialConstraint


class LayerEdgeEditOwner(Protocol):
    """Adapt one layer family to generic edge modification orchestration."""

    def capture(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> LayerEdgeTargetSnapshot | None:
        """Capture editable coverage when this owner supports ``layer``."""
        ...

    def is_current(self, target: LayerEdgeTargetSnapshot) -> bool:
        """Return whether a detached product may still replace its source."""
        ...

    def commit(
        self,
        target: LayerEdgeTargetSnapshot,
        coverage: CoverageSnapshot | None,
    ) -> bool:
        """Commit one settled product through authoritative layer history."""
        ...


@dataclass(frozen=True, slots=True)
class ResolvedLayerEdgeTarget:
    """Pair one captured target with the adapter that owns its source kind."""

    owner: LayerEdgeEditOwner
    snapshot: LayerEdgeTargetSnapshot


class LayerEdgeEditRegistry:
    """Select the authoritative adapter for generic layer edge operations."""

    def __init__(self) -> None:
        """Create an empty ordered adapter registry."""
        self._owners: list[LayerEdgeEditOwner] = []

    def register(self, owner: LayerEdgeEditOwner) -> None:
        """Register one source owner exactly once."""
        if owner not in self._owners:
            self._owners.append(owner)

    def resolve(
        self,
        scene: SceneDescriptor,
        layer_id: uuid.UUID,
    ) -> ResolvedLayerEdgeTarget | None:
        """Capture the addressed layer through its first supporting owner."""
        layer = next(
            (candidate for candidate in scene.layers if candidate.layer_id == layer_id),
            None,
        )
        if layer is None:
            return None
        for owner in self._owners:
            snapshot = owner.capture(scene, layer)
            if snapshot is not None:
                return ResolvedLayerEdgeTarget(owner, snapshot)
        return None


__all__ = [
    "LayerEdgeEditOwner",
    "LayerEdgeEditRegistry",
    "LayerEdgeTargetSnapshot",
    "ResolvedLayerEdgeTarget",
]
