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
"""Public viewport-source and responsive interaction facade."""

from __future__ import annotations

from PySide6.QtCore import Qt

from ..document import CanvasViewportInteraction, CanvasViewportSpec
from ..scene.viewport_selection import ViewportSceneSelection


class ViewportApiMixin:
    """Expose independently identified content views without document mutation."""

    def setViewportSpec(self, spec: CanvasViewportSpec) -> None:
        """Bind selected content and interaction policy to this canvas view."""
        if not isinstance(spec, CanvasViewportSpec):
            raise TypeError("spec must be a CanvasViewportSpec")
        assembler = self._composition_layer_assembler
        if assembler is None:
            raise RuntimeError("composition layer assembler is unavailable")
        selection = ViewportSceneSelection(
            self.document(),
            self.compositionService(),
            assembler,
        )
        composition_id = selection.composition_id(spec)
        record = self.compositionService().record(composition_id)
        self._open_composition_record(record, fit_view=True)
        self.viewSession().set_viewport_spec(spec, composition_id=composition_id)
        self._refresh_active_scene_content(fit_view=True)
        fit_only = spec.interaction is CanvasViewportInteraction.FIT_ONLY
        self.setPanZoomLocked(False)
        if fit_only:
            self.setZoomFit()
        self.setPanZoomLocked(fit_only)

    def viewportSpec(self) -> CanvasViewportSpec | None:
        """Return the explicit source and policy mounted by this view."""
        return self.viewSession().viewport_spec

    def setViewportCornerRadius(self, radius: float) -> None:
        """Clip final viewport pixels using QPane's bounded border compositor."""
        self.presenter().set_viewport_corner_radius(radius)
        if radius > 0.0:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def viewportCornerRadius(self) -> float:
        """Return the final viewport presentation radius in logical pixels."""
        return self.presenter().viewport_corner_radius()


__all__ = ["ViewportApiMixin"]
