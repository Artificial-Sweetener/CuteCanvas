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

"""Validated manifest conversion for composition layer instances."""

from __future__ import annotations

import uuid

from PySide6.QtGui import QColor

from qpane.sdk.scene import ClipCoordinateSpace, LayerClip, LayerInteractionPolicy

from ..composition.layers import CompositionLayerInstance
from ..resources import ProjectResourceReference
from .effect_codec import decode_layer_effect, encode_layer_effect
from .layer_geometry_codec import decode_layer_geometry, encode_layer_geometry
from .layer_mapping_codec import decode_layer_mapping, encode_layer_mapping


def encode_layer(layer: CompositionLayerInstance) -> dict[str, object]:
    """Convert one immutable layer instance into JSON values."""
    tint = None if layer.tint is None else list(layer.tint.getRgb())
    return {
        "layer_id": str(layer.layer_id),
        "source": {
            "kind": layer.source.kind,
            "resource_id": str(layer.source.resource_id),
        },
        "transform": encode_layer_mapping(layer.transform),
        "visible": layer.visible,
        "opacity": layer.opacity,
        "tint": tint,
        "hit_test": layer.hit_test,
        "interaction": [
            layer.interaction.selectable,
            layer.interaction.movable,
            layer.interaction.pixel_editable,
            layer.interaction.reorderable,
            layer.interaction.removable,
        ],
        "role": layer.role,
        "label": layer.label,
        "clip": _encode_clip(layer.clip),
        "metadata": dict(layer.metadata),
        "effects": [encode_layer_effect(effect) for effect in layer.effects],
        "geometry": encode_layer_geometry(layer.geometry),
    }


def decode_layer(
    item: object,
    *,
    legacy_version_two: bool = False,
) -> CompositionLayerInstance:
    """Validate and reconstruct one layer manifest entry."""
    if not isinstance(item, dict):
        raise TypeError("layer entries must be objects")
    transform_values = item["transform"]
    interaction_values = item["interaction"]
    if not isinstance(interaction_values, list) or len(interaction_values) not in {
        3,
        5,
    }:
        raise ValueError("layer interaction must contain three or five values")
    tint_values = item.get("tint")
    tint = None
    if tint_values is not None:
        if not isinstance(tint_values, list) or len(tint_values) != 4:
            raise ValueError("layer tint must contain four channels")
        tint = QColor(*(int(channel) for channel in tint_values))
    metadata = item.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TypeError("layer metadata must be an object")
    source_item = (
        {
            "kind": item["source_kind"],
            "resource_id": item["source_id"],
        }
        if legacy_version_two
        else item.get("source")
    )
    if not isinstance(source_item, dict):
        raise TypeError("layer source must be an object")
    effects = item.get("effects", [])
    if not isinstance(effects, list):
        raise TypeError("layer effects must be a list")
    return CompositionLayerInstance(
        layer_id=uuid.UUID(item["layer_id"]),
        source=_decode_source_reference(
            str(source_item["kind"]),
            uuid.UUID(source_item["resource_id"]),
        ),
        transform=decode_layer_mapping(
            transform_values,
            legacy_version_two=legacy_version_two,
        ),
        visible=bool(item["visible"]),
        opacity=float(item["opacity"]),
        tint=tint,
        hit_test=bool(item["hit_test"]),
        interaction=LayerInteractionPolicy(
            selectable=bool(interaction_values[0]),
            movable=bool(interaction_values[1]),
            pixel_editable=bool(interaction_values[2]),
            reorderable=(
                bool(interaction_values[3]) if len(interaction_values) == 5 else False
            ),
            removable=(
                bool(interaction_values[4]) if len(interaction_values) == 5 else False
            ),
        ),
        role=str(item["role"]),
        label=None if item.get("label") is None else str(item["label"]),
        clip=_decode_clip(item.get("clip")),
        metadata=dict(metadata),
        effects=tuple(decode_layer_effect(effect) for effect in effects),
        geometry=decode_layer_geometry(item.get("geometry")),
    )


def _decode_source_reference(
    kind: str,
    resource_id: uuid.UUID,
) -> ProjectResourceReference:
    """Decode one persisted source reference through known domain values."""
    supported = {
        "mask",
        "project-resource",
        "raster",
        "placed-asset",
        "imported-raster",
        "linked-raster",
        "vector",
    }
    if kind not in supported:
        raise ValueError(f"unsupported layer source kind: {kind}")
    return ProjectResourceReference(resource_id)


def _encode_clip(clip: LayerClip | None) -> dict[str, object] | None:
    """Return detached JSON values for one optional instance clip."""
    if clip is None:
        return None
    return {
        "coordinate_space": clip.coordinate_space.value,
        "rect": [clip.x, clip.y, clip.width, clip.height],
    }


def _decode_clip(item: object) -> LayerClip | None:
    """Validate and decode one optional instance clip."""
    if item is None:
        return None
    if not isinstance(item, dict):
        raise TypeError("layer clip must be an object")
    rect = item.get("rect")
    if not isinstance(rect, list) or len(rect) != 4:
        raise ValueError("layer clip rect must contain four values")
    return LayerClip(
        coordinate_space=ClipCoordinateSpace(str(item["coordinate_space"])),
        x=float(rect[0]),
        y=float(rect[1]),
        width=float(rect[2]),
        height=float(rect[3]),
    )


__all__ = ["decode_layer", "encode_layer"]
