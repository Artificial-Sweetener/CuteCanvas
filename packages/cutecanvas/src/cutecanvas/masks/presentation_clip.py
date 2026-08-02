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

"""Mask canvas-aperture policy for settled and transient presentation."""

from __future__ import annotations

from qpane.sdk.scene import (
    ClipCoordinateSpace,
    LayerClip,
    LayerDescriptor,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
)


def resolve_mask_presentation_clip(
    scene: SceneDescriptor,
    requested: LayerClip | None,
    placement: LayerPlacement,
) -> LayerClip | None:
    """Return an explicit clip or the canvas aperture when a mask can escape."""
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


def resolve_transform_preview_clip(
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    placement: LayerPlacement,
) -> LayerClip | None:
    """Apply mask aperture policy while preserving every other layer clip."""
    if layer.kind is not LayerKind.MASK:
        return layer.clip
    return resolve_mask_presentation_clip(scene, layer.clip, placement)
