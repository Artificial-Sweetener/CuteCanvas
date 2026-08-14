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
"""Retain and replay mask patches independently of raster storage topology."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from qpane.sdk.raster import qimage_to_numpy_view_grayscale8
from qpane.sdk.scene import RasterBounds

from .mask_undo import MaskPatch, MaskPatchCommand


class PatchCoverageSurface(Protocol):
    """Describe coverage storage operations required by patch history."""

    @property
    def bounds(self) -> RasterBounds | None:
        """Return current layer-local storage bounds."""
        ...

    def set_bounds(self, bounds: RasterBounds) -> bool:
        """Reframe storage while retaining intersecting pixels."""
        ...

    def storage_rect(self, layer_rect: RasterBounds) -> RasterBounds | None:
        """Map one layer-local rectangle into current storage coordinates."""
        ...

    def mutate_storage_region(
        self,
        region: RasterBounds,
        mutator: Callable[[np.ndarray, QImage], None],
    ) -> None:
        """Apply one mutation to a current storage rectangle."""
        ...


class PatchCoverageAsset(Protocol):
    """Describe the coverage collaborator needed by patch history."""

    raster: PatchCoverageSurface


class PatchMaskLayer(Protocol):
    """Describe one mask layer resolved for patch replay."""

    coverage: PatchCoverageAsset


class PatchMaskAssets(Protocol):
    """Resolve mask layers without exposing asset-store implementation."""

    def get_layer(self, mask_id: uuid.UUID) -> PatchMaskLayer | None:
        """Return one mask layer when it still exists."""
        ...


class MaskPatchHistory:
    """Own stable patch coordinates, replay, and presentation projection."""

    def __init__(self, assets: PatchMaskAssets) -> None:
        """Bind the authoritative mask asset resolver."""
        self._assets = assets

    def build_command(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None,
    ) -> MaskPatchCommand | None:
        """Detach patches and retain their layer-local coordinate identity."""
        layer = self._assets.get_layer(mask_id)
        if layer is None or not patches:
            return None
        storage_bounds = layer.coverage.raster.bounds
        if storage_bounds is None:
            return None
        normalized = tuple(
            self._normalize_patch(patch, storage_bounds) for patch in patches
        )
        return MaskPatchCommand(
            mask_id,
            normalized,
            self.apply,
            self.resolve_storage_rect,
            notify,
        )

    def apply(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        use_after: bool,
    ) -> None:
        """Replay patches after restoring any compacted-away storage envelope."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return
        raster = layer.coverage.raster
        sequence = tuple(patches) if use_after else tuple(reversed(patches))
        for patch in sequence:
            bounds = patch.bounds
            if bounds is None:
                raise ValueError("retained mask patches require layer-local bounds")
            current = raster.bounds
            if current is None or not current.contains(bounds):
                raster.set_bounds(bounds if current is None else current.united(bounds))
            storage = raster.storage_rect(bounds)
            if storage is None:
                raise ValueError("mask patch bounds must map into coverage storage")
            source = patch.after if use_after else patch.before
            source_view, _ = qimage_to_numpy_view_grayscale8(source)

            def mutate(
                destination: np.ndarray,
                _image: QImage,
                *,
                retained: np.ndarray = source_view,
                selected: np.ndarray = patch.mask,
            ) -> None:
                """Copy selected retained pixels into current canonical storage."""
                np.copyto(destination, retained, where=selected)

            raster.mutate_storage_region(storage, mutate)

    def resolve_storage_rect(
        self,
        mask_id: uuid.UUID,
        patch: MaskPatch,
    ) -> QRect | None:
        """Project stable patch bounds into the current storage coordinate space."""
        layer = self._assets.get_layer(mask_id)
        if layer is None or patch.bounds is None:
            return None
        storage = layer.coverage.raster.storage_rect(patch.bounds)
        return None if storage is None else storage.to_qrect()

    @staticmethod
    def _normalize_patch(
        patch: MaskPatch,
        storage_bounds: RasterBounds,
    ) -> MaskPatch:
        """Detach one patch and derive stable coordinates from capture storage."""
        rect = patch.rect.normalized()
        bounds = patch.bounds or RasterBounds(
            storage_bounds.x + rect.x(),
            storage_bounds.y + rect.y(),
            rect.width(),
            rect.height(),
        )
        return MaskPatch(
            rect,
            patch.before.copy(),
            patch.after.copy(),
            np.array(patch.mask, copy=True, dtype=bool),
            bounds,
        )


__all__ = ["MaskPatchHistory"]
