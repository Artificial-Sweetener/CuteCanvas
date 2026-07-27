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

"""Preserve complete layer products across asynchronous source transitions."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from math import isclose

from ..scene.model import LayerDescriptor
from ..scene.render_plan import (
    SceneRenderItem,
    SceneRenderPlan,
)
from .frame_geometry import RenderFrameGeometry


class SampledFrameContinuity:
    """Retain one complete frame across source recompilation and refinement."""

    def __init__(self) -> None:
        """Initialize without a retired frame."""
        self._retired_plan: SceneRenderPlan | None = None

    def retire(self, plan: SceneRenderPlan | None) -> None:
        """Preserve the last complete frame before source metadata is invalidated."""
        if plan is not None:
            self._retired_plan = plan

    def resolve(
        self,
        current_items: tuple[SceneRenderItem, ...],
        *,
        pending_layer_ids: frozenset[uuid.UUID],
        previous_plan: SceneRenderPlan | None,
        frame: RenderFrameGeometry,
    ) -> tuple[SceneRenderItem, ...]:
        """Keep prior products until every replacement layer has settled."""
        if not pending_layer_ids:
            self._retired_plan = None
            return current_items
        prior = self._retired_plan or previous_plan
        if prior is None or not _same_frame(prior, frame):
            return current_items
        previous_items = tuple(
            item
            for item in prior.render_items
            if item.descriptor.layer_id in pending_layer_ids
        )
        retained_layer_ids = frozenset(
            item.descriptor.layer_id for item in previous_items
        )
        if not retained_layer_ids:
            return current_items
        settled_items = tuple(
            item
            for item in current_items
            if item.descriptor.layer_id not in retained_layer_ids
        )
        return (*settled_items, *previous_items)

    def changed_layer_ids(
        self,
        descriptors: Iterable[LayerDescriptor],
        *,
        previous_plan: SceneRenderPlan | None,
    ) -> frozenset[uuid.UUID]:
        """Return layers without a matching previously presented source revision."""
        prior = self._retired_plan or previous_plan
        if prior is None:
            return frozenset(descriptor.layer_id for descriptor in descriptors)
        prior_descriptors = {
            item.descriptor.layer_id: item.descriptor for item in prior.render_items
        }
        return frozenset(
            descriptor.layer_id
            for descriptor in descriptors
            if (previous := prior_descriptors.get(descriptor.layer_id)) is None
            or (
                previous.source == descriptor.source
                and previous.source_revision != descriptor.source_revision
            )
        )


def _same_frame(plan: SceneRenderPlan, frame: RenderFrameGeometry) -> bool:
    """Return whether prior products project onto the exact current viewport."""
    return (
        isclose(plan.zoom, frame.zoom, rel_tol=1e-9, abs_tol=1e-9)
        and plan.current_pan == frame.current_pan
        and plan.qpane_rect == frame.qpane_rect
        and plan.physical_viewport_rect == frame.physical_viewport_rect
    )
