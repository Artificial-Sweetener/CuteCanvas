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
"""Typed handles for transient QPane presentation effects."""

from __future__ import annotations

import uuid

from qpane import LayerPresentationEffect, LayerPresentationStyle

from .handles import EditorHandleHost


class LayerEffectHandle:
    """Identify one transient QPane-owned presentation effect."""

    def __init__(self, host: EditorHandleHost, effect_id: uuid.UUID) -> None:
        """Bind stable effect identity without caching renderer state."""
        self._host = host
        self._effect_id = effect_id

    @property
    def id(self) -> uuid.UUID:
        """Return stable transient effect identity."""
        return self._effect_id

    @property
    def state(self) -> LayerPresentationEffect:
        """Return the latest effect snapshot or fail after removal."""
        effect = next(
            (
                value
                for value in self._host.layerPresentationEffects()
                if value.effect_id == self._effect_id
            ),
            None,
        )
        if effect is None:
            raise LookupError(f"effect {self._effect_id} no longer exists")
        return effect

    def update(self, style: LayerPresentationStyle) -> bool:
        """Replace this effect's style while retaining draw order."""
        return self._host.updateLayerPresentationEffect(self._effect_id, style)

    def remove(self) -> bool:
        """Remove this effect when it remains registered."""
        return self._host.removeLayerPresentationEffect(self._effect_id)


__all__ = ["LayerEffectHandle"]
