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

"""Build one detached QPane pyramid product through its Ferrastra adapter."""

from __future__ import annotations

from PySide6.QtGui import QImage

from ..execution import CancellationToken
from ..ferrastra import generate_exact_pyramid_levels
from ..ferrastra.reconstruction import RasterReconstructionSpace
from ..scene.identity import SourceRenderAssetKey
from .pyramid_model import ImagePyramid, PyramidStatus


def generate_pyramid(
    asset_key: SourceRenderAssetKey,
    image: QImage,
    min_view_size_px: int,
    cancellation: CancellationToken,
    reconstruction_space: RasterReconstructionSpace = (
        RasterReconstructionSpace.SRGB_ENCODED
    ),
) -> ImagePyramid:
    """Return one complete detached product without mutating manager state."""
    cancellation.raise_if_cancelled()
    full_resolution_image = QImage(image)
    exact = generate_exact_pyramid_levels(
        full_resolution_image,
        min_view_size_px,
        cancellation,
        reconstruction_space=reconstruction_space,
    )
    cancellation.raise_if_cancelled()
    return ImagePyramid(
        asset_key=asset_key,
        full_resolution_image=full_resolution_image,
        reconstruction_space=reconstruction_space,
        levels=exact.levels,
        status=PyramidStatus.COMPLETE,
        size_bytes=full_resolution_image.sizeInBytes() + exact.size_bytes,
    )


__all__ = ["generate_pyramid"]
