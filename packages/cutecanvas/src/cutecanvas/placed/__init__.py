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
"""Non-destructive placed raster sources and external provenance."""

from .model import PlacedAssetMode, PlacedAssetSnapshot, PlacedAssetStatus
from .store import PlacedAssetStore

__all__ = [
    "PlacedAssetMode",
    "PlacedAssetSnapshot",
    "PlacedAssetStatus",
    "PlacedAssetStore",
]
