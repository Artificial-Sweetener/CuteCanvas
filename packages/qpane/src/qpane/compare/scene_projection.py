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

"""Project catalog comparison sources into one coherent scene frame."""

from __future__ import annotations

import uuid
from functools import lru_cache

from PySide6.QtCore import QRectF

from ..catalog.viewer_catalog import ViewerCatalogEntry
from ..rendering.sdk import RenderLayer, RenderScene
from ..scene.affine import LayerTransform
from ..scene.model import LayerPlacement

_SCENE_NAMESPACE = uuid.UUID("79e794cd-6f4f-4c03-a838-21af22d87c46")
_PRIMARY_LAYER_NAMESPACE = uuid.UUID("d50f5466-3298-4417-82ea-df055c7124bf")
_COMPARE_LAYER_NAMESPACE = uuid.UUID("74c79f75-4082-4c18-a0f9-eefcab7b0a48")


class ComparisonSceneProjector:
    """Place both comparison sources over the primary source's normalized frame."""

    def project(
        self,
        primary: ViewerCatalogEntry | None,
        secondary: ViewerCatalogEntry | None,
    ) -> RenderScene | None:
        """Return cache-stable content geometry without presentation clipping."""
        if primary is None:
            return None
        frame = LayerPlacement(
            0.0,
            0.0,
            float(primary.size.width()),
            float(primary.size.height()),
        )
        layers = [
            RenderLayer(
                primary.source,
                layer_id=primary_layer_id(primary.entry_id),
                label=primary.label,
            )
        ]
        if secondary is not None:
            layers.append(
                RenderLayer(
                    secondary.source,
                    layer_id=comparison_layer_id(
                        primary.entry_id,
                        secondary.entry_id,
                    ),
                    transform=LayerTransform.from_placement(
                        secondary.source.bounds,
                        frame,
                    ),
                    label=secondary.label,
                    role="comparison-image",
                )
            )
        return RenderScene(
            QRectF(frame.x, frame.y, frame.width, frame.height),
            tuple(layers),
            scene_id=scene_id(primary.entry_id),
        )


@lru_cache(maxsize=4096)
def scene_id(source_id: uuid.UUID) -> uuid.UUID:
    """Return one cache-stable viewer scene identity."""
    return uuid.uuid5(_SCENE_NAMESPACE, str(source_id))


@lru_cache(maxsize=4096)
def primary_layer_id(source_id: uuid.UUID) -> uuid.UUID:
    """Return one cache-stable primary layer identity."""
    return uuid.uuid5(_PRIMARY_LAYER_NAMESPACE, str(source_id))


@lru_cache(maxsize=4096)
def comparison_layer_id(
    primary_id: uuid.UUID,
    secondary_id: uuid.UUID,
) -> uuid.UUID:
    """Return one cache-stable comparison pair identity."""
    return uuid.uuid5(
        _COMPARE_LAYER_NAMESPACE,
        f"{primary_id}:{secondary_id}",
    )
