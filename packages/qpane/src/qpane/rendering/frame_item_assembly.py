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

"""Assemble ordered frame items across raster, vector, and sampled sources."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from ..scene.raster import RasterBounds
from ..scene.render_plan import SceneRenderItem, SceneRenderPlan
from .compiled_scene import CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .hybrid_planner import SampledFramePlan
from .layer_clip_presentation import LayerClipPresentationRegistry
from .layer_effects import LayerEffectFrameCompiler
from .raster_planner import RasterRenderPlanner
from .sampled_frame_admission import SampledFrameAdmission
from .sampled_frame_continuity import SampledFrameContinuity
from .vector_planner import VectorRenderPlanner


class FrameItemAssembler:
    """Own complete render-item admission, effects, ordering, and clipping."""

    def __init__(
        self,
        raster: RasterRenderPlanner,
        vector: VectorRenderPlanner,
        effects: LayerEffectFrameCompiler,
        continuity: SampledFrameContinuity,
        clips: LayerClipPresentationRegistry,
    ) -> None:
        """Bind the focused frame-item collaborators."""
        self._raster = raster
        self._vector = vector
        self._effects = effects
        self._continuity = continuity
        self._clips = clips

    def assemble(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        sampled: SampledFramePlan,
        transient_support_bounds: Mapping[uuid.UUID, RasterBounds],
        previous_plan: SceneRenderPlan | None,
    ) -> tuple[SceneRenderItem, ...]:
        """Return the complete ordered and presentation-clipped frame items."""
        source_transition_ids = self._continuity.changed_layer_ids(
            (layer.descriptor for layer in compiled.hybrid_layers),
            previous_plan=previous_plan,
        )
        admission = SampledFrameAdmission(
            sampled.pending_layer_ids,
            source_transition_ids,
            frozenset(transient_support_bounds),
            frozenset(item.descriptor.layer_id for item in sampled.items),
        )
        fallback_ids = admission.fallback_candidate_layer_ids
        fallback_layers = tuple(
            layer
            for layer in compiled.hybrid_fallback_layers
            if layer.descriptor.layer_id in fallback_ids
        )
        raster_items = self._raster.build_frame_items(
            compiled,
            frame,
            layers=(*compiled.layers, *fallback_layers),
            allow_exact=_scene_layers_are_stable(compiled, previous_plan),
        )
        fallback_layer_ids = frozenset(
            item.descriptor.layer_id
            for item in raster_items
            if item.descriptor.layer_id in fallback_ids
        )
        vector_items = self._vector.build_frame_items(compiled, frame)
        sampled_items = tuple(
            item
            for item in sampled.items
            if item.descriptor.layer_id not in fallback_layer_ids
        )
        projection_fallbacks = tuple(
            item
            for item in sampled.projection_fallbacks
            if item.descriptor.layer_id not in fallback_layer_ids
        )
        projection_fallback_layer_ids = frozenset(
            item.descriptor.layer_id for item in projection_fallbacks
        )
        effect_items = self._effects.apply(
            (*raster_items, *vector_items, *sampled_items, *projection_fallbacks)
        )
        continuous_items = self._continuity.resolve(
            effect_items,
            pending_layer_ids=admission.continuity_layer_ids(
                fallback_layer_ids | projection_fallback_layer_ids
            ),
            previous_plan=previous_plan,
            frame=frame,
        )
        items_by_layer_id: dict[uuid.UUID, list[SceneRenderItem]] = {}
        for item in continuous_items:
            items_by_layer_id.setdefault(item.descriptor.layer_id, []).append(item)
        ordered_items = tuple(
            item
            for layer in compiled.scene.layers
            for item in items_by_layer_id.get(layer.layer_id, ())
        )
        return self._clips.apply(compiled.scene.scene_id, ordered_items)


def _scene_layers_are_stable(
    compiled: CompiledRenderScene,
    previous_plan: SceneRenderPlan | None,
) -> bool:
    """Prevent exact adoption from exposing an intermediate layer-set transition."""
    if previous_plan is None:
        return True
    previous_layers = frozenset(
        item.descriptor.layer_id for item in previous_plan.render_items
    )
    current_layers = frozenset(
        layer.layer_id for layer in compiled.scene.layers if layer.visible
    )
    return previous_layers == current_layers


__all__ = ["FrameItemAssembler"]
