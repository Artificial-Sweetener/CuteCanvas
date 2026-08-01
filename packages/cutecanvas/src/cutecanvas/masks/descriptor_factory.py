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
"""Mask-domain scene descriptor factory for composition layer assembly."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from qpane.sdk.scene import (
    BlendMode,
    ClipCoordinateSpace,
    LayerClip,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    LayerPlacement,
    RasterBounds,
    SceneDescriptor,
)

from ..composition.layers import CompositionLayerInstance
from ..resources import (
    ProjectResourceKind,
    ProjectResourceRecord,
    ProjectResourceReference,
)


class MaskDescriptorAsset(Protocol):
    """Mask asset geometry required to assemble a descriptor."""

    @property
    def coverage(self):
        """Return authoritative hybrid mask coverage."""
        ...


class MaskDescriptorAssets(Protocol):
    """Resolve mask assets for descriptor assembly."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskDescriptorAsset | None:
        """Return one mask asset when present."""
        ...


class MaskDescriptorRenders(Protocol):
    """Provide render revisions for mask descriptors."""

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return current derived-render revision."""
        ...


@dataclass(frozen=True, slots=True)
class MaskLayerDescriptorFactory:
    """Resolve mask composition instances without owning scene order."""

    assets: MaskDescriptorAssets
    renders: MaskDescriptorRenders

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
        resource: ProjectResourceRecord,
    ) -> LayerDescriptor | None:
        """Resolve one mask instance into a complete scene descriptor."""
        if (
            not isinstance(instance.source, ProjectResourceReference)
            or resource.kind is not ProjectResourceKind.COVERAGE
        ):
            return None
        mask_id = instance.source.resource_id
        asset = self.assets.get_layer(mask_id)
        if asset is None:
            return None
        raster_bounds: RasterBounds | None = asset.coverage.source_bounds()
        if raster_bounds is None:
            return None
        revision = max(
            resource.revision,
            int(self.renders.render_revision(mask_id)),
        )
        placement = instance.transform.map_bounds(raster_bounds)
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.MASK,
            source=instance.source,
            placement=placement,
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=_presentation_clip(scene, instance.clip, placement),
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(
                raster_editable=True,
            ),
            source_revision=revision,
            raster_bounds=raster_bounds,
            transform=instance.transform,
        )


def _presentation_clip(
    scene: SceneDescriptor,
    requested: LayerClip | None,
    placement: LayerPlacement,
) -> LayerClip | None:
    """Apply the canvas aperture only when mask geometry can escape it."""
    if requested is not None:
        return requested
    bounds = scene.bounds
    if (
        placement.x >= bounds.x
        and placement.y >= bounds.y
        and placement.x + placement.width <= bounds.x + bounds.width
        and placement.y + placement.height <= bounds.y + bounds.height
    ):
        return None
    return LayerClip(
        ClipCoordinateSpace.SCENE,
        bounds.x,
        bounds.y,
        bounds.width,
        bounds.height,
    )
