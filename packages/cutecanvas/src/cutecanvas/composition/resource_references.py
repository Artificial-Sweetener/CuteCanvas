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

"""Resource references retained by one composition-layer instance."""

from __future__ import annotations

from typing import Protocol

from qpane.sdk.scene import LayerEffectReference, LayerSourceReference


class CompositionResourceOwner(Protocol):
    """Expose the source references retained by one composition instance."""

    source: LayerSourceReference
    effects: tuple[LayerEffectReference, ...]


def instance_resources(
    instance: CompositionResourceOwner,
) -> tuple[LayerSourceReference, ...]:
    """Return unique main and effect sources retained by one instance."""
    sources = [instance.source]
    for effect in instance.effects:
        sources.extend(effect.retained_sources)
    return tuple(dict.fromkeys(sources))


__all__ = ["instance_resources"]
