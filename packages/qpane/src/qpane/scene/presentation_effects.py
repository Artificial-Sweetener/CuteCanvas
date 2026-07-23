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

"""Immutable public values for transient scene-layer presentation effects."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtGui import QColor


class LayerPresentationEffectKind(str, Enum):
    """Identify how one transient effect emphasizes its target layer."""

    CONTENT_TINT = "content-tint"
    CONTENT_OUTLINE = "content-outline"
    CONTENT_GLOW = "content-glow"
    BOUNDS = "bounds"


@dataclass(frozen=True, slots=True)
class LayerPresentationStyle:
    """Describe one composable transient layer presentation treatment."""

    kind: LayerPresentationEffectKind
    color: QColor
    opacity: float = 1.0
    width: float = 1.0
    radius: float = 0.0

    def __post_init__(self) -> None:
        """Detach Qt values and reject styles unsafe for frame rendering."""
        kind = LayerPresentationEffectKind(self.kind)
        color = QColor(self.color)
        values = (self.opacity, self.width, self.radius)
        if not color.isValid():
            raise ValueError("effect color must be valid")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("effect dimensions and opacity must be finite")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("effect opacity must be between 0.0 and 1.0")
        if self.width < 0.0 or self.radius < 0.0:
            raise ValueError("effect width and radius must be non-negative")
        if self.width > 64.0 or self.radius > 128.0:
            raise ValueError("effect width and radius exceed renderer limits")
        if kind is LayerPresentationEffectKind.CONTENT_OUTLINE and self.width <= 0.0:
            raise ValueError("content outlines require a positive width")
        if kind is LayerPresentationEffectKind.CONTENT_GLOW and self.radius <= 0.0:
            raise ValueError("content glows require a positive radius")
        if kind is LayerPresentationEffectKind.BOUNDS and self.width <= 0.0:
            raise ValueError("bounds effects require a positive width")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "color", color)

    @classmethod
    def tint(
        cls,
        color: QColor,
        *,
        opacity: float = 1.0,
    ) -> LayerPresentationStyle:
        """Return a solid tint constrained to visible layer coverage."""
        return cls(LayerPresentationEffectKind.CONTENT_TINT, color, opacity)

    @classmethod
    def outline(
        cls,
        color: QColor,
        *,
        width: float = 1.0,
        opacity: float = 1.0,
    ) -> LayerPresentationStyle:
        """Return an outer silhouette outline in panel-space pixels."""
        return cls(
            LayerPresentationEffectKind.CONTENT_OUTLINE,
            color,
            opacity,
            width,
        )

    @classmethod
    def glow(
        cls,
        color: QColor,
        *,
        radius: float = 8.0,
        opacity: float = 0.65,
    ) -> LayerPresentationStyle:
        """Return a soft halo outside visible layer coverage."""
        return cls(
            LayerPresentationEffectKind.CONTENT_GLOW,
            color,
            opacity,
            1.0,
            radius,
        )

    @classmethod
    def bounds(
        cls,
        color: QColor,
        *,
        width: float = 1.0,
        opacity: float = 1.0,
    ) -> LayerPresentationStyle:
        """Return a cosmetic rectangle around rendered layer products."""
        return cls(
            LayerPresentationEffectKind.BOUNDS,
            color,
            opacity,
            width,
        )

    @property
    def panel_padding(self) -> float:
        """Return conservative panel-space damage padding for this style."""
        if self.kind is LayerPresentationEffectKind.CONTENT_GLOW:
            return self.radius + 2.0
        if self.kind is LayerPresentationEffectKind.CONTENT_OUTLINE:
            return self.width + 2.0
        if self.kind is LayerPresentationEffectKind.BOUNDS:
            return self.width + 2.0
        return 1.0


@dataclass(frozen=True, slots=True)
class LayerPresentationEffect:
    """Identify one ordered transient treatment for a rendered scene layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    style: LayerPresentationStyle
    effect_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        """Validate public identities and style ownership."""
        if not isinstance(self.scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(self.layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(self.effect_id, uuid.UUID):
            raise TypeError("effect_id must be a UUID")
        if not isinstance(self.style, LayerPresentationStyle):
            raise TypeError("style must be LayerPresentationStyle")
