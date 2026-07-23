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

"""Transient actual-content emphasis owned by the demo layer browser."""

from __future__ import annotations

import uuid

from cutecanvas import CuteCanvas, LayerEffectHandle, LayerHandle
from PySide6.QtGui import QColor

LayerTarget = tuple[uuid.UUID, uuid.UUID]


class LayerBrowserHighlights:
    """Coordinate selected and hovered layer effects without editor mutation."""

    def __init__(self, canvas: CuteCanvas) -> None:
        """Bind the public editor facade used for transient effects."""
        self._canvas = canvas
        self._selected: LayerEffectHandle | None = None
        self._selected_target: LayerTarget | None = None
        self._hovered: LayerEffectHandle | None = None
        self._hovered_target: LayerTarget | None = None

    def select(self, target: LayerTarget | None) -> None:
        """Keep one restrained actual-content outline on the selected row."""
        if target == self._selected_target:
            return
        self._selected = self._remove(self._selected)
        layer = self._open_layer(target)
        self._selected_target = target if layer is not None else None
        if layer is not None:
            self._selected = self._canvas.editor.effects.highlight(
                layer,
                color=QColor(80, 154, 224),
                width=1.0,
                opacity=0.72,
            )

    def hover(self, target: LayerTarget | None) -> None:
        """Keep one stronger outline on the active layer row under the pointer."""
        if target == self._hovered_target:
            return
        self._hovered = self._remove(self._hovered)
        layer = self._open_layer(target)
        self._hovered_target = target if layer is not None else None
        if layer is not None:
            self._hovered = self._canvas.editor.effects.highlight(
                layer,
                color=QColor(104, 190, 242),
                width=2.0,
                opacity=0.92,
            )

    def close(self) -> None:
        """Remove every browser-owned registration during UI teardown."""
        self._selected = self._remove(self._selected)
        self._hovered = self._remove(self._hovered)
        self._selected_target = None
        self._hovered_target = None

    def _open_layer(self, target: LayerTarget | None) -> LayerHandle | None:
        """Resolve one active-document layer handle without opening documents."""
        if target is None:
            return None
        composition_id, layer_id = target
        document = self._canvas.editor.documents.get(composition_id)
        if document is None or not document.is_open:
            return None
        return document.layer(layer_id)

    @staticmethod
    def _remove(effect: LayerEffectHandle | None) -> None:
        """Remove one possibly stale effect handle and return an empty slot."""
        if effect is not None:
            effect.remove()
