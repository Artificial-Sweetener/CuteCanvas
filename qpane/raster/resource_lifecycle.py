#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Final-release ownership for composition-referenced editable rasters."""

from __future__ import annotations

from dataclasses import dataclass

from ..scene.source_references import LayerSourceReference
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
