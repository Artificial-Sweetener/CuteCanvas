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

"""CuteCanvas delegation boundary for QPane-owned presentation effects."""

from __future__ import annotations

import uuid

from qpane import LayerPresentationEffect, LayerPresentationStyle


class EffectApiMixin:
    """Expose source-neutral QPane effects through CuteCanvas scene identities."""

    def addLayerPresentationEffect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Add one transient effect over an active rendered layer."""
        return self.view().add_layer_presentation_effect(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            style,
            effect_id=effect_id,
        )

    def updateLayerPresentationEffect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool:
        """Replace one effect style without changing identity or draw order."""
        return self.view().update_layer_presentation_effect(effect_id, style)

    def removeLayerPresentationEffect(self, effect_id: uuid.UUID) -> bool:
        """Remove one transient effect when present."""
        return self.view().remove_layer_presentation_effect(effect_id)

    def clearLayerPresentationEffects(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> int:
        """Remove matching transient effects and return the removal count."""
        resolved_scene_id = (
            None if scene_id is None else self._resolve_public_scene_id(scene_id)
        )
        return self.view().clear_layer_presentation_effects(
            scene_id=resolved_scene_id,
            layer_id=layer_id,
        )

    def layerPresentationEffects(self) -> tuple[LayerPresentationEffect, ...]:
        """Return every transient effect in deterministic draw order."""
        return self.view().layer_presentation_effects()
