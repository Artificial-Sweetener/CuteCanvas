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

"""Build layer instances for imported raster project resources."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSize
from qpane.sdk.scene import (
    LayerInteractionPolicy,
    LayerPlacement,
    LayerTransform,
    RasterBounds,
)

from ..composition.layers import CompositionLayerInstance
from .model import ProjectResourceReference


def imported_raster_instance(
    resource_id: uuid.UUID,
    size: QSize,
    *,
    layer_id: uuid.UUID | None = None,
    placement: LayerPlacement | None = None,
    interaction: LayerInteractionPolicy | None = None,
    label: str | None = None,
) -> CompositionLayerInstance:
    """Build one ordinary layer instance for detached imported pixels."""
    bounds = RasterBounds.from_size(size)
    destination = placement or LayerPlacement(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )
    return CompositionLayerInstance(
        layer_id=layer_id or uuid.uuid4(),
        source=ProjectResourceReference(resource_id),
        transform=LayerTransform.from_placement(bounds, destination),
        interaction=interaction or LayerInteractionPolicy(),
        role="content",
        label=label,
    )
