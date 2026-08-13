#    Ferrastra - CPU-first native graphics product engine
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

"""Define supported raster reconstruction working spaces."""

from __future__ import annotations

from enum import Enum


class RasterReconstructionSpace(str, Enum):
    """Select the transfer space used while reconstructing sRGB RGBA8 pixels."""

    SRGB_ENCODED = "srgb_encoded"
    SRGB_LINEAR = "srgb_linear"


__all__ = ["RasterReconstructionSpace"]
