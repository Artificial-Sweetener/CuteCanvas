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

"""Resolve sampled layers that require complete prior-frame continuity."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SampledFrameAdmission:
    """Own fallback and prior-frame admission for asynchronously sampled layers."""

    pending_layer_ids: frozenset[uuid.UUID]
    source_transition_layer_ids: frozenset[uuid.UUID]
    transient_support_layer_ids: frozenset[uuid.UUID]
    sampled_layer_ids: frozenset[uuid.UUID]

    @property
    def fallback_candidate_layer_ids(self) -> frozenset[uuid.UUID]:
        """Return layers that need a complete dense fallback product."""
        return (self.pending_layer_ids & self.source_transition_layer_ids) | (
            (self.pending_layer_ids | self.transient_support_layer_ids)
            - self.sampled_layer_ids
        )

    def continuity_layer_ids(
        self,
        fallback_layer_ids: frozenset[uuid.UUID],
    ) -> frozenset[uuid.UUID]:
        """Return pending source transitions without a complete fallback.

        Transient edit support does not replace a base layer product. Its exact
        patch composes over the retained product until a newer complete product
        is ready. Spatial refinement already has a current-projection fallback
        and must not restore a prior item carrying stale geometry.
        """
        unsettled = (self.pending_layer_ids & self.source_transition_layer_ids) | (
            self.pending_layer_ids - self.sampled_layer_ids
        )
        return unsettled - fallback_layer_ids


__all__ = ["SampledFrameAdmission"]
