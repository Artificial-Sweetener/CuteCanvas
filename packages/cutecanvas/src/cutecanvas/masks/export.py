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

"""Export addressed mask coverage without changing editor activation."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtGui import QImage
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from ..resources import ProjectResourceReference
from .mask import MaskAssetStore
from .projection import project_mask_snapshot


class MaskImageExportService:
    """Project one addressed mask into its document canvas without activation."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        composition_ids_for_mask: Callable[[uuid.UUID], tuple[uuid.UUID, ...]],
        current_composition_id: Callable[[], uuid.UUID | None],
        scene_for_composition: Callable[[uuid.UUID], SceneDescriptor],
    ) -> None:
        """Bind the authoritative mask, composition, and scene owners."""
        self._assets = assets
        self._composition_ids_for_mask = composition_ids_for_mask
        self._current_composition_id = current_composition_id
        self._scene_for_composition = scene_for_composition

    def export(
        self,
        mask_id: uuid.UUID,
        *,
        composition_id: uuid.UUID | None = None,
    ) -> QImage | None:
        """Return ``mask_id`` as a detached grayscale image for one composition.

        Args:
            mask_id: Stable identity of the mask resource to project.
            composition_id: Optional composition instance that supplies the canvas
                bounds and transform. It is required when a mask belongs to more
                than one non-active composition.

        Returns:
            A canvas-clipped grayscale snapshot, or ``None`` when the addressed
            mask instance cannot be resolved unambiguously.
        """
        resolved_composition_id = self._resolve_composition_id(
            mask_id,
            composition_id,
        )
        if resolved_composition_id is None:
            return None
        asset = self._assets.get_layer(mask_id)
        if asset is None:
            return None
        try:
            scene = self._scene_for_composition(resolved_composition_id)
        except KeyError:
            return None
        layer = self._layer_for_mask(scene, mask_id)
        if layer is None:
            return None
        width = round(scene.bounds.width)
        height = round(scene.bounds.height)
        if width <= 0 or height <= 0:
            return None
        pixels = project_mask_snapshot(
            asset.coverage.snapshot(),
            layer=layer,
            canvas_x=scene.bounds.x,
            canvas_y=scene.bounds.y,
            canvas_width=width,
            canvas_height=height,
        )
        return numpy_to_qimage_grayscale8(pixels)

    def _resolve_composition_id(
        self,
        mask_id: uuid.UUID,
        composition_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Resolve one unambiguous composition instance for ``mask_id``."""
        composition_ids = self._composition_ids_for_mask(mask_id)
        if composition_id is not None:
            return composition_id if composition_id in composition_ids else None
        active_composition_id = self._current_composition_id()
        if active_composition_id in composition_ids:
            return active_composition_id
        return composition_ids[0] if len(composition_ids) == 1 else None

    @staticmethod
    def _layer_for_mask(
        scene: SceneDescriptor,
        mask_id: uuid.UUID,
    ) -> LayerDescriptor | None:
        """Return the addressed mask layer from one already-resolved scene."""
        return next(
            (
                layer
                for layer in scene.layers
                if isinstance(layer.source, ProjectResourceReference)
                and layer.source.resource_id == mask_id
            ),
            None,
        )
