#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Non-destructive placed raster sources and external provenance."""

from .model import PlacedAssetMode, PlacedAssetSnapshot, PlacedAssetStatus
from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore

__all__ = [
    "PlacedAssetMode",
    "PlacedAssetReference",
    "PlacedAssetSnapshot",
    "PlacedAssetStatus",
    "PlacedAssetStore",
]
