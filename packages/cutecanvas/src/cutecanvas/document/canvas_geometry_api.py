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
"""Headless document workflows for canvas geometry changes."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSize

from .canvas_geometry import CanvasAnchor, CanvasGeometryDomain
from .canvas_resampling import CanvasResamplingOwner


class CanvasDocumentGeometryMixin:
    """Expose document-owned canvas resize, resampling, and crop workflows."""

    def _install_canvas_geometry(self) -> None:
        """Construct geometry, history, and resampling owners for the document."""
        self._geometry = CanvasGeometryDomain.create(
            self._resources.compositions,
            self._resources.pixel_selection,
        )
        self._canvas_resampling = CanvasResamplingOwner(
            document=self._resources,
            masks=self._masks,
            state=self._geometry.state,
            selections=self._resources.pixel_selection,
        )

    def resize_canvas_bounds(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        anchor: CanvasAnchor = CanvasAnchor.CENTER,
    ) -> bool:
        """Resize one canvas and anchor content without resampling pixels."""
        changed = self._geometry.bounds.resize(
            composition_id,
            size,
            anchor=anchor,
        )
        if changed:
            self._events.layers_changed(composition_id)
        return changed

    def crop_layers_to_canvas(self, composition_id: uuid.UUID) -> bool:
        """Clip every layer to current canvas bounds without flattening content."""
        changed = self._geometry.crop.crop(composition_id)
        if changed:
            self._events.layers_changed(composition_id)
        return changed

    @property
    def _canvas_resampling_owner(self) -> CanvasResamplingOwner:
        """Return document-owned capture and adoption for runtime execution."""
        return self._canvas_resampling


__all__ = ["CanvasDocumentGeometryMixin"]
