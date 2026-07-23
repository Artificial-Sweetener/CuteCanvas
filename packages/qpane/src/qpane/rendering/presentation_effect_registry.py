#    QPane - High-performance PySide6 image viewer
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

"""Ordered lifecycle owner for transient layer presentation effects."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import replace

from ..scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationStyle,
)


class LayerPresentationEffectRegistry:
    """Own ordered transient effects independently from durable scene state."""

    def __init__(self) -> None:
        """Initialize an empty insertion-ordered effect collection."""
        self._effects: dict[uuid.UUID, LayerPresentationEffect] = {}

    def add(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> LayerPresentationEffect:
        """Add one effect and return its immutable snapshot."""
        effect = LayerPresentationEffect(
            scene_id=scene_id,
            layer_id=layer_id,
            style=style,
            effect_id=effect_id or uuid.uuid4(),
        )
        if effect.effect_id in self._effects:
            raise ValueError(f"effect ID already exists: {effect.effect_id}")
        self._effects[effect.effect_id] = effect
        return effect

    def update(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> tuple[LayerPresentationEffect, LayerPresentationEffect] | None:
        """Replace one effect style while preserving identity and order."""
        if not isinstance(effect_id, uuid.UUID):
            raise TypeError("effect_id must be a UUID")
        if not isinstance(style, LayerPresentationStyle):
            raise TypeError("style must be LayerPresentationStyle")
        previous = self._effects.get(effect_id)
        if previous is None:
            return None
        current = replace(previous, style=style)
        if current == previous:
            return None
        self._effects[effect_id] = current
        return previous, current

    def remove(self, effect_id: uuid.UUID) -> LayerPresentationEffect | None:
        """Remove one effect and return its previous snapshot when present."""
        if not isinstance(effect_id, uuid.UUID):
            raise TypeError("effect_id must be a UUID")
        return self._effects.pop(effect_id, None)

    def clear(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> tuple[LayerPresentationEffect, ...]:
        """Remove effects matching optional scene and layer filters."""
        if scene_id is not None and not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID or None")
        if layer_id is not None and not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID or None")
        removed = tuple(
            effect
            for effect in self._effects.values()
            if (scene_id is None or effect.scene_id == scene_id)
            and (layer_id is None or effect.layer_id == layer_id)
        )
        for effect in removed:
            self._effects.pop(effect.effect_id, None)
        return removed

    def snapshot(
        self,
        *,
        scene_id: uuid.UUID | None = None,
    ) -> tuple[LayerPresentationEffect, ...]:
        """Return ordered immutable effects, optionally scoped to one scene."""
        if not self._effects:
            return ()
        return tuple(
            effect
            for effect in self._effects.values()
            if scene_id is None or effect.scene_id == scene_id
        )

    def reconcile(
        self,
        scene_id: uuid.UUID | None,
        layer_ids: Iterable[uuid.UUID] = (),
    ) -> tuple[LayerPresentationEffect, ...]:
        """Discard effects that cannot target the active scene snapshot."""
        if not self._effects:
            return ()
        valid_layers = frozenset(layer_ids)
        removed = tuple(
            effect
            for effect in self._effects.values()
            if effect.scene_id != scene_id or effect.layer_id not in valid_layers
        )
        for effect in removed:
            self._effects.pop(effect.effect_id, None)
        return removed
