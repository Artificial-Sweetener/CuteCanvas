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
from dataclasses import dataclass

from PySide6.QtGui import QImage
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from ..coverage import CoverageAsset
from ..resources import ProjectResourceReference
from .mask import MaskAssetStore
from .projection import project_mask_snapshot


@dataclass(frozen=True, slots=True)
class MaskExportSnapshot:
    """Carry one exact bounded mask revision into an external operation."""

    mask_id: uuid.UUID
    composition_id: uuid.UUID
    revision: int
    image: QImage

    def __post_init__(self) -> None:
        """Detach mutable pixels and validate stable export identity."""
        if not isinstance(self.mask_id, uuid.UUID):
            raise TypeError("mask_id must be a UUID")
        if not isinstance(self.composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a non-negative integer")
        if not isinstance(self.image, QImage) or self.image.isNull():
            raise ValueError("image must be a non-null QImage")
        object.__setattr__(self, "image", self.image.copy())


class MaskImageExportService:
    """Project one addressed mask into its document canvas without activation."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        composition_ids_for_mask: Callable[[uuid.UUID], tuple[uuid.UUID, ...]],
        current_composition_id: Callable[[], uuid.UUID | None],
        scene_for_composition: Callable[[uuid.UUID], SceneDescriptor],
        resource_revision: Callable[[uuid.UUID], int | None],
    ) -> None:
        """Bind the authoritative mask, composition, and scene owners."""
        self._assets = assets
        self._composition_ids_for_mask = composition_ids_for_mask
        self._current_composition_id = current_composition_id
        self._scene_for_composition = scene_for_composition
        self._resource_revision = resource_revision

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
        snapshot = self.capture(mask_id, composition_id=composition_id)
        return None if snapshot is None else snapshot.image.copy()

    def capture(
        self,
        mask_id: uuid.UUID,
        *,
        composition_id: uuid.UUID | None = None,
    ) -> MaskExportSnapshot | None:
        """Capture one immutable mask revision before bounded evaluation."""
        resolved_composition_id = self._resolve_composition_id(
            mask_id,
            composition_id,
        )
        if resolved_composition_id is None:
            return None
        captured = self._capture_asset(mask_id)
        if captured is None:
            return None
        revision, asset = captured
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
            asset.snapshot(),
            layer=layer,
            canvas_x=scene.bounds.x,
            canvas_y=scene.bounds.y,
            canvas_width=width,
            canvas_height=height,
        )
        return MaskExportSnapshot(
            mask_id=mask_id,
            composition_id=resolved_composition_id,
            revision=revision,
            image=numpy_to_qimage_grayscale8(pixels),
        )

    def _capture_asset(self, mask_id: uuid.UUID) -> tuple[int, CoverageAsset] | None:
        """Detach one coherent mask resource revision despite concurrent mutation."""
        for _attempt in range(3):
            revision = self._resource_revision(mask_id)
            asset = self._assets.get_layer(mask_id)
            if revision is None or asset is None:
                return None
            state = asset.coverage.state_snapshot()
            if self._resource_revision(mask_id) == revision:
                return revision, CoverageAsset.from_snapshot(mask_id, state)
        return None

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
