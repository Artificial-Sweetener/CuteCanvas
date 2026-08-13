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

"""Translate supported public layer mappings at the composition boundary."""

from __future__ import annotations

from PySide6.QtGui import QTransform

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    LayerTransform,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
    layer_mapping_from_qtransform,
)


def detached_public_layer_mapping(
    mapping: LayerMapping | None,
) -> QTransform | PiecewiseLayerTransform | BilinearLayerTransform:
    """Return one detached host-facing mapping without losing bounded geometry."""
    if mapping is None:
        return QTransform()
    if isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
        return mapping
    return mapping.to_qtransform()


def normalize_public_layer_mapping(
    mapping: QTransform | LayerMapping,
) -> LayerMapping:
    """Normalize one host mapping into the immutable composition contract."""
    if isinstance(mapping, QTransform):
        return layer_mapping_from_qtransform(QTransform(mapping))
    if isinstance(
        mapping,
        (
            LayerTransform,
            ProjectiveLayerTransform,
            PiecewiseLayerTransform,
            BilinearLayerTransform,
        ),
    ):
        return mapping
    raise TypeError("transform must be a supported layer mapping")


__all__ = ["detached_public_layer_mapping", "normalize_public_layer_mapping"]
