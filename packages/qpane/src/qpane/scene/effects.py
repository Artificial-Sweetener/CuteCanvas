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
"""Open typed layer-effect contracts and render-capability routing."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PySide6.QtGui import QPainterPath

from .raster import RasterBounds
from .source_references import LayerSourceReference


@runtime_checkable
class LayerEffectReference(Protocol):
    """Identify one immutable composition-owned layer effect."""

    @property
    def kind(self) -> str:
        """Return the stable persistence and diagnostics kind."""
        ...

    @property
    def retained_sources(self) -> tuple[LayerSourceReference, ...]:
        """Return every source whose lifetime the effect retains."""
        ...


class LayerEffectRenderOwner(Protocol):
    """Produce target-local clipping geometry for one effect type."""

    def clip_path(
        self,
        effect: LayerEffectReference,
        target_bounds: RasterBounds,
    ) -> QPainterPath:
        """Return the exact target-local path retained by the effect."""
        ...


class LayerEffectRenderRegistry:
    """Route typed effects to one exact rendering owner each."""

    def __init__(self) -> None:
        """Initialize an empty exact-type registry."""
        self._owners: dict[type[object], LayerEffectRenderOwner] = {}

    def register(
        self,
        effect_type: type[object],
        owner: LayerEffectRenderOwner,
    ) -> None:
        """Register the sole rendering owner for ``effect_type``."""
        existing = self._owners.get(effect_type)
        if existing is not None and existing is not owner:
            raise ValueError(f"effect owner already registered for {effect_type!r}")
        self._owners[effect_type] = owner

    def combined_clip(
        self,
        effects: tuple[LayerEffectReference, ...],
        target_bounds: RasterBounds | None,
    ) -> QPainterPath | None:
        """Intersect all effect clips or return no clip when no effects exist."""
        if not effects:
            return None
        if target_bounds is None:
            return QPainterPath()
        combined: QPainterPath | None = None
        for effect in effects:
            owner = self._owners.get(type(effect))
            if owner is None:
                return QPainterPath()
            path = owner.clip_path(effect, target_bounds)
            combined = path if combined is None else combined.intersected(path)
        return QPainterPath() if combined is None else combined
