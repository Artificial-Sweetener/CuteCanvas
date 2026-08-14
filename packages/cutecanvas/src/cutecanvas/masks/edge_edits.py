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
"""Adapt mask coverage assets to generic whole-layer edge edits."""

from __future__ import annotations

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.editor.layer_edge_targets import LayerEdgeTargetSnapshot
from cutecanvas.resources import ProjectResourceReference
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from .canvas_aperture import ActiveMaskCanvasAperture
from .mask_service import MaskService


class MaskLayerEdgeEditOwner:
    """Commit generic coverage products through mask transaction history."""

    def __init__(
        self,
        masks: MaskService,
        canvas_aperture: ActiveMaskCanvasAperture,
    ) -> None:
        """Bind authoritative mask storage and canvas aperture owners."""
        self._masks = masks
        self._canvas_aperture = canvas_aperture

    def capture(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> LayerEdgeTargetSnapshot | None:
        """Capture evaluated coverage when ``layer`` references a mask asset."""
        source = layer.source
        if not isinstance(source, ProjectResourceReference):
            return None
        mask = self._masks.assets.get_layer(source.resource_id)
        if mask is None:
            return None
        coverage = mask.coverage.snapshot()
        if coverage.bounds is None:
            return None
        spatial_constraint = self._canvas_aperture.coverage_constraint(
            source.resource_id
        )
        if spatial_constraint is None:
            return None
        return LayerEdgeTargetSnapshot(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            source_id=source.resource_id,
            source_revision=mask.coverage.revision,
            coverage=coverage,
            spatial_constraint=spatial_constraint,
        )

    def is_current(self, target: LayerEdgeTargetSnapshot) -> bool:
        """Reject products built from coverage that changed in the meantime."""
        mask = self._masks.assets.get_layer(target.source_id)
        return bool(
            mask is not None and mask.coverage.revision == target.source_revision
        )

    def commit(
        self,
        target: LayerEdgeTargetSnapshot,
        coverage: CoverageSnapshot | None,
    ) -> bool:
        """Bake one product through the mask's complete reversible transaction."""
        if not self.is_current(target):
            return False
        replacement = coverage or CoverageSnapshot(
            None,
            target.coverage.extent_policy,
            target.coverage.pixels[:0, :0],
        )
        return self._masks.apply_mask_surface(target.source_id, replacement)


__all__ = ["MaskLayerEdgeEditOwner"]
