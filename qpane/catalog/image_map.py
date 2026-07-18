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

"""Helpers for constructing ImageMap structures from host iterables."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtGui import QImage

from ..types import CatalogEntry

ImageMap = dict[UUID, CatalogEntry]
__all__ = ["ImageMap"]


def image_map_from_lists(
    images: Iterable[QImage],
    paths: Iterable[Path | None] | None = None,
    ids: Iterable[UUID] | None = None,
) -> ImageMap:
    """Build an ImageMap from aligned image, path, and ID iterables.

    Args:
        images: Ordered images that define the catalog contents.
        paths: Optional filesystem paths aligned with ``images``.
        ids: Optional UUIDs aligned with ``images``.

    Returns:
        Mapping of UUID to ``CatalogEntry`` records suitable for catalogs.

    Raises:
        ValueError: If ``paths`` or ``ids`` lengths do not match ``images``.
        TypeError: If any image is not a ``QImage`` instance.
    """
    images_list = list(images)
    n = len(images_list)
    if paths is None:
        paths_list = [None] * n
    else:
        paths_list = list(paths)
        if len(paths_list) != n:
            raise ValueError(
                f"paths length mismatch: expected {n}, received {len(paths_list)}"
            )
    if ids is None:
        ids_list = [uuid4() for _ in range(n)]
    else:
        ids_list = list(ids)
        if len(ids_list) != n:
            raise ValueError(
                f"ids length mismatch: expected {n}, received {len(ids_list)}"
            )
    image_map: ImageMap = {}
    for iid, img, p in zip(ids_list, images_list, paths_list):
        if iid in image_map:
            raise ValueError(f"Duplicate image id provided: {iid}")
        if img is None or not isinstance(img, QImage):
            raise TypeError("ImageMap values must be QImage instances")
        image_map[iid] = CatalogEntry(image=img, path=p)
    return image_map
