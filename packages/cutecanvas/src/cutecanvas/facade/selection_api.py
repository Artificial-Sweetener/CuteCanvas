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
"""Pixel-selection public behavior for the CuteCanvas widget facade."""

from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from cutecanvas.editor import EditorOperation
from cutecanvas.types import (
    LayerEdgeOperation,
    PixelSelectionMode,
    PixelSelectionSnapshot,
    RasterExtentPolicy,
)
from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import RasterBounds


class SelectionApiMixin:
    """Expose composition pixel-selection state and commands without owning it."""

    def setPixelSelectionPaintTarget(self) -> bool:
        """Select the active composition's pixel-selection coverage for painting."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.paintingCoordinator().select_pixel_selection(scene_id)
        )

    def pixelSelectionState(self) -> PixelSelectionSnapshot | None:
        """Return the active composition's detached pixel-selection state."""
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return None
        return self._public_pixel_selection_state(
            self.editorInteraction().pixel_selection_state(scene_id)
        )

    def setPixelSelection(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Combine grayscale coverage into the active composition selection.

        Args:
            coverage: Grayscale or color image interpreted as selection coverage.
            bounds: Scene-coordinate bounds occupied by ``coverage``.
            mode: Replacement, addition, subtraction, or intersection behavior.

        Returns:
            True when active selection state changed.

        Raises:
            TypeError: If inputs use unsupported public types.
            ValueError: If coverage is null or dimensions do not match bounds.
        """
        if not isinstance(coverage, QImage):
            raise TypeError("coverage must be a QImage")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        if coverage.isNull():
            raise ValueError("coverage must not be null")
        if (
            coverage.size() != bounds.size()
            or bounds.width() <= 0
            or bounds.height() <= 0
        ):
            raise ValueError("coverage dimensions must match positive bounds")
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if (
            scene_id is None
            or not resolution.allowed
            or not self._anchor_floating_pixels_before_edit()
        ):
            return False
        return self.editorInteraction().commit_pixel_selection(
            scene_id,
            CoverageSnapshot(
                bounds=RasterBounds.from_qrect(bounds),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=qimage_to_numpy_grayscale8(coverage),
            ),
            CoverageCombineMode(mode.value),
        )

    def clearPixelSelection(self) -> bool:
        """Clear pixel selection in the active composition."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_pixel_selection(scene_id)
        )

    def selectAllPixels(self) -> bool:
        """Select every pixel inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().select_all_pixels(scene_id)
        )

    def invertPixelSelection(self) -> bool:
        """Invert pixel selection inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().invert_pixel_selection(scene_id)
        )

    def selectLayerCoverage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Use a coverage-producing layer as composition pixel selection."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if not resolution.allowed or not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layer_coverage(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            CoverageCombineMode(mode.value),
        )

    def expandPixelSelection(self, pixels: int) -> uuid.UUID | None:
        """Expand active selection coverage asynchronously by whole pixels."""
        return self._request_pixel_selection_modification(
            LayerEdgeOperation.EXPAND,
            self._positive_pixel_radius(pixels),
        )

    def contractPixelSelection(self, pixels: int) -> uuid.UUID | None:
        """Contract active selection coverage asynchronously by whole pixels."""
        return self._request_pixel_selection_modification(
            LayerEdgeOperation.CONTRACT,
            self._positive_pixel_radius(pixels),
        )

    def featherPixelSelection(self, radius: float) -> uuid.UUID | None:
        """Feather active selection coverage asynchronously by a pixel radius."""
        normalized = float(radius)
        if not math.isfinite(normalized) or normalized <= 0.0:
            raise ValueError("selection feather radius must be finite and positive")
        return self._request_pixel_selection_modification(
            LayerEdgeOperation.FEATHER,
            normalized,
        )

    def beginPixelSelectionModificationPreview(self) -> uuid.UUID | None:
        """Capture the active selection for a reversible latest-value preview."""

        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if not resolution.allowed or not self._anchor_floating_pixels_before_edit():
            return None
        return self.pixelSelectionModificationCoordinator().begin()

    def updatePixelSelectionModificationPreview(
        self,
        session_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Replace a preview using its immutable original selection."""

        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        if not isinstance(operation, LayerEdgeOperation):
            raise TypeError("operation must be LayerEdgeOperation")
        return self.pixelSelectionModificationCoordinator().update(
            session_id,
            operation,
            radius,
        )

    def settlePixelSelectionModificationPreview(self, session_id: uuid.UUID) -> bool:
        """Commit the latest preview once as one selection history edit."""

        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        return self.pixelSelectionModificationCoordinator().settle(session_id)

    def cancelPixelSelectionModificationPreview(self, session_id: uuid.UUID) -> bool:
        """Restore the original selection without recording history."""

        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        return self.pixelSelectionModificationCoordinator().cancel(session_id)

    def _request_pixel_selection_modification(
        self,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Authorize and submit one active selection transformation."""
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if not resolution.allowed or not self._anchor_floating_pixels_before_edit():
            return None
        return self.pixelSelectionModificationCoordinator().request(
            operation,
            radius,
        )

    @staticmethod
    def _positive_pixel_radius(pixels: int) -> float:
        """Require a positive non-boolean whole-pixel radius."""
        if isinstance(pixels, bool) or not isinstance(pixels, int):
            raise TypeError("selection radius must be an integer")
        if pixels <= 0:
            raise ValueError("selection radius must be positive")
        return float(pixels)


__all__ = ["SelectionApiMixin"]
