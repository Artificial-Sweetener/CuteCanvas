#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Final-release ownership for composition-referenced placed assets."""

from dataclasses import dataclass

from ..scene.source_references import LayerSourceReference
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
