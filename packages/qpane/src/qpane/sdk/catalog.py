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
"""Supported catalog contracts for renderer-backed host collections."""

from ..catalog import (
    Catalog,
    CatalogMutationEvent,
    ImageCatalog,
    ImageMap,
    LinkManager,
    NavigationEvent,
    ViewerCatalog,
)
from ..catalog.source_capabilities import CatalogSourceCapabilities
from ..catalog.source_reference import CatalogImageReference

__all__ = (
    "Catalog",
    "CatalogImageReference",
    "CatalogMutationEvent",
    "CatalogSourceCapabilities",
    "ImageCatalog",
    "ImageMap",
    "LinkManager",
    "NavigationEvent",
    "ViewerCatalog",
)
