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

"""Atomic layer-instance adoption for mask spatial-paint transitions."""

from __future__ import annotations

import uuid
from dataclasses import replace

from qpane.sdk.scene import LayerMapping

from ..composition.geometry_policy import LayerGeometryPolicy
from ..composition.layers import CompositionLayerStore


def update_spatial_paint_geometry(
    layers: CompositionLayerStore,
    composition_id: uuid.UUID,
    layer_id: uuid.UUID,
    mapping: LayerMapping,
    geometry: LayerGeometryPolicy,
) -> bool:
    """Adopt mapping and geometry together through the layer store boundary."""
    instances = layers.layers_for_composition(composition_id)
    match = next(
        (
            (index, instance)
            for index, instance in enumerate(instances)
            if instance.layer_id == layer_id
        ),
        None,
    )
    if match is None:
        return False
    index, instance = match
    return layers.restore_layer(
        composition_id,
        layer_id,
        replace(instance, transform=mapping, geometry=geometry),
        index=index,
    )


__all__ = ["update_spatial_paint_geometry"]
