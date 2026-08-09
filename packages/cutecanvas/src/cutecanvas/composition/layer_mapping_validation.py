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

"""Validation boundary for durable composition-layer mappings."""

from __future__ import annotations

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    LayerTransform,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
)


def validate_composition_layer_mapping(mapping: LayerMapping) -> None:
    """Reject unsupported or singular durable layer mappings."""
    if not isinstance(
        mapping,
        (
            LayerTransform,
            ProjectiveLayerTransform,
            PiecewiseLayerTransform,
            BilinearLayerTransform,
        ),
    ):
        raise TypeError("layer transform must be a supported layer mapping")
    if not mapping.is_invertible:
        raise ValueError("layer transform must be numerically invertible")


__all__ = ["validate_composition_layer_mapping"]
