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
"""Final-release ownership for composition-referenced placed assets."""

from dataclasses import dataclass

from qpane.sdk.scene import LayerSourceReference

from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore


@dataclass(frozen=True, slots=True)
class PlacedAssetResourceLifecycleOwner:
    """Delete placed payloads after their final composition lease is released."""

    assets: PlacedAssetStore
    source_type = PlacedAssetReference

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Delete an unreachable placed payload when present."""
        if isinstance(source, PlacedAssetReference):
            self.assets.remove(source.asset_id)
