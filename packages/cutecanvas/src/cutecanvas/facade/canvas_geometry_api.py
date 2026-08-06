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
"""Public CuteCanvas workflows for canvas geometry changes."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSize

from ..document.canvas_geometry import CanvasAnchor
from ..document.canvas_resampling import CanvasResamplingMode


class CanvasGeometryApiMixin:
    """Expose cohesive canvas-bound, resampling, and crop workflows."""

    def resizeCanvasBounds(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        anchor: CanvasAnchor = CanvasAnchor.CENTER,
    ) -> bool:
        """Resize bounds and align content without resampling or cropping."""
        self._validate_canvas_geometry_request(composition_id, size)
        if not self._prepare_canvas_geometry_edit(composition_id):
            return False
        changed = self.document().resize_canvas_bounds(
            composition_id,
            size,
            anchor=CanvasAnchor(anchor),
        )
        if changed and self.currentCompositionID() == composition_id:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def requestCanvasResampling(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        mode: CanvasResamplingMode = CanvasResamplingMode.SMOOTH,
    ) -> uuid.UUID:
        """Begin source-aware whole-canvas resampling off the GUI thread."""
        self._validate_canvas_geometry_request(composition_id, size)
        if not self._prepare_canvas_geometry_edit(composition_id):
            raise RuntimeError("floating pixels could not be anchored")
        return self.documentRuntime().request_canvas_resampling(
            composition_id,
            size,
            mode=CanvasResamplingMode(mode),
        )

    def cancelCanvasResampling(self, request_id: uuid.UUID) -> bool:
        """Cancel a pending whole-canvas resampling request."""
        if not isinstance(request_id, uuid.UUID):
            raise TypeError("request_id must be a UUID")
        return self.documentRuntime().cancel_canvas_resampling(request_id)

    def cropLayersToCanvas(self, composition_id: uuid.UUID) -> bool:
        """Clip every layer to current bounds without flattening its source."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not self._prepare_canvas_geometry_edit(composition_id):
            return False
        changed = self.document().crop_layers_to_canvas(composition_id)
        if changed and self.currentCompositionID() == composition_id:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def _canvas_resampling_finished(self, result: object) -> None:
        """Refresh the active view and forward one document-runtime result."""
        composition_id = getattr(result, "composition_id", None)
        if getattr(result, "succeeded", False) and (
            self.currentCompositionID() == composition_id
        ):
            self._refresh_active_scene_content(fit_view=False)
        self.canvasResamplingCompleted.emit(result)

    def _prepare_canvas_geometry_edit(self, composition_id: uuid.UUID) -> bool:
        """Anchor provisional pixels only when their active document is targeted."""
        return self.currentCompositionID() != composition_id or bool(
            self._anchor_floating_pixels_before_edit()
        )

    @staticmethod
    def _validate_canvas_geometry_request(
        composition_id: uuid.UUID,
        size: QSize,
    ) -> None:
        """Validate shared public canvas geometry inputs."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(size, QSize):
            raise TypeError("size must be a QSize")
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError("canvas dimensions must be positive")


__all__ = ["CanvasGeometryApiMixin"]
