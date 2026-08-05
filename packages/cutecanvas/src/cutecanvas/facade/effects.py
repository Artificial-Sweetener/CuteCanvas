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

"""Editor-semantic conveniences over QPane's transient effect owner."""

from __future__ import annotations

from PySide6.QtGui import QColor
from qpane import LayerPresentationStyle

from .handles import EditorHandleHost, LayerEffectHandle, LayerHandle


class EffectsFacade:
    """Create transient layer highlights without owning renderer state."""

    def __init__(self, host: EditorHandleHost) -> None:
        """Bind the CuteCanvas facade used by typed layer handles."""
        self._host = host

    def add(
        self,
        layer: LayerHandle,
        style: LayerPresentationStyle,
    ) -> LayerEffectHandle:
        """Add any QPane presentation style to an open document layer."""
        if not isinstance(layer, LayerHandle):
            raise TypeError("layer must be LayerHandle")
        return layer.add_effect(style)

    def highlight(
        self,
        layer: LayerHandle,
        *,
        color: QColor | None = None,
        width: float = 1.0,
        opacity: float = 0.9,
    ) -> LayerEffectHandle:
        """Add a restrained actual-content outline to one open layer."""
        return self.add(
            layer,
            LayerPresentationStyle.outline(
                QColor(75, 155, 225) if color is None else color,
                width=width,
                opacity=opacity,
            ),
        )

    def tint(
        self,
        layer: LayerHandle,
        color: QColor,
        *,
        opacity: float = 0.35,
    ) -> LayerEffectHandle:
        """Add a translucent tint constrained to visible layer coverage."""
        return self.add(
            layer,
            LayerPresentationStyle.tint(color, opacity=opacity),
        )

    def glow(
        self,
        layer: LayerHandle,
        color: QColor,
        *,
        radius: float = 8.0,
        opacity: float = 0.65,
    ) -> LayerEffectHandle:
        """Add a soft halo around one layer's visible coverage."""
        return self.add(
            layer,
            LayerPresentationStyle.glow(
                color,
                radius=radius,
                opacity=opacity,
            ),
        )

    def bounds(
        self,
        layer: LayerHandle,
        *,
        color: QColor | None = None,
        width: float = 1.0,
        opacity: float = 0.9,
    ) -> LayerEffectHandle:
        """Add a cosmetic rectangle around one layer's rendered products."""
        return self.add(
            layer,
            LayerPresentationStyle.bounds(
                QColor(75, 155, 225) if color is None else color,
                width=width,
                opacity=opacity,
            ),
        )

    def clear(self, layer: LayerHandle | None = None) -> int:
        """Remove all effects or only effects targeting one open layer."""
        if layer is None:
            return self._host.clearLayerPresentationEffects()
        if not isinstance(layer, LayerHandle):
            raise TypeError("layer must be LayerHandle or None")
        return self._host.clearLayerPresentationEffects(
            scene_id=layer.scene_id,
            layer_id=layer.id,
        )
