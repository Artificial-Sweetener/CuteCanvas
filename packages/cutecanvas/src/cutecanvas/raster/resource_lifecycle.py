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
"""Final-release ownership for composition-referenced editable rasters."""

from __future__ import annotations

from dataclasses import dataclass

from qpane.sdk.scene import LayerSourceReference

from .assets import EditableRasterAssetStore
from .source_reference import EditableRasterReference


@dataclass(frozen=True, slots=True)
class EditableRasterResourceLifecycleOwner:
    """Delete raster payloads after their final composition lease is released."""

    assets: EditableRasterAssetStore
    source_type = EditableRasterReference

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Delete an unreachable editable-raster payload when present."""
        if isinstance(source, EditableRasterReference):
            self.assets.remove(source.raster_id)
