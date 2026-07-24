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
"""Immutable public values describing Clone Stamp configuration and source state."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform

from .sample_mapping import AffineSampleMapping


class CloneStampAlignment(str, Enum):
    """Control whether the source offset persists between separate strokes."""

    ALIGNED = "aligned"
    UNALIGNED = "unaligned"


class CloneStampSampleMode(str, Enum):
    """Choose the rendered layer range sampled by Clone Stamp."""

    ANCHORED_LAYER = "anchored-layer"
    ANCHORED_LAYER_AND_BELOW = "anchored-layer-and-below"
    VISIBLE_COMPOSITE = "visible-composite"


@dataclass(frozen=True, slots=True)
class CloneStampTransform:
    """Describe the visible transform applied to cloned content."""

    rotation_degrees: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    mirror_horizontal: bool = False
    mirror_vertical: bool = False

    def __post_init__(self) -> None:
        """Reject transforms that cannot produce stable inverse sampling."""
        if not math.isfinite(self.rotation_degrees):
            raise ValueError("clone rotation must be finite")
        for name in ("scale_x", "scale_y"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.mirror_horizontal, bool):
            raise TypeError("mirror_horizontal must be bool")
        if not isinstance(self.mirror_vertical, bool):
            raise TypeError("mirror_vertical must be bool")

    def _inverse_content_transform(self) -> LayerTransform:
        """Return the destination-to-source linear transform."""
        radians = math.radians(self.rotation_degrees)
        cosine = _stable_unit_value(math.cos(radians))
        sine = _stable_unit_value(math.sin(radians))
        signed_scale_x = -self.scale_x if self.mirror_horizontal else self.scale_x
        signed_scale_y = -self.scale_y if self.mirror_vertical else self.scale_y
        output = LayerTransform(
            m11=cosine * signed_scale_x,
            m12=sine * signed_scale_x,
            m21=-sine * signed_scale_y,
            m22=cosine * signed_scale_y,
        )
        inverse = output.inverted()
        if inverse is None:
            raise ValueError("clone content transform must be invertible")
        return inverse


@dataclass(frozen=True, slots=True)
class CloneStampSource:
    """Identify one source anchor in scene and optional layer-source coordinates."""

    scene_id: uuid.UUID
    scene_position: tuple[float, float]
    layer_id: uuid.UUID | None = None
    layer_position: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        """Reject incomplete or non-finite source coordinates."""
        values = self.scene_position
        if self.layer_position is not None:
            values = (*values, *self.layer_position)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("clone source coordinates must be finite")
        if (self.layer_id is None) != (self.layer_position is None):
            raise ValueError("layer clone sources require both layer values")

    def scene_point(self) -> QPointF:
        """Return a detached scene-space source point."""
        return QPointF(*self.scene_position)

    def layer_point(self) -> QPointF | None:
        """Return the detached layer-local point when this source has one."""
        return None if self.layer_position is None else QPointF(*self.layer_position)


@dataclass(frozen=True, slots=True)
class CloneStampState:
    """Return the complete host-facing Clone Stamp configuration snapshot."""

    alignment: CloneStampAlignment = CloneStampAlignment.ALIGNED
    sample_mode: CloneStampSampleMode = CloneStampSampleMode.ANCHORED_LAYER
    transform: CloneStampTransform = CloneStampTransform()
    source: CloneStampSource | None = None

    @property
    def source_set(self) -> bool:
        """Return whether a usable source anchor has been configured."""
        return self.source is not None


@dataclass(frozen=True, slots=True)
class CloneStampMapping:
    """Map destination pixels to one revision-stable clone source."""

    source: CloneStampSource
    sample_mapping: AffineSampleMapping
    layer_ids: frozenset[uuid.UUID] | None

    def __post_init__(self) -> None:
        """Validate the mapping and detach an optional layer scope."""
        if not isinstance(self.sample_mapping, AffineSampleMapping):
            raise TypeError("sample_mapping must be AffineSampleMapping")
        if self.layer_ids is not None:
            normalized = frozenset(self.layer_ids)
            if not all(isinstance(layer_id, uuid.UUID) for layer_id in normalized):
                raise TypeError("clone mapping layer IDs must be UUIDs")
            object.__setattr__(self, "layer_ids", normalized)


def _stable_unit_value(value: float) -> float:
    """Snap quadrantal trigonometry noise without quantizing arbitrary angles."""
    if abs(value) < 1e-12:
        return 0.0
    if abs(value - 1.0) < 1e-12:
        return 1.0
    if abs(value + 1.0) < 1e-12:
        return -1.0
    return value
